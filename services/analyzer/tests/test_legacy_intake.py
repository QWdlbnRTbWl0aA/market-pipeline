"""Synthetic fixtures matching the early collector snapshot structure; no API calls."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analyzer.io import write_json
from analyzer.lifecycle import resolve
from analyzer.normalize import normalize
from analyzer.ports import ModelResponse
from analyzer.research import build_evidence
from analyzer.saved_intake import SavedCollectionIntake
from analyzer.services import run_service


POLICY = {'min_group_listings': 2, 'max_candidates': 5, 'cheap_price_reference': 5}


def legacy_snapshot(sizes=(24, 24)):
    """Legacy fields only: no settings, tags, descriptions, shop IDs or images."""
    queries = []
    niches = [{'category': 'Planners', 'keywords': 'printable weekly planner', 'provisional': True},
              {'category': 'Templates', 'keywords': 'digital budget spreadsheet', 'provisional': True}]
    for index, size in enumerate(sizes):
        rows = []
        for position in range(size):
            rows.append({'listing_id': index * 100 + position + 1,
                         'title': 'Weekly planner sheet' if position else 'Engine repair guide',
                         'url': None, 'source': 'etsy', 'price': 4, 'currency': 'USD',
                         'digital': True, 'bestseller': None, 'bestseller_evidence': None,
                         'listing_favorites': None, 'listing_sales': None, 'shop_sales': None,
                         'listing_age_days': None, 'metric_scope': 'listing',
                         'observed_at': '2026-10-01T00:00:00Z', 'digital_evidence': []})
        queries.append({'niche': niches[index], 'listings': rows})
    return {'run_id': 'legacy-fixture', 'status': 'success',
            'finished_at': '2026-10-01T00:00:00Z', 'dqa': {'fixture': True}, 'queries': queries}


class LocalAbstention:
    def __init__(self):
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return ModelResponse(json.dumps({'items': []}), {'provider': 'synthetic'}, {'fixture': True})


class LegacyIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'

    def save(self, snapshot):
        directory = self.source / snapshot['run_id']
        write_json(directory / 'snapshot.json', snapshot)
        write_json(directory / 'dqa.json', snapshot['dqa'])
        return SavedCollectionIntake(self.source, snapshot['run_id'])

    def test_legacy_shapes_recover_query_intent_and_preserve_raw_provenance(self):
        for sizes in ((24, 24), (24, 24), (24,)):
            with self.subTest(sizes=sizes):
                snapshot = legacy_snapshot(sizes)
                intake = self.save(snapshot)
                before = {p.name: p.read_bytes() for p in intake.directory.iterdir()}
                batch = intake.read()
                self.assertEqual(batch.metadata['query_context']['niches'],
                                 [q['niche'] for q in snapshot['queries']])
                self.assertEqual(batch.provenance['query_context_sources']['niches'],
                                 [f'queries[{i}].niche' for i in range(len(sizes))])
                self.assertEqual(batch.provenance['input_sha256'],
                                 hashlib.sha256(before['snapshot.json']).hexdigest())
                dataset = normalize(batch)
                self.assertEqual(dataset['dqa']['accepted_records'], sum(sizes))
                self.assertEqual(dataset['dqa']['rejected_records'], [])
                evidence = build_evidence(dataset, POLICY)
                flag = next(f for f in evidence['flags'] if f['listing_id'] == 'etsy:listing:1')
                self.assertIn('no_query_terms_in_saved_content', flag['reasons'])
                self.assertTrue(evidence['candidates'])
                self.assertTrue(all('etsy:listing:1' not in c['listing_ids'] for c in evidence['candidates']))
                self.assertEqual({p.name: p.read_bytes() for p in intake.directory.iterdir()}, before)

    def test_null_settings_or_niches_use_saved_queries(self):
        for settings in (None, {}, {'niches': None, 'limit': 24}):
            with self.subTest(settings=settings):
                snapshot = legacy_snapshot((24,))
                snapshot['settings'] = settings
                batch = self.save(snapshot).read()
                self.assertEqual(batch.metadata['query_context']['niches'], [snapshot['queries'][0]['niche']])
                self.assertEqual(batch.metadata['query_context']['limit'], (settings or {}).get('limit'))

    def test_modern_settings_including_empty_niches_remain_authoritative(self):
        for niches in ([{'keywords': 'printable modern study planner', 'category': 'Modern'}], []):
            with self.subTest(niches=niches):
                snapshot = legacy_snapshot((24,))
                settings = {'niches': niches, 'limit': 7, 'shop_ids': ['123'],
                            'search_parameters': {'sort_on': 'score'}, 'page_size': 7, 'max_pages': 1,
                            'exclude_fetched_listings': True, 'exclude_fetched_shops': False}
                snapshot['settings'] = settings
                batch = self.save(snapshot).read()
                self.assertEqual(batch.metadata['query_context'], settings)
                self.assertNotIn('query_context_sources', batch.provenance)
                self.assertEqual(build_evidence(normalize(batch), POLICY)['query_context'], settings)

    def test_absent_query_niches_are_safe(self):
        snapshot = legacy_snapshot((24,))
        snapshot['queries'][0].pop('niche')
        batch = self.save(snapshot).read()
        self.assertEqual(batch.metadata['query_context']['niches'], [])
        self.assertEqual(build_evidence(normalize(batch), POLICY)['observed_listings'], 24)

    def test_nullable_canonical_context_is_safe(self):
        batch = self.save(legacy_snapshot((24,))).read()
        dataset = normalize(batch)
        for context in ({'niches': None}, {}, None):
            dataset['metadata']['query_context'] = context
            self.assertEqual(build_evidence(dataset, POLICY)['observed_listings'], 24)

    def test_malformed_settings_are_rejected_at_intake(self):
        for settings in ('not an object', [], False):
            with self.subTest(settings=settings):
                snapshot = legacy_snapshot((24,))
                snapshot['settings'] = settings
                with self.assertRaisesRegex(ValueError, 'Saved settings must be an object or null'):
                    self.save(snapshot).read()

    def config(self):
        return {'output_root': str(self.root / 'output'), 'model': 'synthetic', 'sample_size': 8,
                'research': POLICY, 'paid': {'enabled': False},
                'endpoints': {s: 'http://127.0.0.1:9999/' + s
                              for s in ('search_refinement', 'market_insights')}}

    def test_both_research_services_complete_once_without_network_or_paid_calls(self):
        deliveries = []

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, *args): return b'{}'

        def transport(request, **kwargs):
            deliveries.append(request)
            return Response()

        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')), \
                patch('analyzer.adapters.openai.OpenAIModel', side_effect=AssertionError('Paid model forbidden')):
            for index, sizes in enumerate(((24, 24), (24, 24), (24,))):
                snapshot = legacy_snapshot(sizes)
                snapshot['run_id'] += '-' + str(index)
                intake = self.save(snapshot)
                for service in ('search_refinement', 'market_insights'):
                    with self.subTest(index=index, service=service):
                        model = LocalAbstention()
                        first = run_service(service, intake, model, self.config(), transport=transport)
                        self.assertEqual(first['analysis_status'], 'completed')
                        self.assertEqual(first['delivery_status'], 'delivered')
                        second = run_service(service, intake, model, copy.deepcopy(self.config()), transport=transport)
                        self.assertTrue(second['duplicate_trigger'])
                        self.assertEqual(first['job_id'], second['job_id'])
                        self.assertEqual(model.calls, 1)
        self.assertEqual(len(deliveries), 6)

    def test_existing_completed_and_failed_jobs_keep_identity_and_do_not_rerun(self):
        intake = self.save(legacy_snapshot())
        batch = intake.read()
        # Seed identities from the deployed recipe, independent of the current constant.
        for service, status in (('search_refinement', 'completed'), ('market_insights', 'failed')):
            identity = {'service': service, 'input_sha256': batch.provenance['input_sha256'],
                        'source_run_id': batch.metadata['source_run_id'],
                        'recipe_version': 'research-v4.1-product-briefs', 'model': 'synthetic',
                        'sample_size': 8, 'research_policy': POLICY, 'paid_policy': {'enabled': False}}
            job_id, directory = resolve(self.config()['output_root'], identity)
            write_json(directory / 'state.json', {**identity, 'job_id': job_id,
                                                 'analysis_status': status, 'delivery_status': 'delivered'})
            before = (directory / 'state.json').read_bytes()
            model = LocalAbstention()
            result = run_service(service, intake, model, self.config(),
                                 transport=lambda *a, **kw: self.fail('Delivery repeated'))
            self.assertTrue(result['duplicate_trigger'])
            self.assertEqual(result['job_id'], job_id)
            self.assertEqual(result['analysis_status'], status)
            self.assertEqual(model.calls, 0)
            self.assertEqual((directory / 'state.json').read_bytes(), before)
