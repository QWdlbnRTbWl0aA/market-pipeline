"""Synthetic enrichment, pagination, tracking, recovery and quota behavior."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs
from etsy_app.core import Store, FetchResult, atomic_json, validate_config
from test_app import SETTINGS


def item(identity, shop=20):
    return {'listing_id': identity, 'shop_id': shop, 'title': 'Printable weekly planner', 'description': 'PDF printable planner',
            'tags': ['planner', 'printable'], 'views': 123, 'num_favorers': 42, 'listing_type': 'download',
            'original_creation_timestamp': 1600000000, 'creation_timestamp': 1700000000, 'updated_timestamp': 1710000000,
            'price': {'amount': 450, 'divisor': 100, 'currency_code': 'USD'}, 'taxonomy_id': 1, 'language': 'en', 'state': 'active'}


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.settings = {**SETTINGS, 'source': 'api', 'limit': 6, 'page_size': 3, 'max_pages': 2,
                         'max_shops': 2, 'max_requests_per_run': 10, 'local_daily_request_budget': 100}
        self.calls = []
        self.env = patch.dict(os.environ, {'ETSY_API_KEY': 'fixture-key', 'ETSY_API_SECRET': 'fixture-secret'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.clock = time.time()
        self.sleep = patch('etsy_app.collection.time.sleep', side_effect=self.advance)
        self.time = patch('etsy_app.collection.time.time', side_effect=lambda: self.clock)
        self.sleep.start(); self.time.start(); self.addCleanup(self.sleep.stop); self.addCleanup(self.time.stop)

    def advance(self, seconds):
        self.clock += seconds

    def fetch(self, url, timeout, headers):
        self.calls.append(url)
        route = urlparse(url); params = parse_qs(route.query)
        if route.path.endswith('/listings/active'):
            offset = int(params.get('offset', ['0'])[0]); limit = int(params['limit'][0])
            body = {'count': 8, 'results': [item(i, 20 + i % 3) for i in range(100 + offset, 100 + offset + limit)]}
        elif '/shops/' in route.path:
            identity = int(route.path.rsplit('/', 1)[-1])
            body = {'shop_id': identity, 'shop_name': 'Fixture Shop', 'transaction_sold_count': 999, 'listing_active_count': 12, 'num_favorers': 500}
        else:
            body = item(int(route.path.rsplit('/', 1)[-1]))
        return FetchResult(200, json.dumps(body).encode(), 'application/json', {'x-limit-per-second': '2', 'x-limit-per-day': '5000', 'x-remaining-today': '4990'})

    def test_unlimited_results_collect_205_listings_and_all_seven_shops(self):
        settings = {**self.settings, 'limit': None, 'page_size': 100, 'max_pages': None,
                    'max_shops': None, 'max_requests_per_run': None}
        validate_config(settings)
        events = []
        self.store.progress_callback = lambda identity, progress: events.append(dict(progress))
        def full(url, timeout, headers):
            self.calls.append(url)
            route = urlparse(url); params = parse_qs(route.query)
            if route.path.endswith('/listings/active'):
                offset = int(params['offset'][0]); limit = int(params['limit'][0])
                body = {'count': 205, 'results': [item(i, 1000 + i % 7) for i in range(offset + 1, min(offset + limit, 205) + 1)]}
            else:
                body = {'shop_id': int(route.path.rsplit('/', 1)[-1]), 'shop_name': 'Synthetic'}
            return FetchResult(200, json.dumps(body).encode(), 'application/json', {'x-limit-per-second': '5', 'x-remaining-this-secon': '4', 'x-remaining-today': '4990'})
        run = self.store.collect(settings, fetcher=full)
        self.assertEqual(run['listing_count'], 205)
        self.assertEqual(len(run['shops']), 7)
        self.assertEqual(run['request_count'], 10)
        self.assertTrue(run['queries'][0]['collection_complete'])
        self.assertEqual(run['status'], 'success')
        self.assertEqual(len(list((self.store.runs / run['run_id']).glob('raw-request-*'))), 10)
        self.assertTrue({'request_sent', 'waiting', 'page_saved', 'finished'} <= {e['phase'] for e in events})
        self.assertEqual(events[-1]['listing_count'], 205)
        self.assertEqual(events[-1]['shops_fetched'], 7)

    def test_unlimited_search_stops_at_provider_offset_with_partial_status(self):
        def endless(url, timeout, headers):
            self.calls.append(url)
            offset = int(parse_qs(urlparse(url).query)['offset'][0])
            body = {'count': 20000, 'results': [item(i) for i in range(offset + 1, offset + 101)]}
            return FetchResult(200, json.dumps(body).encode(), 'application/json', {})
        with patch('etsy_app.collection.MAX_API_OFFSET', 200):
            run = self.store.collect({**self.settings, 'limit': None, 'page_size': 100, 'max_pages': None,
                                      'max_shops': 0, 'max_requests_per_run': None}, fetcher=endless)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(run['status'], 'partial')
        self.assertEqual(run['queries'][0]['pagination_stop'], 'etsy_offset_limit')
        self.assertFalse(run['queries'][0]['collection_complete'])

    def test_seven_shop_followups_are_planned_and_paced(self):
        times = []
        def seven_shops(url, timeout, headers):
            times.append(self.clock)
            if urlparse(url).path.endswith('/listings/active'):
                body = {'count': 7, 'results': [item(i, i + 1000) for i in range(100, 107)]}
            else:
                identity = int(urlparse(url).path.rsplit('/', 1)[-1])
                body = {'shop_id': identity, 'shop_name': 'Synthetic shop'}
            return FetchResult(200, json.dumps(body).encode(), 'application/json',
                               {'x-limit-per-second': '5', 'x-remaining-this-secon': '4', 'x-remaining-today': '4990'})
        run = self.store.collect({**self.settings, 'limit': 7, 'page_size': 7, 'max_shops': 7}, fetcher=seven_shops)
        self.assertEqual(len(times), 8)
        self.assertTrue(all(b - a >= 2 for a, b in zip(times, times[1:])))
        plan = next(p for p in run['request_plans'] if p['stage'] == 'shops')
        self.assertEqual(plan['pending_requests'], 7)
        self.assertEqual(plan['reported_second_slots'], 4)
        self.assertEqual(plan['within_daily_and_run_budgets'], 7)
        self.assertEqual(len(run['throttle_waits']), 7)

    def test_exhausted_second_waits_full_window_plus_buffer(self):
        times = []
        def exhausted(*args):
            times.append(self.clock)
            response = self.fetch(*args)
            return FetchResult(*response, {'x-limit-per-second': '5', 'x-remaining-this-second': '0', 'x-remaining-today': '4990'})
        run = self.store.collect({**self.settings, 'requests_per_second': 1}, fetcher=exhausted)
        self.assertTrue(all(b - a >= 1.25 for a, b in zip(times, times[1:])))
        self.assertEqual(run['status'], 'success')
        self.assertTrue(all(w['seconds'] >= 1.25 for w in run['throttle_waits']))

    def test_remaining_second_survives_restart_and_missing_headers(self):
        from etsy_app.collection import Client
        run = {'run_id': 'synthetic', 'request_count': 0}
        directory = Path(self.tmp.name) / 'synthetic'; directory.mkdir()
        client = Client(self.store, {**self.settings, 'requests_per_second': 1}, run, directory, self.fetch)
        client.observe(200, {'x-limit-per-second': '5', 'x-remaining-this-secon': '0'})
        started = self.clock
        restarted = Client(self.store, {**self.settings, 'requests_per_second': 1}, run, directory, self.fetch)
        restarted.reserve()
        self.assertGreaterEqual(self.clock - started, 1.25)
        self.assertEqual(restarted.state['remaining_second'], 4)

    def test_two_pages_and_separate_bounded_shop_counters(self):
        run = self.store.collect(self.settings, fetcher=self.fetch)
        self.assertEqual(run['status'], 'success'); self.assertEqual(run['request_count'], 4)
        self.assertEqual([p['effective_parameters']['offset'] for p in run['queries'][0]['pages']], [0, 3])
        self.assertEqual(run['queries'][0]['pagination_stop'], 'listing_limit')
        row = run['queries'][0]['listings'][0]
        self.assertEqual(row['listing_views'], 123); self.assertEqual(row['listing_favorites'], 42)
        self.assertNotEqual(row['original_created_at'], row['created_at']); self.assertIsNone(row['shop_sales'])
        self.assertEqual(run['shops'][0]['shop']['transaction_sold_count'], 999)
        self.assertEqual(run['shops'][0]['shop']['shop_favorites'], 500)
        self.assertTrue(run['dqa']['usable_for_shop_research'])
        self.assertTrue(all(p['sha256_matches'] for p in run['dqa']['raw_integrity']))
        self.assertEqual(len(self.store.history('listing', row['listing_id'])), 1)
        self.assertEqual(len(self.store.history('shop', run['shops'][0]['shop_id'])), 1)

    def test_daily_watchlist_and_tracking_only_skip_search(self):
        settings = {**self.settings, 'max_shops': 0, 'tracking': {'listing_ids': ['555'], 'shop_ids': ['20']}}
        tracked = self.store.track(settings, fetcher=self.fetch)
        self.assertEqual(len(self.calls), 2); self.assertEqual(tracked['queries'], [])
        self.assertEqual(tracked['tracked_listings'][0]['listing']['listing_id'], '555')
        self.calls.clear()
        daily = self.store.collect(settings, trigger='daily', fetcher=self.fetch)
        self.assertEqual(len(self.calls), 4); self.assertEqual(daily['tracked_listings'][0]['status'], 'success')
        self.assertEqual(daily['shops'][0]['shop']['shop_id'], '20')
        self.assertEqual(len(self.store.history('listing', '555')), 2)

    def test_daily_tracking_only_mode_does_not_search(self):
        settings = {**self.settings, 'daily_mode': 'tracking', 'max_shops': 0,
                    'tracking': {'listing_ids': ['555'], 'shop_ids': ['20']}}
        run = self.store.collect(settings, trigger='daily', fetcher=self.fetch)
        self.assertEqual(run['queries'], [])
        self.assertEqual(run['mode'], 'tracking')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(run['status'], 'success')

    def test_per_run_budget_preserves_partial_pages(self):
        run = self.store.collect({**self.settings, 'max_requests_per_run': 1}, fetcher=self.fetch)
        self.assertEqual(len(self.calls), 1); self.assertEqual(run['status'], 'partial')
        self.assertEqual(len(run['queries'][0]['listings']), 3)
        self.assertIn('per-run', run['stop_reason'])

    def test_exhausted_daily_quota_blocks_without_request(self):
        key_id = hashlib.sha256(b'fixture-key').hexdigest()[:16]
        atomic_json(Path(self.tmp.name) / 'rate-limit-state.json', {'key_id': key_id, 'remaining_today': 10, 'quota_observed_at': self.clock})
        from etsy_app.collection import RequestBlocked
        with patch('etsy_app.collection.time.sleep', side_effect=RequestBlocked('quota reserve waiting verified')):
            run = self.store.collect(self.settings, fetcher=self.fetch)
        self.assertEqual(self.calls, []); self.assertEqual(run['request_count'], 0)
        self.assertIn('quota reserve', run['stop_reason'])

    def test_missing_headers_consume_last_known_quota_conservatively(self):
        key_id = hashlib.sha256(b'fixture-key').hexdigest()[:16]
        atomic_json(Path(self.tmp.name) / 'rate-limit-state.json', {'key_id': key_id, 'remaining_today': 12, 'quota_observed_at': self.clock})
        def without_headers(*args):
            return tuple(self.fetch(*args))
        from etsy_app.collection import RequestBlocked
        def stop_daily_wait(seconds):
            if seconds >= 30:
                raise RequestBlocked('quota reserve waiting verified')
            self.advance(seconds)
        with patch('etsy_app.collection.time.sleep', side_effect=stop_daily_wait):
            run = self.store.collect(self.settings, fetcher=without_headers)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(run['request_count'], 2)
        self.assertIn('quota reserve', run['stop_reason'])
        state = json.loads((Path(self.tmp.name) / 'rate-limit-state.json').read_text())
        self.assertEqual(state['remaining_today'], 10)

    def test_429_stops_and_cooldown_survives_restart(self):
        calls = []
        def limited(*args):
            calls.append(args)
            return FetchResult(429, b'{"error":"limited"}', 'application/json', {'retry-after': '60'})
        first = self.store.collect(self.settings, fetcher=limited)
        self.assertEqual(len(calls), 1); self.assertEqual(first['status'], 'failed')
        second = Store(self.tmp.name).collect(self.settings, fetcher=limited)
        self.assertEqual(len(calls), 1); self.assertIn('cooldown', second['stop_reason'])
        self.assertTrue((self.store.runs / first['run_id'] / first['queries'][0]['raw_file']).exists())

    def test_spacing_respects_conservative_interval(self):
        started = self.clock
        self.store.collect(self.settings, fetcher=self.fetch)
        self.assertGreaterEqual(self.clock - started, 6)
        with patch('etsy_app.collection.time.sleep') as sleep:
            self.store.collect({**self.settings, 'limit': 1, 'max_shops': 0}, fetcher=self.fetch)
            self.assertGreaterEqual(sleep.call_args.args[0], 2)

    def test_local_daily_budget_is_enforced(self):
        self.store.collect({**self.settings, 'limit': 1, 'max_shops': 0}, fetcher=self.fetch)
        from etsy_app.collection import RequestBlocked
        with patch('etsy_app.collection.time.sleep', side_effect=RequestBlocked('local rolling daily request budget waiting verified')):
            run = self.store.collect({**self.settings, 'local_daily_request_budget': 1}, fetcher=self.fetch)
        self.assertEqual(len(self.calls), 1); self.assertIn('local rolling daily', run['stop_reason'])

    def test_overlap_between_pages_is_deduplicated_and_reported(self):
        def overlapping(url, *args):
            offset = int(parse_qs(urlparse(url).query).get('offset', ['0'])[0])
            rows = [item(100), item(101), item(102)] if offset == 0 else [item(102), item(103), item(104)]
            return (200, json.dumps({'count': 20, 'results': rows}).encode(), 'application/json')
        run = self.store.collect({**self.settings, 'max_shops': 0}, fetcher=overlapping)
        self.assertEqual(run['listing_count'], 5)
        self.assertEqual(run['dqa']['pagination_duplicates_removed'], ['102'])

    def test_offline_recovery_is_idempotent_and_preserves_originals(self):
        run = self.store.collect({**self.settings, 'limit': 1, 'max_shops': 0}, fetcher=self.fetch)
        directory = self.store.runs / run['run_id']; original_path = directory / 'snapshot.json'
        legacy = json.loads(original_path.read_text())
        for row in legacy['queries'][0]['listings']:
            for field in ('listing_views', 'tags', 'description', 'original_created_at'):
                row.pop(field, None)
        atomic_json(original_path, legacy)
        before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        count = len(self.calls)
        self.store.reprocess(); recovered = self.store.read(run['run_id'])
        self.assertEqual(recovered['queries'][0]['listings'][0]['listing_views'], 123)
        self.assertEqual(count, len(self.calls)); self.assertTrue(recovered['dqa']['usable_for_listing_research'])
        first = json.dumps(recovered, sort_keys=True)
        self.store.reprocess(); self.assertEqual(first, json.dumps(self.store.read(run['run_id']), sort_keys=True))
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()})

    def test_tampered_raw_is_not_used_for_recovery(self):
        run = self.store.collect({**self.settings, 'limit': 1, 'max_shops': 0}, fetcher=self.fetch)
        (self.store.runs / run['run_id'] / run['queries'][0]['raw_file']).write_bytes(b'{}')
        report = self.store.reprocess()
        self.assertEqual(report[0]['status'], 'failed')

    def test_config_rejects_unbounded_controls(self):
        for changes in [{'max_pages': 11}, {'max_shops': 21}, {'requests_per_second': 2}, {'max_requests_per_run': 0},
                        {'tracking': {'listing_ids': ['bad']}}, {'daily_mode': 'tracking', 'tracking': []}, {'search_parameters': {'sort_on': 'sales'}}]:
            with self.assertRaises(ValueError):
                validate_config({**self.settings, **changes})
