"""Delivery-only state machine tests: no model, source API or production state."""
import contextlib
import fcntl
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from analyzer.delivery import deliver, policy, recover, retry_saved, publish_failure_events, failure_event
from analyzer.io import write_json
from analyzer.lifecycle import Cursor


class Response(io.BytesIO):
    status = 200
    headers = {}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = 'a' * 64
        self.directory = self.root / 'market_insights' / self.job
        self.payload = {'service': 'market_insights', 'delivery_id': 'b' * 64, 'report': {'fixture': True}}
        self.state = {'job_id': self.job, 'service': 'market_insights', 'source_run_id': 'fixture',
                      'delivery_id': 'b' * 64, 'analysis_status': 'completed', 'delivery_status': 'pending'}
        write_json(self.directory / 'outbound.json', self.payload)
        write_json(self.directory / 'state.json', self.state)
        self.endpoint = 'http://127.0.0.1:9999/market-insights'
        self.config = {'output_root': str(self.root), 'delivery': {'max_attempts': 2, 'retry_base_seconds': 10,
                       'retry_max_seconds': 100}, 'endpoints': {'market_insights': self.endpoint}}
        self.calls = []

    def offline(self, *args, **kwargs):
        self.calls.append(1)
        raise ConnectionRefusedError('Fixture unavailable')

    def success(self, request, **kwargs):
        self.calls.append(request)
        return Response(b'{}')

    def send(self, transport=None, at=100):
        return deliver(self.directory, self.state, self.endpoint, transport or self.offline, self.config, at)

    def test_transient_retries_obey_backoff_and_cap_across_restart(self):
        self.send(); self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.send(at=109)['skipped'])
        self.state = json.loads((self.directory / 'state.json').read_text())
        self.send(at=110)
        self.assertEqual(self.state['delivery_status'], 'retries_exhausted')
        self.send(at=10000); self.assertEqual(len(self.calls), 2)
        events = list((self.root / 'delivery-failures').glob('*.json'))
        self.assertEqual(len(events), 1)
        event = json.loads(events[0].read_text())
        self.assertEqual(event['event_type'], 'analysis_delivery_failed')
        self.assertEqual(event['attempts_total'], 2)
        self.assertTrue(event['explicit_recovery_required'])
        self.assertNotIn('report', event)

    def test_http_classification_and_retry_after(self):
        for code, expected in ((400, 'permanent_failure'), (413, 'permanent_failure'),
                               (409, 'permanent_failure'), (429, 'pending'), (503, 'pending'), (408, 'pending')):
            with self.subTest(code=code):
                self.directory = self.root / 'market_insights' / str(code)
                write_json(self.directory / 'outbound.json', self.payload)
                self.state = {**self.state, 'delivery_status': 'pending', 'delivery_attempts_total': 0,
                              'delivery_attempts_in_generation': 0, 'delivery_next_attempt_at': 0}
                def error(*args, **kwargs):
                    raise urllib.error.HTTPError(self.endpoint, code, 'fixture', {'Retry-After': '120'}, io.BytesIO(b'{}'))
                self.send(error)
                self.assertEqual(self.state['delivery_status'], expected)
                if expected == 'pending':
                    self.assertEqual(self.state['delivery_next_attempt_at'], 220)

    def test_compact_wire_preserves_source_fields_and_id_and_is_frozen(self):
        original = (self.directory / 'outbound.json').read_bytes()
        self.send(self.success)
        self.assertEqual(json.loads(self.calls[0].data), self.payload)
        self.assertEqual(self.calls[0].get_header('Idempotency-key'), self.state['delivery_id'])
        self.assertEqual((self.directory / 'outbound-wire.json').read_bytes(), self.calls[0].data)
        self.assertEqual((self.directory / 'outbound.json').read_bytes(), original)
        self.send(self.success); self.assertEqual(len(self.calls), 1)

    def test_genuinely_oversize_payload_is_parked_before_network(self):
        self.config['delivery']['max_payload_bytes'] = 100
        self.send(self.success)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.state['delivery_status'], 'permanent_failure')
        self.assertEqual(self.state['delivery_last_http_status'], 413)

    def test_old_attempts_do_not_reset_on_upgrade(self):
        write_json(self.directory / 'delivery-0403.json', {'attempt': 403, 'delivered': False})
        self.send(self.success)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.state['delivery_attempts_total'], 403)
        self.assertEqual(self.state['delivery_status'], 'retries_exhausted')

    def test_explicit_recovery_keeps_artifacts_and_identity_and_reopens_cursor(self):
        self.send(); self.send(at=110)
        cursor = Cursor(self.root, 'market_insights'); cursor.finish('fixture', self.state)
        self.assertFalse(cursor.eligible('fixture', '2026-01-01T00:00:00Z'))
        originals = {p.name: p.read_bytes() for p in self.directory.glob('delivery-*.json')}
        outbound = (self.directory / 'outbound.json').read_bytes()
        result = recover(self.config, 'market_insights', self.job, 'Receiver repaired; retry saved payload', self.success, 120)
        self.assertEqual(result['delivery_status'], 'delivered')
        self.assertEqual(result['delivery_attempts_total'], 3)
        self.assertEqual(result['delivery_attempts_in_generation'], 1)
        self.assertEqual(result['analysis_status'], 'completed')
        self.assertEqual(result['delivery_id'], 'b' * 64)
        for name, body in originals.items(): self.assertEqual((self.directory / name).read_bytes(), body)
        self.assertEqual((self.directory / 'outbound.json').read_bytes(), outbound)
        self.assertTrue(recover(self.config, 'market_insights', self.job, 'Duplicate operator request', self.success)['duplicate_recovery'])
        self.assertEqual(len(self.calls), 3)

    def test_ambiguous_attempt_reservation_is_counted_after_crash(self):
        self.state.update(delivery_attempts_total=2, delivery_attempts_in_generation=2)
        self.send(self.success)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.state['delivery_status'], 'retries_exhausted')

    def test_cursor_parks_terminal_delivery_separately_from_analysis(self):
        cursor = Cursor(self.root, 'market_insights')
        for status in ('permanent_failure', 'retries_exhausted'):
            cursor.finish(status, {'analysis_status': 'completed', 'delivery_status': status})
            self.assertFalse(cursor.eligible(status, '2026-01-01T00:00:00Z'))

    def test_broker_is_optional_and_failed_publication_is_durable_and_bounded(self):
        self.send(); self.send(at=110)
        self.assertEqual(publish_failure_events(self.config, self.success, 120), [])
        self.config['delivery']['failure_events'] = {'enabled': True, 'endpoint': 'http://127.0.0.1:9998/events',
                                                     'max_attempts': 2, 'retry_seconds': 10}
        publish_failure_events(self.config, self.offline, 120)
        publish_failure_events(self.config, self.offline, 121)
        publish_failure_events(self.config, self.offline, 130)
        publish_failure_events(self.config, self.offline, 140)
        self.assertEqual(len(self.calls), 4)  # Two delivery + two optional relay attempts.
        receipt = next((self.root / 'delivery-failures').glob('*.publication.json'))
        self.assertEqual(json.loads(receipt.read_text())['status'], 'retries_exhausted')

    def test_successful_broker_publish_preserves_event_id_and_does_not_repeat(self):
        self.send(); self.send(at=110)
        self.config['delivery']['failure_events'] = {'enabled': True, 'endpoint': 'http://127.0.0.1:9998/events'}
        publish_failure_events(self.config, self.success, 120)
        request = self.calls[-1]; event = json.loads(request.data)
        self.assertEqual(request.get_header('Idempotency-key'), event['event_id'])
        before = len(self.calls); publish_failure_events(self.config, self.success, 200)
        self.assertEqual(len(self.calls), before)

    def test_invalid_policy_rejected_without_network(self):
        for invalid in ({'max_attempts': 0}, {'max_attempts': True}, {'max_payload_bytes': 6_000_000},
                        {'retry_base_seconds': float('nan')}, {'failure_events': {'enabled': True}},
                        {'failure_events': {'enabled': True, 'endpoint': 'http://example.com:80/events'}}):
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, TypeError)):
                policy(invalid)

    def test_delivery_options_do_not_change_completed_inference_identity(self):
        from analyzer.lifecycle import semantic
        base = {'job_id': self.job, 'delivery': self.config['delivery']}
        self.assertEqual(semantic(base), semantic({**base, 'delivery': {'max_attempts': 20}}))

    def test_recovery_transient_failure_reopens_watcher_cursor(self):
        self.send(); self.send(at=110)
        cursor = Cursor(self.root, 'market_insights'); cursor.finish('fixture', self.state)
        self.assertFalse(cursor.eligible('fixture', '2026-01-01T00:00:00Z'))
        outcome = recover(self.config, 'market_insights', self.job, 'Receiver being repaired', self.offline, 120)
        self.assertEqual(outcome['delivery_status'], 'pending')
        self.assertTrue(cursor.eligible('fixture', '2026-01-01T00:00:00Z'))
        self.assertEqual(outcome['delivery_attempts_total'], 3)

    def test_cli_recovery_never_constructs_model_or_reads_collection(self):
        from analyzer.services import main
        source = tempfile.TemporaryDirectory(); self.addCleanup(source.cleanup)
        config = {**self.config, 'saved_runs_root': source.name, 'model': 'synthetic',
                  'endpoints': {**self.config['endpoints'], 'search_refinement': 'http://127.0.0.1:9999/search-refinement'}}
        path = self.root / 'settings.json'; write_json(path, config)
        with patch('sys.argv', ['services', '--config', str(path), '--service', 'market_insights',
                               '--recover-delivery', self.job, '--reason', 'Reviewed receiver repair']), \
             patch('signal.signal'), patch('analyzer.services.run_cycle', side_effect=AssertionError('Inference forbidden')), \
             patch('analyzer.saved_intake.SavedCollectionIntake.read', side_effect=AssertionError('Source read forbidden')), \
             patch('analyzer.delivery.LocalHTTP', return_value=self.success), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(json.loads((self.directory / 'state.json').read_text())['analysis_status'], 'completed')

    def test_corrupt_wire_artifact_is_not_overwritten_or_sent(self):
        wire = self.directory / 'outbound-wire.json'; wire.write_bytes(b'corrupt fixture')
        self.send(self.success)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.state['delivery_status'], 'permanent_failure')
        self.assertEqual(wire.read_bytes(), b'corrupt fixture')

    def test_broker_rate_response_respects_retry_after(self):
        self.send(); self.send(at=110)
        self.config['delivery']['failure_events'] = {'enabled': True, 'endpoint': 'http://127.0.0.1:9998/events'}
        def limited(*args, **kwargs):
            self.calls.append(1)
            raise urllib.error.HTTPError(self.endpoint, 429, 'fixture', {'Retry-After': '120'}, io.BytesIO())
        publish_failure_events(self.config, limited, 120)
        publish_failure_events(self.config, limited, 239)
        self.assertEqual(len(self.calls), 3)
        receipt = next((self.root / 'delivery-failures').glob('*.publication.json'))
        self.assertEqual(json.loads(receipt.read_text())['next_attempt_at'], 240)

    def test_optional_publisher_does_not_wait_for_another_service_lock(self):
        self.send(); self.send(at=110)
        self.config['delivery']['failure_events'] = {'enabled': True, 'endpoint': 'http://127.0.0.1:9998/events'}
        with (self.root / 'delivery-failures/.publisher.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            before = len(self.calls)
            self.assertEqual(publish_failure_events(self.config, self.success, 120), [])
            self.assertEqual(len(self.calls), before)

    def test_optional_publisher_has_one_network_attempt_per_poll(self):
        self.send(); self.send(at=110)
        other = {**self.state, 'job_id': 'c' * 64}
        failure_event(self.root / 'market_insights' / ('c' * 64), other, self.config)
        self.config['delivery']['failure_events'] = {'enabled': True, 'endpoint': 'http://127.0.0.1:9998/events'}
        before = len(self.calls)
        self.assertEqual(len(publish_failure_events(self.config, self.success, 120)), 1)
        self.assertEqual(len(self.calls), before+1)
        self.assertEqual(len(publish_failure_events(self.config, self.success, 120)), 1)
        self.assertEqual(len(self.calls), before+2)

    def test_delivery_recovery_before_cursor_floor_can_finish_without_new_inference(self):
        self.send(); self.send(at=110)
        cursor = Cursor(self.root, 'market_insights', '2026-01-02T00:00:00Z')
        cursor.finish('fixture', self.state)
        recover(self.config, 'market_insights', self.job, 'Reviewed historic receiver repair', self.offline, 120)
        self.assertTrue(cursor.eligible('fixture', '2026-01-01T00:00:00Z'))
        self.assertEqual(cursor.pending_delivery('fixture'), self.job)
        changed = {**self.config, 'model': 'different', 'paid': {'enabled': True}}
        with patch('analyzer.services.run_cycle', side_effect=AssertionError('Inference forbidden')), \
             patch('analyzer.saved_intake.SavedCollectionIntake.read', side_effect=AssertionError('Source read forbidden')):
            outcome = retry_saved(changed, 'market_insights', cursor.pending_delivery('fixture'), self.success, 130)
        self.assertEqual(outcome['delivery_status'], 'delivered')
        self.assertEqual(outcome['job_id'], self.job)
        cursor.finish('fixture', outcome)
        self.assertFalse(cursor.eligible('fixture', '2026-01-01T00:00:00Z'))

    def test_watcher_retries_bound_saved_job_when_model_configuration_changes(self):
        from analyzer.services import main
        self.send()
        cursor = Cursor(self.root, 'market_insights'); cursor.finish('fixture', self.state)
        source = tempfile.TemporaryDirectory(); self.addCleanup(source.cleanup)
        config = {**self.config, 'saved_runs_root': source.name, 'model': 'changed-model',
                  'paid': {'enabled': True}, 'endpoints': {**self.config['endpoints'],
                  'search_refinement': 'http://127.0.0.1:9999/search-refinement'}}
        path = self.root / 'settings.json'; write_json(path, config)
        class Stop:
            stopped = False
            def is_set(self): return self.stopped
            def set(self): self.stopped = True
            def wait(self, seconds): self.stopped = True
        with patch('sys.argv', ['services', '--config', str(path), '--service', 'market_insights', '--watch']), \
             patch('signal.signal'), patch('threading.Event', return_value=Stop()), \
             patch('analyzer.services.discover', return_value=['fixture']), \
             patch('analyzer.services.finalization_time', return_value='2026-01-01T00:00:00Z'), \
             patch('analyzer.services.run_cycle', side_effect=AssertionError('Inference forbidden')), \
             patch('analyzer.saved_intake.SavedCollectionIntake.read', side_effect=AssertionError('Source read forbidden')), \
             patch('analyzer.delivery.LocalHTTP', return_value=self.success), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
        saved = json.loads((self.directory / 'state.json').read_text())
        self.assertEqual(saved['delivery_status'], 'delivered')
        self.assertEqual(saved['job_id'], self.job)
        self.assertEqual(saved['delivery_attempts_total'], 2)
