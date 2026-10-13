import base64
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib
from studio_service.core import Studio
from studio_service.dev_budget import Budget, BudgetBlocked
from studio_service.openai_dev import OpenAIDev, key_file
from studio_service.server import configuration, DEFAULT
from studio_service.storage import read, write, Invalid
from studio_service.understanding import aggregate, LocalUnderstanding, validate
from test_studio import BRIEF


def png():
    def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x99\xaa\xbb'*64)*64))+chunk(b'IEND',b'')


class Development(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_one_dollar_global_limit_across_products_restarts_and_threads(self):
        budget=Budget(self.root);budget.reserve('one','product-a',600_000,'generation');budget.settle('one',600_000,{})
        results=[]
        def admission(identity):
            try:Budget(self.root).reserve(identity,'product-b',300_000,'generation');results.append(identity)
            except BudgetBlocked:pass
        workers=[threading.Thread(target=admission,args=(str(i),)) for i in range(6)]
        for worker in workers:worker.start()
        for worker in workers:worker.join()
        self.assertEqual(len(results),1);budget.settle(results[0],300_000,{})
        with self.assertRaises(BudgetBlocked):Budget(self.root).reserve('last','other',100_001,'generation')
        self.assertEqual(budget.summary('product-a')['product_usd'],.6);self.assertEqual(budget.summary('product-b')['charged_or_reserved_usd'],.9)
    def test_unknown_outcome_blocks_every_product_without_new_credentials(self):
        adapter=OpenAIDev(self.root,credentials=lambda:self.fail('Credential loaded'),transport=lambda *a,**k:self.fail('Network called'))
        adapter.budget.reserve('unknown','other',5000,'fixture')
        with self.assertRaises(BudgetBlocked):adapter.text({'hello':'world'},{},'test','product')
        self.assertEqual(adapter.budget.summary('product')['unknown_outcomes'],1)
    def test_text_cache_usage_accounting_and_no_automatic_retry(self):
        calls=[]
        def transport(req,timeout):
            self.assertEqual(req.full_url,'https://api.openai.com/v1/responses');self.assertNotIn('tools',json.loads(req.data));calls.append(1)
            return io.BytesIO(json.dumps({'status':'completed','usage':{'input_tokens':100,'output_tokens':50},'output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]}).encode())
        adapter=OpenAIDev(self.root,transport,lambda:'fixture')
        self.assertEqual(adapter.text({'question':'test'},{},'request','product'),{'ok':True})
        adapter.text({'question':'test'},{},'request','product');self.assertEqual(len(calls),1)
        self.assertEqual(adapter.budget.summary('product')['product_usd'],.00012)
    def test_timeout_keeps_reservation_no_second_call_or_secret_disclosure(self):
        calls=[]
        def transport(*a,**k):calls.append(1);raise TimeoutError('Do not persist provider request headers')
        adapter=OpenAIDev(self.root,transport,lambda:'fixture')
        with self.assertRaises(Invalid):adapter.text({}, {},'request','product')
        with self.assertRaises(BudgetBlocked):adapter.text({}, {},'request','product')
        self.assertEqual(len(calls),1)
        for file in self.root.rglob('*.json'):self.assertNotIn('Bearer fixture',file.read_text())
    @unittest.skipUnless(importlib.util.find_spec('PIL'),'Optional Pillow runtime unavailable')
    def test_real_adapter_image_and_visual_observation_contract_offline(self):
        calls=[]
        def transport(req,timeout):
            body=json.loads(req.data);calls.append(body['model'])
            if req.full_url.endswith('/images/generations'):
                self.assertEqual(body['quality'],'low');self.assertEqual(body['size'],'1024x1024')
                return io.BytesIO(json.dumps({'usage':{'input_tokens_details':{'text_tokens':100,'image_tokens':0},'output_tokens':272},'data':[{'b64_json':base64.b64encode(png()).decode()}]}).encode())
            samples={'samples':[{'index':1,'description':'ילד בכחול','subject':'boy','palette':'blue','composition':'centered','style':'watercolor','texture':'paper','bundle_cohesion':'consistent'}]}
            return io.BytesIO(json.dumps({'status':'completed','usage':{'input_tokens':500,'output_tokens':150},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(samples)}]}]}).encode())
        adapter=OpenAIDev(self.root,transport,lambda:'fixture')
        request={'count':1,'brief':BRIEF,'project_id':'product','operation_id':'request','last_feedback':'','negative_summary':{}}
        assets=adapter.generate(request);self.assertEqual(assets[0].metadata['features']['subject'],'boy');self.assertEqual(assets[0].media_type,'image/png')
        adapter.generate(request);self.assertEqual(len(calls),2);self.assertLess(adapter.budget.summary('product')['product_usd'],.01)
    def test_boy_girl_example_deduplicates_and_distinguishes_subject_not_blue(self):
        studio=Studio(self.root,development=True);project=studio.create(BRIEF,'intake')['project']['id'];studio.tick();state=studio.get(project)
        frame=state['rounds'][0]
        for i,subject in enumerate(('boy','girl','boy')):
            candidate=frame['candidates'][i];candidate['metadata']={'features':{'subject':subject,'palette':'blue'}}
            frame['reviews'][candidate['id']]={'decision':'reject' if subject=='girl' else 'accept','comment':''}
        state['rounds'].append(frame.copy())
        context=aggregate(state);self.assertEqual(len(context['evidence']),3)
        result=validate(LocalUnderstanding().analyze(context,'test',project),context['evidence'])
        self.assertEqual(result['preferences'][0]['prefer'],'boy');self.assertEqual(result['preferences'][0]['avoid'],'girl')
        self.assertEqual([p['aspect'] for p in result['preferences']],['subject'])
    @unittest.skipUnless(importlib.util.find_spec('PIL'),'Optional Pillow runtime unavailable')
    def test_failed_observation_recovery_reuses_paid_images(self):
        images=[];observations=[]
        def transport(req,timeout):
            if req.full_url.endswith('/images/generations'):
                images.append(1)
                return io.BytesIO(json.dumps({'usage':{'input_tokens_details':{'text_tokens':100,'image_tokens':0},'output_tokens':272},'data':[{'b64_json':base64.b64encode(png()).decode()}]}).encode())
            observations.append(1);samples=[] if len(observations)==1 else [{'index':1,'description':'חנוכה','subject':'menorah','palette':'blue','composition':'centered','style':'watercolor','texture':'paper','bundle_cohesion':'consistent'}]
            return io.BytesIO(json.dumps({'status':'completed','usage':{'input_tokens':100,'output_tokens':50},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'samples':samples})}]}]}).encode())
        adapter=OpenAIDev(self.root,transport,lambda:'fixture');request={'count':1,'brief':BRIEF,'project_id':'product','operation_id':'request','last_feedback':'','negative_summary':{}}
        with self.assertRaises(Invalid):adapter.generate(request)
        # Changing only observation instructions creates a new paid observation,
        # while the image receipt is reused across adapter/process instances.
        prior=OpenAIDev.text
        def revised(self,prompt,schema,key,project,images=()):return prior(self,{**prompt,'revision':2},schema,key,project,images)
        with patch.object(OpenAIDev,'text',revised):self.assertEqual(len(OpenAIDev(self.root,transport,lambda:'fixture').generate(request)),1)
        self.assertEqual(len(images),1);self.assertEqual(len(observations),2)
    def test_explicit_preserve_comment_overrides_invented_palette_dislike(self):
        from studio_service.understanding import enforce
        context={'evidence':[{'id':'sample','decision':'reject','comment':'לשמור על צבעי המים והפלטה הרכה, אך לתקן את מספר הנרות.'}],
            'aspects':{'palette':{'blue':{'accepted':[],'rejected':['sample']}}}}
        value={'summary':'Unreliable palette dislike','next_direction':'Change palette','uncertainties':[],
            'preferences':[{'aspect':'palette','prefer':'red','avoid':'blue','evidence_ids':['sample'],'confidence':'high','explanation':'Unsupported'}]}
        result=enforce(value,context)
        self.assertEqual(result['preferences'][0]['avoid'],'');self.assertIn('הפלטה',result['preferences'][0]['prefer'])
        self.assertIn('take precedence',result['next_direction'])
    def test_single_sample_feedback_replaces_only_one_and_logs_every_update(self):
        studio=Studio(self.root,development=True);project=studio.create(BRIEF,'intake')['project']['id'];studio.tick();state=studio.get(project)
        ids=[c['id'] for c in state['rounds'][-1]['candidates']]
        studio.command(project,'review_sample',{'revision':state['revision'],'candidate_id':ids[0],'reviews':{ids[0]:{'decision':'accept_with_comments','comment':'Use a boy, keep blue'}}},'review');studio.tick();state=studio.get(project)
        self.assertEqual(len(state['rounds'][-1]['candidates']),3);self.assertEqual([c['id'] for c in state['rounds'][-1]['candidates']][1:],ids[1:])
        self.assertEqual(state['accepted_samples'][0]['id'],ids[0]);self.assertEqual(len(list((studio.directory(project)/'reasoning-log').glob('*.json'))),1)
        self.assertIn('understanding',state)
    def test_replace_without_decision_is_not_a_rejection(self):
        studio=Studio(self.root);project=studio.create(BRIEF,'intake')['project']['id'];studio.tick();state=studio.get(project)
        candidate=state['rounds'][-1]['candidates'][0]['id']
        studio.command(project,'replace_sample',{'revision':state['revision'],'candidate_id':candidate},'replace');studio.tick()
        self.assertEqual(aggregate(studio.get(project))['evidence'],[])
    def test_budget_rejection_preserves_feedback_and_current_samples(self):
        adapter=OpenAIDev(self.root,credentials=lambda:self.fail('Key opened'),transport=lambda *a,**k:self.fail('Network called'))
        studio=Studio(self.root,understanding=adapter,development=True);project=studio.create(BRIEF,'intake')['project']['id'];studio.tick();state=studio.get(project)
        adapter.budget.reserve('spent','other',1_000_000,'fixture');adapter.budget.settle('spent',1_000_000,{})
        chosen=state['rounds'][-1]['candidates'][0]['id'];studio.command(project,'review_sample',{'revision':state['revision'],'candidate_id':chosen,'reviews':{chosen:{'decision':'reject','comment':'Change palette'}}},'review');studio.tick();state=studio.get(project)
        self.assertEqual(state['phase'],'generation_failed');self.assertEqual(state['rounds'][-1]['reviews'][chosen]['decision'],'reject');self.assertEqual(len(state['rounds'][-1]['candidates']),3)
        log=next((studio.directory(project)/'reasoning-log').glob('*.json'));self.assertEqual(read(log)['status'],'failed')
    def test_openai_config_requires_development_and_key_loader_does_not_source_shell(self):
        path=self.root/'config.json';write(path,{**DEFAULT,'sketch_provider':'openai_dev'})
        with self.assertRaises(Invalid):configuration(path)
        key=self.root/'key.env';key.write_text('export OPENAI_API_KEY=fixture\n');key.chmod(0o600)
        with patch.dict('os.environ',{'STUDIO_OPENAI_CREDENTIAL_FILE':str(key)}):self.assertEqual(key_file(),'fixture')
        key.write_text('export OPENAI_API_KEY=$(echo forbidden)\n')
        with patch.dict('os.environ',{'STUDIO_OPENAI_CREDENTIAL_FILE':str(key)}):
            with self.assertRaises(Invalid):key_file()
    def test_hebrew_hanukkah_fixture_is_product_handoff_with_five_deliverables(self):
        from studio_service.briefs import normalize,missing
        fixture=Path(__file__).resolve().parents[3]/'examples/studio-hanukkah-brief.example.json'
        brief=normalize(read(fixture));self.assertEqual(len(brief['deliverables']),5);self.assertEqual(missing(brief),[])
        self.assertIn('חנוכה',brief['concept']);self.assertIn('אקוורל',brief['visual_direction'])


if __name__=='__main__':unittest.main()
