"""Product-owned, bounded visual evidence; no API clients or credentials.

Only selected listing pages and Etsy's image CDN are readable. Completed and
failed fetch receipts are reused; enrichment never repeats Product inference.
"""
import base64
import copy
import datetime as dt
import hashlib
from html.parser import HTMLParser
import http.client
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import time
import warnings
from urllib.parse import urlsplit
from .core import clean_environment, reject_secrets, write_json

VERSION = 'product-visual-references-v1'
DEFAULT = {'enabled': True, 'allow_listing_pages': True, 'max_images': 3, 'timeout_seconds': 10}


def policy(value=None):
    if value is None: value = {}
    if not isinstance(value, dict) or set(value)-set(DEFAULT): raise ValueError('Invalid visual reference policy')
    result = {**DEFAULT, **value}
    if any(type(result[k]) is not bool for k in ('enabled', 'allow_listing_pages')): raise ValueError('Explicit visual reference flags required')
    if type(result['max_images']) is not int or not 1 <= result['max_images'] <= 3: raise ValueError('One to three visual references allowed')
    if type(result['timeout_seconds']) is not int or not 1 <= result['timeout_seconds'] <= 30: raise ValueError('Bounded image timeout required')
    return result


def allowed(value, kind):
    if not isinstance(value, str) or len(value) > 2000: return False
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.fragment or p.query: return False
        if kind == 'listing':
            return p.hostname in ('www.etsy.com', 'etsy.com') and bool(re.fullmatch(r'/listing/\d+(?:/[A-Za-z0-9_-]+)?/?', p.path))
        return p.hostname == 'i.etsystatic.com' and bool(re.fullmatch(r'/[A-Za-z0-9_./-]+\.(?:jpg|jpeg|png|webp)', p.path, re.I)) and '..' not in p.path
    except ValueError: return False


class FetchError(ValueError):
    def __init__(self, reason, status=None, cached=False):
        super().__init__(reason); self.status = status; self.cached = cached


def fetch(url, limit, timeout):
    """Pin a validated public address; no redirects, proxies, cookies or keys."""
    kind = 'image' if urlsplit(url).hostname == 'i.etsystatic.com' else 'listing'
    if not allowed(url, kind): raise FetchError('Unapproved media source')
    p = urlsplit(url)
    addresses = sorted({row[4][0] for row in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(a).is_global or ipaddress.ip_address(a).is_multicast for a in addresses): raise FetchError('Non-public media address')
    connection = http.client.HTTPSConnection(p.hostname, timeout=timeout, context=ssl.create_default_context())
    # HTTPS still validates the original host and uses that host for SNI.
    connection._create_connection = lambda address, timeout, source_address=None: socket.create_connection((addresses[0], 443), timeout, source_address)
    try:
        connection.request('GET', p.path, headers={'User-Agent': 'MarketPipeline-Product/1.0', 'Accept': 'image/jpeg,image/png,image/webp' if kind == 'image' else 'text/html'})
        response = connection.getresponse()
        if response.status != 200: raise FetchError('Media HTTP failure', response.status)
        mime = response.getheader('Content-Type', '').split(';')[0].lower()
        if mime not in (('image/jpeg', 'image/png', 'image/webp') if kind == 'image' else ('text/html',)): raise FetchError('Unexpected media content type')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdigit() or int(length) > limit): raise FetchError('Media body exceeds limit')
        chunks=[]; size=0; deadline=time.monotonic()+timeout
        while size<=limit:
            if time.monotonic()>deadline: raise FetchError('Media total read timeout')
            chunk=response.read1(min(65536,limit+1-size))
            if not chunk: break
            chunks.append(chunk);size+=len(chunk)
        body=b''.join(chunks)
        if len(body) > limit: raise FetchError('Media body exceeds limit')
        return body
    finally: connection.close()


