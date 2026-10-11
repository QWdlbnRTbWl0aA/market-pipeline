"""Reserve a trial's paid envelope in the shared file ledger, without credentials.

Only bookkeeping: this module has no model/API transport. Reservations/unknown
outcomes are durable safety state and must never be restored during rollback.
"""
import fcntl
import json
from pathlib import Path
from .storage import now, write


def reserve(root, key, policy, maximum_usd=.4284):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with (root/'budget.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);path=root/'budget.json'
        ledger=json.loads(path.read_text()) if path.exists() else {'calls':{}}
        existing=ledger.setdefault('experiments',{}).get(key)
        if existing:return existing
        entries=list(ledger['calls'].values());today=now()[:10]
        if ledger.get('blocked') or any(r['status']=='reserved_unknown' for r in entries):raise ValueError('Paid outcome/access needs reconciliation')
        reservations=[r for r in ledger['experiments'].values() if r['status']=='reserved']
        remaining_cost=sum(max(0,r['maximum_usd']-sum(c['charged_usd'] for c in entries if c.get('experiment_id')==r['experiment_id'])) for r in reservations)
        pending_calls=sum(max(0,4-sum(c.get('experiment_id')==r['experiment_id'] for c in entries)) for r in reservations if r['day']==today)
        day=[r for r in entries if r['at'][:10]==today]
        day_reserved=sum(max(0,r['maximum_usd']-sum(c['charged_usd'] for c in entries if c.get('experiment_id')==r['experiment_id'])) for r in reservations if r['day']==today)
        if (policy.get('daily_calls') is not None and len(day)+pending_calls+4>policy['daily_calls']) or (policy.get('daily_usd') is not None and sum(r['charged_usd'] for r in day)+day_reserved+maximum_usd>policy['daily_usd']+1e-9) or sum(r['charged_usd'] for r in entries)+remaining_cost+maximum_usd>policy['total_usd']+1e-9:
            raise ValueError('Paid envelope unavailable; no collector submission')
        record={'experiment_id':key,'day':today,'at':now(),'maximum_usd':maximum_usd,'maximum_calls':4,'status':'reserved'}
        ledger['experiments'][key]=record;write(path,ledger);return record


def close(root,key):
    root=Path(root)
    with (root/'budget.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);path=root/'budget.json';ledger=json.loads(path.read_text())
        rows=[r for r in ledger['calls'].values() if r.get('experiment_id')==key]
        if any(r['status']=='reserved_unknown' for r in rows):raise ValueError('Unknown paid outcome stays reserved')
        record=ledger.get('experiments',{}).get(key)
        if record:
            record.update(status='closed',closed_at=now(),charged_usd=sum(r['charged_usd'] for r in rows),actual_calls=len(rows));write(path,ledger)
