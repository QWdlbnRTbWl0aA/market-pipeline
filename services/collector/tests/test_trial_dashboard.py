"""Trial isolation, chosen-shop collection, reporting, exports and shared UI routes."""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from etsy_app.core import Store, config, FetchResult
from etsy_app.server import App, handler, request_host_allowed
from etsy_app.reporting import compose_export, summarize
from test_enrichment import item


class TrialDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.settings = {**config(), 'requests_per_second': 1,
                         'local_daily_request_budget':100,
                         'niches': [{'category': 'Synthetic fixture', 'keywords': 'printable'}]}
        self.app = App(self.settings, self.tmp.name)

    def test_trial_settings_do_not_save_and_scheduled_settings_persist(self):
        before = self.app.config_path.read_bytes()
        parameters = {'keywords': 'printable wedding', 'limit': 205, 'shop_ids': ['41', '42']}
        trial = self.app.trial_settings(parameters)
        self.assertEqual(self.app.config_path.read_bytes(), before)
        self.assertEqual(self.app.settings['niches'][0]['keywords'], 'printable')
        self.app.save_configuration({'revision': self.app.configuration()['revision'], 'settings': trial})
        restarted = App(config(self.app.config_path), self.tmp.name, self.app.config_path)
        self.assertEqual(restarted.settings['limit'], 205)
        self.assertEqual(restarted.settings['shop_ids'], ['41', '42'])
        self.assertEqual(restarted.settings['niches'][0]['keywords'], 'printable wedding')

    def test_reject_invalid_trials_without_modifying_file(self):
        before = self.app.config_path.read_bytes()
        for params in [{'keywords': ''}, {'keywords': 'printable', 'limit': True},
                       {'keywords': 'printable', 'shop_ids': ['bad']},
                       {'keywords': 'printable', 'shop_ids': ['3', '3']},
                       {'keywords': 'printable', 'quota_reserve': 0}]:
            with self.assertRaises(ValueError):self.app.trial_settings(params)
        self.assertEqual(self.app.config_path.read_bytes(), before)

    def test_chosen_shops_only_and_provider_keywords_keep_provenance(self):
        calls = []
        def source(url, timeout, headers):
            calls.append(url); route = urlparse(url)
            if route.path.endswith('/listings/active'):
                identity = int(route.path.split('/')[-3]); offset = int(parse_qs(route.query)['offset'][0])
                body = {'count': 2, 'results': [item(identity * 100 + i, identity) for i in range(offset, min(offset + 2, 2))]}
            else:
                body = {'shop_id': int(route.path.rsplit('/', 1)[-1]), 'shop_name': 'Synthetic'}
            return FetchResult(200, json.dumps(body).encode(), 'application/json', {})
        settings = self.app.trial_settings({'keywords': 'printable', 'shop_ids': ['41', '42'], 'limit': None})
        settings['page_size'] = 2
        with patch.dict(os.environ, {'ETSY_API_KEY': 'fixture', 'ETSY_API_SECRET': 'fixture'}), patch('etsy_app.collection.time.sleep'):
            run = self.app.store.collect(settings, fetcher=source)
        self.assertEqual(run['listing_count'], 4)
        self.assertEqual({r['shop_id'] for q in run['queries'] for r in q['listings']}, {'41', '42'})
        self.assertTrue(all('/shops/' in url for url in calls))
        self.assertTrue(all('keywords=printable' in url for url in calls if '/listings/' in url))
        self.assertEqual(run['status'], 'success')
        summary = summarize(run)
        self.assertEqual(summary['reported_available'], 4)
        self.assertEqual(summary['unique_listings'], 4)
        self.assertTrue(all(not e['keyword_filtered_locally'] for e in summary['query_estimates']))
        self.assertEqual(sum(c['listing_count'] for c in summary['categories']), 4)
        before = {p.name: p.read_bytes() for p in (self.app.store.runs / run['run_id']).iterdir() if p.is_file()}
        exported = compose_export(self.app.store, run['run_id'])
        self.assertEqual(len(exported['raw_responses']), 4)
        self.assertEqual(len(exported['results']['listings']), 4)
        self.assertTrue(all(i['sha256_matches'] for i in exported['dqa']['raw_integrity']))
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.app.store.runs / run['run_id']).iterdir() if p.is_file()})

    def test_selected_shop_result_limit_is_global(self):
        calls = []
        def source(url, *args):
            calls.append(url)
            identity = int(urlparse(url).path.split('/')[4])
            body = {'count': 100, 'results': [item(i, identity) for i in range(1, 6)]} if '/listings/' in url else {'shop_id': identity}
            return FetchResult(200, json.dumps(body).encode(), 'application/json', {})
        settings = self.app.trial_settings({'keywords': 'printable', 'shop_ids': ['41', '42'], 'limit': 3})
        settings['page_size'] = 5
        with patch.dict(os.environ, {'ETSY_API_KEY': 'fixture', 'ETSY_API_SECRET': 'fixture'}), patch('etsy_app.collection.time.sleep'):
            run = self.app.store.collect(settings, fetcher=source)
        self.assertEqual(run['listing_count'], 3)
        self.assertEqual(run['selected_shop_search_coverage']['queried'], 1)
        self.assertEqual(len([u for u in calls if '/listings/' in u]), 1)
        self.assertEqual(summarize(run)['selected_shop_initial_search_requests_remaining'], 1)

    def test_request_estimates_report_unknown_unseen_shops(self):
        run = {'queries': [{'niche': {'keywords': 'printable'}, 'provider_result_count': 205,
               'effective_search': {'page_size': 100}, 'pages': [{'http_status': 200, 'returned_count': 100, 'effective_parameters': {'offset': 0}}],
               'listings': [item(1, 2)]}], 'shops': [], 'settings': {}}
        # This minimal normalized fixture supplies only identity/category for counting.
        s = summarize(run)
        self.assertEqual(s['estimated_remaining_listing_requests_full_query'], 2)
        self.assertEqual(s['known_shop_detail_requests_remaining'], 1)
        self.assertEqual(s['estimated_following_requests_lower_bound'], 3)
        self.assertIn('Unseen shop count is unknown', s['estimate_note'])

    def test_versions_hostname_and_trial_http_isolation(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.app))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        for variant in ('v1',):
            with urllib.request.urlopen(base + '/' + variant) as r:
                self.assertIn(f'data-variant="{variant}"', r.read().decode())
        with patch.object(self.app, 'start', return_value={'status': 'synthetic-not-started'}) as start:
            params = {'keywords': 'trial', 'limit': 205, 'shop_ids': []}
            request = urllib.request.Request(base + '/api/collect', data=json.dumps({'parameters': params}).encode(), headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(request).close()
            self.assertEqual(start.call_args.kwargs['settings_override']['limit'], 205)
            self.assertEqual(config(self.app.config_path)['niches'][0]['keywords'], 'printable')
        with patch.dict(os.environ,{'PIPELINE_DASHBOARD_HOSTNAMES':''}):
            self.assertFalse(request_host_allowed('dashboard.example:8090', '198.51.100.20', 8090))
        with patch.dict(os.environ,{'PIPELINE_DASHBOARD_HOSTNAMES':'dashboard.example,dashboard-alt.example'}):
            self.assertTrue(request_host_allowed('dashboard.example:8090', '198.51.100.20', 8090))
            self.assertTrue(request_host_allowed('dashboard-alt.example:8090', '198.51.100.20', 8090))
        self.assertFalse(request_host_allowed('evil.example:8090', '198.51.100.20', 8090))
        self.assertFalse(request_host_allowed(':8090', '198.51.100.20', 8090))