class GuardedFetch:
    """Keep access challenges durable across products and process restarts."""
    def __init__(self, root, transport=None):
        self.root=Path(root);self.transport=transport or fetch

    def __call__(self,url,limit,timeout):
        import fcntl
        kind='image' if urlsplit(url).hostname=='i.etsystatic.com' else 'listing'
        if not allowed(url,kind):raise FetchError('Unapproved media source')
        self.root.mkdir(parents=True,exist_ok=True)
        host=urlsplit(url).hostname
        # Treat apex/www as the same listing site access boundary.
        if host=='etsy.com':host='www.etsy.com'
        block=self.root/(host+'.json')
        with (self.root/(host+'.lock')).open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if block.exists():
                state=json.loads(block.read_text())
                raise FetchError('Saved access block; explicit operator review required before new retrieval',state['status'],cached=True)
            try:return self.transport(url,limit,timeout)
            except FetchError as error:
                if error.status in (401,403,429):
                    write_json(block,{'status':error.status,'host':host,'recorded_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                                      'automatic_retry':False})
                raise


class Metadata(HTMLParser):
    def __init__(self): super().__init__(); self.image = None
    def handle_starttag(self, tag, attrs):
        if tag != 'meta' or self.image: return
        value = dict(attrs)
        if (value.get('property') or value.get('name') or '').lower() in ('og:image', 'twitter:image') and allowed(value.get('content'), 'image'):
            self.image = value['content']


def image_url(sample):
    images=sample.get('images') or []
    if not isinstance(images,list): return None
    for item in images[:10]:
        if isinstance(item, str) and allowed(item, 'image'): return item
        if isinstance(item, dict):
            for key in ('url_570xN', 'url_170x135', 'url_fullxfull', 'url'):
                if allowed(item.get(key), 'image'): return item[key]
    return None


def thumbnail(body):
    from PIL import Image, ImageOps
    if not isinstance(body, bytes) or len(body) > 2_000_000: raise ValueError('Image byte limit')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(body)) as image:
            if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width*image.height > 20_000_000 or getattr(image, 'n_frames', 1) != 1: raise ValueError('Bounded still raster required')
            image = ImageOps.exif_transpose(image); image.thumbnail((512, 512))
            # A fresh RGB image carries no EXIF, ICC, text or other source metadata.
            clean = Image.new('RGB', image.size, 'white')
            if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                rgba = image.convert('RGBA'); clean.paste(rgba, mask=rgba.getchannel('A'))
            else: clean.paste(image.convert('RGB'))
            for quality in (75, 60, 45):
                output = io.BytesIO(); clean.save(output, format='JPEG', quality=quality, optimize=True)
                if output.tell() <= 80_000: return output.getvalue(), clean.size
    raise ValueError('Thumbnail byte limit')


def enrich(product, directory, settings=None, fetcher=None):
    """Return an enriched copy; source product and collection remain unchanged."""
    clean_environment(); reject_secrets(product); settings = policy(settings)
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or GuardedFetch(directory.parent/'visual-access')
    fingerprint = hashlib.sha256(json.dumps({'product': product, 'policy': settings, 'recipe': VERSION}, sort_keys=True).encode()).hexdigest()
    receipt = directory/'visual-reference-result.json'; started = directory/'visual-reference-started.json'
    if receipt.exists():
        result = json.loads(receipt.read_text())
        if result['fingerprint'] != fingerprint: raise ValueError('Visual reference identity changed; use a new revision directory')
    elif started.exists():
        raise RuntimeError('Interrupted visual retrieval; explicit new revision required, no automatic requests')
    else:
        write_json(started, {'fingerprint': fingerprint, 'recipe': VERSION})
        selected = []; seen = set()
        for sample in product.get('samples', []):
            if not allowed(sample.get('url'), 'listing'): continue
            identity = sample.get('listing_id') or sample['url']
            if identity in seen: continue
            seen.add(identity); selected.append(sample)
            if len(selected) == settings['max_images']: break
        result = {'recipe': VERSION, 'fingerprint': fingerprint, 'retrieved_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'references': [], 'failures': [], 'requests': 0, 'cached_failures': 0, 'status': 'disabled' if not settings['enabled'] else 'unavailable',
                  'images_visually_inspected_by_product': False, 'selected_count': len(selected)}
        blocked = set()
        for sample in selected if settings['enabled'] else []:
            record = {k: sample.get(k) for k in ('evidence_id', 'listing_id', 'shop_id', 'title', 'url')}
            source = None
            try:
                source = image_url(sample); origin = 'saved_listing_image_metadata'
                page_sha = None
                if not source:
                    if not settings['allow_listing_pages']: raise FetchError('No saved image URL; public page lookup disabled')
                    if 'listing' in blocked: raise FetchError('Page lookup stopped after access block; no bypass or retries')
                    result['requests'] += 1
                    page = fetcher(sample['url'], 1_000_000, settings['timeout_seconds'])
                    if len(page) > 1_000_000: raise FetchError('Listing page exceeds bound')
                    page_sha = hashlib.sha256(page).hexdigest()
                    parser = Metadata(); parser.feed(page.decode('utf-8', errors='replace'))
                    source = parser.image; origin = 'public_listing_image_metadata'
                    if not source: raise FetchError('No allowed image metadata on listing page')
                if 'image' in blocked: raise FetchError('Image lookup stopped after access block')
                result['requests'] += 1; body = fetcher(source, 2_000_000, settings['timeout_seconds'])
                reduced, size = thumbnail(body)
                interpretation = next((r for r in product.get('definition', {}).get('reference_interpretation', []) if r['evidence_id'] == sample.get('evidence_id')), {})
                result['references'].append({**record, 'source_image_url': source, 'image_url_origin': origin,
                    'source_image_sha256': hashlib.sha256(body).hexdigest(), 'listing_page_sha256': page_sha,
                    'sha256': hashlib.sha256(reduced).hexdigest(), 'width': size[0], 'height': size[1], 'bytes': len(reduced),
                    'image': 'data:image/jpeg;base64,'+base64.b64encode(reduced).decode(),
                    'purpose': interpretation.get('use_for_our_product', 'Reference for original product design'),
                    'do_not_copy': interpretation.get('do_not_copy', 'Do not reproduce source artwork or branding')})
            except Exception as error:
                if getattr(error,'cached',False):
                    result['requests']-=1;result['cached_failures']+=1
                code = getattr(error, 'status', None)
                if code in (401, 403, 429): blocked.add('image' if source else 'listing')
                reason = str(error) if isinstance(error, FetchError) else 'Image retrieval or decoding failed'
                result['failures'].append({**record, 'error_type': type(error).__name__, 'http_status': code, 'reason': reason[:160]})
        if settings['enabled'] and result['references']:
            result['status'] = 'ready' if len(result['references']) == len(selected) else 'partial'
        write_json(receipt, result)
    value = copy.deepcopy(product)
    value['reference_images'] = [r['image'] for r in result['references']]
    value['visual_references'] = [{k: v for k, v in r.items() if k != 'image'} for r in result['references']]
    value['visual_reference_status'] = {k: v for k, v in result.items() if k not in ('references', 'fingerprint')}
    value['visual_reference_guidance'] = ('Studio: inspect the attached reference images alongside the cited purposes; extract composition, palette, typography and product format, then create original artwork. The existing first-sketch style is a proposed direction, not a claim about competitor images.'
        if result['references'] else 'No visual reference images are attached. Visual evidence is incomplete; see retrieval failures below. The first-sketch style remains a proposed direction from text, not an observed competitor style.')
    return value


def revise(path, output, settings=None, fetcher=None):
    """Explicit enrichment of an existing brief, without inference or deliveries."""
    from .briefing import document, html_document
    path = Path(path); output = Path(output)
    if path.is_symlink() or path.name != 'product.json' or path.stat().st_size > 900000: raise ValueError('Bounded saved Product JSON required')
    if output.resolve() == path.parent.resolve(): raise ValueError('Keep the original brief immutable; choose a new output directory')
    product = json.loads(path.read_text())
    if 'definition' not in product or 'samples' not in product: raise ValueError('Grounded Product definition required')
    import fcntl
    output.mkdir(parents=True, exist_ok=True)
    with (output/'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        product = enrich(product, output, settings, fetcher)
        if len(json.dumps(product,ensure_ascii=False,indent=2).encode())>890000:raise ValueError('Studio brief size bound exceeded')
        product['visual_revision'] = {'recipe': VERSION, 'source_brief_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        write_json(output/'product.json', product)
        markdown = document(product); (output/'brief.md').write_text(markdown); (output/'brief.html').write_text(html_document(markdown))
        write_json(output/'studio-handoff.json', {'source': product['source'], 'products': [{'brief': product, 'vision': product['vision']}], 'delivery': 'saved_only', 'finished_products_generated': False})
    return {'directory': str(output), 'visual_status': product['visual_reference_status']['status'], 'images': len(product['reference_images']), 'requests': product['visual_reference_status']['requests'], 'inference_calls': 0, 'deliveries': 0}
