"""Commercial evidence, durable novelty and paid admission: fixtures only."""
import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from analyzer.assessments import key, memory, policy, previous, qualify
from analyzer.opportunities import analyze, stage
from analyzer.ports import IntakeBatch, ModelRequest, ModelResponse
from analyzer.normalize import normalize
from analyzer.research import build_evidence
from analyzer.io import write_json
from analyzer.budget import Budget, BudgetExceeded
from analyzer.adapters.openai import OpenAIModel
from test_production import POLICY, Selection


def data(groups=1):
    names=['amber geometry','birch forest','coral ocean','desert sunset','emerald valley','floral meadow','golden autumn','harbor boats','indigo mountains','juniper leaves','kiwi jungle','lavender garden']
    rows=[];shops=[];prior=[];series={}
    for index,name in enumerate(names[:groups]):
        for shop in range(3):
            seller=str(index*3+shop+1)
            shops.append({'shop_id':seller,'observed_at':'2026-10-15T00:00:00Z','created_at':'2024-01-01T00:00:00Z','transaction_sold_count':140,'listing_active_count':3})
            for listing in range(3):
                identity=f'{index}-{shop}-{listing}'
                rows.append({'id':identity,'title':'Printable '+name,'tags':[name],'description':'Original wall art design','digital':True,
                             'seller_id':seller,'category':'taxonomy:1','price':12,'currency':'USD','metrics':[]})
                series[identity]={'trend_status':'engagement_proxy_ready','intervals':[{'metrics':{'views':{'change':5}}}]}
    for date,sales in [('2026-10-01',100),('2026-10-08',120)]:
        prior.append({'run_id':date,'shops':[{**s,'observed_at':date+'T00:00:00Z','transaction_sold_count':sales} for s in shops],
                      'listings':[], 'shop_inventory_profiles':{s['shop_id']:[r for r in rows if r['seller_id']==s['shop_id']] for s in shops}})
    return normalize(IntakeBatch(rows,{'source_run_id':'current','finished_at':'2026-10-15T00:00:00Z',
        'query_context':{'niches':[{'keywords':'printable'}]},'shops':shops,'history':{'related_observations':prior,'listing_series':series}},
        {'input_sha256':'a'*64,'artifact_directory':'/tmp'}))


