"""Loopback HTTP saved intake, durable queue and local studio handoff worker."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from .core import MAX_BYTES, clean_environment, now, process, validate, valid_key, write_json


def server(root, port=8093, definition_config=None, operations_root=None):
    clean_environment()
    policy = None
    if definition_config:
        from .configuration import load
        policy = load(definition_config)
    root = Path(root)
    inbox = root / 'intake'
    inbox.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    wake = threading.Event()
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            pause = Path(operations_root) / 'product-paused.json' if operations_root else None
            if pause and pause.exists() and json.loads(pause.read_text()).get('paused'):
                stop.wait(1); continue
            for path in sorted(inbox.glob('*.json')):
                receipt = path.with_suffix('.result')
                if receipt.exists():
                    continue
                try:
                    record = json.loads(path.read_text())
                    if policy and policy['enhanced_enabled']:
                        from .definition import enhanced, OllamaDefinition
                        result = enhanced(record['body'].encode(), root / 'definition-outbox', OllamaDefinition(policy['model'],policy['ollama_url']), qualification_root=policy['qualification_root'])
                    else:
                        result = process(record['body'].encode(), root / 'studio-outbox')
                except Exception as error:
                    result = {'status': 'failed', 'error_type': type(error).__name__, 'automatic_retry': False}
                write_json(receipt, result)
            wake.wait(1)
            wake.clear()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != '/health':
                self.reply(404, {'error': 'Unknown route'}); return
            self.reply(200, {'service': 'product', 'status': 'running',
                             'worker_alive': self.server.worker.is_alive(), 'enhanced_enabled': bool(policy and policy['enhanced_enabled']),
                             'received': len(list(inbox.glob('*.json'))),
                             'processed': len(list(inbox.glob('*.result'))),
                             'studio_outbox': str((root / 'studio-outbox').resolve())})

        def do_POST(self):
            if self.headers.get('Origin') or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self.reply(403, {'error': 'Local service interface only'}); return
            if self.path != '/market-insights':
                self.reply(404, {'error': 'Unknown route'}); return
            try:
                self.connection.settimeout(10)
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BYTES:
                    raise ValueError('Payload size')
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('Incomplete body')
                payload = json.loads(body)
                validate(payload)
                key = valid_key(self.headers.get('Idempotency-Key'))
                if payload['delivery_id'] != key:
                    raise ValueError('Mismatched identity')
                digest = hashlib.sha256(body).hexdigest()
                with lock:
                    path = inbox / (key + '.json')
                    duplicate = path.exists()
                    if duplicate and json.loads(path.read_text())['sha256'] != digest:
                        self.reply(409, {'error': 'Identity collision'}); return
                    if not duplicate:
                        write_json(path, {'received_at': now(), 'sha256': digest, 'body': body.decode()})
                wake.set()
                self.reply(200, {'accepted': True, 'job_id': key, 'duplicate': duplicate, 'product_status': 'queued'})
            except (ValueError, TypeError, OSError):
                self.reply(400, {'error': 'Invalid saved market analysis'})

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    http.worker = threading.Thread(target=worker, daemon=True)
    http.worker.start()
    http.stop_worker = stop.set
    return http
