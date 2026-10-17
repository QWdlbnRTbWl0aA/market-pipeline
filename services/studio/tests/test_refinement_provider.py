"""Offline wire contracts: resolved instructions, dimensions, caching and admission."""
import base64
import io
import json
import unittest
from studio_service.providers import OpenAIStudio
from studio_service.dev_budget import BudgetBlocked
from studio_service.refinement import checked_plan,checked_review
from studio_service.storage import Invalid
import test_real_providers as fixture

PLAN={'instruction':'Use ordinary thin paper, no people or props; preserve the actual print.','change':['Thin A4 paper'],'preserve':['Exact vehicle print'],'checks':['Paper has realistic thickness'],'edit_box':[0,0,1,1],'protected_regions':[]}


class Provider(unittest.TestCase):
    setUp=fixture.Providers.setUp;image=fixture.Providers.image
    def transport(self,req,timeout):
        body=json.loads(req.data);self.calls.append((req.full_url,body))
        if '/images/' in req.full_url:
            w,h=map(int,body['size'].split('x'));value={'usage':{'input_tokens_details':{'text_tokens':20,'image_tokens':10},'output_tokens':100},'data':[{'b64_json':base64.b64encode(self.image(w,h)).decode()}]}
        else:
            props=body['text']['format']['schema']['properties']
            value=PLAN if 'instruction' in props else {'checks':[{'requirement':PLAN['checks'][0],'passed':True,'evidence':'Visible thin edge'}],'product_matches_sources':True,'preserved_content':True,'summary':'Matches explicit correction'}
            value={'status':'completed','usage':{'input_tokens':20,'output_tokens':20},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]}
        return io.BytesIO(json.dumps(value).encode())
    def test_top_tier_medium_working_edit_uses_resolved_plan_and_caches_every_step(self):
        m=OpenAIStudio(self.root,self.transport,lambda:'synthetic',limit_usd=25,image_model='gpt-image-2.5-sunburst');pixels=self.image(1152,768)
        plan=m.mockup_correction({'scene':{'image_prompt':'thick paper'},'card_comments':'Thin paper, remove people'},[pixels],'compile',self.project)
        output=m.mockup_refinement_image(pixels,plan,'edit',self.project)
        wire=self.calls[-1][1];self.assertEqual(wire['size'],'1152x768');self.assertEqual(wire['quality'],'medium');self.assertEqual(wire['model'],'gpt-image-2.5-sunburst')
        self.assertEqual(base64.b64decode(wire['images'][0]['image_url'].split(',')[1]),pixels);self.assertNotIn('thick paper',wire['prompt']);self.assertNotIn('blank paper',json.loads(wire['prompt'])['instruction'])
        review=m.mockup_compare(plan,[pixels,output.content],'compare',self.project);self.assertTrue(checked_review(review,plan));before=len(self.calls)
        m.mockup_correction({},[pixels],'compile',self.project);m.mockup_refinement_image(pixels,plan,'edit',self.project);m.mockup_compare(plan,[pixels,output.content],'compare',self.project)
        self.assertEqual(len(self.calls),before)
        m.mockup_refinement_image(pixels,plan,'export',self.project,True);self.assertEqual(self.calls[-1][1]['size'],'1536x1024');self.assertEqual(self.calls[-1][1]['quality'],'high')
    def test_missing_or_reordered_checks_cannot_be_treated_as_success(self):
        for bad in ([{'requirement':'Unrelated easy check','passed':True,'evidence':'A scene'}],[]):
            with self.assertRaises(Invalid):checked_review({'checks':bad,'product_matches_sources':True,'preserved_content':True,'summary':'Claims success'},PLAN)
        for bounds in ([0,0,0,1],[0,0,2,1],[0,0,float('nan'),1]):
            with self.assertRaises(Invalid):checked_plan({**PLAN,'edit_box':bounds})
    def test_refinement_budget_admission_still_precedes_key_access(self):
        keys=[];m=OpenAIStudio(self.root,self.transport,lambda:keys.append(True) or 'synthetic',limit_usd=25)
        m.budget.reserve('used',self.project,2999999,'mockup_refinement_image');m.budget.settle('used',2999999,{})
        with self.assertRaises(BudgetBlocked):m.mockup_refinement_image(self.image(),PLAN,'blocked',self.project)
        self.assertEqual(keys,[]);self.assertEqual(self.calls,[])
