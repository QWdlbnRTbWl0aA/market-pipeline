"""Local dashboard and daily scheduler. Uses only Python's standard library."""
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import ipaddress
import json
import os
import signal
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo
from .core import ROOT, Store, atomic_json, config, now, validate_niche, validate_config


class App:
    def __init__(self, settings, data, config_path=None):
        self.settings = settings
        self.config_path = Path(config_path) if config_path else Path(data) / 'config.json'
        if not self.config_path.exists():
            atomic_json(self.config_path, settings)
        self.store = Store(data)
        self.stop_event=threading.Event()
        self.store.stop_event=self.stop_event
        self.active_thread=None
        self.job = None
        self.lock = threading.RLock()
        self.operations_root = os.environ.get('PIPELINE_OPERATIONS_ROOT')
        self.control_auth_file = os.environ.get('PIPELINE_CONTROL_AUTH_FILE')
        self.controller_url = os.environ.get('PIPELINE_CONTROLLER_URL')
        if self.controller_url:
            from urllib.parse import urlsplit
            parsed = urlsplit(self.controller_url)
            if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError('Fixed numeric-loopback controller required')
        from .control import Jobs
        self.control_jobs = Jobs(self)
        self.scheduler_enabled = False
        self.scheduler_error = None

    def configuration(self):
        with self.lock:
            body = self.config_path.read_bytes()
            self.settings = validate_config(json.loads(body))
            return {**self.settings,
                    'revision': hashlib.sha256(body).hexdigest(),
                    'credentials_present': bool(os.environ.get('ETSY_API_KEY') and os.environ.get('ETSY_API_SECRET')),
                    'daily_enabled': self.settings.get('daily_enabled', True),
                    'scheduler_enabled': self.scheduler_enabled, 'scheduler_error': self.scheduler_error, 'pipeline_paused': self.paused()}

    def save_configuration(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('configuration request must be an object')
        settings = validate_config(payload.get('settings'))
        with self.lock:
            if self.job and self.job['status'] == 'running':
                raise RuntimeError('wait for the current collection before editing configuration')
            if payload.get('revision') != self.configuration()['revision']:
                raise RuntimeError('configuration changed; reload the editor before saving')
            atomic_json(self.config_path, settings)
            self.settings = settings
        return self.configuration()

    def set_daily_enabled(self, payload, instant=None):
        if not isinstance(payload, dict) or set(payload) != {'enabled', 'revision'} or type(payload['enabled']) is not bool:
            raise ValueError('Use enabled true/false and the current configuration revision')
        with self.lock:
            current = self.configuration()
            if payload['revision'] != current['revision']:
                raise RuntimeError('configuration changed; reload before toggling daily runs')
            value = {**self.settings, 'daily_enabled': payload['enabled']}
            if payload['enabled'] and not current['daily_enabled']:
                # Enabling arms the next scheduled time, not a catch-up query now.
                local = (instant or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(value['timezone']))
                due = dt.datetime.combine(local.date(), dt.time.fromisoformat(value['daily_time']), local.tzinfo)
                if due <= local:
                    due += dt.timedelta(days=1)
                value['daily_resume_at'] = due.astimezone(dt.timezone.utc).isoformat()
            atomic_json(self.config_path, validate_config(value))
            self.settings = value
            return self.configuration()

    def trial_settings(self, parameters):
        if not isinstance(parameters, dict) or set(parameters) - {'keywords', 'niches', 'limit', 'shop_ids', 'exclude_fetched_listings', 'exclude_fetched_shops'}:
            raise ValueError('Use keywords or niches, limit, shop_ids and exclusion flags')
        if 'keywords' in parameters and 'niches' in parameters:
            raise ValueError('Use keywords or niches, not both')
        self.configuration()
        value = {**self.settings, 'source': 'api', 'daily_mode': 'search',
                 'niches': parameters.get('niches', [{'category': 'Trial search', 'keywords': parameters.get('keywords')}]),
                 'limit': parameters.get('limit'), 'shop_ids': parameters.get('shop_ids', []), 'max_pages': None}
        for key in ('exclude_fetched_listings', 'exclude_fetched_shops'):
            if key in parameters: value[key] = parameters[key]
        return validate_config(value)

    def paused(self):
        if not self.operations_root: return False
        path = Path(self.operations_root) / 'collector-paused.json'
        return path.exists() and json.loads(path.read_text()).get('paused', False)

    def start(self, niches, trigger='dashboard', tracking_only=False, settings_override=None, collection_context=None):
        with self.lock:
            if self.paused() or self.stop_event.is_set(): raise RuntimeError('Collector admission is paused or shutting down')
            if self.job and self.job['status'] == 'running':
                raise RuntimeError('another collection is running')
            job = {'status': 'running', 'started_at': now(), 'run_id': (collection_context or {}).get('run_id'), 'error': None}
            self.job = job
            settings = settings_override or self.settings
        def progress(run_id, value):
            with self.lock:
                job.update(run_id=run_id, progress=value)
        self.store.collection_context = collection_context or {}
        self.store.progress_callback = progress
        def work():
            try:
                run = self.store.track(settings, trigger) if tracking_only else self.store.collect(settings, niches, trigger)
                job.update(status=run['status'], run_id=run['run_id'])
            except Exception as error:
                job.update(status='failed', error=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        self.active_thread=threading.Thread(target=work, daemon=True);self.active_thread.start()
        return job

    def schedule_tick(self, instant=None):
        with self.lock:
            return self._schedule_tick(instant)

    def _schedule_tick(self, instant=None):
        self.configuration()
        if self.paused(): return False
        if not self.settings.get('daily_enabled', True):
            return False
        stamp = instant or dt.datetime.now(dt.timezone.utc)
        if self.settings.get('daily_resume_at') and stamp < dt.datetime.fromisoformat(self.settings['daily_resume_at']):
            return False
        local = stamp.astimezone(ZoneInfo(self.settings['timezone']))
        if getattr(self, 'schedule_skip_day', None) == local.date().isoformat():
            return False
        due = dt.time.fromisoformat(self.settings['daily_time'])
        day = local.date().isoformat()
        if local.time().replace(tzinfo=None) < due:
            return False
        marker = self.store.directory / 'schedule.json'
        # Use a separate OS lock to guarantee at most one daily start across servers.
        import fcntl
        with (self.store.directory / '.schedule.lock').open('a') as guard:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            if marker.exists() and json.loads(marker.read_text()).get('last_started_day') == day:
                return False
            self.start(self.settings['niches'], 'daily')
            atomic_json(marker, {'last_started_day': day, 'timezone': self.settings['timezone'], 'started_at': now()})
            return True

    def scheduler(self):
        self.scheduler_enabled = True
        while not self.stop_event.is_set():
            try:
                self.schedule_tick()
                self.scheduler_error = None
            except Exception as error:
                self.scheduler_error = type(error).__name__
            self.stop_event.wait(30)


def request_host_allowed(host, local_address, port):
    """Accept this connection's numeric interface address, plus localhost on loopback."""
    try:
        parsed = urlparse('http://' + host)
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return False
        if not parsed.hostname:
            return False
        if (parsed.port or 80) != port:
            return False
        address = ipaddress.ip_address(local_address)
        names = {name.strip().lower().rstrip('.') for name in os.environ.get('PIPELINE_DASHBOARD_HOSTNAMES','').split(',') if name.strip()}
        return parsed.hostname.rstrip('.') in names or parsed.hostname == str(address) or (parsed.hostname == 'localhost' and address.is_loopback)
    except ValueError:
        return False


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value, content_type='application/json', download_name=None):
            body = json.dumps(value, ensure_ascii=False).encode() if content_type == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            if download_name:
                self.send_header('Content-Disposition', f'attachment; filename="{download_name}"')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return request_host_allowed(self.headers.get('Host', ''),
                                        self.connection.getsockname()[0], self.server.server_port)

        def do_GET(self):
            if not self.valid_host():
                self.reply(403, {'error': 'use the dashboard interface IP and port'})
                return
            route = urlparse(self.path)
            params = parse_qs(route.query)
            try:
                if route.path == '/api/pipeline':
                    from .control import controller_request
                    self.reply(200, controller_request(app, '/status'))
                elif route.path == '/api/health':
                    self.reply(200, {'service': 'collector', 'status': 'running', 'scheduler_enabled': app.scheduler_enabled, 'scheduler_error': app.scheduler_error, 'job': app.job})
                elif route.path.startswith('/api/control/jobs/'):
                    from .control import authentication
                    if self.client_address[0] != '127.0.0.1' or not authentication(app.control_auth_file, self.headers.get('X-Pipeline-Control')):
                        self.reply(403, {'error': 'local control authentication required'}); return
                    key = route.path.rsplit('/', 1)[-1]
                    import re
                    if not re.fullmatch('[a-f0-9]{64}', key): raise ValueError('Invalid job ID')
                    value = json.loads((app.control_jobs.root / (key + '.json')).read_text())
                    self.reply(200, app.control_jobs.public(value))
                elif route.path == '/api/config':
                    self.reply(200, app.configuration())
                elif route.path == '/api/shops':
                    self.reply(200, app.store.known_shops())
                elif route.path == '/api/usage':
                    self.reply(200, app.store.request_usage(settings=app.settings))
                elif route.path == '/api/index':
                    index_path = app.store.directory / 'index.json'
                    if not index_path.exists():
                        app.store.rebuild_index()
                    self.reply(200, json.loads(index_path.read_text()))
                elif route.path.startswith('/api/history/'):
                    parts = route.path.strip('/').split('/')
                    if len(parts) != 4:
                        raise ValueError('invalid history route')
                    self.reply(200, app.store.history(parts[2], parts[3]))
                elif route.path == '/api/runs':
                    self.reply(200, app.store.list_runs())
                elif route.path == '/api/job':
                    self.reply(200, app.job)
                elif route.path == '/api/suggestions':
                    self.reply(200, app.store.suggestions(params.get('q', [''])[0], params.get('category', [''])[0]))
                elif route.path.startswith('/api/runs/'):
                    parts = route.path.strip('/').split('/')
                    run = app.store.read(parts[2])
                    if len(parts) == 3:
                        self.reply(200, run)
                    elif len(parts) == 4 and parts[3] == 'summary':
                        from .reporting import summarize
                        self.reply(200, summarize(run))
                    elif len(parts) == 4 and parts[3] == 'download':
                        from .reporting import compose_export
                        self.reply(200, compose_export(app.store, run['run_id']), download_name='etsy-' + run['run_id'] + '.json')
                    elif len(parts) == 4 and parts[3] == 'dqa':
                        self.reply(200, run.get('dqa', {'status': 'not yet available'}))
                    elif len(parts) == 5 and parts[3] == 'raw-file':
                        filename = parts[4]
                        responses = [p for q in run['queries'] for p in (q.get('pages') or [q])]
                        responses += run.get('tracked_listings', []) + run.get('shops', [])
                        if '/' in filename or not any(p.get('raw_file') == filename for p in responses):
                            raise FileNotFoundError()
                        body = (app.store.runs / run['run_id'] / filename).read_bytes()
                        self.reply(200, body, 'text/plain; charset=utf-8')
                    elif len(parts) == 5 and parts[3] == 'raw':
                        index = int(parts[4])
                        if index < 0:
                            raise ValueError('invalid raw index')
                        query = run['queries'][index]
                        if not query.get('raw_file'):
                            raise FileNotFoundError()
                        body = (app.store.runs / run['run_id'] / query['raw_file']).read_bytes()
                        # Serve as text, never execute untrusted Etsy HTML.
                        self.reply(200, body, 'text/plain; charset=utf-8')
                    else:
                        self.reply(404, {'error': 'not found'})
                elif route.path in {'/', '/v1', '/v1/', '/app.js', '/style.css'}:
                    name = {'/app.js': 'app.js', '/style.css': 'style.css'}.get(route.path, 'index.html')
                    mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8'}[name]
                    body = (ROOT / 'static' / name).read_bytes()
                    if name == 'index.html':
                        body = body.replace(b'__VERSION__', b'v1')
                    self.reply(200, body, mime)
                else:
                    self.reply(404, {'error': 'not found'})
            except FileNotFoundError:
                self.reply(404, {'error': 'file not found'})
            except (ValueError, IndexError, KeyError):
                self.reply(400, {'error': 'invalid request or unavailable run'})

        def do_POST(self):
            # LAN support retains browser same-origin and interface-host checks.
            origin = self.headers.get('Origin')
            host = self.headers.get('Host', '')
            if (not self.valid_host() or (origin and origin != f'http://{host}')
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.reply(403, {'error': 'same-origin requests to the dashboard interface only'})
                return
            if self.path == '/api/control/jobs':
                from .control import authentication
                if origin or self.client_address[0] != '127.0.0.1' or not authentication(app.control_auth_file, self.headers.get('X-Pipeline-Control')):
                    self.reply(403, {'error': 'local control authentication required'}); return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 16384: raise ValueError('Bounded job size required')
                    payload = json.loads(self.rfile.read(length))
                    self.reply(202, app.control_jobs.submit(payload))
                except (ValueError, TypeError, KeyError): self.reply(400, {'error': 'Invalid bounded control job'})
                return
            if self.path.startswith('/api/pipeline/'):
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 16384: raise ValueError('Bounded decision size required')
                    from .control import controller_request
                    self.reply(200, controller_request(app, self.path.removeprefix('/api/pipeline'), json.loads(self.rfile.read(length))))
                except (ValueError, OSError): self.reply(400, {'error': 'Pipeline decision unavailable or invalid'})
                return
            if self.path not in {'/api/collect', '/api/config', '/api/track', '/api/scheduled-search', '/api/daily-enabled'}:
                self.reply(404, {'error': 'not found'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16_384:
                    raise ValueError('request must be 1–16384 bytes')
                payload = json.loads(self.rfile.read(length))
                if self.path == '/api/daily-enabled':
                    self.reply(200, app.set_daily_enabled(payload))
                    return
                if self.path == '/api/scheduled-search':
                    value = app.trial_settings(payload.get('parameters'))
                    self.reply(200, app.save_configuration({'settings': value, 'revision': payload.get('revision')}))
                    return
                if self.path == '/api/config':
                    self.reply(200, app.save_configuration(payload))
                    return
                if self.path == '/api/track':
                    if not any(app.settings.get('tracking', {}).get(key) for key in ('listing_ids', 'shop_ids')):
                        raise ValueError('Select listing or shop IDs in Configuration first')
                    self.reply(202, app.start([], 'dashboard-tracking', tracking_only=True))
                    return
                if 'parameters' in payload:
                    value = app.trial_settings(payload['parameters'])
                    self.reply(202, app.start(value['niches'], settings_override=value))
                    return
                niches = payload.get('niches', app.settings['niches'])
                if not isinstance(niches, list) or not 1 <= len(niches) <= 10:
                    raise ValueError('select between 1 and 10 niches')
                niches = [validate_niche(n) for n in niches]
                self.reply(202, app.start(niches))
            except RuntimeError as error:
                self.reply(409, {'error': str(error)})
            except (ValueError, AttributeError) as error:
                self.reply(400, {'error': str(error)})

        def log_message(self, format, *args):
            pass
    return Handler


def serve(settings, data, port=8090, schedule=True, host='127.0.0.1', config_path=None, defer_today=False):
    app = App(settings, data, config_path)
    if defer_today:
        app.schedule_skip_day = dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo(settings['timezone'])).date().isoformat()
    # Build compact legacy metadata once and warm request history before serving.
    app.store.list_runs()
    app.store.request_usage(settings=app.settings)
    server = ThreadingHTTPServer((host, port), handler(app))
    def controls():
        while not app.stop_event.is_set():
            try: app.control_jobs.tick()
            except (OSError, ValueError, BlockingIOError): pass
            app.stop_event.wait(2)
    threading.Thread(target=controls, daemon=True).start()
    if schedule:
        threading.Thread(target=app.scheduler, daemon=True).start()
    print(f'Dashboard listening: http://{host}:{port} (daily scheduler {"on" if schedule else "off"})', flush=True)
    def shutdown(*unused):
        app.stop_event.set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    try:server.serve_forever()
    finally:
        app.stop_event.set();server.server_close()
        if app.active_thread:app.active_thread.join(timeout=45)