class AllSelections(Selection):
    def generate(self,request):
        if set(request.schema['properties'])=={'items'}:return super().generate(request)
        self.calls+=1;items=[]
        for c in json.loads(request.prompt)['candidates'][:request.schema['properties']['items']['maxItems']]:
            refs=[c['evidence'][0]['evidence_id']];item={'candidate_id':c['candidate_id'],'reason':'Repeated saved activity supports product validation.','evidence_ids':refs}
            if 'product_brief' in request.schema['properties']['items']['items']['properties']:
                statement={'text':'An original printable wall art concept','basis':'design_hypothesis','evidence_ids':refs}
                item['product_brief']={'product_concept':'Original wall art','intended_customer':statement,'customer_job':statement,'deliverables':[statement],
                                     'differentiation':statement,'acceptance_checks':['Check print clarity'],'validation_plan':['Test conversion'],'risks':['Purchases remain unverified']}
            items.append(item)
        return ModelResponse(json.dumps({'summary':'Saved context supports validation','items':items,'limitations':['Listing sales are unknown.']}),{'provider':'fixture'},{})


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config={'research':POLICY,'output_root':str(self.root)}
    def candidate(self,dataset):return build_evidence(dataset,POLICY)['candidates'][0]
    def test_shop_context_qualifies_but_never_allocates_sales(self):
        d=data();result=qualify(self.candidate(d),d,[],policy())
        self.assertTrue(result['qualified']);self.assertEqual(result['strong_sales_context_shops'],3)
        self.assertIsNone(result['listing_sales']);self.assertFalse(result['verified_listing_purchase_demand'])
        self.assertEqual(result['shops'][0]['actual_shop_counter_growth'],40)
    def test_seventy_sales_and_large_mixed_inventory_does_not_prove_listing_demand(self):
        d=data()
        for s in d['metadata']['shops']:s['listing_active_count']=100
        for prior in d['metadata']['history']['related_observations']:
            for s in prior['shops']:s['listing_active_count']=100
        result=qualify(self.candidate(d),d,[],policy())
        self.assertFalse(result['qualified']);self.assertEqual(result['strong_sales_context_shops'],0)
        # Even complete, similar inventory cannot turn weak whole-shop activity
        # into invented listing demand. Exercise the annual inventory proxy itself.
        d=data();expanded=[]
        for seller in ('1','2','3'):
            template=next(r for r in d['records'] if r['seller_id']==seller)
            expanded.extend({**template,'id':seller+'-'+str(i)} for i in range(100))
        d['records']=expanded
        for s in d['metadata']['shops']:s.update(transaction_sold_count=170,listing_active_count=100)
        for history,date,counter in zip(d['metadata']['history']['related_observations'],('2025-10-15','2026-04-15'),(100,130)):
            for s in history['shops']:s.update(observed_at=date+'T00:00:00Z',transaction_sold_count=counter,listing_active_count=100)
            history['shop_inventory_profiles']={seller:[r for r in expanded if r['seller_id']==seller] for seller in ('1','2','3')}
        d['metadata']['history']['listing_series']={r['id']:{'trend_status':'engagement_proxy_ready','intervals':[{'metrics':{'views':{'change':5}}}]} for r in expanded}
        result=qualify(self.candidate(d),d,[],policy())
        self.assertFalse(result['qualified']);self.assertEqual(result['shops'][0]['inventory_coverage_lower_bound'],1)
        self.assertLess(result['shops'][0]['shop_inventory_normalized_activity_per_year'],1)
    def test_missing_age_history_reset_and_single_shop_hold(self):
        for fault in ('age','history','reset','conflict','diversity','prices','sparse_prices','query_mismatch','changed_inventory'):
            d=data()
            if fault=='age':
                for s in d['metadata']['shops']:s['created_at']=None
            if fault=='history':d['metadata']['history']['listing_series']={}
            if fault=='reset':
                for s in d['metadata']['shops']:s['transaction_sold_count']=1
            if fault=='conflict':d['metadata']['shops'] += [{**s,'transaction_sold_count':1} for s in d['metadata']['shops']]
            if fault=='diversity':
                for r in d['records']:r['seller_id']='1'
            if fault=='prices':
                for r in d['records']:r['price']=1
            if fault=='sparse_prices':
                for r in d['records'][1:]:r['price']=None
            if fault=='query_mismatch':d['metadata']['query_context']['niches']=[{'keywords':'printable hanukkah'}]
            if fault=='changed_inventory':
                for report in d['metadata']['history']['related_observations']:
                    for rows in report['shop_inventory_profiles'].values():
                        for r in rows:r['title']='Unrelated cat toy';r['tags']=[]
            with self.subTest(fault=fault):
                if fault=='query_mismatch':self.assertEqual(build_evidence(d,POLICY)['candidates'],[])
                else:self.assertFalse(qualify(self.candidate(d),d,[],policy())['qualified'])
    def test_recency_weight_and_stable_concept_identity(self):
        d=data();c=self.candidate(d);as_of=dt.datetime(2026,10,15,tzinfo=dt.timezone.utc)
        rows=[{'source_run_id':'old','source_finished_at':'2026-09-01T00:00:00Z','candidates':[{'key':key(c),'score':0,'suggested':False}]},
              {'source_run_id':'recent','source_finished_at':'2026-10-14T00:00:00Z','candidates':[{'key':key(c),'score':1,'suggested':True}]}]
        m=memory(c,rows,as_of,policy());self.assertGreater(m['weighted_prior_score'],.7);self.assertTrue(m['previously_suggested'])
        self.assertEqual(key({'phrase':'Geometry Amber'}),key({'phrase':'amber geometry'}))
        q=qualify(c,d,rows,policy());self.assertNotEqual(q['score'],q['current_score'])
    def test_more_than_ten_refined_once_and_not_resuggested_across_runs(self):
        d=data(12);models=[AllSelections() for _ in range(3)]
        folder=self.root/'first';folder.mkdir()
        with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            report=analyze(d,folder,self.config,*models)
        self.assertEqual(len(report['recommendations']),10);self.assertTrue(report['target_count_met'])
        self.assertEqual([m.calls for m in models],[1,1,1]);self.assertGreater(report['candidate_counts']['initial'],10)
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'product'))
        from product_service.core import validate
        self.assertEqual(len(validate({'service':'market_insights','status':'completed','delivery_id':'a'*64,'report':report})),10)
        d['metadata'].update(source_run_id='later',finished_at='2026-10-16T00:00:00Z')
        second=self.root/'second';second.mkdir();again=analyze(d,second,self.config,*models)
        self.assertEqual(again['candidate_counts']['previously_suggested_removed'],10)
        self.assertTrue(set(r['opportunity_key'] for r in report['recommendations']).isdisjoint(r['opportunity_key'] for r in again['recommendations']))
        self.assertTrue(previous(self.root,d));self.assertFalse(report['weekly_trend_report_implemented'])
    def test_fewer_than_five_does_not_pad_and_skips_cheap_stage(self):
        folder=self.root/'first';folder.mkdir();models=[AllSelections() for _ in range(3)]
        report=analyze(data(),folder,self.config,*models)
        self.assertEqual(len(report['recommendations']),1);self.assertEqual(report['shortfall'],4)
        self.assertEqual([m.calls for m in models],[0,0,1])
    def test_insufficient_data_skips_all_models_and_retains_negative_assessments(self):
        d=data();d['metadata']['history']={};folder=self.root/'first';folder.mkdir();models=[AllSelections() for _ in range(3)]
        report=analyze(d,folder,self.config,*models)
        self.assertEqual(report['status'],'insufficient_evidence');self.assertEqual([m.calls for m in models],[0,0,0]);self.assertTrue(report['assessment_updates'])
    def test_same_source_other_recipe_does_not_duplicate_reserved_offers(self):
        d=data();first=self.root/'first';first.mkdir();analyze(d,first,self.config,*[AllSelections() for _ in range(3)])
        second=self.root/'second';second.mkdir();models=[AllSelections() for _ in range(3)]
        report=analyze(d,second,self.config,*models);self.assertEqual(report['recommendations'],[]);self.assertEqual([m.calls for m in models],[0,0,0])
    def test_dated_assessments_are_immutable_and_one_source_is_not_overweighted(self):
        d=data();folder=self.root/'first';folder.mkdir();analyze(d,folder,self.config,*[AllSelections() for _ in range(3)])
        path=next(p for p in (self.root/'market-assessments').glob('*.json') if p.name!='offers.json');original=path.read_bytes()
        analyze(d,folder,self.config,*[AllSelections() for _ in range(3)]);self.assertEqual(path.read_bytes(),original)
        copied=json.loads(original);copied['assessed_at']='2099-01-01T00:00:00Z';write_json(self.root/'market-assessments'/'another-recipe.json',copied)
        d['metadata'].update(source_run_id='later',finished_at='2026-10-16T00:00:00Z')
        self.assertEqual(len(previous(self.root,d)),1)
    def test_saved_stage_reuses_response_and_unknown_stage_cannot_repeat(self):
        model=AllSelections();req=ModelRequest('x','{}',{'properties':{'items':{}}})
        class Fixed:
            calls=0
            def generate(self,r):self.calls+=1;return ModelResponse('{}',{}, {})
        model=Fixed();stage(self.root,'saved',model,req);stage(self.root,'saved',model,req);self.assertEqual(model.calls,1)
        write_json(self.root/'stage-unknown'/'started.json',{})
        with self.assertRaises(RuntimeError):stage(self.root,'unknown',model,req)
    def test_development_cap_persists_and_blocks_before_key_loading(self):
        cap={'id':'market-history-development','total_usd':.5};budget=Budget(self.root,None,2,None,cap)
        budget.reserve('old',.45);budget.settle('old',.45,{})
        with self.assertRaises(BudgetExceeded):Budget(self.root,None,2,None,cap).reserve('new',.06)
        with self.assertRaises(BudgetExceeded):Budget(self.root,None,2,None,{**cap,'total_usd':.6}).reserve('new',.01)
        paid={'enabled':True,'daily_usd':None,'total_usd':2,'daily_calls':None,'development':cap,'ledger_root':str(self.root),'max_output_tokens':4000,'max_input_token_bound':90000}
        model=OpenAIModel('gpt-6.1-sol',paid,key_provider=lambda:self.fail('Key loaded beyond cap'))
        with self.assertRaises(BudgetExceeded):model.generate(ModelRequest('x','x'*6000,{}))
    def test_saved_images_are_interpreted_locally_before_bounded_cloud_text(self):
        d=data(12);d['provenance']['artifact_directory']=str(self.root);path=self.root/'images'/'fixture.png';path.parent.mkdir();path.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        for row in d['records']:row['images']=[{'local_path':'images/fixture.png'}]
        class Local(AllSelections):
            def generate(self,request):
                if 'observations' in request.schema['properties']:
                    self.calls+=1;self.assert_images=True
                    refs=request.schema['properties']['observations']['items']['properties']['evidence_id']['enum']
                    return ModelResponse(json.dumps({'observations':[{'evidence_id':refs[0],'visible_content':'Broad painting layout'}]}),{}, {})
                return super().generate(request)
        class TextOnly(AllSelections):
            def generate(self,request):
                if request.images:raise AssertionError('Cloud image call forbidden')
                return super().generate(request)
        folder=self.root/'images-job';folder.mkdir();local=Local();report=analyze(d,folder,self.config,local,TextOnly(),TextOnly())
        self.assertTrue(report['local_image_notes_unverified']);self.assertLessEqual(local.calls,6)
    def test_real_intake_structure_two_services_and_repeat_without_credentials(self):
        from test_services import ServiceTests
        from analyzer.services import run_cycle
        fixture=ServiceTests();fixture.setUp()
        try:
            d=data();parameters={'niches':[{'keywords':'printable'}],'limit':None,'shop_ids':[],'search_parameters':{},'page_size':100,'max_pages':10,'exclude_fetched_listings':False,'exclude_fetched_shops':False}
            for day,transactions in ((1,100),(8,120),(15,140)):
                stamp=f'2026-10-{day:02d}T00:00:00Z';name=f'saved-{day}'
                rows=[{'listing_id':str(i+1),'shop_id':r['seller_id'],'title':r['title'],'description':r['description'],'tags':r['tags'],'digital':True,'taxonomy_id':1,
                       'price':12,'currency':'USD','listing_views':day*10,'listing_favorites':day,'observed_at':stamp} for i,r in enumerate(d['records'])]
                snapshot={'run_id':name,'status':'success','finished_at':stamp,'settings':parameters,'dqa':{},'queries':[{'niche':parameters['niches'][0],'collection_complete':True,'listings':rows}],
                          'shops':[{'shop':{**s,'transaction_sold_count':transactions,'observed_at':stamp}} for s in d['metadata']['shops']]}
                write_json(fixture.source/name/'snapshot.json',snapshot);write_json(fixture.source/name/'dqa.json',{})
            config={**fixture.config,'research':POLICY,'opportunities':policy(),'paid':{'enabled':True,'cheap_model':'fixture-cheap','final_model':'fixture-final'}}
            paid=AllSelections();local={s:AllSelections() for s in fixture.models}
            with patch('analyzer.adapters.openai.OpenAIModel',return_value=paid),patch('analyzer.adapters.openai.api_key',side_effect=AssertionError('Key loaded')):
                result=run_cycle(config,'saved-15',local);again=run_cycle(config,'saved-15',local)
            self.assertTrue(all(r['analysis_status']=='completed' and r['delivery_status']=='delivered' for r in result))
            self.assertTrue(all(r['duplicate_trigger'] for r in again))
            market=json.loads((Path(result[1]['directory'])/'outbound.json').read_text())
            self.assertEqual(len(market['report']['recommendations']),1)
            self.assertLess(len(json.dumps(market)),5_000_000)
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
