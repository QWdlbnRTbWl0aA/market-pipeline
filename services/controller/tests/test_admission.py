import json
from pathlib import Path
import sys,tempfile,unittest
from components import ROOTS
from analyzer.budget import Budget,BudgetExceeded
from pipeline_control.admission import reserve,close

class PaidEnvelopeTests(unittest.TestCase):
 def test_reservation_protects_four_slots_from_other_daily_work(self):
  with tempfile.TemporaryDirectory() as tmp:
   policy={'daily_usd':.5,'total_usd':1.0,'daily_calls':10};r=reserve(tmp,'e'*64,policy)
   self.assertEqual(r['maximum_calls'],4);self.assertEqual(r['maximum_usd'],.462);self.assertEqual(reserve(tmp,'e'*64,policy),r)
   budget=Budget(tmp,.5,1,10)
   for i in range(6):budget.reserve(str(i),.001);budget.settle(str(i),.001,{})
   with self.assertRaises(BudgetExceeded):budget.reserve('seventh',.001)
   for i in range(4):budget.reserve('trial-'+str(i),.01,'e'*64);budget.settle('trial-'+str(i),.001,{})
   close(tmp,'e'*64);value=json.loads((Path(tmp)/'budget.json').read_text());self.assertEqual(value['experiments']['e'*64]['status'],'closed');self.assertEqual(len(value['calls']),10)
 def test_budget_exhaustion_and_unknown_do_not_submit_or_release_funds(self):
  with tempfile.TemporaryDirectory() as tmp:
   budget=Budget(tmp,.5,1,10);budget.reserve('unknown',.01)
   before=(Path(tmp)/'budget.json').read_bytes()
   with self.assertRaises(ValueError):reserve(tmp,'e'*64,{'daily_usd':.5,'total_usd':1,'daily_calls':10})
   self.assertEqual((Path(tmp)/'budget.json').read_bytes(),before)
