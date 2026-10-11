#!/usr/bin/env python3
"""Offline migration into a new state root. Stop writers first; source is unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from prepare import prepare,ROOT


def copy(source,target):
    source=Path(source);target=Path(target)
    if not source.exists():return
    paths=[source,*source.rglob('*')] if source.is_dir() else [source]
    if any(p.is_symlink() for p in paths):raise ValueError('Migration refuses symlink artifacts')
    target.parent.mkdir(parents=True,exist_ok=True)
    if source.is_dir():shutil.copytree(source,target)
    else:shutil.copy2(source,target)


def migrate(state,configs,collector,collector_config,analyzer,ledger,product,controller=None):
    state=Path(state).resolve();configs=Path(configs).resolve()
    if state.exists() or configs.exists():raise ValueError('Use new destinations; existing data must never be overwritten')
    if state.is_relative_to(ROOT) or configs.is_relative_to(ROOT):raise ValueError('Runtime destinations must remain outside source')
    inputs=[Path(p).resolve() for p in (collector,collector_config,analyzer,ledger,product) if p]
    if controller:inputs.append(Path(controller).resolve())
    if any(state.is_relative_to(p) or configs.is_relative_to(p) for p in inputs):raise ValueError('Migration destination overlaps source artifacts')
    for root in inputs:
        if not root.exists():raise ValueError('Required migration input missing')
    ledger_path=Path(ledger)/'budget.json'
    if not ledger_path.is_file():raise ValueError('Existing paid budget ledger required; never reset development spend')
    budget=json.loads(ledger_path.read_text())
    if not isinstance(budget.get('calls'),dict):raise ValueError('Accountable paid ledger required')
    state.mkdir(parents=True,mode=0o700)
    for name in ('runs','requests','derived','dashboard-index','index.json','rate-limit-state.json','schedule.json'):
        copy(Path(collector)/name,state/'collector'/name)
    copy(analyzer,state/'analyzer');copy(ledger,state/'paid-ledger')
    for name in ('intake','studio-outbox','definition-outbox'):
        copy(Path(product)/name,state/'product'/name)
    if controller:copy(controller,state/'controller')
    prepare(state,configs)
    target=state/'collector'/'config.json'
    settings=json.loads(Path(collector_config).read_text())
    settings.update(local_daily_request_budget=None,quota_reserve_percent=5,quota_reserve=0)
    target.write_text(json.dumps(settings,indent=2)+'\n')
    sys.path.insert(0,str(ROOT/'services'/'analyzer'))
    from analyzer.lifecycle import migrate as identities
    migration=identities(state/'analyzer')
    copied=state/'paid-ledger'/'budget.json'
    if copied.read_bytes()!=ledger_path.read_bytes():raise ValueError('Paid ledger changed; stop writers and repeat into a new destination')
    result={'schema_version':1,'source_modified':False,'external_requests':0,
            'paid_ledger_sha256':hashlib.sha256(copied.read_bytes()).hexdigest(),
            'paid_entries':len(budget['calls']),
            'charged_or_reserved_usd':sum(row['charged_usd'] for row in budget['calls'].values()),
            'analysis_states_accounted':migration['states'],'completed_states':migration['completed'],
            'collector_quota_and_request_history_preserved':True,
            'paid_enabled':False,'deployment_started':False}
    (state/'migration.json').write_text(json.dumps(result,indent=2)+'\n')
    for path in [state,configs,*state.rglob('*'),*configs.rglob('*')]:
        path.chmod(0o700 if path.is_dir() else 0o600)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('state','configs','collector','collector-config','analyzer','ledger','product'):p.add_argument('--'+name,required=True)
    p.add_argument('--controller')
    args=p.parse_args();print(json.dumps(migrate(**vars(args)),indent=2))
