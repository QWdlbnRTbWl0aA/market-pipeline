"""Authenticated bounded local jobs, persisted before ACK and never replayed blindly."""
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import uuid
from .core import atomic_json, now, validate_config


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def authentication(path, supplied):
    if not path or not isinstance(supplied, str): return False
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 256: return False
        token = os.read(fd, 257).decode().strip()
        return bool(re.fullmatch('[a-f0-9]{64}', token)) and hmac.compare_digest(token, supplied)
    finally: os.close(fd)


def effective(app, payload):
    fields = {'schema_version', 'job_id', 'manifest_sha256', 'kind', 'lineage', 'parameters', 'bounds', 'approval'}
    if not isinstance(payload, dict) or set(payload) != fields or payload['schema_version'] != 1: raise ValueError('Unsupported bounded job contract')
    for name in ('job_id', 'manifest_sha256'):
        if not isinstance(payload[name], str) or not re.fullmatch('[a-f0-9]{64}', payload[name]): raise ValueError('Invalid job identity/hash')
    approval = payload['approval']
    if not isinstance(approval, dict) or set(approval) != {'manifest_sha256', 'reviewed_by', 'expires_at'} or approval['manifest_sha256'] != payload['manifest_sha256'] or not isinstance(approval['reviewed_by'], str) or not approval['reviewed_by'].strip(): raise ValueError('Exact reviewed manifest required')
    expires = dt.datetime.fromisoformat(approval['expires_at'])
    if expires.tzinfo is None or dt.datetime.now(dt.timezone.utc) >= expires: raise ValueError('Approval expired')
    bounds = payload['bounds']
    if not isinstance(bounds, dict) or set(bounds) != {'max_requests', 'max_pages', 'max_shops'}: raise ValueError('Explicit hard bounds required')
    ceilings=(100,10,20) if payload['kind']=='cycle_search' else (25,1,10)
    for (key, maximum) in zip(('max_requests','max_pages','max_shops'),ceilings):
        if type(bounds[key]) is not int or not (0 if key == 'max_shops' else 1) <= bounds[key] <= maximum: raise ValueError('Experiment bounds exceeded')
    lineage = payload['lineage']
    if not isinstance(lineage, dict) or set(lineage) - {'root_cycle_id', 'parent_run_id', 'experiment_id', 'iteration', 'max_paid_calls', 'cohort_id', 'cycle_id'}: raise ValueError('Unsupported lineage')
    if any(not isinstance(lineage.get(k), str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,99}', lineage[k]) for k in ('root_cycle_id', 'parent_run_id')): raise ValueError('Valid parent/root lineage required')
    if payload['kind'] == 'experiment':
        if lineage.get('experiment_id') != payload['job_id'] or lineage.get('iteration') != 1 or lineage.get('max_paid_calls') != 4: raise ValueError('One follow-up/four paid calls only')
        parameters = payload['parameters']
        settings = app.trial_settings(parameters)
        if settings['limit'] != 100 or len(settings['niches']) > 4 or parameters.get('exclude_fetched_listings') is not False or parameters.get('exclude_fetched_shops') is not False: raise ValueError('Equivalent bounded comparison parameters required')
        demand = len(settings['niches']) * max(1, len(settings.get('shop_ids', []))) + bounds['max_shops']
        if demand > bounds['max_requests']: raise ValueError('Follow-up demand exceeds request reservation')
        if any(k in app.settings.get('search_parameters', {}) for k in ('min_price', 'max_price')):
            raise ValueError('Price-filtered daily configuration needs a separately matched experiment')
        settings.update(limit=100, page_size=100, max_pages=1, max_shops=bounds['max_shops'], max_requests_per_run=bounds['max_requests'],
                        search_parameters={}, daily_mode='search', capture_images=False)
    elif payload['kind'] == 'cycle_search':
        parameters=payload['parameters']
        if not isinstance(lineage.get('cycle_id'),str) or not re.fullmatch('[a-f0-9]{64}',lineage['cycle_id']) or lineage.get('iteration')!=0:raise ValueError('Named cycle lineage required')
        settings=app.trial_settings(parameters)
        if len(settings['niches'])>4 or len(settings['shop_ids'])>5 or parameters.get('exclude_fetched_listings') is not False or parameters.get('exclude_fetched_shops') is not False:raise ValueError('Comparable bounded named cycle required')
        demand=len(settings['niches'])*max(1,len(settings['shop_ids']))*bounds['max_pages']+bounds['max_shops']
        if demand>bounds['max_requests']:raise ValueError('Cycle demand exceeds its reservation')
        settings.update(page_size=100,max_pages=bounds['max_pages'],max_shops=bounds['max_shops'],max_requests_per_run=bounds['max_requests'],
                        search_parameters={},daily_mode='search',capture_images=False)
    elif payload['kind'] == 'tracking':
        ids = payload['parameters']
        if not isinstance(ids, dict) or set(ids) != {'listing_ids', 'shop_ids'} or len(ids['listing_ids']) > 10 or len(ids['shop_ids']) > 5 or len(ids['listing_ids']) + len(ids['shop_ids']) > 15: raise ValueError('Bounded tracked cohort required')
        if bounds['max_requests'] != len(ids['listing_ids']) + len(ids['shop_ids']) or not lineage.get('cohort_id'): raise ValueError('Tracking demand/reservation mismatch')
        app.configuration()
        settings = {**app.settings, 'source': 'api', 'tracking': ids, 'shop_ids': [], 'daily_mode': 'tracking', 'max_pages': 1,
                    'max_shops': 0, 'max_requests_per_run': bounds['max_requests'], 'capture_images': False}
    else: raise ValueError('Unsupported controlled job kind')
    return validate_config(settings)


class Jobs:
    def __init__(self, app):
        self.app = app; self.root = app.store.directory / 'control-jobs'; self.root.mkdir(exist_ok=True)

    def submit(self, payload):
        settings = effective(self.app, payload)
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / (payload['job_id'] + '.json')
            sha = digest(payload)
            if path.exists():
                previous = json.loads(path.read_text())
                if previous['request_sha256'] != sha: raise ValueError('Controlled job identity collision')
                return {**self.public(previous), 'duplicate': True}
            # Root/iteration is reserved atomically in the collector too.
            if payload['kind'] == 'experiment':
                for old in self.root.glob('*.json'):
                    other = json.loads(old.read_text())['request']
                    if other['kind'] == 'experiment' and other['lineage']['root_cycle_id'] == payload['lineage']['root_cycle_id']:
                        raise ValueError('Root cycle already has a submitted experiment')
            run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12]
            row = {'job_id': payload['job_id'], 'run_id': run_id, 'status': 'queued', 'request_sha256': sha,
                   'request': payload, 'effective_settings': settings, 'accepted_at': now()}
            atomic_json(path, row)
            return {**self.public(row), 'duplicate': False}

    @staticmethod
    def public(row):
        return {k: row.get(k) for k in ('job_id', 'run_id', 'status', 'request_sha256', 'accepted_at', 'finished_at', 'request_count', 'error_type')}

    def tick(self):
        with (self.root / '.worker.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for path in sorted(self.root.glob('*.json')):
                row = json.loads(path.read_text()); snapshot = self.app.store.runs / row['run_id'] / 'snapshot.json'
                if row['status'] in {'completed', 'failed', 'requires_reconciliation', 'cancelled'}: continue
                if snapshot.exists():
                    saved = json.loads(snapshot.read_text())
                    if saved.get('finished_at'):
                        row.update(status='completed' if saved['status'] == 'success' else 'failed', finished_at=saved['finished_at'], request_count=saved.get('request_count'))
                        atomic_json(path, row); continue
                    if self.app.job and self.app.job.get('run_id') == row['run_id'] and self.app.job['status'] == 'running': continue
                if row['status'] != 'queued':
                    row.update(status='requires_reconciliation', error_type='InterruptedCollection', automatic_retry=False)
                    atomic_json(path, row); continue
                if self.app.paused(): continue
                if self.app.job and self.app.job['status'] == 'running': continue
                try:
                    # Recheck expiry and current safety settings immediately before dispatch.
                    settings = effective(self.app, row['request'])
                    row.update(status='dispatching', dispatched_at=now()); atomic_json(path, row)
                    context = {'run_id': row['run_id'], 'control_job_id': row['job_id'], 'lineage': row['request']['lineage'],
                               'artifact_kind': {'tracking':'tracking','experiment':'experiment','cycle_search':'discovery'}[row['request']['kind']],
                               'manifest_sha256': row['request']['manifest_sha256']}
                    self.app.start(settings['niches'], 'approved-' + row['request']['kind'], row['request']['kind'] == 'tracking', settings, context)
                    row['status'] = 'running'; atomic_json(path, row)
                except Exception as error:
                    row.update(status='failed', error_type=type(error).__name__, automatic_retry=False); atomic_json(path, row)
                break


def controller_request(app, route, payload=None):
    """Fixed loopback proxy; never expose auth file/token or accept arbitrary URLs."""
    import urllib.request
    if not app.controller_url: raise ValueError('Pipeline controller not configured')
    if not re.fullmatch(r'/(status|proposals/[a-f0-9]{64}/(decision|labels)|cohorts/[a-f0-9]{64}/decision|cycles(/[a-f0-9]{64}/decision)?|operations)', route): raise ValueError('Unsupported controller route')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args): raise ValueError('Controller redirects forbidden')
    url = app.controller_url + route
    request = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=3) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000: raise ValueError('Controller response too large')
    return json.loads(body)
