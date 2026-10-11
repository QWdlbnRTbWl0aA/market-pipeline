"""Task policy boundaries, using synthetic ledgers and provider observations only."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
for component in ('collector','analyzer','controller'):sys.path.insert(0,str(ROOT/'services'/component))
from analyzer.budget import Budget,BudgetExceeded
from etsy_app.quota import quota_view
from pipeline_control.admission import reserve,close


class PolicyTests(unittest.TestCase):
    def test_more_than_ten_daily_calls_then_total_two_dollar_block(self):
        with tempfile.TemporaryDirectory() as temp:
            budget=Budget(temp,None,2,None)
            for i in range(20):
                budget.reserve(str(i),.1);budget.settle(str(i),.1,{})
            with self.assertRaises(BudgetExceeded):budget.reserve('twenty-first',.001)
            value=json.loads((Path(temp)/'budget.json').read_text())
            self.assertEqual(len(value['calls']),20)

    def test_prior_spend_and_cross_day_experiment_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            budget=Budget(temp,None,2,None)
            budget.reserve('previous',.1570365);budget.settle('previous',.1570365,{})
            envelope=reserve(temp,'e'*64,{'daily_usd':None,'daily_calls':None,'total_usd':2})
            path=Path(temp)/'budget.json';ledger=json.loads(path.read_text())
            ledger['experiments']['e'*64]['day']='2020-01-01';path.write_text(json.dumps(ledger))
            budget.reserve('next-day',.1,experiment_id='e'*64);budget.settle('next-day',.001,{})
            self.assertAlmostEqual(json.loads(path.read_text())['calls']['previous']['charged_usd'],.1570365)
            close(temp,'e'*64)
            with self.assertRaises(BudgetExceeded):budget.reserve('over-total',1.9)

    def test_five_percent_provider_reserve_and_missing_header_bootstrap(self):
        now=1800000000.;settings={'local_daily_request_budget':None,'quota_reserve_percent':5}
        state={'limit_per_day':5000,'remaining_today':251,'quota_observed_at':now}
        view=quota_view([],state,settings,now)
        self.assertEqual(view['reserve'],250);self.assertEqual(view['effective_daily_ceiling'],4750)
        self.assertEqual(view['safe_requests_available'],1)
        self.assertFalse(quota_view([],{**state,'remaining_today':250},settings,now)['ready'])
        self.assertEqual(quota_view([],{**state,'limit_per_day':5010,'remaining_today':5000},settings,now)['reserve'],251)
        bootstrap=quota_view([],{},settings,now);self.assertEqual(bootstrap['safe_requests_available'],1)
        events=[(dt.datetime.fromtimestamp(now-1,dt.timezone.utc),{})]
        self.assertFalse(quota_view(events,{},settings,now)['ready'])

    def test_published_templates_have_no_daily_caps_or_expiry(self):
        collector=json.loads((ROOT/'config'/'collector.example.json').read_text())
        self.assertIsNone(collector['local_daily_request_budget']);self.assertEqual(collector['quota_reserve_percent'],5)
        for name,key in [('analyzer','paid'),('controller','paid_policy')]:
            policy=json.loads((ROOT/'config'/(name+'.example.json')).read_text())[key]
            self.assertEqual(policy['total_usd'],2);self.assertIsNone(policy['daily_usd']);self.assertIsNone(policy['daily_calls'])
