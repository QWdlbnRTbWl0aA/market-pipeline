"""Durable, independent report services and file-based post-finalization trigger."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import time
import urllib.request
from .adapters.ollama import VerifiedOllamaModel
from .io import now, write_json
from .normalize import normalize
from .saved_intake import SavedCollectionIntake, discover, finalization_time
from .security import LocalHTTP, assert_clean_environment, local_url, reject_secrets
from .service_reports import SERVICES, RECIPE_VERSION, request_for, validate
from .research import VERSION as RESEARCH_VERSION
from .lifecycle import resolve, Cursor, heartbeat, event, envelope


def load_config(path):
    assert_clean_environment()
    config_path = Path(path).resolve()
    if 'etsy_pipeline' in config_path.parts:
        raise ValueError('Configuration must be independent of collector files')
    if config_path.suffix != '.json' or any(part.startswith('.env') for part in config_path.parts):
        raise ValueError('Only independent JSON configuration files allowed; env files forbidden')
    config = json.loads(config_path.read_text())
    reject_secrets(config)
    allowed = {'saved_runs_root', 'output_root', 'model', 'model_digest', 'ollama_url', 'sample_size', 'poll_seconds', 'endpoints', 'research', 'paid', 'email_config', 'operations_root', 'cohort_root'}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError('Independent analyzer configuration has unknown fields')
    if set(config.get('endpoints', {})) != set(SERVICES):
        raise ValueError('Both independent HTTP endpoints required')
    config.setdefault('sample_size', 8)
    config.setdefault('poll_seconds', 30)
    config.setdefault('model', 'gemma3:4b')
    config.setdefault('ollama_url', 'http://127.0.0.1:11434')
    if type(config['sample_size']) is not int or not 1 <= config['sample_size'] <= 20:
        raise ValueError('sample_size must be 1–20')
    if type(config['poll_seconds']) not in (int, float) or not 1 <= config['poll_seconds'] <= 60:
        raise ValueError('poll_seconds must be 1–60')
    if 'research' in config:
        from .production_config import validate_policy
        validate_policy(config)
    local_url(config['ollama_url'])
    for endpoint in config['endpoints'].values():
        local_url(endpoint)
    root, output = Path(config['saved_runs_root']).resolve(), Path(config['output_root']).resolve()
    if root == output or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError('Analyzer output must be separate from source artifacts')
    config['saved_runs_root'], config['output_root'] = str(root), str(output)
    return config


def deliver(directory, state, endpoint, transport):
    payload = (directory / 'outbound.json').read_bytes()
    request = urllib.request.Request(local_url(endpoint), data=payload,
                                    headers={'Content-Type': 'application/json', 'Idempotency-Key': state['delivery_id']})
    prior = sorted(directory.glob('delivery-*.json'))
    result = {'attempt': len(prior)+1, 'at': now(), 'endpoint': endpoint, 'idempotency_key': state['delivery_id'],
              'payload_sha256': hashlib.sha256(payload).hexdigest(), 'delivered': False}
    try:
        with transport(request, timeout=10) as response:
            result['http_status'] = response.status
            body = response.read(4097)
            result['response_excerpt'] = body[:4096].decode('utf-8', errors='replace')
            result['response_truncated'] = len(body) > 4096
            result['delivered'] = 200 <= response.status < 300
    except Exception as error:
        result['error'] = {'type': type(error).__name__, 'message': str(error)}
    write_json(directory / f"delivery-{result['attempt']:04d}.json", result)
    state['delivery_status'] = 'delivered' if result['delivered'] else 'pending'
    state['updated_at'] = now()
    write_json(directory / 'state.json', state)
    return result


def run_service(service, intake, model, config, retry_failed=False, transport=None):
    assert_clean_environment()
    transport = transport or LocalHTTP()
    batch = intake.read()
    identity = {'service': service, 'input_sha256': batch.provenance['input_sha256'],
                'source_run_id': batch.metadata['source_run_id'], 'recipe_version': RESEARCH_VERSION if 'research' in config else RECIPE_VERSION,
                'model': config['model'], 'model_digest': config.get('model_digest'), 'sample_size': config['sample_size'],
                'research_policy': config.get('research'), 'paid_policy': config.get('paid'),
                'semantic_context': batch.metadata.get('semantic_context'),
                'history_sha256': hashlib.sha256(json.dumps(batch.metadata.get('history'),sort_keys=True).encode()).hexdigest()}
    job_id, directory = resolve(config['output_root'], identity)
    directory.mkdir(parents=True, exist_ok=True)
    # Cross-process guard prevents duplicate generation from concurrent triggers.
    with (directory / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'service': service, 'status': 'busy', 'job_id': job_id}
        state_path = directory / 'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if state.get('analysis_status') == 'completed' or state.get('analysis_status') in ('failed', 'budget_waiting') and not retry_failed:
            if state.get('delivery_status') != 'delivered':
                deliver(directory, state, config['endpoints'][service], transport)
            return {**state, 'duplicate_trigger': True, 'directory': str(directory)}
        # A running record from an interrupted process is never silently rerun.
        if state.get('analysis_status') == 'running' and not retry_failed:
            return {**state, 'status': 'interrupted_requires_explicit_retry', 'directory': str(directory)}
        if state:
            attempt = len(list(directory.glob('previous-state-*.json'))) + 1
            write_json(directory / f'previous-state-{attempt:04d}.json', state)
            # Preserve artifacts from failed explicit retries rather than overwrite.
            archive = directory / f'previous-attempt-{attempt:04d}'
            archive.mkdir()
            for path in directory.glob('*.json'):
                if path.name != 'state.json' and not path.name.startswith('previous-state-'):
                    path.rename(archive / path.name)
        state = {'job_id': job_id, **identity, **{k: batch.metadata.get('lineage',{}).get(k) for k in ('root_cycle_id','parent_run_id','experiment_id','iteration')}, 'analysis_status': 'running', 'delivery_status': 'pending', 'started_at': now()}
        write_json(state_path, state)
        payload = {'schema_version': 1, 'job_id': job_id, 'service': service, 'source': batch.provenance,
                   'source_run_id': batch.metadata['source_run_id'], 'recommendations_applied': False, 'recipe_version': identity['recipe_version']}
        try:
            dataset = normalize(batch)
            write_json(directory / 'normalized.json', dataset)
            if dataset['metadata'].get('history'):
                write_json(directory / 'history-v2.json', dataset['metadata']['history'])
            if not dataset['records']:
                if dataset['dqa']['rejected_records']:raise ValueError('Saved records all failed mechanical normalization; model not called')
                payload.update(status='completed',report={'status':'insufficient_evidence','recommendations':[], 'summary':'No usable retained listings or approved saved cohort observations; no model call.', 'source_query_coverage':batch.metadata.get('query_coverage'), 'source_dqa':batch.metadata.get('source_dqa')},normalization_dqa=dataset['dqa'])
            elif 'research' in config:
                from .research import analyze
                from .adapters.openai import OpenAIModel
                paid=config['paid']
                cheap=OpenAIModel(paid['cheap_model'],paid,experiment_id=batch.metadata.get('lineage',{}).get('experiment_id')) if paid['enabled'] else None
                good=OpenAIModel(paid['final_model'],paid,experiment_id=batch.metadata.get('lineage',{}).get('experiment_id')) if paid['enabled'] else None
                report=analyze(service,dataset,directory,config,model,cheap,good)
                write_json(directory/'validation.json',{'passed':True,'scope':'Deterministic facts and per-candidate citation membership; semantic review required'})
                payload.update(status='completed',report=report,normalization_dqa=dataset['dqa'],semantic_review_required=True)
            else:
                request, context = request_for(service, dataset, config['sample_size'])
                write_json(directory / 'request.json', {'system': request.system, 'prompt': request.prompt, 'schema': request.schema,
                                                        'images': list(request.images), 'recipe_version': RECIPE_VERSION})
                write_json(directory / 'context.json', context)
                response = model.generate(request)
                write_json(directory / 'response.json', {'text': response.text, 'metadata': response.metadata, 'raw': response.raw})
                report = validate(response.text, context['evidence_catalog'])
                write_json(directory / 'validation.json', {'passed': True, 'scope': 'JSON shape and supplied evidence references only; no semantic/quality assessment'})
                payload.update(status='completed', report=report, context=context, normalization_dqa=dataset['dqa'],
                               model_metadata=response.metadata, semantic_review_required=True)
            state['analysis_status'] = 'completed'
        except Exception as error:
            payload.update(status='failed', error={'type': type(error).__name__, 'message': str(error)})
            write_json(directory / 'validation.json', {'passed': False, 'scope': 'Flow/mechanical failure', 'error': payload['error']})
            from .budget import BudgetExceeded
            state['analysis_status'] = 'budget_waiting' if isinstance(error, BudgetExceeded) else 'failed'
            if isinstance(error, BudgetExceeded): payload['status'] = 'budget_waiting'
        payload['envelope'] = envelope(payload, batch.metadata)
        payload['finished_at'] = now()
        payload['delivery_id'] = hashlib.sha256((job_id+json.dumps(payload, sort_keys=True)).encode()).hexdigest()
        state['delivery_id'] = payload['delivery_id']
        write_json(directory / 'outbound.json', payload)
        # Commit analysis completion before HTTP so delivery retries never rerun LLM.
        state['finished_at'] = payload['finished_at']
        write_json(state_path, state)
        event(config['output_root'], job_id, 'analysis_completed', {'service': service, 'source_run_id': batch.metadata['source_run_id'], 'status': state['analysis_status'], 'delivery_id': state['delivery_id']})
        deliver(directory, state, config['endpoints'][service], transport)
        return {**state, 'directory': str(directory)}


def run_cycle(config, run_id, models=None, retry_failed=False, transport=None, service_names=SERVICES):
    assert_clean_environment()
    results = []
    for service in service_names:
        if service not in SERVICES:
            raise ValueError('Unknown analysis service')
        try:
            if models:
                model = models[service]
            else:
                transport_model = LocalHTTP()
                model=VerifiedOllamaModel(config['model'],config['ollama_url'],timeout=180,transport=transport_model,digest=config.get('model_digest'))
                if 'research' in config:
                    from .adapters.cached import CachedLocalModel
                    model=CachedLocalModel(model,Path(config['paid']['ledger_root']).parent/'local-cache',{'model':config['model'],'digest':config.get('model_digest')})
            from .history import HistoryIntake
            intake=HistoryIntake(config['saved_runs_root'],run_id,cohort_root=config.get('cohort_root') if service=='market_insights' else None,as_of=config.get('refresh_as_of')) if 'research' in config else SavedCollectionIntake(config['saved_runs_root'],run_id)
            results.append(run_service(service, intake, model,
                                       config, retry_failed, transport))
        except Exception as error:
            # A service/intake/configuration exception cannot suppress the other service.
            result = {'service': service, 'source_run_id': run_id, 'status': 'failed_before_analysis',
                      'error': {'type': type(error).__name__, 'message': str(error)}}
            results.append(result)
    for result in results:
        if result.get('service')=='market_insights' and result.get('analysis_status')=='completed' and config.get('email_config'):
            directory=Path(result['directory'])
            try:
                from .email_delivery import prepare,configuration
                outbox=prepare(directory/'outbound.json',configuration(config['email_config']))
                write_json(directory/'email-preparation.json',{'status':'awaiting_exact_message_review','outbox_directory':str(outbox),'automatic_send':False})
            except Exception as error:
                write_json(directory/'email-preparation.json',{'status':'failed','error_type':type(error).__name__,'analysis_unaffected':True})
    return results


def main():
    import signal
    import threading
    stopping=threading.Event()
    signal.signal(signal.SIGTERM,lambda *unused:stopping.set())
    signal.signal(signal.SIGINT,lambda *unused:stopping.set())
    parser = argparse.ArgumentParser(description='Independent saved-artifact analysis services')
    parser.add_argument('--config', default='services-config.json')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--run', help='Finalized successful saved collection ID')
    group.add_argument('--latest', action='store_true')
    group.add_argument('--watch', action='store_true', help='Poll finalized successes; durable state skips completed/failed work')
    parser.add_argument('--service', choices=['both', *SERVICES], default='both', help='Run a service independently or both')
    parser.add_argument('--since', help='Watch only collections finalized after this ISO UTC timestamp (no historic backlog)')
    parser.add_argument('--retry-failed', action='store_true', help='Explicitly retry failed/interrupted analysis; never completed work')
    parser.add_argument('--dry-run',action='store_true',help='Force no paid API; local Ollama only in separate output directory')
    parser.add_argument('--refresh-as-of',help='Explicit dated market report refresh from saved artifacts; never watcher driven')
    args = parser.parse_args()
    if args.refresh_as_of and (not args.run or args.service != 'market_insights'):parser.error('Refresh requires one --run and --service market_insights')
    config = load_config(args.config)
    if args.refresh_as_of:config['refresh_as_of']=args.refresh_as_of
    if args.dry_run and 'paid' in config:
        config['paid']={**config['paid'],'enabled':False}
        config['output_root']=str(Path(config['output_root'])/'dry-runs')
    if args.watch and args.retry_failed:
        parser.error('Automatic inference retries forbidden; retry explicitly with --run')
    selected = SERVICES if args.service == 'both' else (args.service,)
    cursors = {s: Cursor(config['output_root'], s, args.since) for s in selected} if args.watch else {}
    while True:
        if stopping.is_set():return 0
        identities = discover(config['saved_runs_root']) if args.latest or args.watch else [args.run]
        if args.latest:
            identities = identities[-1:]
        results = []
        for identity in identities:
            for service in selected:
                if stopping.is_set():return 0
                if args.watch and config.get('operations_root'):
                    pause = Path(config['operations_root']) / (service + '-paused.json')
                    if pause.exists() and json.loads(pause.read_text()).get('paused'):
                        heartbeat(config['output_root'], service, status='paused'); continue
                if args.watch and not cursors[service].eligible(identity, finalization_time(config['saved_runs_root'], identity)):
                    continue
                if args.watch:
                    heartbeat(config['output_root'], service, status='analyzing', source_run_id=identity)
                current = run_cycle(config, identity, retry_failed=args.retry_failed, service_names=(service,))
                results.extend(current)
                print(json.dumps({'source_run_id': identity, 'services': current}), flush=True)
                if args.watch:
                    cursors[service].finish(identity, current[0])
                    heartbeat(config['output_root'], service, status='idle', last_result=current[0])
        if args.watch:
            for service in selected:
                heartbeat(config['output_root'], service, status='idle')
        if not args.watch:
            return 0 if identities and all(r.get('analysis_status') == 'completed' and r.get('delivery_status') == 'delivered' for r in results) else 1
        stopping.wait(config['poll_seconds'])


if __name__ == '__main__':
    raise SystemExit(main())
