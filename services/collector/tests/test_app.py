"""All source bodies here are synthetic fixtures, never real Etsy data."""
import datetime as dt
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from etsy_app.core import Store, atomic_json, config, dqa, parse_api, parse_public, safe_url
from etsy_app.server import App, handler, request_host_allowed

HTML_FIXTURE = b'''<html><ul><li data-listing-id="123"><a href="/listing/123/planner?ref=test"><img alt="Printable Weekly Planner"><h3>Printable Weekly Planner</h3></a><span>Bestseller</span><span>Digital download</span></li><li data-listing-id="456"><a href="/listing/456/book"><h3>Physical notebook</h3></a></li></ul><script type="application/ld+json">{"@type":"Product","url":"https://www.etsy.com/listing/123/planner","name":"Printable Weekly Planner","offers":{"price":"4.50","priceCurrency":"USD"}}</script></html>'''
API_FIXTURE = json.dumps({'results': [{'listing_id': 123, 'title': 'Printable Weekly Planner', 'url': 'https://www.etsy.com/listing/123/planner', 'listing_type': 'download', 'price': {'amount': 450, 'divisor': 100, 'currency_code': 'USD'}, 'num_favorers': 9}, {'listing_id':456,'title':'Notebook','listing_type':'physical'}]}).encode()
SETTINGS = {'source': 'public', 'limit': 24, 'timeout_seconds': 5, 'daily_time': '09:00', 'timezone': 'Asia/Jerusalem', 'niches': [{'category': 'Planners', 'keywords': 'printable weekly planner', 'provisional': True}]}


