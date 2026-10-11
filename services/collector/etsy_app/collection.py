"""Bounded API search, entity tracking and conservative shared request control."""
import datetime as dt
import email.utils
import hashlib
import json
import os
import time
import urllib.parse
import uuid
from pathlib import Path
from .core import LOCK, atomic_json, now, validate_niche
from .entities import parse_listings, parse_shop

SAFETY_BUFFER = 0.25
MAX_API_OFFSET = 12000

BASE = 'https://openapi.etsy.com/v3/application/'


class RequestBlocked(ValueError):
    pass


def number(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class Client:
    def __init__(self, store, settings, run, directory, fetcher):
        self.store, self.settings, self.run, self.directory, self.fetcher = store, settings, run, directory, fetcher
        self.count = 0
        self.stopped = None
        from .exclusions import prior_identities
        self.previous_listings, self.previous_shops = prior_identities(store) if any(settings.get(k) for k in ('exclude_fetched_listings', 'exclude_fetched_shops')) else (set(), set())
        self.cycle_listings, self.cycle_shops = set(), set()
        run['fetched_identities'] = {'listing_ids': [], 'shop_ids': []}
        run['exclusions'] = {'prior_listings': len(self.previous_listings), 'prior_shops': len(self.previous_shops), 'shop_calls_skipped': [], 'scope': 'Local filtering; Etsy search response and raw data still include excluded identities. Explicit daily tracking bypasses discovery exclusions.'}
        self.key, self.secret = os.environ.get('ETSY_API_KEY'), os.environ.get('ETSY_API_SECRET')
        self.state_path = store.directory / 'rate-limit-state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.key_id = hashlib.sha256((self.key or '').encode()).hexdigest()[:16]
        if self.state.get('key_id') != self.key_id:
            self.state = {'key_id': self.key_id}

    def report(self, phase, **details):
        progress = {'phase': phase, 'updated_at': now(), 'request_count': self.count,
                    'listing_count': sum(len(q['listings']) for q in self.run.get('queries', [])),
                    'shops_fetched': sum(bool(r.get('shop')) for r in self.run.get('shops', [])), **details}
        self.run['progress'] = progress
        atomic_json(self.directory / 'snapshot.json', self.run)
        callback = getattr(self.store, 'progress_callback', None)
        if callback:
            callback(self.run['run_id'], progress)

    def get(self, path, parameters=None):
        parameters = parameters or {}
        url = BASE + path + ('?' + urllib.parse.urlencode(parameters) if parameters else '')
        record = {'source_url': url, 'effective_parameters': parameters, 'requested_at': now(),
                  'http_status': None, 'raw_file': None, 'raw_sha256': None, 'status': 'failed', 'error': None}
        body = None
        try:
            self.reserve()
            identity = uuid.uuid4().hex
            event = {'request_id': identity, 'source': 'api', 'key_id': self.key_id, 'run_id': self.run['run_id'],
                     'started_at': now(), 'http_status': None, 'source_url': url, 'effective_parameters': parameters}
            record.update(request_id=identity, requested_at=event['started_at'])
            atomic_json(self.store.directory / 'requests' / (identity + '.json'), event)
            self.count += 1
            self.run['request_count'] = self.count
            self.state['last_attempt'] = time.time()
            atomic_json(self.state_path, self.state)
            self.report('request_sent', endpoint=path)
            try:
                response = self.fetcher(url, self.settings['timeout_seconds'], {'x-api-key': self.key + ':' + self.secret})
                status, body, content_type = response
                limits = getattr(response, 'rate_limits', {})
                event.update(http_status=status, finished_at=now(), rate_limits=limits)
                filename = f'raw-request-{identity}.json'
                (self.directory / filename).write_bytes(body)
                record.update(finished_at=event['finished_at'], http_status=status, content_type=content_type, raw_file=filename,
                              raw_sha256=hashlib.sha256(body).hexdigest(), rate_limits=limits)
                self.observe(status, limits)
                if status in {401, 403, 429}:
                    self.stopped = f'Etsy access/rate challenge (HTTP {status}); remaining requests stopped'
                    raise RequestBlocked(self.stopped)
                if status != 200:
                    raise ValueError(f'Etsy returned HTTP {status}')
                if len(body) > 8_000_000:
                    raise ValueError('Response exceeds 8 MB bound; raw response truncated')
                record['status'] = 'success'
            except Exception as error:
                event.update(finished_at=now(), error_type=type(error).__name__)
                raise
            finally:
                atomic_json(self.store.directory / 'requests' / (identity + '.json'), event)
        except Exception as error:
            record['error'] = str(error) if isinstance(error, ValueError) else f'{type(error).__name__}: source request failed'
            if isinstance(error, RequestBlocked):
                self.stopped = str(error)
                if record['http_status'] is None:
                    record['status'] = 'skipped'
        self.run['request_count'] = self.count
        self.report('response_received' if record['status'] == 'success' else 'request_stopped', endpoint=path, http_status=record['http_status'], error=record['error'])
        return record, body

    def plan(self, stage, pending):
        """Persist bounded follow-up demand; never authorize an unpaced burst."""
        current = time.time()
        quota = self.store.request_usage(instant=dt.datetime.fromtimestamp(current, dt.timezone.utc), settings=self.settings, state=self.state)['quota']
        daily_available = quota['safe_requests_available']
        local_available = daily_available
        run_cap=self.settings.get('max_requests_per_run',20)
        run_available=max(0,run_cap-self.count) if run_cap is not None else pending
        available = min(pending, local_available, run_available, daily_available if daily_available is not None else pending)
        window_until = self.state.get('second_window_until', 0)
        second_available = self.state.get('remaining_second') if current < window_until else self.state.get('limit_per_second')
        interval = max(1 / self.settings.get('requests_per_second', .5), 1 + SAFETY_BUFFER)
        plan = {'stage': stage, 'planned_at': now(), 'pending_requests': pending,
                'within_daily_and_run_budgets': available, 'reported_second_slots': second_available,
                'minimum_spacing_seconds': interval, 'safety_buffer_seconds': SAFETY_BUFFER,
                'daily_quota': quota,
                'next_request_wait_seconds': max(quota['wait_seconds'] or 0, self.state.get('next_allowed', 0) - current,
                                                self.state.get('last_attempt', 0) + interval - current,
                                                window_until - current if second_available == 0 else 0),
                'policy': 'Sequential paced requests; recheck quotas before each request; no automatic challenge retries'}
        self.run.setdefault('request_plans', []).append(plan)
        atomic_json(self.directory / 'snapshot.json', self.run)
        return plan

    def reserve(self):
        if getattr(self.store,'stop_event',None) and self.store.stop_event.is_set():
            raise RequestBlocked('Collector daemon shutdown: no further request admitted')
        if self.stopped:
            raise RequestBlocked(self.stopped)
        if not self.key or not self.secret:
            raise RequestBlocked('Set ETSY_API_KEY and ETSY_API_SECRET to use the official API')
        if self.settings.get('max_requests_per_run', 20) is not None and self.count >= self.settings.get('max_requests_per_run', 20):
            raise RequestBlocked('Configured per-run request budget reached')
        # Admission is recomputed after every bounded wait, including restart.
        while True:
            if getattr(self.store,'stop_event',None) and self.store.stop_event.is_set():
                raise RequestBlocked('Collector daemon shutdown during quota wait')
            current = time.time()
            if current < self.state.get('blocked_until', 0):
                raise RequestBlocked('Etsy Retry-After cooldown is still active; automatic challenge retry disabled')
            quota = self.store.request_usage(
                instant=dt.datetime.fromtimestamp(current, dt.timezone.utc), settings=self.settings, state=self.state)['quota']
            self.run['quota'] = quota
            if quota['ready']:
                break
            if self.settings.get('local_daily_request_budget') is None and quota['provider_limit'] is None:
                raise RequestBlocked('Etsy quota headers unavailable after bootstrap; no further request admitted')
            if quota['wait_seconds'] is None:
                raise RequestBlocked('Configured daily ceiling cannot allow a request; change budgets/reserve')
            seconds = max(.25, quota['wait_seconds'])
            self.report('waiting', reason='; '.join(quota['reasons']), quota=quota,
                        wait_seconds=seconds, resume_at=quota['next_available_at'])
            # Wait in small increments so progress and budgets remain current.
            time.sleep(min(30, seconds))
        observed = self.state.get('quota_observed_at', 0)
        remaining = self.state.get('remaining_today')
        limit = self.state.get('limit_per_second')
        if limit is not None and limit < 1:
            raise RequestBlocked('Server-reported per-second quota unavailable')
        interval = 1 / self.settings.get('requests_per_second', .5)
        wait = max(self.state.get('last_attempt', 0) + max(interval, 1 + SAFETY_BUFFER), self.state.get('next_allowed', 0)) - current
        if self.state.get('remaining_second') == 0:
            wait = max(wait, self.state.get('second_window_until', 0) - current)
        if wait > 11:
            raise RequestBlocked('Next permitted local request slot is more than 11 seconds away')
        if wait > 0:
            self.run.setdefault('throttle_waits', []).append({'recorded_at': now(), 'seconds': wait,
                'reason': 'Configured pacing and reported per-second allowance', 'resume_at':
                dt.datetime.fromtimestamp(current + wait, dt.timezone.utc).isoformat()})
            atomic_json(self.directory / 'snapshot.json', self.run)
            self.report('waiting', reason='Rate-limit protection: request spacing or exhausted per-second slots', wait_seconds=wait, resume_at=dt.datetime.fromtimestamp(current + wait, dt.timezone.utc).isoformat())
            time.sleep(wait)
        current = time.time()
        quota = self.store.request_usage(instant=dt.datetime.fromtimestamp(current, dt.timezone.utc), settings=self.settings, state=self.state)['quota']
        if not quota['ready']:
            return self.reserve()
        # Consume a reported slot even if the next response omits headers.
        if current >= self.state.get('second_window_until', 0):
            self.state['remaining_second'] = self.state.get('limit_per_second')
            self.state['second_window_until'] = current + 1 + SAFETY_BUFFER
        slots = self.state.get('remaining_second')
        if slots is not None:
            self.state['remaining_second'] = max(0, slots - 1)
        if remaining is not None and current - observed < 86400:
            self.state['remaining_today'] = max(0, remaining - 1)

    def observe(self, status, limits):
        for header, field in [('x-remaining-today', 'remaining_today'), ('x-limit-per-second', 'limit_per_second'),
                              ('x-limit-per-day', 'limit_per_day')]:
            value = number(limits.get(header))
            if value is not None:
                self.state[field] = value
        if 'x-remaining-today' in limits:
            self.state['quota_observed_at'] = time.time()
            self.state['daily_anchor_remaining'] = self.state.get('remaining_today')
            limit = self.state.get('limit_per_day')
            if limit is not None:
                self.state['daily_anchor_used'] = max(0, limit - self.state['remaining_today'])
        remaining_second = number(limits.get('x-remaining-this-second', limits.get('x-remaining-this-secon')))
        if remaining_second is not None:
            self.state['remaining_second'] = max(0, remaining_second)
            self.state['second_window_until'] = time.time() + 1 + SAFETY_BUFFER
            if remaining_second <= 0:
                self.state['next_allowed'] = self.state['second_window_until']
        if status == 429:
            retry = limits.get('retry-after', '60')
            try:
                seconds = max(1, float(retry))
            except (ValueError, TypeError):
                try:
                    seconds = max(1, email.utils.parsedate_to_datetime(retry).timestamp() - time.time())
                except (ValueError, TypeError):
                    seconds = 60
            self.state['blocked_until'] = time.time() + seconds + SAFETY_BUFFER
        atomic_json(self.state_path, self.state)


def provenance(run, response):
    return {'run_id': run['run_id'], **{key: response.get(key) for key in
            ('raw_file', 'raw_sha256', 'source_url', 'effective_parameters', 'requested_at', 'request_id')}}


def _search(client, niche, shop_id=None, total_limit=None):
    settings = client.settings
    page_size = settings.get('page_size') or settings.get('limit') or 100
    maximum = settings.get('max_pages', 1)
    base = {'keywords': niche['keywords'], 'sort_on': 'score', 'sort_order': 'desc', **settings.get('search_parameters', {})}
    if niche.get('taxonomy_id'):
        base['taxonomy_id'] = niche['taxonomy_id']
    if shop_id is not None:
        base = {'keywords': niche['keywords'], 'sort_on': 'created', 'sort_order': 'desc'}
    endpoint = 'shops/' + str(shop_id) + '/listings/active' if shop_id is not None else 'listings/active'
    collection_limit = total_limit if total_limit is not None else settings['limit']
    query = {'shop_id': shop_id, 'keyword_filter': 'Etsy keywords',
             'reported_count_scope': 'Etsy keyword matches in selected shop' if shop_id is not None else 'Etsy keyword matches', 'source_rows_returned': 0, 'source_rows_filtered_out': 0, 'matching_rows_not_retained_due_to_limit': 0, 'niche': niche, 'source': 'api', 'status': 'failed', 'listings': [], 'pages': [],
             'requested_at': now(), 'http_status': None, 'raw_file': None, 'raw_sha256': None, 'error': None,
             'effective_search': {'endpoint': BASE + endpoint, 'parameters': base,
                                  'page_size': page_size, 'max_pages': maximum, 'listing_limit': collection_limit},
             'category_filter': 'etsy_taxonomy' if niche.get('taxonomy_id') else 'local niche group; keywords sent to Etsy',
             'excluded_listing_count': 0, 'excluded_shop_listing_count': 0, 'duplicate_ids_across_pages': [], 'pagination_stop': None, 'provider_result_count': None}
    excluded_shops = client.previous_shops | client.cycle_shops
    seen = set()
    offset = 0
    client.run['queries'].append(query)
    client.report('search_started', keywords=niche['keywords'])
    while maximum is None or len(query['pages']) < maximum:
        if offset > MAX_API_OFFSET:
            query['pagination_stop'] = 'etsy_offset_limit'
            break
        counted = query['source_rows_returned'] if any(settings.get(k) for k in ('exclude_fetched_listings', 'exclude_fetched_shops')) else len(query['listings'])
        limit = min(page_size, collection_limit - counted) if collection_limit is not None else page_size
        response, body = client.get(endpoint, {**base, 'limit': limit, 'offset': offset})
        query['pages'].append(response)
        if len(query['pages']) == 1:
            for key in ('source_url', 'http_status', 'raw_file', 'raw_sha256', 'request_id'):
                query[key] = response.get(key)
        if response['status'] != 'success':
            query['error'] = response['error']
            query['status'] = 'partial' if query['listings'] else response['status']
            query['pagination_stop'] = 'request_failed_or_blocked'
            break
        try:
            payload = json.loads(body)
            items = parse_listings(body, response['requested_at'], provenance(client.run, response))
            response['returned_count'] = len(items)
            query['source_rows_returned'] += len(items)
            query['provider_result_count'] = payload.get('count')
            for row in items:
                client.run['fetched_identities']['listing_ids'].append(row['listing_id'])
                if row.get('shop_id'): client.run['fetched_identities']['shop_ids'].append(row['shop_id'])
                if settings.get('exclude_fetched_shops') and row.get('shop_id') in excluded_shops:
                    query['excluded_shop_listing_count'] += 1
                    continue
                if settings.get('exclude_fetched_listings') and row['listing_id'] in (client.previous_listings | client.cycle_listings):
                    query['excluded_listing_count'] += 1
                    continue
                if shop_id is not None:
                    if str(row.get('shop_id')) != str(shop_id):
                        raise ValueError('listing shop ID does not match selected shop')
                if collection_limit is not None and len(query['listings']) >= collection_limit:
                    query['matching_rows_not_retained_due_to_limit'] += 1
                    continue
                if row['listing_id'] in seen:
                    query['duplicate_ids_across_pages'].append(row['listing_id'])
                else:
                    seen.add(row['listing_id'])
                    query['listings'].append(row)
                    client.cycle_listings.add(row['listing_id'])
            query['status'] = 'success'
            remaining_pages = max(0, (int(payload['count']) - offset - len(items) + page_size - 1) // page_size) if number(payload.get('count')) is not None else 1
            known_shops = len({r['shop_id'] for r in query['listings'] if r.get('shop_id')} | set(map(str, settings.get('shop_ids', []))))
            shop_cap = settings.get('max_shops', 0)
            client.plan('search_followups', (min(remaining_pages, max(0, maximum - len(query['pages']))) if maximum is not None else remaining_pages) + (min(shop_cap, known_shops) if shop_cap is not None else known_shops))
            client.run['listing_count'] = sum(len(q['listings']) for q in client.run['queries'])
            client.report('page_saved', pages_fetched=len(query['pages']), provider_result_count=query['provider_result_count'])
            offset += len(items)
            total = number(payload.get('count'))
            capped_count = query['source_rows_returned'] if any(settings.get(k) for k in ('exclude_fetched_listings', 'exclude_fetched_shops')) else len(query['listings'])
            if collection_limit is not None and capped_count >= collection_limit and (query['matching_rows_not_retained_due_to_limit'] > 0 or not (total is not None and offset >= total)):
                query['pagination_stop'] = 'listing_limit'
                break
            if len(items) < limit or (total is not None and offset >= total):
                query['pagination_stop'] = 'source_exhausted'
                break
            if collection_limit is not None and capped_count >= collection_limit:
                query['pagination_stop'] = 'listing_limit'
                break
        except (ValueError, KeyError, TypeError) as error:
            response.update(status='failed', error=f'{type(error).__name__}: invalid listing response')
            query.update(status='partial' if query['listings'] else 'failed', error=response['error'], pagination_stop='parse_failure')
            break
    query['pagination_stop'] = query['pagination_stop'] or 'page_limit'
    query['collection_complete'] = query['pagination_stop'] == 'source_exhausted'
    if settings['limit'] is None and maximum is None and not query['collection_complete'] and query['status'] == 'success':
        query['status'] = 'partial'
    client.cycle_shops.update(client.run['fetched_identities']['shop_ids'])
    return query


def collect_api(store, settings, niches, trigger, fetcher, tracking_only=False):
    search_enabled = not tracking_only and not (trigger == 'daily' and settings.get('daily_mode') == 'tracking')
    tracking_enabled = tracking_only or (trigger == 'daily' and settings.get('daily_mode', 'both') != 'search')
    selected = [validate_niche(n) for n in (settings['niches'] if niches is None else niches)] if search_enabled else []
    if search_enabled and not 1 <= len(selected) <= 10:
        raise ValueError('select between 1 and 10 niches')
    if not LOCK.acquire(blocking=False):
        raise RuntimeError('another collection is running')
    import fcntl
    guard = None
    try:
        guard = (store.directory / '.collect.lock').open('a')
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another collection is running')
        context = getattr(store, 'collection_context', {})
        identity = context.get('run_id') or (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12])
        directory = store.runs / identity
        directory.mkdir()
        run = {'schema_version': 2, 'run_id': identity, 'started_at': now(), 'finished_at': None, 'status': 'running',
               'trigger': trigger, 'mode': 'tracking' if not search_enabled else 'search+tracking' if tracking_enabled else 'search', 'settings': settings,
               'queries': [], 'tracked_listings': [], 'shops': [], 'listing_count': 0, 'request_count': 0}
        run.update(artifact_kind=context.get('artifact_kind', 'tracking' if not search_enabled else 'discovery'),
                   lineage=context.get('lineage', {}), control_job_id=context.get('control_job_id'), manifest_sha256=context.get('manifest_sha256'))
        atomic_json(directory / 'snapshot.json', run)
        client = Client(store, settings, run, directory, fetcher)
        tracking = settings.get('tracking', {}) if tracking_enabled else {}
        chosen_shops = list(map(str, settings.get('shop_ids', [])))
        for niche in selected:
            niche_queries_start = len(run['queries'])
            for shop_id in (chosen_shops or [None]):
                remaining_limit = settings['limit'] - sum(q['source_rows_returned'] if any(settings.get(k) for k in ('exclude_fetched_listings', 'exclude_fetched_shops')) else len(q['listings']) for q in run['queries'][niche_queries_start:]) if chosen_shops and settings['limit'] is not None else settings['limit']
                if remaining_limit is not None and remaining_limit <= 0:
                    break
                if settings.get('exclude_fetched_shops') and shop_id in (client.previous_shops | client.cycle_shops):
                    run['exclusions']['shop_calls_skipped'].append(shop_id)
                    continue
                _search(client, niche, shop_id, remaining_limit)
                atomic_json(directory / 'snapshot.json', run)
                if client.stopped:
                    break
        if chosen_shops:
            run['selected_shop_search_coverage'] = {'selected': len(chosen_shops)*len(selected), 'queried': len(run['queries']), 'not_queried': len(chosen_shops)*len(selected) - len(run['queries']), 'distinct_selected_shops':len(chosen_shops), 'scope':'shop-search pairs'}
        client.plan('tracked_listings', len(tracking.get('listing_ids', [])))
        for listing_id in tracking.get('listing_ids', []):
            record, body = client.get('listings/' + str(listing_id), {'includes':'Images'} if settings.get('capture_images') else None)
            record['listing_id'] = str(listing_id)
            if record['status'] == 'success':
                try:
                    row = parse_listings(body, record['requested_at'], provenance(run, record))[0]
                    if row['listing_id'] != str(listing_id):
                        raise ValueError('returned listing ID does not match request')
                    if settings.get('capture_images'):
                        from .images import save_images
                        record['image_downloads'] = save_images(row, directory, maximum=1)
                    record['listing'] = row
                except (ValueError, KeyError, IndexError):
                    record.update(status='failed', error='Invalid tracked listing response')
            run['tracked_listings'].append(record)
            atomic_json(directory / 'snapshot.json', run)
        rows = [row for query in run['queries'] for row in query['listings']]
        rows += [item['listing'] for item in run['tracked_listings'] if item.get('listing')]
        explicit_shops = list(dict.fromkeys(chosen_shops + list(map(str, tracking.get('shop_ids', [])))))
        discovered = list(dict.fromkeys(row['shop_id'] for row in rows if row.get('shop_id') and row['shop_id'] not in explicit_shops))
        maximum = settings.get('max_shops', 0)
        shop_ids = explicit_shops + (discovered[:maximum] if maximum is not None else discovered)
        run['shop_coverage'] = {'explicit_requested': len(explicit_shops), 'discovered': len(discovered),
                                'discovered_selected': min(maximum, len(discovered)) if maximum is not None else len(discovered), 'discovered_not_requested': max(0, len(discovered) - maximum) if maximum is not None else 0}
        tracked_shops = set(map(str, tracking.get('shop_ids', [])))
        skipped = [sid for sid in shop_ids if settings.get('exclude_fetched_shops') and sid in client.previous_shops and sid not in tracked_shops]
        run['exclusions']['shop_calls_skipped'] += skipped
        shop_ids = [sid for sid in shop_ids if sid not in skipped]
        client.plan('shops', len(shop_ids))
        for position, shop_id in enumerate(shop_ids):
            client.plan('shops_remaining', len(shop_ids) - position)
            record, body = client.get('shops/' + shop_id)
            record['shop_id'] = shop_id
            if record['status'] == 'success':
                try:
                    shop = parse_shop(body, record['requested_at'], provenance(run, record))
                    if shop['shop_id'] != shop_id:
                        raise ValueError('returned shop ID does not match request')
                    record['shop'] = shop
                except (ValueError, KeyError, TypeError):
                    record.update(status='failed', error='Invalid shop response')
            run['shops'].append(record)
            if client.stopped:
                run['shop_coverage']['not_attempted_due_to_stop'] = len(shop_ids) - position - 1
                break
            atomic_json(directory / 'snapshot.json', run)
        outcomes = [item['status'] for item in run['queries'] + run['tracked_listings'] + run['shops']]
        successes = sum(status == 'success' for status in outcomes)
        run['status'] = 'success' if (not outcomes and run['exclusions']['shop_calls_skipped']) or (outcomes and successes == len(outcomes)) else 'partial' if successes or rows else 'failed'
        client.report('finished', status=run['status'], stop_reason=client.stopped)
        run.update(finished_at=now(), listing_count=sum(len(q['listings']) for q in run['queries']) + sum(bool(i.get('listing')) for i in run['tracked_listings']),
                   stop_reason=client.stopped)
        for k in run['fetched_identities']: run['fetched_identities'][k] = sorted(set(run['fetched_identities'][k]))
        from .quality import check
        run['dqa'] = check(run, directory)
        atomic_json(directory / 'snapshot.json', run)
        atomic_json(directory / 'dqa.json', run['dqa'])
        store.rebuild_index()
        envelope = {'schema_version': 1, 'event_type': 'collection_finalized', 'root_cycle_id': run['lineage'].get('root_cycle_id', identity),
                    'parent_run_id': run['lineage'].get('parent_run_id'), 'run_id': identity, 'artifact_kind': run['artifact_kind'],
                    'status': run['status'], 'finished_at': run['finished_at'], 'snapshot_sha256': hashlib.sha256((directory / 'snapshot.json').read_bytes()).hexdigest()}
        atomic_json(store.directory / 'events' / (identity + '.json'), envelope)
        return run
    finally:
        if guard:
            guard.close()
        LOCK.release()
