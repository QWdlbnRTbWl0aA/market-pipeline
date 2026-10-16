"""Small same-origin Studio API and static approval interface."""
import ipaddress
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
from .core import Studio
from .storage import Conflict, Invalid, canonical, read, reject_secrets

STATIC = Path(__file__).parent / 'static'
LOG = logging.getLogger(__name__)
DEFAULT = {'schema_version': 1, 'sketch_provider': 'mock', 'professional_provider': 'mock',
           'broker_provider': 'mock', 'listing_provider': 'blocked', 'allowed_hostnames': [], 'development_openai': False}


def configuration(path=None):
    config = read(path) if path else dict(DEFAULT)
    reject_secrets(config)
    if isinstance(config,dict):config={'development_openai':False,**config}
    if not isinstance(config, dict) or set(config) != set(DEFAULT): raise Invalid('Unexpected Studio configuration')
    for key in ('schema_version', 'sketch_provider', 'professional_provider', 'broker_provider', 'listing_provider'):
        allowed=('mock','openai_dev') if key in ('sketch_provider','professional_provider') else ('mock','file') if key=='broker_provider' else (DEFAULT[key],)
        if config[key] not in allowed: raise Invalid('Unknown provider or live listing is forbidden')
    if type(config['development_openai']) is not bool:raise Invalid('Explicit development setting required')
    if any(config[k]=='openai_dev' for k in ('sketch_provider','professional_provider')) and not config['development_openai']:raise Invalid('OpenAI is development-only')
    names = config['allowed_hostnames']
    if not isinstance(names, list) or len(names) > 20 or any(not isinstance(n, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}', n) for n in names):
        raise Invalid('Invalid allowed hostnames')
    return config


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, studio, config=None):
        self.studio = studio; self.config = config or DEFAULT
        self.stop_worker = threading.Event(); self.worker = None
        super().__init__(address, Handler)

    def start_worker(self):
        def work():
            while not self.stop_worker.is_set():
                try: self.studio.tick()
                except Exception: LOG.exception('Studio worker tick failed; artifacts preserved')
                self.stop_worker.wait(0.4)
        self.worker = threading.Thread(target=work, name='studio-generation', daemon=True); self.worker.start()

    def server_close(self):
        self.stop_worker.set()
        if self.worker: self.worker.join(timeout=5)
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *args): pass

    def reply(self, status, body, media='application/json', filename=None):
        if not isinstance(body, bytes): body = canonical(body)
        self.send_response(status)
        self.send_header('Content-Type', media); self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if filename: self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers(); self.wfile.write(body)

    def trusted_host(self):
        raw = self.headers.get('Host', '')
        if any(c in raw for c in '/\\@\r\n'): return False
        try:
            parsed = urlsplit('http://'+raw); host = parsed.hostname
            if parsed.port != self.server.server_port: return False
            if host in ('localhost', *self.server.config['allowed_hostnames']): return True
            address = ipaddress.ip_address(host)
            bound = self.server.server_address[0]
            return str(address) == bound or (bound == '0.0.0.0' and address.version == 4)
        except (ValueError, TypeError): return False

    def route(self, mutate=False):
        if not self.trusted_host(): self.reply(403, {'error': 'Untrusted Host'}); return
        if mutate:
            origin = self.headers.get('Origin')
            if (origin and origin != 'http://'+self.headers['Host']) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self.reply(403, {'error': 'Same-origin requests required'}); return
        path = urlsplit(self.path).path
        if mutate: self.post(path)
        else: self.get(path)

    def do_GET(self): self.safe_route()
    def do_POST(self): self.safe_route(True)

    def safe_route(self, mutate=False):
        try: self.route(mutate)
        except Conflict as error: self.reply(409, {'error': str(error)})
        except (Invalid, ValueError, TypeError, KeyError, RecursionError): self.reply(400, {'error': 'Invalid request or workflow transition'})
        except FileNotFoundError: self.reply(404, {'error': 'Not found'})
        except Exception:
            LOG.exception('Studio HTTP request failed'); self.reply(500, {'error': 'Request failed; saved artifacts preserved'})

    def get(self, path):
        studio = self.server.studio
        if path == '/health': return self.reply(200, {'status': 'running', 'providers': getattr(studio.sketches,'name','mock'), 'etsy_connected': False})
        if path in ('/', '/app.js', '/style.css'):
            filename, media = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}[path]
            return self.reply(200, (STATIC / filename).read_bytes(), media)
        if path == '/api/projects': return self.reply(200, {'projects': studio.list()})
        if path == '/api/runtime':return self.reply(200,{'sketch_provider':getattr(studio.sketches,'name','mock'),
            'professional_provider':getattr(studio.professional,'name','mock'),'development':studio.development,
            'understanding_provider':getattr(studio.understanding,'name','local'),
            'broker_provider':getattr(studio.broker,'name','custom'),'listing_provider':'blocked',
            'spending':studio.budget.summary('')})
        payload_match=re.fullmatch(r'/api/projects/([a-f0-9]{32})/payloads(?:/([a-f0-9]{64})(/body)?)?',path)
        if payload_match:
            project,call_id,body_only=payload_match.groups()
            result=studio.payloads(project,call_id)
            if body_only:return self.reply(200,result['body'],filename='studio-api-body.json')
            return self.reply(200,result)
        match = re.fullmatch(r'/api/projects/([a-f0-9]{32})(?:/(download|asset|reasoning)/?([a-f0-9]{32}-[0-9]{1,2})?)?', path)
        if match:
            project, kind, candidate_id = match.groups(); state = studio.get(project)
            if kind=='reasoning':
                if not studio.development:return self.reply(404,{'error':'Development log disabled'})
                logs=[read(p) for p in (studio.directory(project)/'reasoning-log').glob('*.json')]
                return self.reply(200,{'entries':sorted(logs,key=lambda r:r['at'])})
            if kind == 'download':
                if state['phase'] != 'approved': raise Conflict('Approve a final sample before downloading')
                return self.reply(200, (studio.directory(project) / 'product.zip').read_bytes(), 'application/zip', 'studio-product.zip')
            if kind == 'asset':
                candidate = next((c for r in state['rounds'] for c in r['candidates'] if c['id'] == candidate_id), None)
                if not candidate: raise FileNotFoundError()
                file = studio.directory(project) / candidate['file']
                if file.is_symlink() or not file.resolve().is_relative_to(studio.directory(project)): raise Invalid('Invalid asset')
                return self.reply(200, file.read_bytes(), candidate.get('media_type','image/svg+xml'))
            return self.reply(200, {'project': state})
        self.reply(404, {'error': 'Not found'})

    def post(self, path):
        if self.headers.get('Transfer-Encoding'): raise Invalid('Chunked input unsupported')
        length = int(self.headers.get('Content-Length', '0'))
        if length <= 0: raise Invalid('JSON body required')
        self.connection.settimeout(5)
        if length > 1_000_000:
            # Drain a bounded near-limit body so ordinary clients can receive the
            # admission response instead of racing a closed socket while sending.
            # Very large senders must handle early connection rejection themselves.
            if length <= 2_000_000:
                try: self.rfile.read(length)
                except OSError: pass
            return self.reply(413, {'error': 'Brief exceeds 1MB'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': 'application/json required'})
        body = self.rfile.read(length)
        if len(body) != length: raise Invalid('Incomplete body')
        payload = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(Invalid('Non-finite JSON')))
        key = self.headers.get('Idempotency-Key')
        if path in ('/api/briefs','/api/library/briefs'):
            return self.reply(200,self.server.studio.create(payload,key,library=True))
        match = re.fullmatch(r'/api/projects/([a-f0-9]{32})/actions/([a-z_]+)', path)
        if match: return self.reply(200, self.server.studio.command(*match.groups(), payload, key))
        self.reply(404, {'error': 'Not found'})