def good_fetch(url, timeout, headers):
    return 200, HTML_FIXTURE, 'text/html'


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)

    def test_parse_card_badge_and_jsonld_without_inventing_metrics(self):
        rows = parse_public(HTML_FIXTURE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['title'], 'Printable Weekly Planner')
        self.assertEqual(rows[0]['price'], 4.5)
        self.assertTrue(rows[0]['bestseller'])
        self.assertTrue(rows[0]['digital'])
        self.assertIsNone(rows[1]['bestseller'])
        self.assertIsNone(rows[1]['digital'])
        self.assertIsNone(rows[0]['listing_sales'])
        self.assertIsNone(rows[0]['shop_sales'])

    def test_api_money_and_metric_scope(self):
        rows = parse_api(API_FIXTURE)
        self.assertEqual(rows[0]['price'], 4.5)
        self.assertEqual(rows[0]['listing_favorites'], 9)
        self.assertTrue(rows[0]['digital'])
        self.assertFalse(rows[1]['digital'])
        self.assertIsNone(rows[0]['bestseller'])
        self.assertIsNone(rows[1]['price'])

    def test_untrusted_listing_url_is_restricted(self):
        self.assertEqual(safe_url('javascript:alert(1)', 123), 'https://www.etsy.com/listing/123')
        self.assertEqual(safe_url('https://evil.example/listing/123', 123), 'https://www.etsy.com/listing/123')

    def test_repeat_execution_preserves_raw_and_snapshot(self):
        first = self.store.collect(SETTINGS, fetcher=good_fetch)
        path = self.store.runs / first['run_id'] / 'snapshot.json'
        before = path.read_bytes()
        second = self.store.collect(SETTINGS, fetcher=good_fetch)
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((path.parent / 'raw-0.html').read_bytes(), HTML_FIXTURE)
        self.assertEqual(len(self.store.list_runs()), 2)

    def test_access_challenge_stops_remaining_queries_and_preserves_body(self):
        calls = []
        def denied(*args):
            calls.append(args)
            return 403, b'captcha challenge', 'text/html'
        settings = {**SETTINGS, 'niches': SETTINGS['niches'] * 2}
        run = self.store.collect(settings, fetcher=denied)
        self.assertEqual(len(calls), 1)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['queries'][1]['status'], 'skipped')
        self.assertEqual((self.store.runs / run['run_id'] / 'raw-0.html').read_bytes(), b'captcha challenge')
        self.assertFalse(run['dqa']['usable_for_listing_research'])

    def test_http_200_captcha_is_not_empty_success(self):
        run = self.store.collect(SETTINGS, fetcher=lambda *a: (200, b'captcha-delivery.com', 'text/html'))
        self.assertEqual(run['status'], 'failed')
        self.assertIn('access challenge', run['queries'][0]['error'])

    def test_partial_run_and_empty_response_explicit(self):
        calls = iter([(200, HTML_FIXTURE, 'text/html'), (200, b'<html>nothing</html>', 'text/html')])
        run = self.store.collect({**SETTINGS, 'niches': SETTINGS['niches'] * 2}, fetcher=lambda *a: next(calls))
        self.assertEqual(run['status'], 'partial')
        self.assertEqual(run['dqa']['query_coverage']['successful'], 1)
        self.assertFalse(run['dqa']['usable_for_listing_research'])

    def test_timeout_is_saved_without_sensitive_exception(self):
        def timeout(*a):
            raise TimeoutError('secret should never appear')
        run = self.store.collect(SETTINGS, fetcher=timeout)
        self.assertEqual(run['status'], 'failed')
        self.assertNotIn('secret', json.dumps(run))

    def test_api_credentials_required_and_never_persisted(self):
        with patch.dict(os.environ, {}, clear=True):
            run = self.store.collect({**SETTINGS, 'source': 'api'}, fetcher=good_fetch)
            self.assertIn('ETSY_API_KEY', run['queries'][0]['error'])
        captured = []
        def api_fetch(url, timeout, headers):
            captured.append(headers)
            return 200, API_FIXTURE, 'application/json'
        with patch.dict(os.environ, {'ETSY_API_KEY': 'test-key', 'ETSY_API_SECRET': 'test-secret'}):
            run = self.store.collect({**SETTINGS, 'source': 'api'}, fetcher=api_fetch)
        self.assertEqual(captured[0]['x-api-key'], 'test-key:test-secret')
        self.assertNotIn('test-secret', json.dumps(run))
        self.assertEqual(run['status'], 'success')

    def test_dqa_relevance_completeness_and_raw_integrity(self):
        run = self.store.collect(SETTINGS, fetcher=good_fetch)
        report = run['dqa']
        self.assertEqual(report['digital_unknown'], 1)
        self.assertEqual(report['field_completeness']['listing_sales']['present'], 0)
        self.assertEqual(report['relevance_title_no_token_overlap'], ['456'])
        self.assertTrue(all(x['matches_saved_source'] for x in report['source_sample']))
        directory = self.store.runs / run['run_id']
        (directory / 'raw-0.html').write_bytes(b'<html></html>')
        report = dqa(run, directory)
        self.assertFalse(report['raw_integrity'][0]['sha256_matches'])
        self.assertFalse(report['usable_for_listing_research'])

    def test_suggestions_only_from_saved_titles(self):
        self.assertEqual(self.store.suggestions(), [])
        self.store.collect(SETTINGS, fetcher=good_fetch)
        self.assertIn('weekly planner', [r['keywords'] for r in self.store.suggestions('weekly', 'Planners')])
        self.assertEqual(self.store.suggestions(category='Unknown'), [])
        self.assertTrue(all(r['example_url'].startswith('https://www.etsy.com/listing/') for r in self.store.suggestions()))

    def test_parallel_collection_rejected(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            release.wait(3)
            return good_fetch(*args)
        worker = threading.Thread(target=lambda: self.store.collect(SETTINGS, fetcher=slow))
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            with self.assertRaisesRegex(RuntimeError, 'another collection'):
                self.store.collect(SETTINGS, fetcher=good_fetch)
        finally:
            release.set()
            worker.join()

    def test_atomic_write_retains_previous_valid_file_on_invalid_json(self):
        path = Path(self.tmp.name) / 'test.json'
        atomic_json(path, {'valid': True})
        with self.assertRaises(ValueError):
            atomic_json(path, {'bad': float('nan')})
        self.assertEqual(json.loads(path.read_text()), {'valid': True})

    def test_corrupt_run_is_visible_and_path_traversal_rejected(self):
        directory = self.store.runs / 'corrupt'
        directory.mkdir()
        (directory / 'snapshot.json').write_text('{broken')
        self.assertEqual(self.store.list_runs()[0]['status'], 'corrupt')
        with self.assertRaises(ValueError):
            self.store.read('../../config')

    def test_invalid_niche_does_not_start_a_run(self):
        with self.assertRaises(ValueError):
            self.store.collect(SETTINGS, [{'category': 'A', 'keywords': ''}])
        self.assertEqual(self.store.list_runs(), [])


class SchedulerTests(unittest.TestCase):
    def test_daily_scheduler_executes_collection_and_saves_run(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            app = App(SETTINGS, directory)
            original = app.store.collect
            with patch.object(app.store, 'collect', side_effect=lambda settings, niches, trigger: original(settings, niches, trigger, fetcher=good_fetch)):
                self.assertTrue(app.schedule_tick(dt.datetime(2026, 10, 6, 7, 0, tzinfo=dt.timezone.utc)))
                deadline = time.monotonic() + 3
                while app.job['status'] == 'running' and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(app.job['status'], 'success')
                run = app.store.read(app.job['run_id'])
                self.assertEqual(run['trigger'], 'daily')
                self.assertEqual(run['listing_count'], 2)

    def test_timezone_daily_once_and_restart_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            app = App(SETTINGS, directory)
            with patch.object(app, 'start') as start:
                self.assertFalse(app.schedule_tick(dt.datetime(2026, 10, 6, 5, 0, tzinfo=dt.timezone.utc)))
                self.assertTrue(app.schedule_tick(dt.datetime(2026, 10, 6, 7, 0, tzinfo=dt.timezone.utc)))
                self.assertFalse(app.schedule_tick(dt.datetime(2026, 10, 6, 8, 0, tzinfo=dt.timezone.utc)))
                start.assert_called_once_with(SETTINGS['niches'], 'daily')
            restarted = App(SETTINGS, directory)
            with patch.object(restarted, 'start') as start:
                self.assertFalse(restarted.schedule_tick(dt.datetime(2026, 10, 6, 8, 0, tzinfo=dt.timezone.utc)))
                self.assertTrue(restarted.schedule_tick(dt.datetime(2026, 10, 7, 7, 0, tzinfo=dt.timezone.utc)))
                start.assert_called_once()


class HostTests(unittest.TestCase):
    def test_lan_and_loopback_hosts_allowed_on_correct_interface(self):
        self.assertTrue(request_host_allowed('192.0.2.10:8090', '192.0.2.10', 8090))
        self.assertTrue(request_host_allowed('127.0.0.1:8090', '127.0.0.1', 8090))
        self.assertTrue(request_host_allowed('localhost:8090', '127.0.0.1', 8090))

    def test_foreign_hosts_wrong_ports_and_malformed_hosts_rejected(self):
        for host in ['evil.example:8090', '192.0.2.11:8090', '192.0.2.10:1234',
                     '192.0.2.10', 'user@192.0.2.10:8090', '192.0.2.10:8090/path',
                     '192.0.2.10:bad', 'localhost:8090']:
            self.assertFalse(request_host_allowed(host, '192.0.2.10', 8090), host)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(SETTINGS, self.tmp.name)
        self.run = self.app.store.collect(SETTINGS, fetcher=good_fetch)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.app))
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.base + path)

    def test_dashboard_static_config_and_history(self):
        with self.get('/') as response:
            self.assertIn(b'viewport', response.read())
            self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        with self.get('/api/runs') as response:
            self.assertEqual(json.load(response)[0]['run_id'], self.run['run_id'])
        with self.get('/api/config') as response:
            self.assertNotIn('ETSY_API_SECRET', json.dumps(json.load(response)))

    def test_raw_served_as_text_and_dqa_accessible(self):
        path = '/api/runs/' + self.run['run_id']
        with self.get(path + '/raw/0') as response:
            self.assertEqual(response.headers['Content-Type'], 'text/plain; charset=utf-8')
            self.assertEqual(response.read(), HTML_FIXTURE)
        with self.get(path + '/dqa') as response:
            self.assertEqual(json.load(response)['listing_count'], 2)

    def test_http_on_demand_executes_and_persists_collection(self):
        import time
        original = self.app.store.collect
        with patch.object(self.app.store, 'collect', side_effect=lambda settings, niches, trigger: original(settings, niches, trigger, fetcher=good_fetch)):
            request = urllib.request.Request(self.base + '/api/collect', data=json.dumps({'niches': SETTINGS['niches']}).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 202)
            deadline = time.monotonic() + 3
            while self.app.job['status'] == 'running' and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(self.app.job['status'], 'success')
            self.assertEqual(len(self.app.store.list_runs()), 2)
            with self.get('/api/job') as response:
                self.assertEqual(json.load(response)['run_id'], self.app.job['run_id'])

    def test_invalid_input_and_cross_origin_rejected(self):
        cases = [({'niches': []}, {}, 400), ({}, {'Origin': 'https://evil.example'}, 403)]
        for payload, headers, status in cases:
            request = urllib.request.Request(self.base + '/api/collect', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **headers})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, status)

    def test_foreign_host_cannot_read_dashboard(self):
        request = urllib.request.Request(self.base, headers={'Host': 'evil.example'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 403)

    def test_same_origin_collection_allowed_cross_site_rejected(self):
        with patch.object(self.app, 'start', return_value={'status': 'running'}) as start:
            request = urllib.request.Request(self.base + '/api/collect',
                       data=json.dumps({'niches': SETTINGS['niches']}).encode(),
                       headers={'Content-Type': 'application/json', 'Origin': self.base})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 202)
            start.assert_called_once()
            request.add_header('Sec-Fetch-Site', 'cross-site')
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
            self.assertEqual(start.call_count, 1)

    def test_on_demand_http_request_dispatches(self):
        with patch('etsy_app.server.App.start') as start:
            start.return_value = {'status': 'running', 'run_id': None}
            request = urllib.request.Request(self.base + '/api/collect', data=json.dumps({'niches': SETTINGS['niches']}).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 202)
            start.assert_called_once_with(SETTINGS['niches'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
