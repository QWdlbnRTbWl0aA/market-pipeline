"""Multiple-search and exclusion behavior without provider requests."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlparse
from etsy_app.core import Store,FetchResult,atomic_json
from etsy_app.server import App
from test_app import SETTINGS
from test_enrichment import item

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name);self.settings={**SETTINGS,'source':'api','limit':1,'page_size':1,'max_pages':1,'max_shops':0,'max_requests_per_run':10}
        self.env=patch.dict(os.environ,{'ETSY_API_KEY':'fixture','ETSY_API_SECRET':'fixture'});self.env.start();self.addCleanup(self.env.stop)
        self.sleep=patch('etsy_app.collection.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
        self.calls=[]
    def source(self,url,*args):
        self.calls.append(url);return FetchResult(200,json.dumps({'count':1000,'results':[item(11,22)]}).encode(),'application/json',{})
    def test_filtered_result_never_expands_one_result_probe(self):
        prior=self.store.collect(self.settings,fetcher=self.source)
        raw=(self.store.runs/prior['run_id']/prior['queries'][0]['raw_file']).read_bytes()
        run=self.store.collect({**self.settings,'exclude_fetched_shops':True,'exclude_fetched_listings':True},fetcher=self.source)
        self.assertEqual(run['request_count'],1);self.assertEqual(run['listing_count'],0)
        self.assertEqual(run['queries'][0]['excluded_shop_listing_count'],1)
        self.assertEqual(run['queries'][0]['provider_result_count'],1000)
        self.assertEqual((self.store.runs/prior['run_id']/prior['queries'][0]['raw_file']).read_bytes(),raw)
        self.assertTrue(all(parse_qs(urlparse(u).query)['limit']==['1'] for u in self.calls))
    def test_shop_query_skipped_and_zero_request_success_persists(self):
        self.store.collect(self.settings,fetcher=self.source)
        run=self.store.collect({**self.settings,'shop_ids':['22'],'exclude_fetched_shops':True},fetcher=self.source)
        self.assertEqual(run['request_count'],0);self.assertEqual(run['status'],'success')
        self.assertIn('22',run['exclusions']['shop_calls_skipped'])
    def test_new_shop_retains_multiple_listings_in_one_search_but_next_search_excluded(self):
        run=self.store.collect({**self.settings,'exclude_fetched_shops':True,'niches':[{'category':'A','keywords':'printable a'},{'category':'B','keywords':'printable b'}]},fetcher=self.source)
        self.assertEqual(run['request_count'],2);self.assertEqual(len(run['queries'][0]['listings']),1)
        self.assertEqual(run['queries'][1]['excluded_shop_listing_count'],1)
    def test_multi_search_save_and_restart_round_trip(self):
        path=self.store.directory/'config.json';app=App(self.settings,self.tmp.name,path)
        params={'niches':[{'category':'A','keywords':'printable a'},{'category':'B','keywords':'printable b'}],'limit':1,'exclude_fetched_shops':True}
        value=app.trial_settings(params);app.save_configuration({'settings':value,'revision':app.configuration()['revision']})
        self.assertEqual(App(self.settings,self.tmp.name,path).configuration()['niches'],value['niches'])
        with self.assertRaises(ValueError):app.trial_settings({**params,'keywords':'ambiguous'})
    def test_tracking_bypasses_discovery_exclusions(self):
        self.store.collect(self.settings,fetcher=self.source)
        def tracked(url,*args):
            self.calls.append(url);return FetchResult(200,json.dumps(item(11,22)).encode(),'application/json',{})
        run=self.store.track({**self.settings,'exclude_fetched_shops':True,'exclude_fetched_listings':True,'tracking':{'listing_ids':['11'],'shop_ids':[]}},fetcher=tracked)
        self.assertEqual(len(run['tracked_listings']),1);self.assertEqual(run['request_count'],1)
