"""Bounded HTTP delivery, immutable source artifacts and durable failure-event outbox."""
import datetime as dt
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from .io import now, write_json
from .lifecycle import digest
from .security import LocalHTTP, local_url, assert_clean_environment

TERMINAL = {'permanent_failure', 'retries_exhausted'}
DEFAULTS = {'max_attempts': 5, 'retry_base_seconds': 30, 'retry_max_seconds': 3600,
            'max_payload_bytes': 5_000_000}
EVENT_DEFAULTS = {'enabled': False, 'endpoint': None, 'max_attempts': 3, 'retry_seconds': 60}


def policy(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {*DEFAULTS, 'failure_events'}:
        raise ValueError('Invalid delivery policy fields')
    result = {**DEFAULTS, **value}
    for name, maximum in (('max_attempts', 10000), ('max_payload_bytes', 5_000_000)):
        if type(result[name]) is not int or not 1 <= result[name] <= maximum:
            raise ValueError('Invalid delivery attempt/payload bound')
    for name in ('retry_base_seconds', 'retry_max_seconds'):
        x = result[name]
        if type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 86400:
            raise ValueError('Invalid delivery retry interval')
    if result['retry_max_seconds'] < result['retry_base_seconds']:
        raise ValueError('Maximum retry interval below base')
    events = value.get('failure_events', {})
    if not isinstance(events, dict) or set(events) - set(EVENT_DEFAULTS):
        raise ValueError('Invalid failure-event policy fields')
    events = {**EVENT_DEFAULTS, **events}
    if type(events['enabled']) is not bool or type(events['max_attempts']) is not int or not 1 <= events['max_attempts'] <= 100:
        raise ValueError('Invalid failure-event retry bound')
    seconds = events['retry_seconds']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 86400:
        raise ValueError('Invalid failure-event retry interval')
    if events['enabled'] or events['endpoint'] is not None:
        local_url(events['endpoint'])
    result['failure_events'] = events
    return result


def iso(timestamp):
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat()


def retry_after(headers, timestamp):
    value = (headers or {}).get('Retry-After')
    if value is None:
        return 0
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - timestamp
        except (ValueError, TypeError, OverflowError):
            return 0
    return seconds if math.isfinite(seconds) and 0 <= seconds <= 31_536_000 else 0


def http_failure(status):
    if status in (408, 425, 429) or 500 <= status <= 599 and status not in (501, 505):
        return 'transient'
    return 'permanent'


def transport_failure(error):
    return 'transient' if isinstance(error, (OSError, urllib.error.URLError, http.client.HTTPException)) else 'permanent'


def attempt_count(directory, state):
    """Honor old numbered receipts; imported evidence receipts retain their attempt field."""
    paths = list(directory.glob('delivery-*.json'))
    counts = [state.get('delivery_attempts_total', 0)]
    for path in paths:
        match = re.fullmatch(r'delivery-(\d+)\.json', path.name)
        if match:
            counts.append(int(match[1]))
        elif path.name in ('delivery-first.json', 'delivery-last.json'):
            counts.append(json.loads(path.read_text()).get('attempt', 0))
    return max(counts)


def failure_event(directory, state, config):
    root = Path(config.get('output_root', directory.parent.parent))
    generation = state.get('delivery_generation', 0)
    key = digest({'job': state['job_id'], 'delivery': state['delivery_id'], 'generation': generation})
    event = {'schema_version': 1, 'event_id': key, 'event_type': 'analysis_delivery_failed',
             'at': now(), 'service': state.get('service', directory.parent.name), 'job_id': state['job_id'],
             'source_run_id': state.get('source_run_id'), 'delivery_id': state['delivery_id'],
             'delivery_generation': generation, 'delivery_status': state['delivery_status'],
             'attempts_total': state.get('delivery_attempts_total', 0),
             'attempts_in_generation': state.get('delivery_attempts_in_generation', 0),
             'last_http_status': state.get('delivery_last_http_status'),
             'last_error_type': state.get('delivery_last_error_type'),
             'reason': state.get('delivery_failure_reason'), 'outbound_artifact': str(directory / 'outbound.json'),
             'explicit_recovery_required': True}
    # This file is the local publication, even when the optional broker relay is off.
    path = root / 'delivery-failures' / (key + '.json')
    if not path.exists():
        write_json(path, event)
    state['delivery_failure_event_id'] = key
    write_json(directory / 'state.json', state)
    return key


def publish_failure_events(config, transport=None, timestamp=None):
    """Optional HTTP broker relay: bounded, independent, at-least-once by event ID."""
    assert_clean_environment()
    cfg = policy(config.get('delivery'))['failure_events']
    if not cfg['enabled']:
        return []
    timestamp = time.time() if timestamp is None else timestamp
    transport = transport or LocalHTTP()
    results = []
    root = Path(config['output_root']) / 'delivery-failures'
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.publisher.lock').open('a') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []  # Another watcher publishes; optional relay must not block this service.
        for path in sorted(root.glob('*.json')):
            if path.name.endswith('.publication.json'):
                continue
            receipt_path = path.with_suffix('.publication.json')
            receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {'attempts': 0}
            if receipt.get('status') in ('published', 'permanent_failure', 'retries_exhausted') or receipt.get('next_attempt_at', 0) > timestamp:
                continue
            if receipt['attempts'] >= cfg['max_attempts']:
                receipt['status'] = 'retries_exhausted'
                write_json(receipt_path, receipt)
                continue
            event = json.loads(path.read_text())
            receipt.update(attempts=receipt['attempts']+1, status='pending_unknown',
                           next_attempt_at=timestamp+cfg['retry_seconds'], event_id=event['event_id'])
            write_json(receipt_path, receipt)  # Count uncertain/crashed publications before sending.
            req = urllib.request.Request(cfg['endpoint'], data=path.read_bytes(),
                                         headers={'Content-Type': 'application/json', 'Idempotency-Key': event['event_id']})
            classification = 'transient'
            try:
                with transport(req, timeout=10) as response:
                    status = response.status
                    receipt['next_attempt_at'] = max(receipt['next_attempt_at'], timestamp+retry_after(getattr(response, 'headers', {}), timestamp))
                receipt['http_status'] = status
                receipt['status'] = 'published' if 200 <= status < 300 else 'pending'
                classification = http_failure(status)
            except urllib.error.HTTPError as error:
                receipt.update(http_status=error.code, status='pending')
                receipt['next_attempt_at'] = max(receipt['next_attempt_at'], timestamp+retry_after(error.headers, timestamp))
                classification = http_failure(error.code)
                error.close()
            except Exception as error:
                receipt.update(status='pending', error_type=type(error).__name__)
                classification = transport_failure(error)
            if receipt['status'] != 'published':
                if classification == 'permanent': receipt['status'] = 'permanent_failure'
                elif receipt['attempts'] >= cfg['max_attempts']: receipt['status'] = 'retries_exhausted'
            write_json(receipt_path, receipt)
            results.append(receipt)
            if len(results) >= 1:
                break
    return results


def deliver(directory, state, endpoint, transport=None, config=None, timestamp=None):
    assert_clean_environment()
    directory = Path(directory)
    config = config or {}
    cfg = policy(config.get('delivery'))
    timestamp = time.time() if timestamp is None else timestamp
    transport = transport or LocalHTTP()
    if state.get('delivery_status') == 'delivered':
        return {'skipped': True, 'delivered': True}
    if state.get('delivery_status') in TERMINAL:
        failure_event(directory, state, config)
        return {'skipped': True, 'delivery_status': state['delivery_status']}
    if state.get('delivery_next_attempt_at', 0) > timestamp:
        return {'skipped': True, 'delivery_status': 'waiting'}
    total = attempt_count(directory, state)
    generation_attempts = state.get('delivery_attempts_in_generation', total)
    state.update(delivery_attempts_total=total, delivery_attempts_in_generation=generation_attempts)
    if generation_attempts >= cfg['max_attempts']:
        state.update(delivery_status='retries_exhausted', delivery_failure_reason='retry_limit_reached')
        failure_event(directory, state, config)
        return {'skipped': True, 'delivery_status': 'retries_exhausted'}
    source = (directory / 'outbound.json').read_bytes()
    result = {'attempt': total+1, 'at': iso(timestamp), 'endpoint': endpoint,
              'idempotency_key': state['delivery_id'], 'delivered': False,
              'request_attempted': False,
              'source_payload_sha256': hashlib.sha256(source).hexdigest()}
    classification = 'permanent'
    wait = min(cfg['retry_max_seconds'], cfg['retry_base_seconds'] * 2 ** min(generation_attempts, 20))
    try:
        endpoint = local_url(endpoint)
        value = json.loads(source)
        if not isinstance(value, dict) or value.get('delivery_id') != state['delivery_id']:
            raise ValueError('Saved delivery identity mismatch')
        payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False).encode()
        result.update(payload_sha256=hashlib.sha256(payload).hexdigest(), payload_bytes=len(payload))
        if len(payload) > cfg['max_payload_bytes']:
            result.update(http_status=413, error={'type': 'PayloadTooLarge', 'message': 'Compact payload exceeds receiver bound'})
        else:
            wire = directory / 'outbound-wire.json'
            if wire.exists() and wire.read_bytes() != payload:
                raise ValueError('Saved wire artifact mismatch')
            if not wire.exists(): write_json(wire, value, compact=True)
            # Reserve this attempt before HTTP. Restart cannot evade the retry cap.
            state.update(delivery_attempts_total=total+1, delivery_attempts_in_generation=generation_attempts+1,
                         delivery_next_attempt_at=timestamp+wait, delivery_status='pending')
            write_json(directory / 'state.json', state)
            write_json(directory / f'delivery-{total+1:04d}.json', {**result, 'status': 'attempting'})
            req = urllib.request.Request(endpoint, data=payload, headers={'Content-Type': 'application/json',
                                          'Idempotency-Key': state['delivery_id']})
            result['request_attempted'] = True
            try:
                with transport(req, timeout=10) as response:
                    result['http_status'] = response.status
                    result['delivered'] = 200 <= response.status < 300
                    classification = http_failure(response.status)
                    wait = max(wait, retry_after(getattr(response, 'headers', {}), timestamp))
                    response.read(4097)  # Bound consumption; don't persist arbitrary echoed source content.
            except urllib.error.HTTPError as error:
                result.update(http_status=error.code, error={'type': 'HTTPError', 'message': 'HTTP delivery rejected'})
                classification = http_failure(error.code)
                wait = max(wait, retry_after(error.headers, timestamp))
                error.close()
            except Exception as error:
                classification = transport_failure(error)
                result['error'] = {'type': type(error).__name__, 'message': 'Delivery transport failed'}
    except (ValueError, TypeError, UnicodeError) as error:
        result['error'] = {'type': type(error).__name__, 'message': 'Invalid saved delivery artifact or endpoint'}
    result['classification'] = 'success' if result['delivered'] else classification
    state.update(delivery_attempts_total=total+1, delivery_attempts_in_generation=generation_attempts+1,
                 delivery_next_attempt_at=timestamp+wait, updated_at=iso(timestamp),
                 delivery_last_http_status=result.get('http_status'),
                 delivery_last_error_type=result.get('error', {}).get('type'))
    if result['delivered']:
        state['delivery_status'] = 'delivered'
    elif classification == 'permanent':
        state.update(delivery_status='permanent_failure', delivery_failure_reason=result.get('error', {}).get('type', 'http_rejection'))
    elif generation_attempts+1 >= cfg['max_attempts']:
        state.update(delivery_status='retries_exhausted', delivery_failure_reason='retry_limit_reached')
    else:
        state['delivery_status'] = 'pending'
    write_json(directory / f'delivery-{total+1:04d}.json', result)
    write_json(directory / 'state.json', state)
    if state['delivery_status'] in TERMINAL:
        failure_event(directory, state, config)
    return result


