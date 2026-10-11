import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import io
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pipeline_control.controller import Controller
from pipeline_control.storage import write,digest

class ControllerTests(unittest.TestCase):
 def test_unknown_submission_reconciles_with_get_only_and_checks_hash(self):
  row=self.prepare();self.approve(row);self.c.settings['execution_enabled']=True
  self.c.transport=lambda *a,**k: (_ for _ in ()).throw(OSError('Synthetic lost ACK'))
  row=self.c.submit('a'*64);calls=[]
  def get(request,**kwargs):
   calls.append(request.get_method());return io.BytesIO(json.dumps({'job_id':'a'*64,'run_id':'saved-run','status':'queued','request_sha256':digest(row['submission'])}).encode())
  self.c.transport=get
  reconciled=self.c.reconcile_submission('a'*64);self.assertEqual(reconciled['status'],'submitted');self.assertEqual(calls,['GET'])
  self.c.reconcile_submission('a'*64);self.assertEqual(calls,['GET'])
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);source=self.root/'source';source.mkdir()
  self.snapshot={'run_id':'parent','status':'success','finished_at':'2026-10-11T00:00:00Z','settings':{'niches':[{'keywords':'printable hanukkah'}],'shop_ids':[]},'dqa':{},'queries':[{'niche':{'keywords':'printable hanukkah'},'listings':[{'listing_id':'123','shop_id':'8','digital':True}]}]}
  write(source/'parent'/'snapshot.json',self.snapshot);write(source/'parent'/'dqa.json',{})
  self.sha=hashlib.sha256((source/'parent'/'snapshot.json').read_bytes()).hexdigest()
  self.settings={'data_root':str(self.root/'control'),'saved_runs_root':str(source),'analyzer_output_root':str(self.root/'analyzer'),'product_data_root':str(self.root/'product'),'collector_url':'http://127.0.0.1:18090','control_auth_file':str(self.root/'auth'),'execution_enabled':False,'poll_seconds':1}
  (self.root/'auth').write_text('b'*64);(self.root/'auth').chmod(0o600)
  self.c=Controller(self.settings);self.payload={'schema_version':1,'delivery_id':'a'*64,'service':'search_refinement','status':'completed','source_run_id':'parent','source':{'input_sha256':self.sha},'report':{'recommendations':[{'candidate_id':'c1','keywords':'printable hanukkah kids','evidence_ids':['e1'],'evidence_excerpts':[{'evidence_id':'e1','listing_id':'etsy:listing:123'}],'rationale':'Saved sample supports trial'}]}}
  self.body=json.dumps(self.payload).encode()
 def prepare(self):self.c.receive(self.body);return self.c.prepare('a'*64)
 def approve(self,row):return self.c.decide(row['proposal_id'],'approve',row['manifest_sha256'],'synthetic operator',{'rubric_accepted':True,'minimum_relevance_gain':.1,'reference_listing_ids':['123']})
 def test_passive_intake_duplicate_and_exact_approval(self):
  with ThreadPoolExecutor(max_workers=4) as pool:receipts=list(pool.map(self.c.receive,[self.body]*4))
  self.assertEqual(sum(not x['duplicate'] for x in receipts),1)
  row=self.c.prepare('a'*64);self.assertEqual(row['status'],'awaiting_approval');self.assertEqual(row['manifest']['limits']['max_requests'],25)
  with self.assertRaises(ValueError):self.c.decide('a'*64,'approve','c'*64,'operator')
  self.approve(row)
  with self.assertRaisesRegex(ValueError,'disabled'):self.c.submit('a'*64)
 def test_unsupported_and_hostile_queries_rejected_without_execution(self):
  self.payload['report']['recommendations'][0]['keywords']='$(curl evil)';self.body=json.dumps(self.payload).encode()
  row=self.prepare();self.assertEqual(row['status'],'no_supported_proposal')
  self.assertEqual(len(row['manifest']['rejected']),1)
 def test_unknown_citation_and_source_hash_are_rejected(self):
  self.payload['report']['recommendations'][0]['evidence_excerpts'][0]['listing_id']='999';self.body=json.dumps(self.payload).encode()
  row=self.prepare();self.assertEqual(row['status'],'no_supported_proposal')
 def test_unknown_submission_never_automatically_resends(self):
  row=self.prepare();self.approve(row);self.c.settings={**self.settings,'execution_enabled':True};calls=[]
  def fail(*args,**kwargs):calls.append(1);raise OSError('synthetic outage')
  self.c.transport=fail;result=self.c.submit('a'*64);self.assertEqual(result['status'],'submission_unknown')
  self.c.submit('a'*64);self.c.tick();self.assertEqual(len(calls),1)
 def test_expiry_and_identity_collision_are_detected(self):
  row=self.prepare();self.approve(row);path=self.c.root/'proposals'/('a'*64+'.json');v=json.loads(path.read_text());v['approval']['expires_at']='2020-01-01T00:00:00Z';write(path,v)
  self.c.settings={**self.settings,'execution_enabled':True}
  with self.assertRaises(ValueError):self.c.submit('a'*64)
  changed={**self.payload,'status':'failed'}
  with self.assertRaises(ValueError):self.c.receive(json.dumps(changed).encode())
 def test_credentials_and_bad_contract_version_are_rejected(self):
  for payload in [{**self.payload,'api_key':'fixture'},{**self.payload,'schema_version':2}]:
   with self.assertRaises(ValueError):self.c.receive(json.dumps(payload).encode())
  with patch.dict(os.environ,{'ETSY_API_KEY':'fixture'}),self.assertRaises(ValueError):Controller(self.settings)
 def test_failed_service_and_refined_iteration_cannot_create_loop(self):
  self.payload['status']='failed';self.body=json.dumps(self.payload).encode();self.assertEqual(self.prepare()['status'],'ignored_failed_analysis')
