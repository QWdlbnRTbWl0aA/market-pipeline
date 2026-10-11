"""Bounded collection, source parsing, atomic snapshots and mechanical DQA."""
import collections
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
LOCK = threading.Lock()
STOP_WORDS = {'the', 'and', 'for', 'with', 'this', 'that', 'your', 'from', 'are', 'you', 'set', 'a', 'of', 'to', 'in'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if path.name == 'snapshot.json' and path.parent.parent.name == 'runs':
        from .dashboard_index import index_snapshot
        try:
            index_snapshot(path, value)
        except (ValueError, KeyError, TypeError):
            pass  # Preserve malformed snapshots for explicit corrupt-run reporting.


def config(path=None):
    return validate_config(json.loads(Path(path or ROOT / 'config.example.json').read_text()))


def validate_config(value):
    if not isinstance(value, dict):
        raise ValueError('configuration must be an object')
    allowed = {'source', 'limit', 'timeout_seconds', 'daily_time', 'timezone', 'niches',
               'page_size', 'max_pages', 'max_shops', 'max_requests_per_run', 'local_daily_request_budget',
               'requests_per_second', 'quota_reserve', 'quota_reserve_percent', 'tracking', 'search_parameters', 'daily_mode', 'shop_ids', 'daily_enabled', 'daily_resume_at', 'exclude_fetched_listings', 'exclude_fetched_shops', 'capture_images'}
    if set(value) - allowed:
        raise ValueError('configuration contains unsupported fields')
    if value.get('source') not in {'public', 'api'}:
        raise ValueError('source must be public or api')
    for key, upper in [('limit', 1000000 if value.get('source') == 'api' else 100), ('timeout_seconds', 60)]:
        if key == 'limit' and value.get(key) is None and value.get('source') == 'api':
            continue
        if type(value.get(key)) is not int or not 1 <= value[key] <= upper:
            raise ValueError(f'{key} must be between 1 and {upper}')
    if not isinstance(value.get('niches'), list) or not 1 <= len(value['niches']) <= 10:
        raise ValueError('configure between 1 and 10 niches')
    niches = [validate_niche(niche) for niche in value['niches']]
    for key, lower, upper in [('page_size', 1, 100), ('max_pages', 1, 10), ('max_shops', 0, 20),
                              ('max_requests_per_run', 1, 100), ('local_daily_request_budget', 1, 10000), ('quota_reserve', 0, 1000)]:
        if key in {'max_pages', 'max_shops', 'max_requests_per_run', 'local_daily_request_budget'} and value.get(key, 'absent') is None and value.get('source') == 'api':
            continue
        if key in value and (type(value[key]) is not int or not lower <= value[key] <= upper):
            raise ValueError(f'{key} must be between {lower} and {upper}')
    if 'quota_reserve_percent' in value and (type(value['quota_reserve_percent']) not in (int,float) or not 0<=value['quota_reserve_percent']<100):
        raise ValueError('quota_reserve_percent must be between 0 and 100 exclusive')
    if 'requests_per_second' in value and (type(value['requests_per_second']) not in (int, float) or not .1 <= value['requests_per_second'] <= 1):
        raise ValueError('requests_per_second must be between 0.1 and 1')
    for key in ('exclude_fetched_listings', 'exclude_fetched_shops', 'capture_images'):
        if key in value and type(value[key]) is not bool:
            raise ValueError(key + ' must be true or false')
    if 'daily_enabled' in value and type(value['daily_enabled']) is not bool:
        raise ValueError('daily_enabled must be true or false')
    if value.get('daily_resume_at') is not None:
        try:
            resume = dt.datetime.fromisoformat(value['daily_resume_at'])
            if resume.tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('daily_resume_at must be a timezone-aware ISO timestamp') from None
    if value.get('daily_mode', 'both') not in {'search', 'tracking', 'both'}:
        raise ValueError('daily_mode must be search, tracking or both')
    if value.get('daily_mode') == 'tracking' and (not isinstance(value.get('tracking'), dict) or value['source'] != 'api' or not any(value.get('tracking', {}).get(k) for k in ('listing_ids', 'shop_ids'))):
        raise ValueError('daily tracking mode requires API source and selected IDs')
    if 'shop_ids' in value:
        ids = value['shop_ids']
        if not isinstance(ids, list) or len(ids) > 100 or any(not re.fullmatch(r'[1-9][0-9]{0,19}', str(identity)) for identity in ids) or len(set(map(str, ids))) != len(ids):
            raise ValueError('shop_ids must contain at most 100 unique positive Etsy shop IDs')
    if 'tracking' in value:
        tracking = value['tracking']
        if not isinstance(tracking, dict) or set(tracking) - {'listing_ids', 'shop_ids'}:
            raise ValueError('tracking requires listing_ids and shop_ids')
        for key, maximum in [('listing_ids', 20), ('shop_ids', 10)]:
            ids = tracking.get(key, [])
            if not isinstance(ids, list) or len(ids) > maximum or any(not re.fullmatch(r'[1-9][0-9]{0,19}', str(identity)) for identity in ids):
                raise ValueError(f'tracking {key} must contain at most {maximum} positive IDs')
            if len(set(map(str, ids))) != len(ids):
                raise ValueError('tracking IDs must be unique')
    if 'search_parameters' in value:
        search = value['search_parameters']
        if not isinstance(search, dict) or set(search) - {'sort_on', 'sort_order', 'min_price', 'max_price'}:
            raise ValueError('unsupported search parameters')
        if search.get('sort_on', 'score') not in {'score', 'created', 'updated', 'price'} or search.get('sort_order', 'desc') not in {'asc', 'desc'}:
            raise ValueError('invalid search sorting')
        for field in ('min_price', 'max_price'):
            if field in search and (type(search[field]) not in (int, float) or not 0 <= search[field] <= 100000):
                raise ValueError('search prices must be nonnegative numbers')
        if search.get('min_price', 0) > search.get('max_price', 100000):
            raise ValueError('minimum price exceeds maximum price')

    try:
        if not isinstance(value.get('daily_time'), str):
            raise ValueError()
        daily = dt.time.fromisoformat(value['daily_time'])
        if daily.tzinfo is not None:
            raise ValueError()
        if not isinstance(value.get('timezone'), str):
            raise ValueError()
        ZoneInfo(value['timezone'])
    except (ValueError, KeyError):
        raise ValueError('use a valid local daily time and IANA timezone') from None
    return {**value, 'niches': niches}


def validate_niche(niche):
    if not isinstance(niche, dict):
        raise ValueError('niche must be an object')
    for field in ('category', 'keywords'):
        if not isinstance(niche.get(field), str) or not 1 <= len(niche[field].strip()) <= 160:
            raise ValueError(f'{field} must contain 1–160 characters')
    taxonomy = niche.get('taxonomy_id')
    if taxonomy is not None and (type(taxonomy) is not int or taxonomy <= 0):
        raise ValueError('taxonomy_id must be a positive Etsy taxonomy ID')
    if 'provisional' in niche and type(niche['provisional']) is not bool:
        raise ValueError('provisional must be true or false')
    return {k: niche[k].strip() if k in {'category', 'keywords'} else niche[k]
            for k in ('category', 'keywords', 'provisional', 'taxonomy_id') if k in niche}


RATE_HEADERS = ('x-limit-per-second', 'x-remaining-this-second', 'x-remaining-this-secon',
                'x-limit-per-day', 'x-remaining-today', 'retry-after')


class FetchResult(tuple):
    def __new__(cls, status, body, content_type, headers):
        result = super().__new__(cls, (status, body, content_type))
        result.rate_limits = {name: headers[name] for name in RATE_HEADERS if name in headers}
        return result


def fetch(url, timeout, headers=None):
    request = urllib.request.Request(url, headers={'User-Agent': 'EtsyResearchTrial/0.1', **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return FetchResult(response.status, response.read(8_000_001),
                               response.headers.get('Content-Type', ''), response.headers)
    except urllib.error.HTTPError as error:
        return FetchResult(error.code, error.read(8_000_001),
                           error.headers.get('Content-Type', ''), error.headers)


def tokens(value):
    return [w for w in re.findall(r'[a-z0-9]+', value.lower()) if len(w) > 2 and w not in STOP_WORDS]


def listing(identity, title, url, source, price=None, currency=None, digital=None, bestseller=None, evidence=None):
    return {'listing_id': str(identity), 'title': html.unescape(title).strip(), 'url': url,
            'source': source, 'price': price, 'currency': currency, 'digital': digital,
            'bestseller': bestseller, 'bestseller_evidence': evidence, 'listing_favorites': None,
            'listing_sales': None, 'shop_sales': None, 'listing_age_days': None,
            'metric_scope': {'price': 'listing observed', 'listing_favorites': 'listing observed when available',
                             'listing_sales': 'unavailable', 'shop_sales': 'unavailable'},
            'observed_at': now()}


class EtsyHTML(HTMLParser):
    """Parse listing cards and JSON-LD; never execute scripts or infer sales."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.cards = []
        self.current = None
        self.anchor = None
        self.script = None
        self.documents = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'}:
            self.stack.append(tag)
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.script = []
        identity = attrs.get('data-listing-id')
        if identity and identity.isdigit() and self.current is None:
            self.current = {'id': identity, 'depth': len(self.stack), 'text': [], 'title': None, 'url': None}
        if tag == 'a' and re.search(r'/listing/\d+', attrs.get('href', '')):
            self.anchor = {'url': attrs['href'], 'title': attrs.get('title'), 'text': [], 'depth': len(self.stack)}
            if self.current:
                self.current['url'] = attrs['href']
                self.current['title'] = attrs.get('title') or self.current['title']
        if self.current and tag == 'img':
            self.current['title'] = self.current['title'] or attrs.get('alt')
        if self.current and tag in {'h2', 'h3'}:
            self.current['heading_depth'] = len(self.stack)
            self.current['heading'] = []

    def handle_data(self, value):
        if self.script is not None:
            self.script.append(value)
        if self.current:
            self.current['text'].append(value)
            if self.current.get('heading_depth'):
                self.current['heading'].append(value)
        if self.anchor:
            self.anchor['text'].append(value)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            try:
                self.documents.append(json.loads(''.join(self.script)))
            except ValueError:
                pass
            self.script = None
        if tag not in self.stack:
            return
        depth = len(self.stack) - self.stack[::-1].index(tag)
        if self.current and self.current.get('heading_depth') == depth:
            self.current['title'] = self.current['title'] or ' '.join(self.current['heading']).strip()
            self.current.pop('heading_depth', None)
        if self.anchor and self.anchor['depth'] == depth:
            if not self.current:
                match = re.search(r'/listing/(\d+)', self.anchor['url'])
                self.cards.append({'id': match[1], 'title': self.anchor['title'] or ' '.join(self.anchor['text']),
                                   'url': self.anchor['url'], 'text': self.anchor['text']})
            self.anchor = None
        if self.current and self.current['depth'] == depth:
            self.cards.append(self.current)
            self.current = None
        self.stack = self.stack[:depth - 1]


def safe_url(value, identity):
    parsed = urllib.parse.urlparse(urllib.parse.urljoin('https://www.etsy.com', value or ''))
    if parsed.scheme != 'https' or parsed.hostname not in {'etsy.com', 'www.etsy.com'}:
        return f'https://www.etsy.com/listing/{identity}'
    return urllib.parse.urlunparse(parsed._replace(query='', fragment=''))


def parse_public(body):
    parser = EtsyHTML()
    parser.feed(body.decode('utf-8', errors='replace'))
    rows = {}
    for card in parser.cards:
        title = card.get('title') or ''
        if not title.strip():
            continue
        text = ' '.join(card['text'])
        badge = re.search(r'\bbest\s*seller\b', text, re.I)
        # Search text hints are weaker than a listing_type from the official API.
        digital = True if re.search(r'\bdigital download\b|\binstant download\b', text, re.I) else None
        row = listing(card['id'], title, safe_url(card['url'], card['id']), 'etsy_public',
                      digital=digital, bestseller=True if badge else None,
                      evidence=badge[0] if badge else None)
        row['digital_evidence'] = 'observed card text' if digital else None
        rows.setdefault(card['id'], row)
    def visit(item):
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            if item.get('@type') == 'Product':
                match = re.search(r'/listing/(\d+)', item.get('url', ''))
                if match and isinstance(item.get('name'), str):
                    identity = match[1]
                    offers = item.get('offers', {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    try:
                        price = float(offers.get('price'))
                    except (TypeError, ValueError):
                        price = None
                    row = rows.setdefault(identity, listing(identity, item['name'], safe_url(item['url'], identity), 'etsy_public'))
                    row['price'], row['currency'] = price, offers.get('priceCurrency')
            for child in item.values():
                if isinstance(child, (list, dict)):
                    visit(child)
    for document in parser.documents:
        visit(document)
    return list(rows.values())


def parse_api(body):
    from .entities import parse_listings
    return parse_listings(body)


def dqa(run, directory):
    from .quality import check
    return check(run, directory)


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.runs = self.directory / 'runs'
        self.runs.mkdir(parents=True, exist_ok=True)
        from .dashboard_index import DashboardIndex
        self.dashboard_index = DashboardIndex(self.directory)

    def list_runs(self):
        return self.dashboard_index.runs()

    def known_shops(self):
        return self.dashboard_index.shops()

    def read(self, identity):
        if not re.fullmatch(r'[0-9TZ-]+-[a-f0-9]{12}', identity):
            raise ValueError('invalid run ID')
        original = self.runs / identity / 'snapshot.json'
        pointer = self.directory / 'derived' / identity / 'current.json'
        if pointer.exists():
            version = json.loads(pointer.read_text())['version']
            if not re.fullmatch(r'[a-f0-9]{64}', version):
                raise ValueError('invalid derived version')
            return json.loads((pointer.parent / version / 'snapshot.json').read_text())
        return json.loads(original.read_text())

    def suggestions(self, prefix='', category=''):
        terms = collections.Counter()
        evidence = {}
        for run_info in self.list_runs()[:30]:
            if run_info['status'] == 'corrupt':
                continue
            for query in self.read(run_info['run_id'])['queries']:
                if category and category != query['niche']['category']:
                    continue
                for row in query['listings']:
                    words = tokens(row['title'])
                    for size in (2, 3):
                        for index in range(len(words) - size + 1):
                            phrase = ' '.join(words[index:index + size])
                            if prefix.lower() in phrase:
                                terms[phrase] += 1
                                evidence[phrase] = row['url']
        return [{'keywords': phrase, 'observations': count, 'example_url': evidence[phrase]} for phrase, count in terms.most_common(12)]

    def track(self, settings, trigger='tracking', fetcher=fetch):
        from .collection import collect_api
        if settings['source'] != 'api':
            raise ValueError('listing and shop tracking requires the official API')
        if not any(settings.get('tracking', {}).get(key) for key in ('listing_ids', 'shop_ids')):
            raise ValueError('Select at least one listing or shop ID for tracking')
        return collect_api(self, settings, [], trigger, fetcher, tracking_only=True)

    def reprocess(self):
        from .history import recover
        return recover(self)

    def rebuild_index(self):
        from .history import rebuild_index
        return rebuild_index(self)

    def history(self, kind, identity):
        if kind not in {'listing', 'shop'} or not re.fullmatch(r'[1-9][0-9]{0,19}', identity):
            raise ValueError('invalid history entity')
        path = self.directory / 'index.json'
        if not path.exists():
            self.rebuild_index()
        index = json.loads(path.read_text())
        rows = index.get('by_' + kind, {}).get(identity, [])
        return [row for row in rows if row['record_type'] == kind]

    def request_usage(self, instant=None, settings=None, state=None):
        instant = instant or dt.datetime.now(dt.timezone.utc)
        events = {}
        for event in self.dashboard_index.requests():
            if isinstance(event, dict) and event.get('source') == 'api' and event.get('request_id'):
                events[event['request_id']] = event
        dated = []
        for event in events.values():
            try:
                stamp = dt.datetime.fromisoformat(event['started_at'])
                if stamp.tzinfo is not None:
                    dated.append((stamp, event))
            except (ValueError, KeyError, TypeError):
                continue
        latest = max((item for item in dated if item[1].get('rate_limits')), default=None, key=lambda item: item[0])
        from .quota import quota_view
        if state is None:
            try:
                state = json.loads((self.directory / 'rate-limit-state.json').read_text())
            except (OSError, ValueError):
                state = {}
        quota = quota_view(dated, state, settings or {}, instant.timestamp())
        return {'quota': quota, 'checked_at': instant.isoformat(),
                'last_5_minutes': sum(0 <= (instant - stamp).total_seconds() < 300 for stamp, _ in dated),
                'last_24_hours': sum(0 <= (instant - stamp).total_seconds() < 86400 for stamp, _ in dated),
                'last_second': sum(0 <= (instant - stamp).total_seconds() < 1 for stamp, _ in dated),
                'last_known_rate_limits': latest[1]['rate_limits'] if latest else None,
                'rate_limits_observed_at': latest[0].isoformat() if latest else None,
                'scope': 'Local recorded API attempts; other apps using this key are not included.',
                'history_note': 'Includes recorded historical search responses; earlier unrecorded transport failures cannot be reconstructed.',
                'official_windows': 'Etsy limits requests per second and rolling 24 hours; five minutes is an activity counter.'}

    def collect(self, settings, niches=None, trigger='manual', fetcher=fetch):
        if settings['source'] == 'api':
            from .collection import collect_api
            return collect_api(self, settings, niches, trigger, fetcher)
        selected = [validate_niche(n) for n in (niches if niches is not None else settings['niches'])]
        if not 1 <= len(selected) <= 10:
            raise ValueError('select between 1 and 10 niches')
        if not LOCK.acquire(blocking=False):
            raise RuntimeError('another collection is running')
        # Cross-process lock also protects manual CLI vs server/scheduler runs.
        import fcntl
        guard = (self.directory / '.collect.lock').open('a')
        try:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('another collection is running')
            identity = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12]
            directory = self.runs / identity
            directory.mkdir()
            run = {'schema_version': 1, 'run_id': identity, 'started_at': now(), 'finished_at': None,
                   'status': 'running', 'trigger': trigger, 'queries': [], 'listing_count': 0}
            atomic_json(directory / 'snapshot.json', run)
            stop_reason = None
            for index, niche in enumerate(selected):
                source = settings['source']
                params = {'q': niche['keywords']}
                headers = {}
                if source == 'api':
                    params = {'keywords': niche['keywords'], 'limit': settings['limit'], 'sort_on': 'score'}
                    if niche.get('taxonomy_id'):
                        params['taxonomy_id'] = niche['taxonomy_id']
                    url = 'https://openapi.etsy.com/v3/application/listings/active?'
                    key, secret = os.environ.get('ETSY_API_KEY'), os.environ.get('ETSY_API_SECRET')
                    if key and secret:
                        headers['x-api-key'] = key + ':' + secret
                else:
                    url = 'https://www.etsy.com/search?'
                url += urllib.parse.urlencode(params)
                query = {'niche': niche, 'source': source, 'source_url': url, 'requested_at': now(), 'status': 'failed',
                         'http_status': None, 'raw_file': None, 'raw_sha256': None, 'error': None, 'listings': [],
                         'category_filter': 'etsy_taxonomy' if source == 'api' and niche.get('taxonomy_id') else 'local niche group; keywords sent to Etsy'}
                event = None
                try:
                    if stop_reason:
                        query['status'] = 'skipped'
                        raise ValueError('Skipped after access challenge: ' + stop_reason)
                    if source == 'api' and not headers:
                        raise ValueError('Set ETSY_API_KEY and ETSY_API_SECRET to use the official API')
                    if source == 'api':
                        request_id = uuid.uuid4().hex
                        event = {'request_id': request_id, 'source': 'api', 'run_id': identity,
                                 'started_at': now(), 'http_status': None}
                        query['request_id'] = request_id
                        atomic_json(self.directory / 'requests' / (request_id + '.json'), event)
                    response = fetcher(url, settings['timeout_seconds'], headers)
                    status, body, content_type = response
                    if event is not None:
                        event.update(http_status=status, finished_at=now(),
                                     rate_limits=getattr(response, 'rate_limits', {}))
                        atomic_json(self.directory / 'requests' / (event['request_id'] + '.json'), event)
                    query['http_status'] = status
                    query['content_type'] = content_type
                    raw_file = f'raw-{index}.json' if source == 'api' else f'raw-{index}.html'
                    (directory / raw_file).write_bytes(body)
                    query['raw_file'] = raw_file
                    query['raw_sha256'] = hashlib.sha256(body).hexdigest()
                    lowered = body[:200_000].lower()
                    if status in {401, 403, 429} or b'captcha-delivery.com' in lowered or b'g-recaptcha' in lowered:
                        stop_reason = f'Etsy access challenge (HTTP {status}); collection stopped without bypass'
                        raise ValueError(stop_reason)
                    if status != 200:
                        raise ValueError(f'Etsy returned HTTP {status}')
                    if len(body) > 8_000_000:
                        raise ValueError('Response exceeds the 8 MB safety bound; raw response is truncated')
                    rows = parse_api(body) if source == 'api' else parse_public(body)
                    query['listings'] = rows[:settings['limit']]
                    if not rows:
                        raise ValueError('No listings parsed; empty results or unsupported page structure')
                    query['status'] = 'success'
                except Exception as error:
                    # Do not log arbitrary exception text, which could contain credentials.
                    query['error'] = str(error) if isinstance(error, ValueError) else f'{type(error).__name__}: source request or parsing failed'
                    if event is not None and event['http_status'] is None:
                        event.update(finished_at=now(), error_type=type(error).__name__)
                        atomic_json(self.directory / 'requests' / (event['request_id'] + '.json'), event)
                run['queries'].append(query)
                atomic_json(directory / 'snapshot.json', run)
            successes = sum(q['status'] == 'success' for q in run['queries'])
            run['status'] = 'success' if successes == len(selected) else 'partial' if successes else 'failed'
            run['finished_at'] = now()
            run['listing_count'] = sum(len(q['listings']) for q in run['queries'])
            run['dqa'] = dqa(run, directory)
            atomic_json(directory / 'snapshot.json', run)
            atomic_json(directory / 'dqa.json', run['dqa'])
            self.rebuild_index()
            return run
        finally:
            guard.close()
            LOCK.release()
