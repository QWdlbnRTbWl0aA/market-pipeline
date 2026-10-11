import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from etsy_app.core import config,atomic_json
from etsy_app.server import App,handler
from http.server import ThreadingHTTPServer
import threading
import urllib.request
import urllib.error
from etsy_app.control import Jobs,effective,authentication

class ControlJobTests(unittest.TestCase):
 def test_http_control_auth_and_browser_decision_same_origin(self):
  path=self.root/'control-auth';path.write_text('d'*64);path.chmod(0o600);self.app.control_auth_file=str(path)
  http=ThreadingHTTPServer(('127.0.0.1',0),handler(self.app));threading.Thread(target=http.serve_forever,daemon=True).start()
  self.addCleanup(http.server_close);self.addCleanup(http.shutdown)
  url='http://127.0.0.1:'+str(http.server_port)
  def send(route,headers):
   req=urllib.request.Request(url+route,json.dumps(self.request).encode(),headers={'Content-Type':'application/json',**headers})
   try:
    with urllib.request.urlopen(req,timeout=3) as response:return response.status
   except urllib.error.HTTPError as response:return response.code
  for headers in ({},{'X-Pipeline-Control':'wrong'},{'X-Pipeline-Control':'d'*64,'Origin':url}):self.assertEqual(send('/api/control/jobs',headers),403)
  self.assertEqual(list(self.app.control_jobs.root.glob('*.json')),[])
  self.assertEqual(send('/api/control/jobs',{'X-Pipeline-Control':'d'*64}),202)
  with patch('etsy_app.control.controller_request',return_value={'accepted':True}) as proxy:
   self.assertEqual(send('/api/pipeline/operations',{'Origin':'http://evil.invalid'}),403);proxy.assert_not_called()
   self.assertEqual(send('/api/pipeline/operations',{'Origin':url}),200);proxy.assert_called_once()
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.app=App(config(),self.root)
  self.request={'schema_version':1,'job_id':'a'*64,'manifest_sha256':'b'*64,'kind':'experiment','lineage':{'root_cycle_id':'parent-1','parent_run_id':'parent-1','experiment_id':'a'*64,'iteration':1,'max_paid_calls':4},'parameters':{'niches':[{'category':'Test','keywords':'printable hanukkah'},{'category':'Test','keywords':'printable hanukkah kids'}],'limit':100,'shop_ids':[],'exclude_fetched_listings':False,'exclude_fetched_shops':False},'bounds':{'max_requests':12,'max_pages':1,'max_shops':10},'approval':{'manifest_sha256':'b'*64,'reviewed_by':'synthetic test','expires_at':(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=1)).isoformat()}}
 def test_duplicate_ack_does_not_create_or_start_another_job(self):
  with patch.object(self.app,'start') as start:
   a=self.app.control_jobs.submit(self.request);b=self.app.control_jobs.submit(self.request)
   self.assertEqual(a['run_id'],b['run_id']);self.assertTrue(b['duplicate']);start.assert_not_called()
   self.app.control_jobs.tick();start.assert_called_once()
   self.app.control_jobs.tick();start.assert_called_once()
   row=json.loads((self.app.control_jobs.root/('a'*64+'.json')).read_text());self.assertEqual(row['status'],'requires_reconciliation')
 def test_safety_bounds_and_daily_settings_are_preserved(self):
  before=self.app.config_path.read_bytes();settings=effective(self.app,self.request)
  self.assertEqual(settings['max_requests_per_run'],12);self.assertEqual(settings['requests_per_second'],self.app.settings['requests_per_second'])
  self.assertEqual(settings['quota_reserve'],self.app.settings['quota_reserve']);self.assertEqual(self.app.config_path.read_bytes(),before)
  for changed in [{'max_requests':26,'max_pages':1,'max_shops':10},{'max_requests':2,'max_pages':1,'max_shops':10}]:
   with self.assertRaises(ValueError):effective(self.app,{**self.request,'bounds':changed})
 def test_root_reservation_prevents_equivalent_new_job(self):
  self.app.control_jobs.submit(self.request)
  second=json.loads(json.dumps(self.request));second['job_id']='c'*64;second['lineage']['experiment_id']='c'*64
  with self.assertRaises(ValueError):self.app.control_jobs.submit(second)
 def test_interrupted_and_finalized_runs_reconcile_without_requests(self):
  result=self.app.control_jobs.submit(self.request);path=self.app.control_jobs.root/('a'*64+'.json')
  row=json.loads(path.read_text());row['status']='running';atomic_json(path,row)
  snapshot={'schema_version':2,'run_id':result['run_id'],'status':'success','started_at':'2026-10-11T00:00:00Z','finished_at':'2026-10-11T01:00:00Z','trigger':'approved-experiment','listing_count':0,'queries':[],'request_count':12}
  atomic_json(self.app.store.runs/result['run_id']/'snapshot.json',snapshot)
  with patch.object(self.app,'start') as start:self.app.control_jobs.tick();start.assert_not_called()
  self.assertEqual(json.loads(path.read_text())['status'],'completed')
 def test_auth_is_dedicated_and_refuses_symlinks_and_bad_mode(self):
  path=self.root/'control-auth';path.write_text('a'*64);path.chmod(0o600)
  self.assertTrue(authentication(path,'a'*64));self.assertFalse(authentication(path,'b'*64));path.chmod(0o644)
  self.assertFalse(authentication(path,'a'*64))
 def test_expired_approval_stops_before_queue(self):
  self.request['approval']['expires_at']='2020-01-01T00:00:00Z'
  with self.assertRaises(ValueError):self.app.control_jobs.submit(self.request)
  self.assertEqual(list(self.app.control_jobs.root.glob('*.json')),[])
