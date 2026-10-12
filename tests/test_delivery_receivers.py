"""Real loopback receiver contract tests with synthetic analyzer artifacts only."""
import copy
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
for service in ('analyzer', 'controller', 'product'):
    sys.path.insert(0, str(ROOT / 'services' / service))
sys.path.insert(0, str(ROOT / 'deploy'))
from prepare import prepare
from analyzer.delivery import deliver
from analyzer.io import write_json
from product_service.core import validate, process
from product_service.definition import enhanced
from product_service.server import server as product_server
from pipeline_control.server import server as controller_server


def preview():
    return {'schema_version': 1, 'service': 'market_insights', 'status': 'completed',
            'job_id': 'a' * 64, 'delivery_id': 'b' * 64, 'source_run_id': 'fixture',
            'report': {'status': 'local_preview', 'execution_mode': 'local_only', 'final_model_completed': False,
                       'recommendations': [{'candidate_id': 'c1', 'rationale': 'Synthetic saved observation',
                                            'product_brief': None}]}}


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        prepare(self.root / 'state', self.root / 'config')
        cfg = json.loads((self.root / 'config/controller.json').read_text())
        self.product = product_server(self.root / 'product', 0)
        self.controller = controller_server(cfg, 0)
        self.receivers = (self.product, self.controller)
        self.controller.stop_worker()  # Delivery contract only, no experiment preparation.
        for server in self.receivers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(self.stop)

    def stop(self):
        for server in self.receivers:
            server.stop_worker(); server.shutdown(); server.worker.join(timeout=2); server.server_close()

    def post(self, server, route, payload):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        request = urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+route, data=body,
                                         headers={'Content-Type': 'application/json', 'Idempotency-Key': 'b' * 64})
        return urllib.request.urlopen(request, timeout=3)

    def test_preview_is_acknowledged_and_durably_waits_without_product_generation(self):
        value = preview()
        with self.post(self.product, '/market-insights', value) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)['product_status'], 'awaiting_product_brief')
        inbox = self.root / 'product/intake'
        for _ in range(100):
            if list(inbox.glob('*.result')): break
            time.sleep(.01)
        result = json.loads(next(inbox.glob('*.result')).read_text())
        self.assertEqual(result['status'], 'awaiting_product_brief')
        self.assertEqual(result['products'], 0)
        self.assertEqual(list((self.root / 'product').rglob('*.svg')), [])
        body = json.dumps(value).encode()
        with patch('product_service.definition.OllamaDefinition', side_effect=AssertionError('Model forbidden')):
            outcome = enhanced(body, self.root / 'enhanced')
        self.assertEqual(outcome['status'], 'awaiting_product_brief')
        self.assertTrue(enhanced(body, self.root / 'enhanced')['duplicate'])

    def test_invalid_nested_shapes_get_400_and_receiver_stays_healthy(self):
        for bad in ([None], {'product_brief': None}, {'product_brief': []}, None):
            value = preview(); value['report']['status'] = 'provisional'
            value['report']['recommendations'] = bad if isinstance(bad, list) or bad is None else [bad]
            with self.subTest(bad=bad), self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(self.product, '/market-insights', value)
            self.assertEqual(caught.exception.code, 400); caught.exception.close()
        for server in self.receivers:
            with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/health', timeout=3) as response:
                self.assertEqual(response.status, 200)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post(self.controller, '/search-refinement', b'[]')
        self.assertEqual(caught.exception.code, 400); caught.exception.close()

    def test_oversize_headers_get_413_without_reading_body(self):
        for server, route in ((self.product, '/market-insights'), (self.controller, '/search-refinement')):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                connection.putrequest('POST', route)
                connection.putheader('Content-Length', '5000001'); connection.endheaders()
                response = connection.getresponse(); self.assertEqual(response.status, 413); response.read()
            finally: connection.close()

    def test_storage_failure_gets_transient_503(self):
        with patch('product_service.server.write_json', side_effect=OSError('Fixture disk failure')):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(self.product, '/market-insights', preview())
            self.assertEqual(caught.exception.code, 503); caught.exception.close()
        with patch.object(self.controller.controller, 'receive', side_effect=OSError('Fixture disk failure')):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(self.controller, '/search-refinement', preview())
            self.assertEqual(caught.exception.code, 503); caught.exception.close()

    def test_pretty_to_compact_replay_is_semantically_idempotent(self):
        for server, route, service in ((self.product, '/market-insights', 'market_insights'),
                                       (self.controller, '/search-refinement', 'search_refinement')):
            value = preview(); value['service'] = service
            pretty = json.dumps(value, indent=2).encode()
            compact = json.dumps(value, separators=(',', ':'), sort_keys=True).encode()
            with self.post(server, route, pretty) as response: self.assertEqual(response.status, 200)
            with self.post(server, route, compact) as response: self.assertTrue(json.load(response)['duplicate'])
            altered = copy.deepcopy(value); altered['source_run_id'] = 'different'
            with self.assertRaises(urllib.error.HTTPError) as caught: self.post(server, route, altered)
            self.assertIn(caught.exception.code, (400, 409)); caught.exception.close()

    def test_large_saved_artifact_compacts_and_delivers_to_both_real_receivers(self):
        for server, service, route in ((self.product, 'market_insights', '/market-insights'),
                                       (self.controller, 'search_refinement', '/search-refinement')):
            value = preview(); value['service'] = service
            value['report']['recommendations'][0]['facts'] = {'history': [{'sample': 'synthetic', 'value': None}] * 100000}
            directory = self.root / 'outputs' / service / ('a' * 64)
            write_json(directory / 'outbound.json', value)
            original = (directory / 'outbound.json').read_bytes()
            self.assertGreater(len(original), 5_000_000)
            state = {'job_id': 'a' * 64, 'service': service, 'source_run_id': 'fixture',
                     'delivery_id': 'b' * 64, 'delivery_status': 'pending', 'analysis_status': 'completed'}
            endpoint = 'http://127.0.0.1:'+str(server.server_port)+route
            result = deliver(directory, state, endpoint)
            self.assertTrue(result['delivered']); self.assertLess(result['payload_bytes'], 5_000_000)
            self.assertEqual((directory / 'outbound.json').read_bytes(), original)
            self.assertEqual(state['delivery_id'], value['delivery_id'])
