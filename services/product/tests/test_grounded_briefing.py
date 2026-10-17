"""Real service contracts, synthetic model transport; no external side effects."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from product_service.briefing import checked, context, define, default_model, OpenAIBrief, OllamaBrief
from product_service.paid import policy, key
from product_service.core import process
from test_flow import fixture, FixtureBrief


class GroundedBriefing(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.row=fixture()['report']['recommendations'][0]
    def test_unknown_urls_placeholders_counts_and_citations_fail_closed(self):
        value=FixtureBrief().generate(context(self.row))['definition'];samples=context(self.row)['samples']
        for mutate in (lambda d:d.update(title='TBD'),lambda d:d['components'][0].update(quantity=17),
                       lambda d:d['components'][0].update(evidence_ids=['foreign']),
                       lambda d:d['first_sketch'].update(component='Missing component'),
                       lambda d:d['first_sketch'].update(composition='A4 (8.5 x 11 inches)'),
                       lambda d:d['reference_interpretation'][0].update(evidence_id='foreign')):
            broken=copy.deepcopy(value);mutate(broken)
            with self.assertRaises(ValueError):checked(broken,samples)
        for url in ('javascript:alert(1)','https://example.com/listing/1','http://www.etsy.com/listing/1'):
            row=copy.deepcopy(self.row);row['evidence_excerpts'][0]['url']=url
            with self.assertRaises(ValueError):context(row)
        valid=copy.deepcopy(value);valid['production_files']=['A4 and US Letter at 8.5 x 11 inches; A4 uses 210 x 297 mm']
        self.assertEqual(checked(valid,samples),valid)
    def test_invalid_completed_response_is_durable_and_revalidated_without_inference(self):
        class Broken(FixtureBrief):
            def generate(self,value):
                result=super().generate(value);result['definition']['title']='TBD';return result
        model=Broken()
        for _ in range(2):
            with self.assertRaises(ValueError):define(self.row,self.root,model)
        self.assertEqual(model.calls,1);self.assertTrue((self.root/'definition-response.json').exists())
    def test_unknown_model_outcome_cannot_automatically_repeat(self):
        class Unknown:
            calls=0
            def generate(self,value):self.calls+=1;raise TimeoutError()
        model=Unknown()
        with self.assertRaises(TimeoutError):define(self.row,self.root,model)
        with self.assertRaises(RuntimeError):define(self.row,self.root,model)
        self.assertEqual(model.calls,1)
    def test_budget_rejection_is_known_unsent_and_allows_explicit_recovery(self):
        from pipeline_budget import BudgetExceeded
        class Denied:
            def generate(self,value):raise BudgetExceeded('No request sent')
        with self.assertRaises(BudgetExceeded):define(self.row,self.root,Denied())
        self.assertFalse((self.root/'definition-started.json').exists())
        self.assertFalse(json.loads((self.root/'definition-admission-rejected.json').read_text())['request_sent'])
        model=FixtureBrief();define(self.row,self.root,model);self.assertEqual(model.calls,1)
    def test_cache_write_premium_and_cached_read_prices(self):
        from pipeline_openai import usage_cost
        usage={'input_tokens':1000,'input_tokens_details':{'cached_tokens':200,'cache_write_tokens':600},'output_tokens':100}
        self.assertAlmostEqual(usage_cost('gpt-6.1-sol',usage),.00292)
        with self.assertRaises(ValueError):usage_cost('gpt-6.1-sol',{**usage,'input_tokens':100})
    def test_openai_definition_uses_real_bounded_adapter_contract_and_cache(self):
        settings={'provider':'openai','model':'gpt-6.1-sol','paid':{'enabled':True,'daily_usd':None,'daily_calls':None,
            'total_usd':2,'ledger_root':str(self.root),'max_output_tokens':4500,'max_input_token_bound':50000,
            'development':{'id':'market-history-development','total_usd':.5}}}
        value=context(self.row);definition=FixtureBrief().generate(value)['definition'];calls=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,*a):return json.dumps({'status':'completed','usage':{'input_tokens':100,'output_tokens':100},
                'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(definition)}]}]}).encode()
        def transport(request,**kwargs):
            self.assertEqual(request.full_url,'https://api.openai.com/v1/responses');self.assertEqual(kwargs['timeout'],240)
            calls.append(json.loads(request.data));return Response()
        with patch('product_service.paid.key',return_value='synthetic-private-key'):
            model=OpenAIBrief(settings);model.model.transport=transport
            first=model.generate(value);second=model.generate(value)
        self.assertEqual(checked(first['definition'],value['samples']),definition)
        self.assertEqual(len(calls),1);self.assertTrue(second['metadata']['cache_hit'])
        self.assertEqual(calls[0]['reasoning']['effort'],'medium');self.assertFalse(calls[0]['store'])
        self.assertIn(value['samples'][0]['description_excerpt'],calls[0]['input'])
        for path in self.root.rglob('*.json'):self.assertNotIn('synthetic-private-key',path.read_text())
    def test_local_definition_separates_inventory_and_derives_counts(self):
        value=context(self.row);definition=FixtureBrief().generate(value)['definition'];calls=[]
        modules=[{k:v for k,v in c.items() if k!='quantity'} for c in definition['components']]
        final={k:v for k,v in definition.items() if k!='components'}
        final['reference_interpretation']=[{k:v for k,v in r.items() if k!='observed_content'} for r in final['reference_interpretation']]
        class Response:
            def __init__(self,text):self.text=text
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,*a):return json.dumps({'done':True,'done_reason':'stop','response':json.dumps(self.text)}).encode()
        def transport(request,**kwargs):
            self.assertEqual(request.full_url,'http://127.0.0.1:11434/api/generate')
            calls.append(json.loads(request.data));return Response({'components':modules} if len(calls)==1 else final)
        result=OllamaBrief(transport=transport).generate(value)
        checked(result['definition'],value['samples'])
        self.assertEqual(result['definition']['components'][0]['quantity'],4)
        self.assertNotIn('quantity',calls[0]['format']['properties']['components']['items']['properties'])
        self.assertNotIn('components',calls[1]['format']['properties'])
        self.assertEqual(result['definition']['reference_interpretation'][0]['observed_content'],value['samples'][0]['title'])
        self.assertEqual(result['metadata']['local_calls'],2)
    def test_independent_product_and_analyzer_share_budget_unknown_and_cache(self):
        from pipeline_budget import Budget, BudgetExceeded
        from pipeline_openai import ModelRequest, OpenAIModel
        p={'enabled':True,'daily_usd':None,'daily_calls':None,'total_usd':2,'ledger_root':str(self.root),
           'max_output_tokens':1000,'max_input_token_bound':10000,'development':{'id':'market-history-development','total_usd':.5}}
        existing=Budget(self.root,None,2,None,p['development']);existing.reserve('previous',.49);existing.settle('previous',.49,{})
        calls=[]
        model=OpenAIModel('gpt-6.1-sol',p,key_provider=lambda:calls.append('key'),transport=lambda *a,**k:calls.append('http'))
        with self.assertRaises(BudgetExceeded):model.generate(ModelRequest('system','prompt',{}))
        self.assertEqual(calls,[])
        self.assertEqual(json.loads((self.root/'budget.json').read_text())['calls']['previous']['charged_usd'],.49)
    def test_explicit_held_unknown_policy_counts_full_cost_and_never_resends_identity(self):
        from pipeline_budget import Budget, BudgetExceeded
        budget=Budget(self.root,None,2,None);budget.reserve('unknown',.4)
        with self.assertRaises(BudgetExceeded):budget.reserve('unrelated',.1)
        explicit=Budget(self.root,None,2,None,allow_held_unknown=True)
        explicit.reserve('new-recipe',.2)
        with self.assertRaises(BudgetExceeded):explicit.reserve('unknown',.1)
        with self.assertRaises(BudgetExceeded):explicit.reserve('too-much',1.5)
        ledger=json.loads((self.root/'budget.json').read_text())
        self.assertEqual(ledger['calls']['unknown']['status'],'reserved_unknown')
        self.assertEqual(ledger['calls']['unknown']['charged_usd'],.4)
        ledger['calls']['unknown']['charged_usd']=.1;(self.root/'budget.json').write_text(json.dumps(ledger))
        with self.assertRaises(BudgetExceeded):explicit.reserve('under-held',.1)
    def test_product_never_loads_etsy_or_inherited_credentials(self):
        for variable in ('ETSY_API_KEY','OPENAI_API_KEY','SMTP_PASSWORD'):
            with patch.dict(os.environ,{variable:'synthetic'}),patch('os.open',side_effect=AssertionError('Credential loaded')):
                with self.assertRaises(ValueError):key()
        with patch.dict(os.environ,{'PIPELINE_PRODUCT_OPENAI_KEY_FILE':str(self.root/'etsy.env')}),patch('os.open',side_effect=AssertionError('Etsy file opened')):
            with self.assertRaises(ValueError):key()
    def test_paid_policy_and_optional_unit_access_are_explicit(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'deploy'))
        from unit_templates import render
        settings={'provider':'openai','model':'gpt-6.1-sol','paid':{'enabled':True,'daily_usd':None,'daily_calls':None,
            'total_usd':2,'ledger_root':str(self.root),'max_output_tokens':4500,'max_input_token_bound':50000,
            'development':{'id':'market-history-development','total_usd':.5}}}
        self.assertEqual(policy(settings),settings)
        total_only=copy.deepcopy(settings);total_only['paid'].pop('development')
        self.assertEqual(policy(total_only),total_only)
        for path,value in (('total_usd',3),('max_output_tokens',100000),('enabled','true')):
            invalid=copy.deepcopy(settings);invalid['paid'][path]=value
            with self.assertRaises(ValueError):policy(invalid)
        self.assertNotIn('LoadCredential=openai.env',render('product'))
        unit=render('product',product_paid=True)
        self.assertIn('LoadCredential=openai.env',unit);self.assertIn('ReadWritePaths=/var/lib/market-pipeline/product /var/lib/market-pipeline/paid-ledger',unit)
        self.assertNotIn('etsy.env',unit)
    def test_exact_definition_reaches_studio_adapter_and_html_has_no_internal_exports(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'studio'))
        from studio_service.briefs import normalize
        result=process(json.dumps(fixture()).encode(),self.root,FixtureBrief())
        folder=Path(result['directory'])/'product-01';product=json.loads((folder/'product.json').read_text());studio=normalize(product)
        self.assertEqual(studio['concept'],product['definition']['title'])
        self.assertIn('Match the shapes',studio['requirements']);self.assertEqual(len(studio['deliverables']),2)
        page=(folder/'brief.html').read_text()
        for forbidden in ('<script','<img','/product.json','/brief.md','draft-',str(Path.home())):self.assertNotIn(forbidden,page)
        self.assertIn(self.row['evidence_excerpts'][0]['url'],page)
        self.assertNotIn('placeholder',page.lower())
