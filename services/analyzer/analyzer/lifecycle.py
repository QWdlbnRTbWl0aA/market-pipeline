"""Durable semantic identities, compatibility receipts and per-service intake cursors.

Operational budgets/endpoints are deliberately absent from inference identity.
These files are not rollback candidates: they prevent duplicate external work.
"""
import datetime as dt
import fcntl
import hashlib
import json
from pathlib import Path
from .io import now, write_json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def semantic(identity):
    paid = identity.get('paid_policy') or {}
    context = identity.get('semantic_context')
    if isinstance(context,dict) and not any(context.values()): context=None
    return {k: (context if k=='semantic_context' else identity.get(k)) for k in ('service', 'input_sha256', 'source_run_id', 'recipe_version',
            'model', 'model_digest', 'sample_size', 'research_policy', 'semantic_context')} | {
        'paid_stages': {k: paid.get(k) for k in ('enabled', 'cheap_model', 'final_model')}}


def migrate(root):
    """Account for every legacy state without touching artifacts or paid ledgers."""
    root = Path(root)
    directory = root / 'lifecycle'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.migration.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        aliases, accounted = {}, []
        for service in ('search_refinement', 'market_insights'):
            for path in sorted((root / service).glob('*/state.json')):
                if path.is_symlink():
                    raise ValueError('Symlink state refused during migration')
                state = json.loads(path.read_text())
                if state.get('service') != service or not state.get('input_sha256'):
                    raise ValueError('Unaccountable state: ' + str(path))
                key = digest(semantic(state))
                row = {'directory': str(path.parent.resolve()), 'job_id': state['job_id'],
                       'analysis_status': state['analysis_status'], 'state_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                aliases.setdefault(key, []).append(row)
                accounted.append(row)
        manifest = {'schema_version': 1, 'migrated_at': now(), 'aliases': aliases, 'accounted': accounted,
                    'states': len(accounted), 'completed': sum(r['analysis_status'] == 'completed' for r in accounted),
                    'external_ledgers_modified': False}
        write_json(directory / 'identity-map.json', manifest)
        return manifest


def resolve(root, identity):
    root = Path(root)
    key = digest(semantic(identity))
    manifest = root / 'lifecycle' / 'identity-map.json'
    # Migration is explicit before deployment. A new empty test root needs no map.
    if manifest.exists():
        choices = json.loads(manifest.read_text())['aliases'].get(key, [])
        if choices:
            choices.sort(key=lambda r: (r['analysis_status'] != 'completed', r['job_id']))
            choice = choices[0]
            path = Path(choice['directory'])
            if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
                raise ValueError('Compatibility receipt escapes output root')
            return choice['job_id'], path
    return key, root / identity['service'] / key


class Cursor:
    """An initial floor never advances on restart; pending work persists before calls."""
    def __init__(self, root, service, since=None):
        self.directory = Path(root) / 'lifecycle' / 'cursors' / service
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'cursor.json'
        if not self.path.exists():
            if since:
                instant = dt.datetime.fromisoformat(since.replace('Z', '+00:00'))
                if instant.tzinfo is None:
                    raise ValueError('Cursor floor must include timezone')
            write_json(self.path, {'schema_version': 1, 'initial_floor': since, 'created_at': now()})
        self.floor = json.loads(self.path.read_text())['initial_floor']

    def eligible(self, run_id, finalized_at):
        record = self.directory / (run_id + '.json')
        saved = json.loads(record.read_text()) if record.exists() else {}
        if saved.get('terminal'):
            return False
        if self.floor and dt.datetime.fromisoformat(finalized_at.replace('Z', '+00:00')) <= dt.datetime.fromisoformat(self.floor.replace('Z', '+00:00')) and not saved.get('delivery_only_recovery'):
            return False
        if not record.exists():
            write_json(record, {'source_run_id': run_id, 'finalized_at': finalized_at, 'status': 'pending', 'terminal': False})
        return True

    def pending_delivery(self, run_id):
        record = self.directory / (run_id + '.json')
        saved = json.loads(record.read_text()) if record.exists() else {}
        result = saved.get('result') or {}
        if not saved.get('terminal') and result.get('delivery_status') == 'pending' and result.get('analysis_status') in ('completed', 'failed', 'budget_waiting'):
            return result.get('job_id')
        return None

    def finish(self, run_id, result):
        terminal = result.get('analysis_status') in ('completed', 'failed', 'budget_waiting') and result.get('delivery_status') in ('delivered', 'permanent_failure', 'retries_exhausted')
        # Interrupted or intake failures are parked, never automatic inference retries.
        attention = result.get('status') in ('interrupted_requires_explicit_retry', 'failed_before_analysis')
        write_json(self.directory / (run_id + '.json'), {'source_run_id': run_id, 'updated_at': now(),
                   'status': 'requires_attention' if attention else result.get('analysis_status', result.get('status')),
                   'delivery_only_recovery': result.get('delivery_generation', 0) > 0,
                   'terminal': terminal or attention, 'result': result})


def heartbeat(root, service, **value):
    write_json(Path(root) / 'lifecycle' / ('heartbeat-' + service + '.json'), {'service': service, 'at': now(), **value})


def event(root, job_id, kind, value):
    key = digest({'job': job_id, 'kind': kind, 'value': value})
    path = Path(root) / 'lifecycle' / 'events' / (key + '.json')
    if not path.exists():
        write_json(path, {'schema_version': 1, 'event_id': key, 'event_type': kind, 'recorded_at': now(),
                          'job_id': job_id, **value})


def envelope(payload, metadata):
    lineage = metadata.get('lineage') or {}
    return {'schema_version': 1, 'event_type': 'analysis_completed', 'root_cycle_id': lineage.get('root_cycle_id') or payload['source_run_id'],
            'parent_run_id': lineage.get('parent_run_id'), 'experiment_id': lineage.get('experiment_id'),
            'iteration': lineage.get('iteration', 0), 'artifact_kind': metadata.get('artifact_kind', 'discovery'),
            'input_sha256': payload['source']['input_sha256'], 'recipe': payload['recipe_version'],
            'analysis_job_id': payload['job_id']}


if __name__ == '__main__':
    import argparse
    from .services import load_config
    parser = argparse.ArgumentParser(description='Migrate legacy analysis receipts before starting workers')
    parser.add_argument('--config', default='services-config.json')
    args, _ = parser.parse_known_args()
    cfg = load_config(args.config)
    result = migrate(cfg['output_root'])
    print(json.dumps({'migration_states': result['states'], 'completed': result['completed'], 'external_calls': 0}))
