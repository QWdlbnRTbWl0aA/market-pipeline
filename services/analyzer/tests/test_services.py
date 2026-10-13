"""Functional/security tests use saved data and synthetic models, never Etsy/Ollama inference."""
import builtins
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
from analyzer.io import write_json
from analyzer.mock_receiver import server
from analyzer.ports import ModelResponse
from analyzer.saved_intake import SavedCollectionIntake, discover
from analyzer.security import LocalHTTP, assert_clean_environment
from analyzer.services import load_config, run_cycle, run_service
from analyzer.service_reports import SERVICES


class FakeModel:
    def __init__(self, broken=False):
        self.calls = 0
        self.broken = broken
    def generate(self, request):
        self.calls += 1
        if self.broken:
            raise RuntimeError('Synthetic generation failure')
        return ModelResponse(json.dumps({'summary': 'Synthetic functional test only.',
             'findings': [{'observation': 'Synthetic observation.', 'evidence_ids': ['e1']}],
             'recommendations': ['Synthetic recommendation, not applied.'], 'limitations': ['Fixture output; quality not assessed.']}),
             {'provider': 'synthetic'}, {'fixture': True})


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source';self.source.mkdir()
        self.snapshot = {'run_id': 'cycle-1', 'status': 'success', 'finished_at': '2026-10-10T00:00:00Z',
                         'settings': {'niches': [{'keywords': 'printable'}]}, 'dqa': {'fixture': True},
                         'queries': [{'listings': [{'listing_id': '1', 'title': 'Printable planner',
                                                  'description': 'A planning sheet.', 'tags': ['planner'], 'digital': True}]}]}
        self.save()
        self.receiver = server(self.root / 'receiver', 0)
        thread = threading.Thread(target=self.receiver.serve_forever, daemon=True);thread.start()
        self.addCleanup(self.receiver.server_close);self.addCleanup(self.receiver.shutdown)
        url = 'http://127.0.0.1:'+str(self.receiver.server_port)
        self.config = {'saved_runs_root': str(self.source), 'output_root': str(self.root/'output'), 'model': 'synthetic',
                       'delivery': {'retry_base_seconds': 0, 'retry_max_seconds': 0},
                       'sample_size': 1, 'endpoints': {'search_refinement': url+'/search-refinement', 'market_insights': url+'/market-insights'}}
        self.models = {name: FakeModel() for name in SERVICES}

    def save(self):
        folder = self.source / 'cycle-1';folder.mkdir(exist_ok=True)
        write_json(folder/'snapshot.json', self.snapshot);write_json(folder/'dqa.json', self.snapshot['dqa'])

    def test_two_services_http_delivery_repeat_and_restart_idempotency(self):
        original = (self.source/'cycle-1'/'snapshot.json').read_bytes()
        first = run_cycle(self.config, 'cycle-1', self.models)
        second = run_cycle(json.loads(json.dumps(self.config)), 'cycle-1', self.models)
        self.assertTrue(all(row['delivery_status'] == 'delivered' for row in first))
        self.assertTrue(all(row['duplicate_trigger'] for row in second))
        self.assertEqual([m.calls for m in self.models.values()], [1,1])
        self.assertEqual(len(list((self.root/'receiver').glob('*-ack.json'))), 2)
        self.assertEqual((self.source/'cycle-1'/'snapshot.json').read_bytes(), original)
        for row in first:
            payload = json.loads((Path(row['directory'])/'outbound.json').read_text())
            self.assertFalse(payload['recommendations_applied'])
            self.assertEqual(payload['service'], row['service'])
            self.assertEqual(payload['model_metadata']['provider'], 'synthetic')

    def test_failure_in_either_service_does_not_suppress_other(self):
        for broken in SERVICES:
            models = {name: FakeModel(name == broken) for name in SERVICES}
            config = {**self.config, 'output_root': str(self.root / ('failure-'+broken))}
            result = run_cycle(config, 'cycle-1', models)
            self.assertEqual([m.calls for m in models.values()], [1,1])
            self.assertEqual(next(r for r in result if r['service'] == broken)['analysis_status'], 'failed')
            self.assertEqual(next(r for r in result if r['service'] != broken)['analysis_status'], 'completed')
            run_cycle(config, 'cycle-1', models)
            self.assertEqual([m.calls for m in models.values()], [1,1])

    def test_undelivered_payload_retried_without_regeneration(self):
        class Offline:
            def __call__(self, *args, **kwargs):
                raise OSError('Synthetic receiver offline')
        first = run_cycle(self.config, 'cycle-1', self.models, transport=Offline())
        self.assertTrue(all(r['delivery_status'] == 'pending' for r in first))
        second = run_cycle(self.config, 'cycle-1', self.models)
        self.assertTrue(all(r['delivery_status'] == 'delivered' for r in second))
        self.assertEqual([m.calls for m in self.models.values()], [1,1])
        for row in second:
            self.assertEqual(len(list(Path(row['directory']).glob('delivery-*.json'))), 2)

    def test_only_finalized_success_with_matching_dqa_triggers(self):
        for status in ('running', 'partial', 'failed', 'cancelled'):
            self.snapshot['status'] = status;self.save()
            self.assertEqual(discover(self.source), [])
            results = run_cycle(self.config, 'cycle-1', self.models)
            self.assertTrue(all(r['status'] == 'failed_before_analysis' for r in results))
        self.snapshot['status'] = 'success';self.snapshot['finished_at'] = None;self.save()
        self.assertEqual(discover(self.source), [])
        self.snapshot['finished_at'] = '2026-10-10T00:00:00Z';self.save()
        write_json(self.source/'cycle-1'/'dqa.json', {'mismatch': True})
        self.assertEqual(discover(self.source), [])
        self.save();self.assertEqual(discover(self.source), ['cycle-1'])
        for malformed in ('invalid-date', '2026-10-10'):
            self.snapshot['finished_at']=malformed;self.save()
            self.assertEqual(discover(self.source),[])
        self.assertEqual([m.calls for m in self.models.values()], [0,0])

    def test_concurrent_triggers_cannot_duplicate_inference(self):
        started, release = threading.Event(), threading.Event()
        class Blocking(FakeModel):
            def generate(self, request):
                started.set();release.wait(3)
                return super().generate(request)
        model = Blocking();intake = SavedCollectionIntake(self.source, 'cycle-1')
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run_service, SERVICES[0], intake, model, self.config)
            self.assertTrue(started.wait(2))
            second = run_service(SERVICES[0], intake, model, self.config)
            self.assertEqual(second['status'], 'busy');release.set()
            self.assertEqual(first.result()['analysis_status'], 'completed')
        self.assertEqual(model.calls, 1)

    def test_neither_service_loads_credentials_or_calls_etsy(self):
        original_open = io.open
        def guarded_open(path, *args, **kwargs):
            if not isinstance(path, int):
                parts = Path(path).parts
                self.assertFalse(any(part.startswith('.env') for part in parts), 'credential file accessed')
            return original_open(path, *args, **kwargs)
        original_builtin = builtins.open
        def guarded_builtin(path, *args, **kwargs):
            if not isinstance(path, int):
                self.assertFalse(any(part.startswith('.env') for part in Path(path).parts))
            return original_builtin(path, *args, **kwargs)
        original_transport = LocalHTTP.__call__
        seen = []
        def spy(instance, request, **kwargs):
            url = request if isinstance(request, str) else request.full_url
            self.assertTrue(url.startswith('http://127.0.0.1:'))
            self.assertNotIn('etsy.com', url);seen.append(url)
            return original_transport(instance, request, **kwargs)
        with patch('io.open', side_effect=guarded_open), patch('builtins.open', side_effect=guarded_builtin), patch.object(LocalHTTP, '__call__', spy):
            results = run_cycle(self.config, 'cycle-1', self.models)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(r['analysis_status'] == 'completed' for r in results))
        with patch.dict(os.environ, {'ETSY_API_KEY': 'synthetic-do-not-load'}), self.assertRaises(ValueError):
            run_cycle(self.config, 'cycle-1', self.models)

    def test_config_and_artifact_credentials_are_rejected(self):
        path = self.root/'independent.json'
        write_json(path, {**self.config, 'api_key': 'fixture'})
        with self.assertRaises(ValueError):load_config(path)
        self.snapshot['settings']['api_secret'] = 'fixture';self.save()
        with self.assertRaises(ValueError):SavedCollectionIntake(self.source, 'cycle-1').read()
        with self.assertRaises(ValueError):load_config(self.root/'.env')

    def test_network_policy_rejects_api_remote_hosts_redirects_and_proxy(self):
        transport = LocalHTTP()
        for url in ('https://openapi.etsy.com/v3/application/listings/active', 'http://www.etsy.com:80/',
                    'http://192.0.2.10:8090/', 'http://127.0.0.1:8090/?api_key=x'):
            with self.assertRaises(ValueError):transport(url)
        self.assertEqual([type(h).__name__ for h in transport.opener.handlers].count('ProxyHandler'), 0)
        from analyzer.security import NoRedirect
        with self.assertRaises(ValueError):NoRedirect().redirect_request(None,None,302,'',{},'https://etsy.com')

    def test_saved_image_attachment_and_no_remote_fetch(self):
        folder = self.source/'cycle-1';(folder/'images').mkdir()
        (folder/'images'/'one.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        self.snapshot['queries'][0]['listings'][0]['images'] = [
            {'local_path': 'images/one.png'}, {'url': 'https://etsy.com/image'}, {'local_path': '../../.env'}]
        self.save()
        results = run_cycle(self.config, 'cycle-1', self.models)
        market = next(r for r in results if r['service'] == 'market_insights')
        request = json.loads((Path(market['directory'])/'request.json').read_text())
        context = json.loads((Path(market['directory'])/'context.json').read_text())
        self.assertEqual(len(request['images']), 1)
        self.assertEqual([i['status'] for i in context['image_audit']], ['attached','remote_reference_not_fetched','unsafe_local_path_rejected'])

    def test_explicit_failed_retry_preserves_history_and_changes_delivery_identity(self):
        self.models['search_refinement'] = FakeModel(True)
        first = run_cycle(self.config, 'cycle-1', self.models)
        self.models['search_refinement'] = FakeModel()
        second = run_cycle(self.config, 'cycle-1', self.models, retry_failed=True)
        self.assertEqual(self.models['search_refinement'].calls, 1)
        self.assertEqual(self.models['market_insights'].calls, 1)
        self.assertTrue(all(r['analysis_status']=='completed' and r['delivery_status']=='delivered' for r in second))
        old = next(r for r in first if r['service']=='search_refinement')
        new = next(r for r in second if r['service']=='search_refinement')
        self.assertNotEqual(old['delivery_id'], new['delivery_id'])
        self.assertTrue((Path(new['directory'])/'previous-attempt-0001'/'outbound.json').exists())

    def test_actual_ollama_adapters_never_load_credentials_or_etsy_api(self):
        config = {**self.config, 'ollama_url': 'http://127.0.0.1:11434'}
        original = LocalHTTP.__call__
        seen = []
        class FakeResponse:
            status = 200
            def __init__(self, value): self.value=value
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self, *args): return json.dumps(self.value).encode()
        def spy(instance, request, **kwargs):
            url = request.full_url if hasattr(request,'full_url') else request
            seen.append(url)
            self.assertTrue(url.startswith('http://127.0.0.1:'))
            if url.endswith('/api/tags'):
                return FakeResponse({'models':[{'name':'synthetic'}]})
            if url.endswith('/api/generate'):
                self.assertNotIn('api_key',json.loads(request.data))
                return FakeResponse({'done':True, 'model':'synthetic', 'response':FakeModel().generate(None).text})
            return original(instance,request,**kwargs)
        original_open=io.open
        def guarded(path,*args,**kwargs):
            if not isinstance(path,int):
                self.assertFalse(any(part.startswith('.env') for part in Path(path).parts))
            return original_open(path,*args,**kwargs)
        with patch.object(LocalHTTP,'__call__',spy), patch('io.open',side_effect=guarded):
            results=run_cycle(config,'cycle-1')
        self.assertTrue(all(r['analysis_status']=='completed' for r in results))
        self.assertEqual(sum(url.endswith('/api/generate') for url in seen),2)
        self.assertEqual(len(seen),6)

    def test_clean_launcher_removes_inherited_collector_environment(self):
        import subprocess
        environment={**os.environ,'ETSY_API_KEY':'synthetic-sentinel'}
        command=['bash',str(Path(__file__).resolve().parents[1]/'run-services.sh'),
                 '--config',str(self.root/'missing.json'),'--latest']
        result=subprocess.run(command,env=environment,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('FileNotFoundError',result.stderr)
        self.assertNotIn('Collector environment detected',result.stderr)
        self.assertNotIn('synthetic-sentinel',result.stderr)

    def test_services_can_run_independently(self):
        result=run_cycle(self.config,'cycle-1',self.models,service_names=('market_insights',))
        self.assertEqual(len(result),1)
        self.assertEqual(self.models['market_insights'].calls,1)
        self.assertEqual(self.models['search_refinement'].calls,0)

    def test_watcher_detects_finalization_and_skips_repeated_completed_work(self):
        from analyzer.services import main
        self.snapshot['status']='running';self.snapshot['finished_at']=None;self.save()
        config_path=self.root/'independent.json';write_json(config_path,self.config)
        sleeps=[]
        def sleep(timeout=None):
            if timeout is None:return True # Thread.start's internal Event.wait is unrelated to polling.
            sleeps.append(1)
            if len(sleeps)==1:
                self.snapshot['status']='success';self.snapshot['finished_at']='2026-10-10T00:00:01Z';self.save()
            elif len(sleeps)==3:
                raise KeyboardInterrupt()
        actual=run_cycle
        def injected(config,identity,**kwargs):
            return actual(config,identity,self.models,**kwargs)
        with patch('sys.argv',['services','--config',str(config_path),'--watch','--since','2026-10-10T00:00:00Z']), patch('analyzer.services.run_cycle',side_effect=injected), patch('threading.Event.wait',side_effect=sleep), patch('sys.stdout',new_callable=io.StringIO), self.assertRaises(KeyboardInterrupt):
            main()
        self.assertEqual([m.calls for m in self.models.values()],[1,1])

    def test_intake_paths_cannot_escape_saved_root(self):
        for identity in ('../outside', '/etc', '..'):
            with self.assertRaises(ValueError):SavedCollectionIntake(self.source, identity)
        (self.source/'escape').symlink_to(self.root)
        with self.assertRaises(ValueError):SavedCollectionIntake(self.source, 'escape')
        path = self.source/'cycle-1'/'snapshot.json';path.unlink();path.symlink_to(self.root/'secret.json')
        with self.assertRaises(ValueError):SavedCollectionIntake(self.source, 'cycle-1').read()


if __name__ == '__main__':
    unittest.main()

class EmptyCycleTests(unittest.TestCase):
 setUp=ServiceTests.setUp
 save=ServiceTests.save
 def test_valid_zero_new_results_completes_without_any_model_call(self):
  self.snapshot['queries'][0]['listings']=[];self.save()
  results=run_cycle(self.config,'cycle-1',self.models)
  self.assertTrue(all(r['analysis_status']=='completed' for r in results));self.assertEqual([m.calls for m in self.models.values()],[0,0])
  for r in results:self.assertEqual(json.loads((Path(r['directory'])/'outbound.json').read_text())['report']['status'],'insufficient_evidence')
