import json
from pathlib import Path
import tempfile
import unittest
from analyzer.io import write_json
from analyzer.lifecycle import Cursor, digest, semantic, migrate, resolve

class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.identity={'service':'market_insights','input_sha256':'a'*64,'source_run_id':'cycle-1','recipe_version':'r1','model':'local','model_digest':'v1','sample_size':8,'paid_policy':{'enabled':True,'cheap_model':'cheap','final_model':'good','daily_calls':10},'history_sha256':'original'}
 def test_budget_endpoint_and_history_refresh_do_not_repeat_completed_inference(self):
  original=digest(semantic(self.identity));changed={**self.identity,'history_sha256':'later','paid_policy':{**self.identity['paid_policy'],'daily_calls':20,'ledger_root':'different','daily_usd':1}}
  self.assertEqual(original,digest(semantic(changed)))
  self.assertNotEqual(original,digest(semantic({**self.identity,'recipe_version':'r2'})))
 def test_explicit_migration_accounts_for_legacy_and_preserves_bytes(self):
  path=self.root/'market_insights'/'legacy'/'state.json';write_json(path,{**self.identity,'job_id':'legacy','analysis_status':'completed'})
  before=path.read_bytes();manifest=migrate(self.root)
  self.assertEqual(manifest['completed'],1);self.assertEqual(path.read_bytes(),before)
  key,folder=resolve(self.root,{**self.identity,'paid_policy':{**self.identity['paid_policy'],'daily_calls':3}})
  self.assertEqual(key,'legacy');self.assertEqual(folder,path.parent)
 def test_cursor_restart_preserves_floor_and_pending_gap(self):
  first=Cursor(self.root,'search_refinement','2026-10-10T00:00:00Z')
  self.assertFalse(first.eligible('old','2026-10-09T00:00:00Z'))
  self.assertTrue(first.eligible('pending','2026-10-11T00:00:00Z'))
  restart=Cursor(self.root,'search_refinement','2026-10-12T00:00:00Z')
  self.assertTrue(restart.eligible('missed','2026-10-11T01:00:00Z'))
  self.assertTrue(restart.eligible('pending','2026-10-11T00:00:00Z'))
  restart.finish('pending',{'analysis_status':'completed','delivery_status':'delivered'})
  self.assertFalse(restart.eligible('pending','2026-10-11T00:00:00Z'))
 def test_failure_is_parked_separately(self):
  a=Cursor(self.root,'search_refinement');b=Cursor(self.root,'market_insights')
  a.finish('cycle',{'status':'interrupted_requires_explicit_retry'})
  self.assertFalse(a.eligible('cycle','2026-10-11T00:00:00Z'));self.assertTrue(b.eligible('cycle','2026-10-11T00:00:00Z'))

class ExperimentBudgetTests(unittest.TestCase):
 def test_four_incremental_calls_shared_across_services(self):
  from analyzer.budget import Budget,BudgetExceeded
  with tempfile.TemporaryDirectory() as temp:
   budget=Budget(temp,1,1,10)
   for i in range(4):budget.reserve(str(i),.01,'a'*64);budget.settle(str(i),.001,{})
   with self.assertRaises(BudgetExceeded):budget.reserve('fifth',.01,'a'*64)
 def test_unknown_outcome_blocks_other_paid_work_without_releasing_reservation(self):
  from analyzer.budget import Budget,BudgetExceeded
  with tempfile.TemporaryDirectory() as temp:
   budget=Budget(temp,1,1,10);budget.reserve('unknown',.01)
   with self.assertRaises(BudgetExceeded):budget.reserve('other',.01)
   self.assertEqual(json.loads((Path(temp)/'budget.json').read_text())['calls']['unknown']['charged_usd'],.01)
