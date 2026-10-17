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


class FixtureBrief:
    """Synthetic provider, injected explicitly: unit tests never use live models."""
    def __init__(self):self.calls=0
    def generate(self,context):
        self.calls+=1;ref=context['samples'][0]['evidence_id']
        return {'definition':{'title':context['initial_direction']['product_concept'],
            'audience':'Adults guiding children','customer_job':'Practice sorting shapes',
            'product_mechanism':'Sort cut-out shape cards onto matching shapes',
            'scope':'Four shape cards plus a one-page adult setup guide',
            'components':[{'name':'Shape cards','quantity':4,'format':'A4 PDF; four cards per page',
                'content':['Circle: match the round outline','Square: match four equal sides','Triangle: match three corners','Rectangle: match two long sides'],'evidence_ids':[ref]},
                {'name':'Adult guide','quantity':1,'format':'A4 PDF','content':['Print at actual size; adult cuts cards; child sorts onto outlines.'],'evidence_ids':[ref]}],
            'first_sketch':{'component':'Shape cards','composition':'Four equal cards in a two-by-two grid with matching outlines',
                'exact_visible_text':['Match the shapes','Circle','Square','Triangle','Rectangle'],
                'illustration_subjects':['Circle, square, triangle and rectangle outlines'],
                'interaction':'Child places each adult-cut shape on its matching outline',
                'style':'Proposed flat geometric outlines','palette':['Black outlines','White background'],
                'typography':'Large sans serif labels','avoid':['Decorative background behind outlines'],'reference_evidence_ids':[ref]},
            'customer_use_steps':['Adult prints and cuts the cards','Child matches shapes to outlines'],
            'production_files':['A4 PDF at actual size; 10 mm margins','Editable vector master'],
            'acceptance_checks':['All four shapes appear once and have matching outlines','No cut line crosses text'],
            'proposed_choices_and_assumptions':['Four shapes and flat outlines are original design choices'],
            'reference_interpretation':[{'evidence_id':sample['evidence_id'],'observed_content':sample.get('description_excerpt') or sample['title'],
                'use_for_our_product':'A printable sorting interaction','do_not_copy':'Source artwork and branded wording'} for sample in context['samples'][:2]]},
            'metadata':{'provider':'synthetic','paid_calls':0},'raw':{'synthetic':True}}


def fixture():
    statement = {'text': 'Synthetic classroom printable', 'basis': 'design_hypothesis', 'evidence_ids': ['fixture-1']}
    brief = {'product_concept': 'Synthetic learning cards', 'intended_customer': statement,
             'customer_job': statement, 'differentiation': statement, 'deliverables': [statement],
             'acceptance_checks': ['Fixture print check'], 'validation_plan': ['Fixture interview'], 'risks': ['Fixture risk']}
    return {'service': 'market_insights', 'status': 'completed', 'delivery_id': 'a' * 64, 'job_id': 'synthetic',
            'source_run_id': 'fixture', 'report': {'recommendations': [{'candidate_id': 'fixture-1', 'rationale': 'Fixture evidence', 'product_brief': brief,
                'evidence_excerpts':[{'evidence_id':'fixture-1','listing_id':'1','shop_id':'4','title':'Synthetic classroom cards',
                    'description_excerpt':'Printable classroom cards','url':'https://www.etsy.com/listing/1/synthetic-test-reference'}]}]}}


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.model=FixtureBrief();self.factory=patch('product_service.briefing.default_model',return_value=self.model)
        self.factory.start();self.addCleanup(self.factory.stop)
        self.media=patch('product_service.visual_references.fetch',side_effect=AssertionError('Synthetic tests forbid external media'))
        self.media.start();self.addCleanup(self.media.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_flow_is_idempotent_and_defines_real_content_without_mock_art(self):
        body = json.dumps(fixture()).encode()
        result = process(body, self.root)
        folder = Path(result['directory']); state_before = (folder / 'state.json').read_bytes()
        self.assertEqual(result['products'], 1)
        self.assertEqual(list(folder.glob('product-*/*.svg')), [])
        product=json.loads((folder/'product-01/product.json').read_text())
        self.assertEqual(product['definition']['components'][0]['quantity'],4)
        self.assertIn('https://www.etsy.com/listing/1/',(folder/'product-01/brief.html').read_text())
        self.assertEqual(json.loads((folder/'studio-handoff.json').read_text())['products'][0]['brief'],product)
        self.assertTrue(process(body, self.root)['duplicate'])
        self.assertEqual(state_before, (folder / 'state.json').read_bytes())
        self.assertEqual(self.model.calls,1)
        changed = fixture(); changed['report']['recommendations'][0]['rationale'] = 'Changed content'
        with self.assertRaises(ValueError): process(json.dumps(changed).encode(), self.root)

    def test_text_is_escaped_and_no_source_commands_executed(self):
        value = fixture(); value['report']['recommendations'][0]['product_brief']['product_concept'] = '<script>alert(1)</script> $(touch /tmp/not-executed)'
        result = process(json.dumps(value).encode(), self.root)
        page = (Path(result['directory']) / 'product-01/brief.html').read_text()
        self.assertNotIn('<script>', page); self.assertIn('&lt;script&gt;', page)

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
