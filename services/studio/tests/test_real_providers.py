"""Real JSON API contracts with offline transports and temporary credentials."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from studio_service.providers import OpenAIStudio,GeminiStudio,Comparison
from studio_service.storage import Invalid,read,write,write_bytes
from studio_service.dev_budget import Budget,BudgetBlocked
from studio_service.production import png


class Providers(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.project='a'*32;self.calls=[];Budget(self.root/'development-openai').authorize(25,'Explicit zero-spend synthetic fixture',initialize_empty=True)
    def image(self,w=1024,h=1024):return png(Image.new('RGB',(w,h),'#88aabb'))
    def transport(self,req,timeout):
        body=json.loads(req.data);self.calls.append((req.full_url,body,req.data))
        if '/images/' in req.full_url:
            w,h=map(int,body['size'].split('x'));value={'usage':{'input_tokens_details':{'text_tokens':20,'image_tokens':10},'output_tokens':100},
                'data':[{'b64_json':base64.b64encode(self.image(w,h)).decode()} for _ in range(body['n'])]}
        else:
            count=body['text']['format']['schema']['properties']['samples']['maxItems']
            samples=[{k:'actual observed fixture' for k in ('description','subject','palette','composition','style','texture','bundle_cohesion')} for i in range(count)]
            value={'status':'completed','usage':{'input_tokens':20,'output_tokens':20},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'samples':samples})}]}]}
        return io.BytesIO(json.dumps(value).encode())
    def request(self):
        return {'operation_id':'operation','project_id':self.project,'count':3,'mode':'sketch','accepted':[],'rejected':[],
            'optimized_prompt':'Generate ONE representative watercolor menorah picture; do not make a collage','brief':{'concept':'Original holiday picture'},'reference_images':[]}

    def test_flare_generates_then_edits_exact_accepted_pixels_and_cache_is_reused(self):
        model=OpenAIStudio(self.root,self.transport,lambda:'synthetic-secret',limit_usd=25);request=self.request();images=model.generate(request)
        self.assertEqual(len(images),3);self.assertEqual(self.calls[0][0],'https://api.openai.com/v1/images/generations')
        image=images[0].content;path=self.root/'projects'/self.project/'generations/one.png';write_bytes(path,image)
        candidate={'file':'generations/one.png','sha256':hashlib.sha256(image).hexdigest()}
        edited={**request,'operation_id':'edit','accepted':[candidate],'optimized_prompt':'Keep the approved palette; remove background details'}
        result=model.generate(edited);wire=next(body for url,body,raw in self.calls if url.endswith('/images/edits'))
        self.assertEqual(base64.b64decode(wire['images'][0]['image_url'].split(',')[1]),image)
        self.assertEqual(result[0].metadata['edit_input_sha256'],[candidate['sha256']])
        count=len(self.calls);model.generate(edited);self.assertEqual(len(self.calls),count)
        model.generate({**edited,'optimized_prompt':'A code-only prompt correction during recovery'})
        self.assertEqual(len(self.calls),count)
        for path in (self.root/'development-openai/calls').glob('*/request.json'):
            saved=read(path);self.assertIn(saved['body']['model'],('gpt-image-2.5-flare','gpt-4.1-mini-2025-04-14'))
            self.assertNotIn('synthetic-secret',path.read_text())

    def test_unknown_outcome_keeps_hold_and_never_repeats_network_or_key_loading(self):
        keys=[]
        def timeout(*a,**k):self.calls.append('network');raise TimeoutError()
        model=OpenAIStudio(self.root,timeout,lambda:keys.append('key') or 'synthetic',limit_usd=25)
        with self.assertRaises(Invalid):model.generate(self.request())
        with self.assertRaises(BudgetBlocked):model.generate(self.request())
        self.assertEqual(self.calls,['network']);self.assertEqual(keys,['key'])
        self.assertEqual(model.budget.summary(self.project)['unknown_outcomes'],1)

    def test_production_uses_native_dimensions_one_asset_and_no_vision_call(self):
        model=OpenAIStudio(self.root,self.transport,lambda:'synthetic',limit_usd=25,image_model='gpt-image-2.5-sunburst')
        request={**self.request(),'count':1,'mode':'production','production_unit':{'description':'An oil jug'},
                 'production_plan':{'style':'Original watercolor'},'last_feedback':'Preserve texture','image_size':[2256,3280]}
        result=model.generate(request)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][1]['quality'],'high')
        self.assertEqual(self.calls[0][1]['model'],'gpt-image-2.5-sunburst');self.assertEqual(result[0].metadata['native_height'],3280)

    def test_nano_uses_stateless_interactions_no_search_and_conservative_shared_accounting(self):
        def transport(req,timeout):
            body=json.loads(req.data);self.calls.append((req.full_url,body))
            return io.BytesIO(json.dumps({'status':'completed','usage':{'total_input_tokens':100,'total_output_tokens':1120},
                'steps':[{'type':'thought','summary':[{'type':'image','data':'ignored'}]},
                         {'type':'model_output','content':[{'type':'image','data':base64.b64encode(self.image()).decode(),'mime_type':'image/png'}]}]}).encode())
        model=GeminiStudio(self.root,transport,lambda:'synthetic',limit_usd=25)
        request={**self.request(),'count':1};result=model.generate(request)
        self.assertEqual(len(result),1);self.assertEqual(self.calls[0][0],'https://generativelanguage.googleapis.com/v1beta/interactions')
        self.assertFalse(self.calls[0][1]['store']);self.assertNotIn('tools',self.calls[0][1])
        self.assertAlmostEqual(model.budget.summary(self.project)['charged_or_reserved_usd'],.03375)
        model.generate(request);self.assertEqual(len(self.calls),1)
        model.generate({**request,'optimized_prompt':'Code correction during recovery'});self.assertEqual(len(self.calls),1)

    def test_model_comparison_reuses_the_exact_same_prompt_and_acceptance_evidence(self):
        class Route:
            def __init__(self):self.requests=[]
            def generate(self,r):self.requests.append(r);return [object()]
        flare,nano=Route(),Route();comparison=Comparison(flare,nano,False);request=self.request();comparison.generate(request)
        all_requests=flare.requests+nano.requests;self.assertEqual(len(all_requests),3)
        self.assertTrue(all(r['optimized_prompt']==request['optimized_prompt'] for r in all_requests))
        self.assertEqual(len({r['operation_id'] for r in all_requests}),3)

    def test_credential_cli_formats_permissions_and_values_stay_out_of_responses(self):
        import importlib.util
        path=Path(__file__).resolve().parents[3]/'tools/provider_keys.py';spec=importlib.util.spec_from_file_location('provider_keys',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        value='synthetic-provider-fixture'
        result=module.manage(self.root/'credentials','add','google',value)
        self.assertNotIn(value,json.dumps(result));self.assertEqual((self.root/'credentials/studio-google.env').stat().st_mode&0o777,0o600)
        self.assertTrue(module.manage(self.root/'credentials','check','google')['local_format_valid'])
        with self.assertRaises(ValueError):module.manage(self.root/'credentials','add','google',value)
        module.manage(self.root/'credentials','update','google',value+'-updated');module.manage(self.root/'credentials','remove','google')
        self.assertEqual(module.manage(self.root/'credentials','list')['providers'],[])

    def test_lifestyle_contract_cheap_planning_then_low_concept_then_accepted_background_high_edit(self):
        from test_lifestyle import Scenes
        def transport(req,timeout):
            body=json.loads(req.data);self.calls.append((req.full_url,body))
            if '/images/' in req.full_url:
                w,h=map(int,body['size'].split('x'));result={'usage':{'input_tokens_details':{'text_tokens':20,'image_tokens':10},'output_tokens':100},'data':[{'b64_json':base64.b64encode(self.image(w,h)).decode()}]}
            else:
                schema=body['text']['format']['schema']
                result_value=({'product_understanding':'Saved product','direction':'Warm family context','scenes':[{'title':'Family use','description':'A supervised activity','image_prompt':'Natural family photograph with clear blank foreground page','page_id':'unit-01'}]} if 'scenes' in schema['properties'] else {'usable':True,'reason':'Clear page','quad':[[.1,.2],[.9,.2],[.9,.9],[.1,.9]]})
                result={'status':'completed','usage':{'input_tokens':20,'output_tokens':20},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(result_value)}]}]}
            return io.BytesIO(json.dumps(result).encode())
        model=OpenAIStudio(self.root,transport,lambda:'synthetic',limit_usd=25)
        import random
        large=png(Image.frombytes('RGB',(1300,1300),random.Random(0).randbytes(1300*1300*3)));self.assertGreater(len(large),2000000)
        plan=model.mockup_plan({'inventory':[],'comments':'Warm family'},1,'plan',self.project,[large]);scene=plan['scenes'][0]
        self.assertEqual(self.calls[0][1]['input'][0]['content'][1]['detail'],'low')
        concept=model.mockup_scene(scene,'Warm family','concept',self.project)
        path=self.root/'projects'/self.project/'lifestyle/concept/background.png';write_bytes(path,concept.content)
        reference={'background_file':'lifestyle/concept/background.png','background_sha256':hashlib.sha256(concept.content).hexdigest()}
        final=model.mockup_scene(scene,'Keep warm light','final',self.project,True,reference)
        surface=model.mockup_surface(final.content,'surface',self.project);self.assertTrue(surface['usable'])
        image_calls=[b for u,b in self.calls if '/images/' in u];self.assertEqual(image_calls[0]['quality'],'low');self.assertEqual(image_calls[1]['quality'],'high')
        self.assertEqual(base64.b64decode(image_calls[1]['images'][0]['image_url'].split(',')[1]),concept.content)
        before=len(self.calls);model.mockup_scene(scene,'A code-only correction','final',self.project,True,reference);self.assertEqual(len(self.calls),before)
        rows=read(self.root/'development-openai/budget.json')['calls'].values();self.assertTrue(all(r['stage'].startswith('mockup_') for r in rows))

    def test_mockup_stage_cap_blocks_before_credentials_even_with_total_budget_remaining(self):
        keys=[];model=OpenAIStudio(self.root,self.transport,lambda:keys.append('key') or 'synthetic',limit_usd=25)
        model.budget.reserve('prior',self.project,2900000,'mockup_final_image');model.budget.settle('prior',2900000,{})
        scene={'title':'Scene','description':'An actual product scene','image_prompt':'A scene','page_id':'unit-01'}
        with self.assertRaises(BudgetBlocked):model.mockup_scene(scene,'','new',self.project)
        self.assertEqual(keys,[]);self.assertEqual(self.calls,[])

    def test_gallery_surfaces_and_final_edit_use_actual_scene_medium_and_precise_model(self):
        def transport(req,timeout):
            body=json.loads(req.data);self.calls.append((req.full_url,body,req.data))
            if '/images/' in req.full_url:
                w,h=map(int,body['size'].split('x'));value={'usage':{'input_tokens_details':{'text_tokens':20,'image_tokens':10},'output_tokens':100},'data':[{'b64_json':base64.b64encode(self.image(w,h)).decode()}]}
            else:
                value={'status':'completed','usage':{'input_tokens':20,'output_tokens':20},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'surfaces':[{'page_id':'unit-01','usable':True,'reason':'Clear paper','quad':[[.1,.1],[.4,.1],[.4,.7],[.1,.7]]},{'page_id':'unit-02','usable':True,'reason':'Clear paper','quad':[[.6,.1],[.9,.1],[.9,.7],[.6,.7]]}]})}]}]}
            return io.BytesIO(json.dumps(value).encode())
        model=OpenAIStudio(self.root,transport,lambda:'synthetic',limit_usd=25,image_model='gpt-image-2.5-sunburst')
        scene={'title':'Usage steps','description':'An illustrated activity storyboard','image_prompt':'Three cartoon panels','page_id':'unit-01','scene_type':'storyboard'}
        background=self.image();path=self.root/'projects'/self.project/'lifestyle/saved.png';write_bytes(path,background)
        result=model.mockup_surfaces(background,scene,['unit-01','unit-02'],'surfaces',self.project);self.assertEqual(len(result['surfaces']),2)
        wire=self.calls[-1][1];self.assertIn('scene_type',wire['input'][0]['content'][0]['text']);self.assertEqual(wire['input'][0]['content'][1]['detail'],'low')
        model.mockup_scene(scene,'Fix hands only','finish',self.project,True,{'background_file':'lifestyle/saved.png','background_sha256':hashlib.sha256(background).hexdigest()})
        url,wire,_=self.calls[-1];self.assertTrue(url.endswith('/images/edits'));self.assertEqual(wire['model'],'gpt-image-2.5-sunburst');self.assertEqual(wire['quality'],'high')
        prompt=json.loads(wire['prompt']);self.assertIn('Preserve its concept, composition',prompt['refinement_contract']);self.assertIn('cartoon',prompt['task']);self.assertEqual(prompt['scene']['scene_type'],'storyboard')
        self.assertEqual(base64.b64decode(wire['images'][0]['image_url'].split(',')[1]),background)

    def test_incomplete_plan_logs_exact_provider_diagnostic_without_automatic_retry(self):
        response={'id':'synthetic-response','status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'usage':{'input_tokens':100,'output_tokens':2400},'output':[{'type':'message','content':[{'type':'output_text','text':'{"scenes": ['}]}]}
        def transport(req,timeout):self.calls.append(json.loads(req.data));return io.BytesIO(json.dumps(response).encode())
        model=OpenAIStudio(self.root,transport,lambda:'synthetic',limit_usd=25)
        from studio_service.providers import PlanningFailure
        for _ in range(2):
            with self.assertRaises(PlanningFailure) as caught:model.mockup_plan({'inventory':[{'id':'unit-01'}]},1,'one-scene',self.project)
            self.assertEqual(caught.exception.diagnostic['response'],response)
        self.assertEqual(len(self.calls),1);wire=self.calls[0];self.assertGreater(wire['max_output_tokens'],2400)
        schema=wire['text']['format']['schema'];self.assertLessEqual(schema['properties']['product_understanding']['maxLength'],400)
        self.assertEqual(schema['properties']['scenes']['items']['properties']['page_id']['enum'],['unit-01'])
        self.assertEqual(model.budget.summary(self.project)['unknown_outcomes'],0)
