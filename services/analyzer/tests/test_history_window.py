import json
from pathlib import Path
import tempfile
import unittest
from analyzer.history import series_summary,HistoryIntake
from analyzer.io import write_json
from analyzer.lifecycle import digest, semantic

def row(day,views=None,favorites=None):
 return {'id':'etsy:listing:1','title':'Saved printable','seller_id':'4','observed_at':f'2026-10-{day:02d}T00:00:00Z','metrics':[{'scope':'listing','name':'views','value':views},{'scope':'listing','name':'favorites','value':favorites}]}

class HistoryWindowTests(unittest.TestCase):
 def test_approved_cohort_uses_saved_tracking_on_empty_discovery_and_refresh_is_explicit(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/'runs';cohorts=Path(temp)/'cohorts'
   def save(name,day,tracking=False):
    r={'listing_id':'1','shop_id':'4','title':'Saved printable','digital':True,'observed_at':f'2026-10-{day:02d}T00:00:00Z','listing_views':day}
    v={'run_id':name,'status':'success','finished_at':r['observed_at'],'mode':'tracking' if tracking else 'search','dqa':{},'settings':{'niches':[{'keywords':'printable'}]},'queries':[],'tracked_listings':[{'status':'success','listing':r}] if tracking else [],'shops':[]}
    write_json(root/name/'snapshot.json',v);write_json(root/name/'dqa.json',{})
   save('tracking-old',1,True);save('discovery',8);save('tracking-new',9,True)
   manifest={'listing_ids':['1']};sha=digest(manifest)
   write_json(cohorts/'selected.json',{'manifest':manifest,'manifest_sha256':sha,'approval':{'manifest_sha256':sha},'status':'active'})
   before=HistoryIntake(root,'discovery',cohort_root=cohorts).read()
   after=HistoryIntake(root,'discovery',cohort_root=cohorts,as_of='2026-10-10T00:00:00Z').read()
   self.assertEqual(before.records[0]['observed_at'],'2026-10-01T00:00:00Z')
   self.assertEqual(after.records[0]['observed_at'],'2026-10-09T00:00:00Z')
   self.assertEqual(after.metadata['cohort_context']['scope'],before.metadata['cohort_context']['scope'])
   self.assertNotEqual(semantic({'semantic_context':before.metadata['semantic_context']}),semantic({'semantic_context':after.metadata['semantic_context']}))
   self.assertEqual(after.metadata['semantic_context'],HistoryIntake(root,'discovery',cohort_root=cohorts,as_of='2026-10-10T00:00:00Z').read().metadata['semantic_context'])
   with self.assertRaises(ValueError):HistoryIntake(root,'discovery',as_of='2100-01-01T00:00:00Z').read()
 def test_seven_day_gate_counts_comparable_metrics_not_missing_days(self):
  points=[row(1,None,1),row(2,None,2),row(3,None,3),row(8,5,None)]
  self.assertEqual(series_summary(points,('views','favorites'),'listing')['trend_status'],'insufficient_evidence')
  points=[row(1,1),row(4,2),row(8,3)]
  self.assertEqual(series_summary(points,('views',),'listing')['trend_status'],'engagement_proxy_ready')
 def test_resets_duplicates_and_currency_changes_are_flagged(self):
  points=[{**row(1,10),'price':3,'currency':'USD'},row(4,9),{**row(8,20),'price':5,'currency':'EUR'}]
  result=series_summary(points,('views',),'listing')
  self.assertTrue(result['counter_reset_or_correction']);self.assertEqual(result['trend_status'],'insufficient_evidence')
  self.assertIsNone(result['intervals'][-1]['price']['change'])
  result=series_summary([row(1,1),row(1,2),row(8,3)],('views',),'listing')
  self.assertTrue(result['duplicate_timestamp_conflicts'])
 def test_unbounded_default_finds_older_tracking_identity_among_many_unrelated_runs(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/'runs';root.mkdir()
   def save(name,day,listing=1,tracking=False):
    r={'listing_id':str(listing),'shop_id':'4','title':'Saved printable','digital':True,'observed_at':f'2026-10-{day:02d}T00:00:00Z','listing_views':day}
    v={'run_id':name,'status':'success','finished_at':r['observed_at'],'mode':'tracking' if tracking else 'search','dqa':{},'settings':{'niches':[{'keywords':'printable'}]},'queries':[] if tracking else [{'listings':[r]}],'tracked_listings':[{'status':'success','listing':r}] if tracking else [],'shops':[]}
    write_json(root/name/'snapshot.json',v);write_json(root/name/'dqa.json',{})
   save('old-tracking',1,tracking=True)
   for i in range(20):save('unrelated-'+str(i),7,listing=i+100)
   save('new',25)
   result=HistoryIntake(root,'new').read().metadata['history']
   self.assertIn('old-tracking',[r['run_id'] for r in result['related_observations']]);self.assertEqual(result['listing_series']['etsy:listing:1']['observations'],2)
   self.assertIsNone(result['window_days'])
