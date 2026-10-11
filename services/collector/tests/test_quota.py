"""Deterministic saved-history admission tests: never request Etsy."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from etsy_app.quota import quota_view
from etsy_app.core import Store, atomic_json
from etsy_app.collection import Client


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.current = 1800000000.
        self.state = {'key_id':'key', 'quota_observed_at':self.current, 'remaining_today':1, 'limit_per_day':5}
        self.settings = {'local_daily_request_budget':10, 'quota_reserve':1}

    def events(self, offsets):
        return [(dt.datetime.fromtimestamp(self.current+offset,dt.timezone.utc),
                 {'http_status':200, 'finished_at':dt.datetime.fromtimestamp(self.current+offset+.5,dt.timezone.utc).isoformat(), 'key_id':'key'})
                for offset in offsets]

    def test_provider_limit_caps_larger_local_budget_and_reserve(self):
        view=quota_view(self.events([-86390,-100,-90,-80]),self.state,self.settings,self.current)
        self.assertEqual(view['effective_daily_ceiling'],4)
        self.assertEqual(view['safe_requests_available'],0)
        self.assertAlmostEqual(view['wait_seconds'],10.75)
        later=quota_view(self.events([-86390,-100,-90,-80]),self.state,self.settings,self.current+10.75)
        self.assertTrue(later['ready']);self.assertEqual(later['safe_requests_available'],1)
        self.assertEqual(later['projected_remaining'],2)

    def test_must_expire_enough_requests_to_restore_reserve(self):
        state={**self.state,'remaining_today':0}
        view=quota_view(self.events([-86390,-86380,-90]),state,self.settings,self.current)
        self.assertAlmostEqual(view['wait_seconds'],20.75)
        self.assertFalse(quota_view(self.events([-86390,-86380,-90]),state,self.settings,self.current+15)['ready'])

    def test_unknown_usage_is_not_credited_before_full_observation_window(self):
        state={**self.state,'remaining_today':0,'limit_per_day':100}
        view=quota_view(self.events([-86390]),state,{'local_daily_request_budget':1000,'quota_reserve':10},self.current)
        self.assertAlmostEqual(view['wait_seconds'],86400.25)
        self.assertEqual(view['projected_remaining'],0)

    def test_saved_retry_after_is_respected_and_zero_ceiling_cannot_send(self):
        state={**self.state,'blocked_until':self.current+40}
        view=quota_view(self.events([-86390,-100,-90,-80]),state,self.settings,self.current)
        self.assertEqual(view['wait_seconds'],40)
        impossible=quota_view([],self.state,{**self.settings,'quota_reserve':5},self.current)
        self.assertFalse(impossible['ready']);self.assertIsNone(impossible['wait_seconds'])

    def test_clock_rounding_or_rollback_does_not_bypass_observed_quota(self):
        view=quota_view([],{**self.state,'quota_observed_at':self.current+.000001},self.settings,self.current)
        self.assertFalse(view['ready'])
        self.assertGreater(view['wait_seconds'],86400)

    def test_other_key_history_cannot_grant_current_key_quota(self):
        events=self.events([-86390]);events[0][1]['key_id']='another-key'
        view=quota_view(events,self.state,self.settings,self.current)
        self.assertEqual(view['local_key_requests_24h'],0)
        self.assertAlmostEqual(view['wait_seconds'],86400.25)

    def test_reservation_waits_rechecks_and_recovers_from_saved_history(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'ETSY_API_KEY':'fixture','ETSY_API_SECRET':'fixture'}):
            store=Store(directory);root=Path(directory);(root/'requests').mkdir()
            key=hashlib.sha256(b'fixture').hexdigest()[:16]
            offsets=[-86390,-100,-90,-80]
            for index,(stamp,event) in enumerate(self.events(offsets)):
                atomic_json(root/'requests'/f'{index}.json',dict(event,request_id=str(index),key_id=key,source='api',started_at=stamp.isoformat()))
            atomic_json(root/'rate-limit-state.json',dict(self.state,key_id=key))
            output=root/'scratch';output.mkdir()
            clock=[self.current];phases=[]
            store.progress_callback=lambda run_id,progress:phases.append(progress)
            run={'run_id':'fixture','queries':[],'shops':[]}
            client=Client(store,self.settings,run,output,lambda *args: self.fail('No network allowed'))
            def advance(seconds):clock[0]+=seconds
            with patch('etsy_app.collection.time.time',side_effect=lambda:clock[0]), patch('etsy_app.collection.time.sleep',side_effect=advance):
                client.reserve()
            self.assertAlmostEqual(clock[0],self.current+10.75)
            self.assertEqual(client.count,0)
            self.assertTrue(any(p['phase']=='waiting' and p['quota']['safe_requests_available']==0 for p in phases))
            # The credited slot is consumed locally; it cannot be reused with missing headers.
            view=store.request_usage(instant=dt.datetime.fromtimestamp(clock[0],dt.timezone.utc),settings=self.settings,state=client.state)['quota']
            self.assertFalse(view['ready'])


if __name__=='__main__':unittest.main()
