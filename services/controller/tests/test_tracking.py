import datetime as dt
import json
from pathlib import Path
import unittest
import test_controller
from zoneinfo import ZoneInfo
from pipeline_control.tracking import prepare,decide,tick
from pipeline_control.storage import write

class TrackingTests(unittest.TestCase):
 setUp=test_controller.ControllerTests.setUp
 def test_saved_access_challenge_pauses_future_days(self):
  path=self.root/'market.json';write(path,{**self.payload,'service':'market_insights'});row=prepare(self.c,path)
  row=decide(self.c,row['cohort_id'],'approve',row['manifest_sha256'],'synthetic reviewer');self.c.settings['execution_enabled']=True
  start=dt.date.fromisoformat(row['approval']['start_day']);calls=[];run_id=self.payload['source_run_id']
  def submit(value):calls.append(value);return {'run_id':run_id}
  tick(self.c,submit,dt.datetime.combine(start,dt.time(10),ZoneInfo('Asia/Jerusalem')))
  write(self.c.source/run_id/'snapshot.json',{'status':'failed','tracked_listings':[{'http_status':429}]})
  tick(self.c,submit,dt.datetime.combine(start+dt.timedelta(days=1),dt.time(10),ZoneInfo('Asia/Jerusalem')))
  self.assertEqual(len(calls),1)
  from pipeline_control.storage import read
  self.assertEqual(read(self.c.root/'cohorts'/(row['cohort_id']+'.json'))['status'],'paused_access_challenge')
 def test_cohort_window_duplicate_days_and_unknown_submission_are_bounded(self):
  payload={**self.payload,'service':'market_insights'};path=self.root/'market.json';write(path,payload)
  row=prepare(self.c,path);again=prepare(self.c,path);self.assertEqual(row['cohort_id'],again['cohort_id'])
  row=decide(self.c,row['cohort_id'],'approve',row['manifest_sha256'],'synthetic reviewer');self.c.settings['execution_enabled']=True
  start=dt.date.fromisoformat(row['approval']['start_day']);calls=[]
  def submit(value):calls.append(value);return {'job_id':value['job_id'],'run_id':'fixture'}
  for i in range(15):
   instant=dt.datetime.combine(start+dt.timedelta(days=i),dt.time(10),ZoneInfo("Asia/Jerusalem"))
   tick(self.c,submit,instant);tick(self.c,submit,instant)
  self.assertEqual(len(calls),15);self.assertTrue(all(r['bounds']['max_requests']==2 for r in calls));self.assertEqual(sum(r['bounds']['max_requests'] for r in calls),30)
  self.assertIsNone(row['approval']['end_day']);self.assertIsNone(row['manifest']['maximum_requests'])
 def test_tracking_failure_is_not_retried_the_same_day(self):
  payload={**self.payload,'service':'market_insights'};path=self.root/'market.json';write(path,payload);row=prepare(self.c,path)
  row=decide(self.c,row['cohort_id'],'approve',row['manifest_sha256'],'synthetic reviewer');self.c.settings['execution_enabled']=True;calls=[]
  start=dt.date.fromisoformat(row['approval']['start_day']);instant=dt.datetime.combine(start,dt.time(10),ZoneInfo("Asia/Jerusalem"))
  def fail(value):calls.append(value);raise OSError('Synthetic outage')
  tick(self.c,fail,instant);tick(self.c,fail,instant);self.assertEqual(len(calls),1)