def saved_directory(config, service, job_id):
    if service not in ('search_refinement', 'market_insights') or not re.fullmatch('[a-f0-9]{64}', job_id):
        raise ValueError('One saved service/job required')
    directory = Path(config['output_root']).resolve() / service / job_id
    if directory.is_symlink() or not directory.is_dir() or directory.resolve().parent.parent != Path(config['output_root']).resolve():
        raise ValueError('Unknown regular saved job')
    return directory


def saved_state(directory, service, job_id):
    state = json.loads((directory / 'state.json').read_text())
    if state.get('job_id') != job_id or state.get('service') != service or state.get('analysis_status') not in ('completed', 'failed', 'budget_waiting'):
        raise ValueError('Finalized saved analysis required')
    source_id = state.get('source_run_id')
    if not isinstance(source_id, str) or Path(source_id).name != source_id or source_id in ('.', '..'):
        raise ValueError('Valid saved source identity required')
    return state


def retry_saved(config, service, job_id, transport=None, timestamp=None):
    """A pending watcher retry stays bound to its saved job, even after config changes."""
    assert_clean_environment()
    directory = saved_directory(config, service, job_id)
    with (directory / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        state = saved_state(directory, service, job_id)
        deliver(directory, state, config['endpoints'][service], transport, config, timestamp)
        return {**state, 'directory': str(directory)}


def recover(config, service, job_id, reason, transport=None, timestamp=None):
    """Explicit delivery-only recovery; preserves analysis, identities and every receipt."""
    assert_clean_environment()
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError('Bounded recovery reason required')
    directory = saved_directory(config, service, job_id)
    with (directory / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        state = saved_state(directory, service, job_id)
        if state.get('delivery_status') == 'delivered': return {**state, 'duplicate_recovery': True}
        generation = state.get('delivery_generation', 0)+1
        write_json(directory / f'delivery-recovery-{generation:04d}.json',
                   {'at': now(), 'reason': reason, 'previous_state': state, 'new_generation': generation})
        state.update(delivery_generation=generation, delivery_attempts_in_generation=0,
                     delivery_attempts_total=attempt_count(directory, state), delivery_next_attempt_at=0,
                     delivery_status='pending')
        state.pop('delivery_failure_reason', None)
        state.pop('delivery_failure_event_id', None)
        write_json(directory / 'state.json', state)
        deliver(directory, state, config['endpoints'][service], transport, config, timestamp)
        from .lifecycle import Cursor
        cursor = Path(config['output_root']) / 'lifecycle' / 'cursors' / service / (state['source_run_id']+'.json')
        if cursor.exists(): Cursor(config['output_root'], service).finish(state['source_run_id'], state)
        return state
