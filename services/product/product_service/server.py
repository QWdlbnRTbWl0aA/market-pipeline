"""Loopback HTTP saved intake, durable queue and local studio handoff worker."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from .core import MAX_BYTES, clean_environment, now, process, validate, valid_key, write_json, waiting_for_brief


def server(root, port=8093, definition_config=None, operations_root=None, brief_model=None):
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
    if policy and policy['mail']['enabled']:
        from pipeline_mail import write,read
        activation=root/'mail-activation.json'
        if not activation.exists():write(activation,{'at':now()})
        mail_since=read(activation)['at']

    def worker():
        while not stop.is_set():
            pause = Path(operations_root) / 'product-paused.json' if operations_root else None
            if pause and pause.exists() and json.loads(pause.read_text()).get('paused'):
                stop.wait(1); continue
            for path in sorted(inbox.glob('*.json')):
                receipt = path.with_suffix('.result')
                if receipt.exists() and (not policy or not policy['mail']['enabled'] or path.with_suffix('.mail').exists()) and (not policy or not policy['studio_delivery']['enabled'] or path.with_suffix('.studio').exists()):continue
                try:
                    record = json.loads(path.read_text())
                    if receipt.exists():
                        result=json.loads(receipt.read_text())
                    elif policy and policy['enhanced_enabled']:
                        from .definition import enhanced, OllamaDefinition
                        result = enhanced(record['body'].encode(), root / 'definition-outbox', OllamaDefinition(policy['model'],policy['ollama_url']), qualification_root=policy['qualification_root'])
                    else:
                        from .briefing import default_model
                        model=brief_model or default_model(policy.get('briefing') if policy else None)
                        result = process(record['body'].encode(), root / 'studio-outbox', model)
                except Exception as error:
                    result = {'status': 'failed', 'error_type': type(error).__name__, 'automatic_retry': False}
                if not receipt.exists():write_json(receipt, result)
                if policy and policy['studio_delivery']['enabled'] and result.get('directory') and not path.with_suffix('.studio').exists():
                    try:
                        from .studio_delivery import prepare as queue_studio
                        queued=queue_studio(result,root,policy['studio_delivery']);write_json(path.with_suffix('.studio'),{'status':'queued','brief_ids':queued})
                    except Exception as error:write_json(path.with_suffix('.studio'),{'status':'preparation_failed','error_type':type(error).__name__})
                mail_receipt=path.with_suffix('.mail')
                if policy and policy['mail']['enabled'] and result.get('directory') and record.get('received_at','')>=mail_since and not mail_receipt.exists():
                    try:
                        from .automatic_mail import prepare
                        prepared=prepare(result,root,policy['mail']);write_json(mail_receipt,{'status':'queued','outbox':str(prepared)})
                    except Exception as error:write_json(mail_receipt,{'status':'preparation_failed','error_type':type(error).__name__,'definition_unaffected':True})
            if policy and policy['mail']['enabled']:
                try:
                    from .automatic_mail import deliver
                    deliver(root,policy['mail'])
                except Exception as error:write_json(root/'mail-worker-error.json',{'error_type':type(error).__name__})
            if policy and policy['studio_delivery']['enabled']:
                try:
                    from .studio_delivery import tick as deliver_studio
                    deliver_studio(root,policy['studio_delivery'])
                except Exception as error:write_json(root/'studio-worker-error.json',{'error_type':type(error).__name__})
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
                    self.close_connection = True
                    self.reply(413, {'error': 'Payload size', 'max_bytes': MAX_BYTES}); return
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
                    if duplicate:
                        old = json.loads(path.read_text())
                        if old['sha256'] != digest and json.dumps(json.loads(old['body']),sort_keys=True,allow_nan=False) != json.dumps(payload,sort_keys=True,allow_nan=False):
                            self.reply(409, {'error': 'Identity collision'}); return
                    if not duplicate:
                        write_json(path, {'received_at': now(), 'sha256': digest, 'body': body.decode()})
                wake.set()
                self.reply(200, {'accepted': True, 'job_id': key, 'duplicate': duplicate,
                                 'product_status': 'awaiting_product_brief' if waiting_for_brief(payload) else 'queued'})
            except (ValueError, TypeError, AttributeError, KeyError):
                self.reply(400, {'error': 'Invalid saved market analysis'})
            except OSError:
                self.reply(503, {'error': 'Intake storage unavailable'})

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    http.worker = threading.Thread(target=worker, daemon=True)
    http.worker.start()
    http.stop_worker = stop.set
    return http
