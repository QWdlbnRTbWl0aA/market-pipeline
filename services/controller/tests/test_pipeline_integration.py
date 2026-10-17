"""Entire direct/refined flows over labelled synthetic source/model adapters only."""
import hashlib,json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
from components import ROOTS
from etsy_app.core import Store,config,FetchResult,atomic_json
from etsy_app.server import App,handler
from http.server import ThreadingHTTPServer
from analyzer.services import run_cycle
from pipeline_control.controller import Controller
from pipeline_control.server import server as control_server
from pipeline_control.storage import write
from product_service.server import server as product_server
from product_service.definition import enhanced

class DefinitionFixture:
 def __init__(self):self.calls=0
 def generate(self,context,schema):
  self.calls+=1;ref=context['samples'][0]['evidence_id'];definition={'audience':'Synthetic test family hosts','job':'Synthetic activity task','content_units':[{'title':t,'purpose':'Labelled fixture content only','tasks':['Synthetic test task'],'evidence_ids':[ref]} for t in ('Fixture cards','Fixture host guide','Fixture worksheet')],**{k:['Synthetic first requirement','Synthetic second requirement'] for k in ('user_flow','package','accessibility','localization','acceptance_tests','assumptions')},'design_directions':[{'name':n,'palette':['#ffffff','#123456'],'typography':'Synthetic sans serif','content_unit_indices':[i],'intent':'Synthetic functional layout'} for i,n in enumerate(('Fixture card layout','Fixture guided layout'))]}
  return {'definition':definition,'provider':'synthetic','raw':{'fixture':True}}

class ResearchFixture:
 def __init__(self,broken=False):self.calls=0;self.broken=broken
 def generate(self,service,dataset):
  self.calls+=1
  if self.broken:raise RuntimeError('Synthetic stage outage')
  rows=[r for r in dataset['records'] if r['digital'] is True];r=rows[0];excerpt={'evidence_id':'e1','listing_id':r['id'],'title':r['title'],'digital':True,'shop_id':r['seller_id']}
  statement={'text':'Synthetic family activity product','basis':'design_hypothesis','evidence_ids':['e1']}
  brief={'product_concept':'Synthetic functional product, not a recommendation','intended_customer':statement,'customer_job':statement,'differentiation':statement,'deliverables':[statement],'acceptance_checks':['Synthetic print check'],'validation_plan':['Synthetic reference review'],'risks':['Synthetic data only']}
  return {'service':service,'status':'provisional','recommendations':[{'candidate_id':'c1','keywords':'printable hanukkah kids','evidence_ids':['e1'],'evidence_excerpts':[excerpt],'rationale':'Synthetic functional candidate','product_brief':brief if service=='market_insights' else None,'facts':{'shop_count':len({r['seller_id'] for r in rows}),'performance_cross_check':{'history_qualification':dataset['metadata']['history']['listing_series'],'shop_history_qualification':dataset['metadata']['history']['shop_series'],'positive_shop_sales_intervals':sum((v.get('change') or 0)>0 for s in dataset['metadata']['history']['shop_series'].values() for d in s['intervals'] for k,v in d['metrics'].items() if k=='transaction_sold_count')}},'high_demand_verified':False,'thin_supply_verified':False}]}

