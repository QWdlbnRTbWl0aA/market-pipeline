"""Synthetic research payloads; no paid inference, source requests or email."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from xml.etree import ElementTree
from product_service.core import SavedReportIntake, process
from product_service.server import server


def fixture():
    statement = {'text': 'Synthetic classroom printable', 'basis': 'design_hypothesis', 'evidence_ids': ['fixture-1']}
    brief = {'product_concept': 'Synthetic learning cards', 'intended_customer': statement,
             'customer_job': statement, 'differentiation': statement, 'deliverables': [statement],
             'acceptance_checks': ['Fixture print check'], 'validation_plan': ['Fixture interview'], 'risks': ['Fixture risk']}
    return {'service': 'market_insights', 'status': 'completed', 'delivery_id': 'a' * 64, 'job_id': 'synthetic',
            'source_run_id': 'fixture', 'report': {'recommendations': [{'candidate_id': 'fixture-1', 'rationale': 'Fixture evidence', 'product_brief': brief}]}}


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_flow_is_idempotent_and_creates_valid_three_drafts(self):
        body = json.dumps(fixture()).encode()
        result = process(body, self.root)
        folder = Path(result['directory']); state_before = (folder / 'state.json').read_bytes()
        self.assertEqual(result['products'], 1)
        self.assertEqual(len(list(folder.glob('product-*/*.svg'))), 3)
        for draft in folder.glob('product-*/*.svg'):
            ElementTree.fromstring(draft.read_text())
        self.assertTrue(process(body, self.root)['duplicate'])
        self.assertEqual(state_before, (folder / 'state.json').read_bytes())
        changed = fixture(); changed['report']['recommendations'][0]['rationale'] = 'Changed content'
        with self.assertRaises(ValueError): process(json.dumps(changed).encode(), self.root)

    def test_text_is_escaped_and_no_source_commands_executed(self):
        value = fixture(); value['report']['recommendations'][0]['product_brief']['product_concept'] = '<script>alert(1)</script> $(touch /tmp/not-executed)'
        result = process(json.dumps(value).encode(), self.root)
        svg = (Path(result['directory']) / 'product-01/draft-cover.svg').read_text()
        self.assertNotIn('<script>', svg); self.assertIn('&lt;script&gt;', svg)

    def test_failed_analysis_is_preserved_without_products(self):
        value = fixture(); value['status'] = 'failed'; value.pop('report')
        result = process(json.dumps(value).encode(), self.root)
        self.assertEqual(result['status'], 'ignored_failed_analysis'); self.assertEqual(result['products'], 0)

    def test_credentials_and_incomplete_briefs_rejected(self):
        value = fixture(); value['api_key'] = 'synthetic-secret'
        with self.assertRaises(ValueError): process(json.dumps(value).encode(), self.root)
        value = fixture(); del value['report']['recommendations'][0]['product_brief']['deliverables']
        with self.assertRaises(ValueError): process(json.dumps(value).encode(), self.root)
        for variable in ('ETSY_API_KEY', 'OPENAI_API_KEY', 'SMTP_PASSWORD'):
            with patch.dict('os.environ', {variable: 'fixture'}):
                with self.assertRaises(ValueError): process(json.dumps(fixture()).encode(), self.root)

    def test_intake_never_opens_credentials_or_urls(self):
        with patch('pathlib.Path.read_bytes', side_effect=AssertionError('Credential opened')):
            with self.assertRaises(ValueError): SavedReportIntake().read(self.root / '.env_files/etsy.env')
            with self.assertRaises(ValueError): SavedReportIntake().read('https://api.etsy.com/listings')

    def test_http_ack_duplicates_collision_and_worker(self):
        http = server(self.root, 0); thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        url = 'http://127.0.0.1:%s/market-insights' % http.server_port
        def post(value):
            request = urllib.request.Request(url, data=json.dumps(value).encode(), headers={'Content-Type': 'application/json', 'Idempotency-Key': value['delivery_id']})
            with urllib.request.urlopen(request, timeout=3) as response: return json.loads(response.read())
        try:
            self.assertFalse(post(fixture())['duplicate']); self.assertTrue(post(fixture())['duplicate'])
            changed = fixture(); changed['status'] = 'failed'
            with self.assertRaises(urllib.error.HTTPError) as error: post(changed)
            self.assertEqual(error.exception.code, 409)
            deadline = time.monotonic() + 3
            receipt = self.root / 'intake' / ('a' * 64 + '.result')
            while not receipt.exists() and time.monotonic() < deadline: time.sleep(.02)
            self.assertEqual(json.loads(receipt.read_text())['status'], 'completed')
        finally:
            http.shutdown(); http.stop_worker(); http.server_close(); thread.join()

    def test_durable_intake_resumes_on_start(self):
        value = fixture(); body = json.dumps(value)
        inbox = self.root / 'intake'; inbox.mkdir()
        (inbox / ('a' * 64 + '.json')).write_text(json.dumps({'body': body, 'sha256': hashlib.sha256(body.encode()).hexdigest()}))
        http = server(self.root, 0)
        try:
            deadline = time.monotonic() + 3
            receipt = inbox / ('a' * 64 + '.result')
            while not receipt.exists() and time.monotonic() < deadline: time.sleep(.02)
            self.assertEqual(json.loads(receipt.read_text())['products'], 1)
        finally: http.stop_worker(); http.server_close()
