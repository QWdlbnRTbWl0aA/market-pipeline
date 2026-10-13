import gzip
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

from studio_service.adapters import MockGenerator, checked_asset
from studio_service.core import Studio
from studio_service.ports import Asset
from studio_service.server import Server, configuration
from studio_service.storage import Invalid, Conflict, read, write

BRIEF = {'concept':'Weekly meal planner','audience':'Busy families','purpose':'Plan meals and shopping',
         'deliverables':['Weekly grid','Shopping list'],'visual_direction':'Warm minimal printable','requirements':'Readable typography'}
SETTINGS = {'width':210,'height':297,'unit':'mm','dpi':150,'format':'svg','color_mode':'color','bleed_mm':0}


class RecordingGenerator(MockGenerator):
    def __init__(self): self.requests=[]
    def generate(self, request): self.requests.append(request); return super().generate(request)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.generator=RecordingGenerator()
        self.studio=Studio(self.tmp.name,sketches=self.generator,professional=self.generator); self.sequence=0
    def tearDown(self): self.tmp.cleanup()
    def create(self, brief=None):
        state=self.studio.create(brief or BRIEF,'intake')['project']; self.project=state['id']; self.studio.tick(); return self.state()
    def state(self): return self.studio.get(self.project)
    def act(self, action, **extra):
        self.sequence+=1;return self.studio.command(self.project,action,{'revision':self.state()['revision'],**extra},str(self.sequence))['project']
    def accept(self):
        candidate=self.state()['rounds'][-1]['candidates'][0]['id']
        return {candidate:{'decision':'accept_with_comments','comment':'Keep the writing space'}}
    def professional(self):
        self.create();self.act('generate_final',reviews=self.accept(),settings=SETTINGS,consent_expensive=True);self.studio.tick();return self.state()

    def test_missing_information_broker_durable_and_idempotent(self):
        state=self.create({'concept':'Planner'});self.assertEqual(state['phase'],'needs_information')
        self.assertEqual(len(self.generator.requests),0);self.assertEqual(len(state['missing_information']),4)
        message=next((Path(self.tmp.name)/'mock-broker').glob('*.json'));event=read(message)
        self.assertIn('למי מיועד המוצר?',event['message']);self.assertEqual(event['brief']['concept'],'Planner')
        self.studio.tick();self.assertEqual(len(list(message.parent.glob('*.json'))),1)
        self.assertEqual(self.state()['notification']['delivery']['status'],'recorded')
        self.act('update_brief',brief=BRIEF);self.studio.tick();self.assertEqual(len(self.state()['rounds'][-1]['candidates']),3)

    def test_sketch_round_carries_accepted_comments_and_rejected_references(self):
        state=self.create();self.assertEqual(len(state['rounds'][0]['candidates']),3)
        reviews=self.accept();rejected=state['rounds'][0]['candidates'][1]['id'];reviews[rejected]={'decision':'reject','comment':'Too crowded'}
        self.act('next_sketches',reviews=reviews,comments='More breathing room');self.studio.tick()
        request=self.generator.requests[-1];self.assertEqual(request['count'],3)
        self.assertEqual(request['accepted'][0]['review']['comment'],'Keep the writing space')
        self.assertEqual(request['rejected'][0]['id'],rejected);self.assertEqual(request['last_feedback'],'More breathing room')
        self.assertTrue((self.studio.directory(self.project)/request['accepted'][0]['file']).exists())

    def test_start_over_compacts_full_interaction_as_negative_example(self):
        self.create();self.act('save_feedback',reviews=self.accept(),comments='Wrong direction')
        original=self.state();state=self.act('start_over',comments='Explore a different layout')
        self.assertEqual(state['epoch'],2);self.assertEqual(state['rounds'],[])
        self.assertEqual(state['negative_summary']['review_counts']['accept_with_comments'],1)
        archived=json.loads(gzip.decompress((self.studio.directory(self.project)/state['archives'][0]['file']).read_bytes()))
        import hashlib
        raw=(self.studio.directory(self.project)/state['archives'][0]['file']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),state['archives'][0]['sha256'])
        self.assertEqual(hashlib.sha256(gzip.decompress(raw)).hexdigest(),state['archives'][0]['content_sha256'])
        self.assertEqual(archived['rounds'][0]['candidates'],original['rounds'][0]['candidates'])
        self.assertEqual(archived['interaction'][0]['payload']['comments'],'Wrong direction')
        self.assertEqual(archived['interaction'][-1]['payload']['comments'],'Explore a different layout')
        self.studio.tick();request=self.generator.requests[-1];self.assertEqual(request['accepted'],[])
        self.assertEqual(request['negative_summary']['abandoned_epochs'],1);self.assertEqual(len(request['archived_negative_examples']),1)

    def test_professional_loop_three_samples_settings_back_and_final_blocked(self):
        state=self.professional();self.assertEqual(len(state['rounds'][-1]['candidates']),3)
        self.assertEqual(self.generator.requests[-1]['settings']['pixel_width'],1240)
        self.act('next_professional',reviews=self.accept(),consent_expensive=True);self.studio.tick()
        self.assertEqual(self.generator.requests[-1]['count'],3)
        self.act('back_to_sketches',reviews=self.accept());self.studio.tick();self.assertEqual(self.state()['phase'],'sketch_review')
        self.act('generate_final',reviews=self.accept(),settings=SETTINGS,consent_expensive=True);self.studio.tick()
        selected=next(iter(self.accept()));self.act('approve_final',reviews=self.accept(),candidate_id=selected)
        state=self.state();self.assertEqual(state['phase'],'approved');self.assertFalse(state['listing']['etsy_api_called'])
        directory=self.studio.directory(self.project);self.assertEqual(read(directory/'listing-handoff.json')['status'],'blocked_not_wired')
        with zipfile.ZipFile(directory/'product.zip') as output:
            self.assertEqual(set(output.namelist()),{'product.svg','metadata.json','README.txt'})
            self.assertFalse(json.loads(output.read('metadata.json'))['sale_ready'])
        with self.assertRaises(Conflict):self.act('start_over')

    def test_expensive_consent_and_size_validation_before_generation(self):
        self.create();revision=self.state()['revision']
        for params in ({}, {'consent_expensive':True,'settings':{**SETTINGS,'width':8192}}):
            with self.assertRaises(Invalid):self.act('generate_final',reviews=self.accept(),**params)
            self.assertEqual(self.state()['revision'],revision)
        self.assertEqual(len(self.generator.requests),1)

    def test_stale_review_and_duplicate_actions_do_not_generate_twice(self):
        self.create();payload={'revision':self.state()['revision'],'reviews':self.accept()}
        first=self.studio.command(self.project,'next_sketches',payload,'same');self.studio.tick()
        self.assertTrue(self.studio.command(self.project,'next_sketches',payload,'same')['duplicate'])
        self.assertEqual(len(self.generator.requests),2)
        with self.assertRaises(Conflict):self.studio.command(self.project,'save_feedback',payload,'stale')
        with self.assertRaises(Conflict):self.studio.command(self.project,'next_sketches',{**payload,'comments':'different'},'same')
        self.assertFalse(first['duplicate'])

    def test_final_approval_replay_preserves_original_artifacts(self):
        self.professional();reviews=self.accept();selected=next(iter(reviews))
        payload={'revision':self.state()['revision'],'reviews':reviews,'candidate_id':selected}
        self.studio.command(self.project,'approve_final',payload,'approval')
        directory=self.studio.directory(self.project)
        before={name:(directory/name).read_bytes() for name in ('approved-product.json','listing-handoff.json','product.zip')}
        self.assertTrue(Studio(self.tmp.name).command(self.project,'approve_final',payload,'approval')['duplicate'])
        self.assertEqual(before,{name:(directory/name).read_bytes() for name in before})
        self.assertEqual(len(self.generator.requests),2)

    def test_approval_write_interruption_resumes_original_reservation(self):
        self.professional();reviews=self.accept();selected=next(iter(reviews));directory=self.studio.directory(self.project)
        payload={'revision':self.state()['revision'],'reviews':reviews,'candidate_id':selected}
        with patch('studio_service.core.write_bytes',side_effect=OSError('Synthetic write failure')):
            with self.assertRaises(OSError):self.studio.command(self.project,'approve_final',payload,'approval')
        reserved=(directory/'approved-product.json').read_bytes()
        self.assertEqual(self.state()['phase'],'professional_review')
        self.studio.command(self.project,'approve_final',payload,'approval')
        self.assertEqual((directory/'approved-product.json').read_bytes(),reserved)
        self.assertEqual(self.state()['phase'],'approved')

    def test_provider_request_response_and_asset_hashes_survive_restart(self):
        import hashlib
        self.create();state=self.state();folder=self.studio.directory(self.project)/'generations'/state['active_operation']
        for candidate in read(folder/'response.json')['candidates']:
            raw=(self.studio.directory(self.project)/candidate['file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),candidate['sha256'])
        self.assertEqual(read(folder/'request.json')['brief'],BRIEF)
        self.assertEqual(read(folder/'operation.json')['status'],'completed')
        Studio(self.tmp.name).tick();self.assertEqual(self.state()['rounds'],state['rounds'])

    def test_intake_key_conflict_and_restart_preserve_work(self):
        self.create();self.assertTrue(self.studio.create(BRIEF,'intake')['duplicate'])
        with self.assertRaises(Conflict):self.studio.create({**BRIEF,'concept':'Other'},'intake')
        self.studio=Studio(self.tmp.name,sketches=self.generator);self.studio.tick();self.assertEqual(len(self.generator.requests),1)

    def test_all_rejected_samples_can_iterate_and_invalid_comments_fail(self):
        self.create();reviews={c['id']:{'decision':'reject'} for c in self.state()['rounds'][-1]['candidates']}
        self.act('next_sketches',reviews=reviews);self.studio.tick()
        self.assertEqual(len(self.generator.requests[-1]['rejected']),3)
        with self.assertRaises(Invalid):self.act('save_feedback',reviews={self.state()['rounds'][-1]['candidates'][0]['id']:{'decision':'accept_with_comments'}})

    def test_interrupted_generation_never_automatically_repeats(self):
        self.project=self.studio.create(BRIEF,'intake')['project']['id']
        state=self.state();folder=self.studio.directory(self.project)/'generations'/state['active_operation']
        write(folder/'operation.json',{'status':'started'})
        self.studio.tick();self.assertEqual(self.state()['phase'],'generation_failed');self.assertEqual(len(self.generator.requests),0)
        self.act('retry_generation');self.studio.tick();self.assertEqual(len(self.generator.requests),1)

    def test_parallel_workers_do_not_mark_live_generation_interrupted(self):
        entered=threading.Event();release=threading.Event();generator=self.generator
        def slow(request):entered.set();release.wait(3);return MockGenerator().generate(request)
        generator.generate=slow;self.project=self.studio.create(BRIEF,'intake')['project']['id']
        worker=threading.Thread(target=self.studio.tick);worker.start();self.assertTrue(entered.wait(2))
        Studio(self.tmp.name).tick();self.assertEqual(self.state()['phase'],'generating_sketch')
        release.set();worker.join(3);self.assertFalse(worker.is_alive());self.assertEqual(self.state()['phase'],'sketch_review')

    def test_provider_failure_retained_and_explicit_recovery_only(self):
        self.generator.generate=lambda request: []
        self.create();self.assertEqual(self.state()['phase'],'generation_failed')
        self.studio.tick();self.assertEqual(self.state()['phase'],'generation_failed')
        folder=self.studio.directory(self.project)/'generations'/self.state()['active_operation']
        self.assertEqual(read(folder/'operation.json')['error_type'],'Invalid')
        self.generator.generate=MockGenerator().generate;self.act('retry_generation');self.studio.tick();self.assertEqual(self.state()['phase'],'sketch_review')

    def test_broker_failure_does_not_generate_or_lose_message_and_is_bounded(self):
        class Broken:
            def publish(self,message):raise RuntimeError('Unavailable')
        self.studio.broker=Broken();self.create({'concept':'Planner'})
        for _ in range(6):self.studio.tick()
        self.assertEqual(self.state()['notification']['delivery']['attempts'],3)
        self.assertEqual(self.state()['phase'],'needs_information');self.assertEqual(len(self.generator.requests),0)

    def test_product_handoff_normalizes_and_requests_missing_style(self):
        state=self.create({'vision':'Meal planner','customer':{'text':'Families'},'customer_job':{'text':'Plan meals'},'deliverables':['Grid']})
        self.assertEqual(state['brief']['audience'],'Families');self.assertEqual(state['missing_information'][0]['field'],'visual_direction')

    def test_no_credentials_no_network_and_listing_injection_blocked(self):
        with patch.dict(os.environ,{'ETSY_API_KEY':'fixture-never-loaded'}):
            with self.assertRaises(Invalid):Studio(self.tmp.name)
        with self.assertRaises(Invalid):self.studio.create({**BRIEF,'credentials':{}},'secret')
        with patch('socket.create_connection',side_effect=AssertionError('Network forbidden')):
            self.professional()
            class Forbidden:
                def request_listing(self,approved):raise AssertionError('Live listing forbidden')
            self.studio.listing=Forbidden();chosen=next(iter(self.accept()))
            self.act('approve_final',reviews=self.accept(),candidate_id=chosen)
        self.assertFalse(self.state()['listing']['etsy_api_called'])

    def test_unsafe_asset_markup_and_configuration_are_rejected(self):
        for markup in ('<script/>','<image href="https://example.com/image"/>','<rect onclick="alert(1)"/>','<rect fill="url(#a)"/>'):
            with self.assertRaises(Invalid):checked_asset(Asset(('<svg xmlns="http://www.w3.org/2000/svg">'+markup+'</svg>').encode(),'image/svg+xml','test'))
        config=Path(self.tmp.name)/'config.json';write(config,{'api_key':'not-a-key'})
        with self.assertRaises(Invalid):configuration(config)


class HTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.server=Server(('127.0.0.1',0),Studio(self.tmp.name))
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def call(self,path,body=None,headers=None):
        headers={'Content-Type':'application/json','Idempotency-Key':'http-test',**(headers or {})}
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=3) as response:return response.status,response.read(),dict(response.headers)
        except urllib.error.HTTPError as error:return error.code,error.read(),dict(error.headers)
    def test_http_brief_actions_assets_and_mobile_ui(self):
        status,body,headers=self.call('/');self.assertEqual(status,200);self.assertIn(b'name="viewport"',body);self.assertIn('Content-Security-Policy',headers)
        status,body,_=self.call('/api/briefs',BRIEF);self.assertEqual(status,200);project=json.loads(body)['project']
        self.server.studio.tick();state=self.server.studio.get(project['id']);candidate=state['rounds'][0]['candidates'][0]
        status,body,_=self.call('/api/projects/'+project['id']+'/asset/'+candidate['id']);self.assertEqual(status,200);self.assertTrue(body.startswith(b'<svg'))
        self.assertEqual(self.call('/api/projects/'+project['id']+'/download')[0],409)
    def test_host_origin_json_size_and_traversal_protection(self):
        self.assertEqual(self.call('/health',headers={'Host':'attacker.example:1234'})[0],403)
        self.assertEqual(self.call('/api/briefs',BRIEF,{'Origin':'https://attacker.example'})[0],403)
        self.assertEqual(self.call('/api/briefs',BRIEF,{'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.call('/api/briefs',{'concept':'x'*1_000_001})[0],413)
        self.assertEqual(self.call('/../../config/studio.example.json')[0],404)
        self.assertEqual(self.call('/api/briefs',[]) [0],400)
        self.assertEqual(self.call('/health')[0],200)


if __name__=='__main__':unittest.main()