class IntegrationTests(unittest.TestCase):
 def test_direct_refined_http_duplicate_restart_independent_failure_and_rollback(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);data=root/'collector';settings={**config(ROOTS['collector']/'config.example.json'),'source':'api','local_daily_request_budget':100,'niches':[{'category':'Synthetic','keywords':'printable hanukkah'}],'limit':100,'max_pages':1,'page_size':100,'max_shops':10,'max_requests_per_run':25,'exclude_fetched_listings':False,'exclude_fetched_shops':False,'search_parameters':{},'tracking':{'listing_ids':[],'shop_ids':[]}}
   calls=[]
   def listing(i,digital=True):return {'listing_id':1100+i,'shop_id':40+i,'title':'Synthetic Hanukkah printable cards' if digital else 'Synthetic physical holiday vase','description':'Labelled functional fixture only','tags':['hanukkah','kids'],'is_digital':digital,'listing_type':'download' if digital else 'physical','views':100,'num_favorers':10,'taxonomy_id':1350,'price':{'amount':500,'divisor':100,'currency_code':'USD'}}
   def source(url,timeout,headers):
    self.assertEqual(headers['x-api-key'],'fixture:fixture');calls.append(url);parsed=urlparse(url)
    if parsed.path.endswith('/listings/active'):
     kids='kids' in parse_qs(parsed.query)['keywords'][0];rows=[listing(i) for i in (1,2,3)]+([] if kids else [listing(4,False)]);body={'count':len(rows),'results':rows}
    else:body={'shop_id':int(parsed.path.rsplit('/',1)[-1]),'shop_name':'Synthetic shop','transaction_sold_count':100,'listing_active_count':20}
    return FetchResult(200,json.dumps(body).encode(),'application/json',{})
   store=Store(data)
   with patch.dict(os.environ,{'ETSY_API_KEY':'fixture','ETSY_API_SECRET':'fixture'}),patch('etsy_app.collection.time.sleep'):
    parent=store.collect(settings,fetcher=source)
   # Synthetic dated observations provide a seven-day gate fixture. These are
   # not claimed as real elapsed observations.
   for day in (4,8):
    prior=json.loads(json.dumps(parent));prior['run_id']=f'202610{day:02d}T000000Z-00000000000{day}';prior['finished_at']=f'2026-10-{day:02d}T00:00:00Z';prior['mode']='tracking';prior['artifact_kind']='tracking'
    for record in prior['shops']:
     record['shop']['observed_at']=prior['finished_at'];record['shop']['transaction_sold_count']=day
    for query in prior['queries']:
     for row in query['listings']:row['observed_at']=prior['finished_at'];row['listing_views']=day
    atomic_json(store.runs/prior['run_id']/'snapshot.json',prior);atomic_json(store.runs/prior['run_id']/'dqa.json',prior['dqa'])
   app=App(settings,data);auth=root/'auth';auth.write_text('a'*64);auth.chmod(0o600);app.control_auth_file=str(auth)
   collect_server=ThreadingHTTPServer(('127.0.0.1',0),handler(app))
   output=root/'analyzer';control_settings={'data_root':str(root/'control'),'saved_runs_root':str(store.runs),'analyzer_output_root':str(output),'product_data_root':str(root/'product'),'collector_url':'http://127.0.0.1:'+str(collect_server.server_port),'control_auth_file':str(auth),'execution_enabled':False,'poll_seconds':1}
   controller_server=control_server(control_settings,0);controller=controller_server.controller;model=DefinitionFixture()
   process_patch=patch('product_service.server.process',side_effect=lambda body,out,*unused:enhanced(body,out,model,qualification_root=controller.root/'qualifications'))
   process_patch.start();products=product_server(root/'product',0);control_settings['product_url']='http://127.0.0.1:'+str(products.server_port)
   servers=[collect_server,controller_server,products]
   for http in servers:threading.Thread(target=http.serve_forever,daemon=True).start()
   cfg={'saved_runs_root':str(store.runs),'output_root':str(output),'model':'synthetic','sample_size':8,'research':{},'paid':{'enabled':False,'ledger_root':str(root/'paid'),'cheap_model':'gpt-6-luna','final_model':'gpt-6.1-sol'},'endpoints':{'search_refinement':'http://127.0.0.1:'+str(controller_server.server_port)+'/search-refinement','market_insights':control_settings['product_url']+'/market-insights'}}
   models={s:ResearchFixture() for s in ('search_refinement','market_insights')}
   def analyze(service,dataset,directory,config,local,*args):return local.generate(service,dataset)
   try:
    with patch('analyzer.research.analyze',side_effect=analyze):
     direct=run_cycle(cfg,parent['run_id'],models);duplicate=run_cycle(cfg,parent['run_id'],models)
     self.assertTrue(all(r.get('duplicate_trigger') for r in duplicate));self.assertEqual([m.calls for m in models.values()],[1,1])
     key=json.loads((Path(direct[0]['directory'])/'outbound.json').read_text())['delivery_id'];proposal=controller.prepare(key)
     ids=proposal['manifest']['phrases'][0]['listing_ids'];controller.decide(key,'approve',proposal['manifest_sha256'],'synthetic operator',{'rubric_accepted':True,'minimum_relevance_gain':.1,'reference_listing_ids':ids});controller.settings['execution_enabled']=True
     submitted=controller.submit(key);self.assertEqual(submitted['status'],'submitted');collector_id=submitted['collector_receipt']['run_id']
     actual=app.store.collect
     with patch.dict(os.environ,{'ETSY_API_KEY':'fixture','ETSY_API_SECRET':'fixture'}),patch('etsy_app.collection.time.sleep'),patch.object(app.store,'collect',side_effect=lambda settings,niches=None,trigger='manual':actual(settings,niches,trigger,source)):
      app.control_jobs.tick()
      for _ in range(500):
       if app.job['status']!='running':break
       threading.Event().wait(.005)
      self.assertEqual(app.job['status'],'success',app.job);app.control_jobs.tick()
     requests=len(calls);replayed=controller.submit(key);self.assertEqual(replayed['collector_receipt']['run_id'],collector_id);self.assertEqual(len(calls),requests)
     controller.complete(key);p=json.loads((controller.root/'proposals'/(key+'.json')).read_text());self.assertEqual(p['status'],'awaiting_human_labels')
     # Blank/uncertain labels never qualify. Fully synthetic human-reference
     # labels are supplied here solely to exercise acceptance mechanics.
     labels={'snapshot_sha256':p['comparison']['snapshot_sha256'],'reviewer':'synthetic reference reviewer','labels':{r['listing_id']:'irrelevant' if r['listing_id']=='1104' else 'relevant' for r in p['comparison']['review_sample']}}
     refined=run_cycle(cfg,collector_id,models);run_cycle(cfg,collector_id,models)
     self.assertEqual([m.calls for m in models.values()],[2,2])
     for _ in range(100):
      if len(list((root/'product'/'intake').glob('*.result')))>=2:break
      time.sleep(.01)
     accepted=controller.labels(key,labels);self.assertEqual(accepted['status'],'accepted')
     controller.qualified_delivery(key);controller.qualified_delivery(key)
     for _ in range(100):
      receipts=list((root/'product'/'intake').glob('*.result'))
      if len(receipts)>=3:break
      time.sleep(.01)
     statuses=[json.loads(p.read_text())['status'] for p in receipts]
     self.assertIn('completed_drafts',statuses);self.assertIn('review_pending',statuses)
     controller.settings['execution_enabled']=False;controller.tick();self.assertEqual(len(calls),requests)
     self.assertEqual((data/'config.json').read_bytes(),app.config_path.read_bytes())
     broken={s:ResearchFixture(s=='search_refinement') for s in models}
     failed_cfg={**cfg,'output_root':str(root/'failure-output')};r=run_cycle(failed_cfg,parent['run_id'],broken)
     self.assertEqual(r[0]['analysis_status'],'failed');self.assertEqual(r[1]['analysis_status'],'completed')
     self.assertEqual([m.calls for m in broken.values()],[1,1]);self.assertLessEqual(json.loads((store.runs/collector_id/'snapshot.json').read_text())['request_count'],25)
   finally:
    for http in servers:
     if hasattr(http,'stop_worker'):http.stop_worker()
     http.shutdown();http.server_close()
    process_patch.stop()
