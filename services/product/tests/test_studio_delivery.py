"""Actual local HTTP, saved Product fixtures, no inference or external API calls."""
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
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'studio'))
from studio_service.core import Studio
from studio_service.server import Server
from studio_service.adapters import MockGenerator
from studio_service.storage import read
from product_service.core import process
from product_service.studio_delivery import policy,prepare,tick,backfill,recover
from test_flow import fixture,FixtureBrief


class Generator(MockGenerator):
    def __init__(self):self.calls=0
    def generate(self,request):self.calls+=1;return super().generate(request)


class StudioDelivery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        factory=patch('product_service.briefing.default_model',return_value=FixtureBrief());factory.start();self.addCleanup(factory.stop)
        media=patch('product_service.visual_references.fetch',side_effect=AssertionError('Synthetic tests forbid media retrieval'));media.start();self.addCleanup(media.stop)
        self.generator=Generator();self.studio=Studio(self.root/'studio',sketches=self.generator)
        self.http=Server(('127.0.0.1',0),self.studio);self.http.start_worker();threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.settings=policy({'enabled':True,'endpoint':f'http://127.0.0.1:{self.http.server_port}/api/library/briefs','max_attempts':2,'retry_seconds':1})
    def tearDown(self):self.http.shutdown();self.http.server_close()
    def result(self):return process(json.dumps(fixture()).encode(),self.root/'product/studio-outbox')
    def test_delivery_and_backfill_never_generate_repeated_import_is_same_library_entry(self):
        result=self.result();keys=prepare(result,self.root/'product',self.settings)
        states=tick(self.root/'product',self.settings);self.assertEqual(states[0]['status'],'delivered')
        project=states[0]['project_id'];saved=self.studio.get(project)
        self.assertEqual(saved['phase'],'brief_ready');self.assertEqual(saved['rounds'],[]);self.assertEqual(self.generator.calls,0)
        self.assertEqual(saved['source_brief'],json.loads((Path(result['directory'])/'product-01/product.json').read_bytes()))
        self.assertEqual(backfill(self.root/'product',self.settings),keys)
        tick(self.root/'product',self.settings);self.assertEqual(len(self.studio.list()),1)
        state=self.studio.get(project);brief={**state['brief'],'visual_direction':'Soft watercolor'}
        state=self.studio.command(project,'update_brief',{'revision':state['revision'],'brief':brief},'edit')['project']
        self.studio.tick();self.assertEqual(state['phase'],'brief_ready');self.assertEqual(self.generator.calls,0)
        payload={'revision':state['revision']};started=self.studio.command(project,'start_sketches',payload,'human-start')
        self.assertTrue(self.studio.command(project,'start_sketches',payload,'human-start')['duplicate'])
        self.studio.tick();self.assertEqual(self.generator.calls,1);self.assertEqual(len(self.studio.get(project)['rounds'][0]['candidates']),3)
        # Timeout after successful save is safe to replay with the exact identity.
        directory=self.root/'product/studio-delivery'/keys[0]
        request_body=(directory/'payload.json').read_bytes()
        duplicate=self.studio.create(json.loads(request_body),keys[0],library=True)
        self.assertTrue(duplicate['duplicate']);self.assertEqual(len(self.studio.list()),1)
    def test_complete_import_and_refresh_stay_idle_without_budget_or_broker_work(self):
        brief={'concept':'Wall art','audience':'Families','purpose':'Decorate','deliverables':['Five prints'],'visual_direction':'Watercolor'}
        state=self.studio.create(brief,'complete')['project']
        self.assertEqual(state['phase'],'brief_ready')
        with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            for _ in range(3):self.studio.tick();self.studio.list();self.studio.get(state['id'])
        self.assertEqual(self.generator.calls,0)
        self.assertFalse((self.root/'studio/development-openai/budget.json').exists())
        self.assertFalse(list((self.root/'studio/broker-outbox').glob('*.json')))
    def test_payload_tamper_is_held_before_any_http_request(self):
        keys=prepare(self.result(),self.root/'product',self.settings)
        directory=self.root/'product/studio-delivery'/keys[0]
        (directory/'payload.json').write_text('{}')
        def forbidden(*args,**kwargs):self.fail('Tampered payload was sent')
        state=tick(self.root/'product',self.settings,forbidden)[0]
        self.assertEqual(state['status'],'permanent_failure');self.assertEqual(self.studio.list(),[])
    def test_retry_limit_permanent_errors_recovery_and_attempt_history(self):
        keys=prepare(self.result(),self.root/'product',self.settings)
        def unavailable(*args,**kwargs):raise urllib.error.URLError('offline')
        for at in (1,2,3):tick(self.root/'product',self.settings,unavailable,at=at)
        directory=self.root/'product/studio-delivery'/keys[0];state=read(directory/'delivery.json')
        self.assertEqual(state['status'],'retries_exhausted');self.assertEqual(state['attempts'],2)
        self.assertTrue((directory/'failure-event.json').exists())
        recover(self.root/'product',keys[0],self.settings,'Receiver corrected')
        self.assertEqual(tick(self.root/'product',self.settings,at=4)[0]['status'],'delivered')
        self.assertEqual(len(list(directory.glob('attempt-*.json'))),3)
        with self.assertRaises(ValueError):recover(self.root/'product',keys[0],self.settings,'Do not resend delivered')
    def test_wrong_routes_remote_endpoints_and_receiver_old_release_fail_closed(self):
        for endpoint in ('http://127.0.0.1:8096/api/briefs','https://api.etsy.com/api/library/briefs','http://192.0.2.1:8096/api/library/briefs'):
            with self.assertRaises(ValueError):policy({'endpoint':endpoint})
        keys=prepare(self.result(),self.root/'product',self.settings)
        def old_receiver(request,timeout):raise urllib.error.HTTPError(request.full_url,404,'old release',{},None)
        self.assertEqual(tick(self.root/'product',self.settings,old_receiver)[0]['status'],'permanent_failure')
        self.assertEqual(tick(self.root/'product',self.settings),[]);self.assertEqual(self.studio.list(),[])
    def test_product_worker_wires_incoming_saved_analysis_to_passive_library(self):
        from product_service.server import server
        config=json.loads((Path(__file__).resolve().parents[3]/'config/product.example.json').read_text())
        config['studio_delivery']=self.settings;path=self.root/'product-config.json';path.write_text(json.dumps(config))
        producer=server(self.root/'product',0,path)
        threading.Thread(target=producer.serve_forever,daemon=True).start()
        try:
            body=json.dumps(fixture()).encode();url=f'http://127.0.0.1:{producer.server_port}/market-insights'
            request=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json','Idempotency-Key':'a'*64})
            with urllib.request.urlopen(request,timeout=3) as response:self.assertTrue(json.load(response)['accepted'])
            end=time.monotonic()+4
            while not self.studio.list() and time.monotonic()<end:time.sleep(.05)
            self.assertEqual(len(self.studio.list()),1);self.assertEqual(self.generator.calls,0)
            with urllib.request.urlopen(request,timeout=3) as response:self.assertTrue(json.load(response)['duplicate'])
            self.assertEqual(len(self.studio.list()),1)
        finally:producer.stop_worker();producer.shutdown();producer.worker.join(timeout=5);producer.server_close()
    def test_enhanced_saved_brief_is_delivered_with_full_source_requirements(self):
        from product_service.definition import enhanced
        from test_definition import LocalFixture
        value=fixture();value['report']['recommendations'][0]['evidence_excerpts']=[{'evidence_id':'fixture-1','listing_id':'1','title':'Synthetic card'}]
        result=enhanced(json.dumps(value).encode(),self.root/'product/definition-outbox',LocalFixture(),True)
        self.assertEqual(result['status'],'completed_drafts')
        self.assertEqual(len(prepare(result,self.root/'product',self.settings)),1)
        state=tick(self.root/'product',self.settings)[0];self.assertEqual(state['status'],'delivered')
        saved=self.studio.get(state['project_id']);self.assertEqual(saved['phase'],'brief_ready')
        self.assertTrue(saved['source_brief']['source_requirements']);self.assertEqual(self.generator.calls,0)
