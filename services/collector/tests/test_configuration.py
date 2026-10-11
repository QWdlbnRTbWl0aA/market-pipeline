"""Configuration and request-counter tests; all Etsy responses are synthetic."""
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
from etsy_app.core import Store, FetchResult, atomic_json, config, validate_config
from etsy_app.server import App, handler
from test_app import SETTINGS, API_FIXTURE


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = App(SETTINGS, self.tmp.name)

    def test_deployment_deferral_preserves_next_daily_execution(self):
        self.app.schedule_skip_day = '2026-10-06'
        with patch.object(self.app, 'start') as start:
            self.assertFalse(self.app.schedule_tick(dt.datetime(2026, 10, 6, 7, 0, tzinfo=dt.timezone.utc)))
            self.assertTrue(self.app.schedule_tick(dt.datetime(2026, 10, 7, 7, 0, tzinfo=dt.timezone.utc)))
            start.assert_called_once()

    def test_save_persists_and_applies_without_collection(self):
        changed = {**SETTINGS, 'limit': 12, 'daily_time': '11:30',
                   'niches': [{'category': 'New category', 'keywords': 'digital invitation'}]}
        with patch.object(self.app, 'start') as start:
            self.app.save_configuration({'revision': self.app.configuration()['revision'], 'settings': changed})
            start.assert_not_called()
        self.assertEqual(config(self.app.config_path), changed)
        self.assertEqual(self.app.settings, changed)
        self.assertEqual(self.app.store.list_runs(), [])

    def test_invalid_configuration_preserves_file(self):
        original = self.app.config_path.read_bytes()
        for changed in [{**SETTINGS, 'limit': True}, {**SETTINGS, 'timeout_seconds': 0},
                        {**SETTINGS, 'niches': []}, {**SETTINGS, 'timezone': 'Not/AZone'},
                        {**SETTINGS, 'daily_time': '99:99'}, {**SETTINGS, 'ETSY_API_SECRET': 'never-save'}]:
            with self.assertRaises(ValueError):
                self.app.save_configuration({'revision': self.app.configuration()['revision'], 'settings': changed})
            self.assertEqual(self.app.config_path.read_bytes(), original)

    def test_stale_editor_does_not_overwrite_new_configuration(self):
        revision = self.app.configuration()['revision']
        self.app.save_configuration({'revision': revision, 'settings': {**SETTINGS, 'limit': 12}})
        with self.assertRaisesRegex(RuntimeError, 'configuration changed'):
            self.app.save_configuration({'revision': revision, 'settings': SETTINGS})
        self.assertEqual(config(self.app.config_path)['limit'], 12)

    def test_running_collection_blocks_config_save(self):
        self.app.job = {'status': 'running'}
        with self.assertRaisesRegex(RuntimeError, 'current collection'):
            self.app.save_configuration({'revision': self.app.configuration()['revision'], 'settings': SETTINGS})

    def test_external_file_edit_is_loaded_without_stale_overwrite(self):
        revision = self.app.configuration()['revision']
        atomic_json(self.app.config_path, {**SETTINGS, 'limit': 21})
        self.assertEqual(self.app.configuration()['limit'], 21)
        self.assertEqual(self.app.settings['limit'], 21)
        with self.assertRaises(RuntimeError):
            self.app.save_configuration({'revision': revision, 'settings': SETTINGS})

    def test_restart_uses_saved_configuration(self):
        self.app.save_configuration({'revision': self.app.configuration()['revision'], 'settings': {**SETTINGS, 'limit': 7}})
        restarted = App(config(self.app.config_path), self.tmp.name, self.app.config_path)
        self.assertEqual(restarted.configuration()['limit'], 7)


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)

    def test_rolling_boundaries_and_future_events(self):
        instant = dt.datetime(2026, 10, 8, 12, tzinfo=dt.timezone.utc)
        for index, age in enumerate([0, 299, 300, 86399, 86400, -1]):
            atomic_json(Path(self.tmp.name) / 'requests' / f'{index}.json',
                        {'request_id': str(index), 'source': 'api', 'started_at': (instant - dt.timedelta(seconds=age)).isoformat()})
        usage = self.store.request_usage(instant)
        self.assertEqual(usage['last_5_minutes'], 2)
        self.assertEqual(usage['last_24_hours'], 4)
        self.assertEqual(usage['last_second'], 1)

    def test_api_attempts_count_timeout_and_headers_without_secrets(self):
        settings = {**SETTINGS, 'source': 'api'}
        with patch.dict(os.environ, {'ETSY_API_KEY': 'fake-key', 'ETSY_API_SECRET': 'fake-secret'}):
            self.store.collect(settings, fetcher=lambda *a: FetchResult(200, API_FIXTURE, 'application/json',
                                  {'x-limit-per-day': '5000', 'x-remaining-today': '4999', 'x-api-key': 'fake-secret'}))
            def timeout(*args):
                raise TimeoutError('fake-secret')
            self.store.collect(settings, fetcher=timeout)
        usage = self.store.request_usage()
        self.assertEqual(usage['last_5_minutes'], 2)
        self.assertEqual(usage['last_known_rate_limits']['x-limit-per-day'], '5000')
        self.assertNotIn('fake-secret', json.dumps(usage))
        persisted = ''.join(p.read_text() for p in (Path(self.tmp.name) / 'requests').glob('*.json'))
        self.assertNotIn('fake-secret', persisted)

    def test_missing_credentials_and_public_source_do_not_count(self):
        with patch.dict(os.environ, {}, clear=True):
            self.store.collect({**SETTINGS, 'source': 'api'}, fetcher=lambda *a: self.fail('must not fetch'))
        self.store.collect(SETTINGS, fetcher=lambda *a: (403, b'blocked fixture', 'text/html'))
        self.assertEqual(self.store.request_usage()['last_24_hours'], 0)

    def test_recorded_legacy_requests_count_once_across_restarts(self):
        with patch.dict(os.environ, {'ETSY_API_KEY': 'fake', 'ETSY_API_SECRET': 'fake'}):
            run = self.store.collect({**SETTINGS, 'source': 'api'}, fetcher=lambda *a: (200, API_FIXTURE, 'application/json'))
        self.assertEqual(self.store.request_usage()['last_24_hours'], 1)
        # Simulate original snapshots that predate the request ledger.
        for q in run['queries']:
            q.pop('request_id')
        atomic_json(self.store.runs / run['run_id'] / 'snapshot.json', run)
        for path in (Path(self.tmp.name) / 'requests').glob('*.json'):
            path.unlink()
        self.assertEqual(Store(self.tmp.name).request_usage()['last_24_hours'], 1)
        self.assertEqual(Store(self.tmp.name).request_usage()['last_24_hours'], 1)


class SettingsHTTPTests(unittest.TestCase):
    def test_save_and_counters_endpoints_do_not_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            app = App(SETTINGS, directory)
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with patch('etsy_app.core.fetch', side_effect=AssertionError('no live requests allowed')), patch.object(app, 'start') as start:
                    payload = {'revision': app.configuration()['revision'], 'settings': {**SETTINGS, 'limit': 11}}
                    req = urllib.request.Request(base + '/api/config', data=json.dumps(payload).encode(),
                                                 headers={'Content-Type': 'application/json', 'Origin': base})
                    with urllib.request.urlopen(req) as response:
                        self.assertEqual(json.load(response)['limit'], 11)
                    with urllib.request.urlopen(base + '/api/usage') as response:
                        self.assertEqual(json.load(response)['last_24_hours'], 0)
                    start.assert_not_called()
                    req.add_header('Origin', 'https://evil.example')
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(req)
                    self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown(); server.server_close(); thread.join()
