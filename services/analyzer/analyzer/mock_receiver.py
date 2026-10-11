"""Local development receiver: preserve requests and durable idempotent ACKs."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from .io import now, write_json


def server(output, port=8092):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path not in {'/search-refinement', '/market-insights'}:
                self.send_error(404); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 5_000_000:
                    raise ValueError('Payload limit')
                body = self.rfile.read(length)
                payload = json.loads(body)
                key = self.headers.get('Idempotency-Key', '')
                if len(key) != 64 or any(c not in '0123456789abcdef' for c in key) or payload.get('delivery_id') != key:
                    raise ValueError('Invalid idempotency key')
                digest = hashlib.sha256(body).hexdigest()
                with lock:
                    record = root / (key+'.json')
                    duplicate = record.exists()
                    if duplicate and json.loads(record.read_text())['sha256'] != digest:
                        self.send_error(409); return
                    count = len(list(root.glob(key+'-request-*.json'))) + 1
                    write_json(root / (key+f'-request-{count:04d}.json'), {'received_at': now(), 'path': self.path, 'payload': payload, 'sha256': digest, 'duplicate': duplicate})
                    if not duplicate:
                        write_json(root / (key+'.json'), {'received_at': now(), 'path': self.path, 'payload': payload,
                                                     'sha256': digest, 'duplicate': duplicate})
                    acknowledgement = {'accepted': True, 'job_id': key, 'duplicate': duplicate}
                    write_json(root / (key+'-ack.json'), acknowledgement)
                response = json.dumps(acknowledgement).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(response)));self.end_headers();self.wfile.write(response)
            except (ValueError, OSError, TypeError):
                self.send_error(400)
        def log_message(self, *args):
            pass
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='test-output/receiver')
    parser.add_argument('--port', type=int, default=8092)
    args = parser.parse_args()
    server(args.output, args.port).serve_forever()
