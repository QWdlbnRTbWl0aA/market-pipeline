"""Explicit stage recovery; reconciliation is saved-output delivery only.

Never release an unknown paid reservation or repeat completed inference. A retry
still passes shared paid admission, response caches and job locks.
"""
import argparse
import hashlib
import json
from pathlib import Path
from .io import write_json
from .security import assert_clean_environment, LocalHTTP
from .services import load_config, run_cycle, deliver


def operate(config, service, job_id, action):
    assert_clean_environment()
    if service not in ('search_refinement','market_insights') or action not in ('retry','reconcile') or len(job_id)!=64 or any(c not in '0123456789abcdef' for c in job_id):raise ValueError('Exact scoped saved analysis operation required')
    root=Path(config['output_root']).resolve();directory=root/service/job_id
    if directory.is_symlink():raise ValueError('Saved job symlink forbidden')
    state=json.loads((directory/'state.json').read_text())
    if state['job_id']!=job_id or state['service']!=service:raise ValueError('Saved job identity collision')
    import fcntl
    with (directory/'.operation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if action=='retry':
            # Unknown reservations block paid admission globally. Existing request
            # hashes cannot be re-reserved even on explicit retries.
            result=run_cycle(config,state['source_run_id'],retry_failed=True,service_names=(service,))[0]
        else:
            if state.get('analysis_status')=='running' or not (directory/'outbound.json').exists():raise ValueError('No finalized saved output; external outcome needs manual evidence')
            payload=json.loads((directory/'outbound.json').read_text())
            if payload.get('delivery_id')!=state.get('delivery_id'):raise ValueError('Incomplete saved delivery commit')
            if state.get('delivery_status')!='delivered':deliver(directory,state,config['endpoints'][service],LocalHTTP())
            result={**state,'reconciled':'saved_delivery_only','new_inference':False,'unknown_reservations_released':False}
        write_json(directory/'operator-result.json',result);return result


def main():
    parser=argparse.ArgumentParser(description='Explicit independent stage recovery')
    parser.add_argument('--config',required=True);parser.add_argument('--service',required=True);parser.add_argument('--job',required=True);parser.add_argument('--action',choices=('retry','reconcile'),required=True)
    args=parser.parse_args();print(json.dumps(operate(load_config(args.config),args.service,args.job,args.action)))


if __name__=='__main__':main()
