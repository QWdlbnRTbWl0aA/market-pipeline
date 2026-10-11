"""Create backward-compatible receipts; never restore dynamic ledgers or raw data.

Run this script with the known-good analyzer as its import root BEFORE rollback.
New/old receipts and tracking-park records coexist. Unknown outcomes stay parked.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def bridge(config, output, legacy_code):
    # Loaded in a separate clean process so old/new package namespaces never mix.
    sys.path.insert(0, str(Path(legacy_code).resolve()))
    from analyzer.history import HistoryIntake
    from analyzer.saved_intake import SavedCollectionIntake, discover
    from analyzer.services import RECIPE_VERSION, RESEARCH_VERSION
    from analyzer.io import write_json, now
    from analyzer.security import assert_clean_environment, reject_secrets
    assert_clean_environment();reject_secrets(config)
    output=Path(output).resolve();mapping=[];sources={}
    for service in ('search_refinement','market_insights'):
        states={}
        for path in (output/service).glob('*/state.json'):
            if path.is_symlink():raise ValueError('Receipt symlink refused')
            state=json.loads(path.read_text());reject_secrets(state)
            states.setdefault(state['source_run_id'],[]).append((path,state))
        for run_id in discover(config['saved_runs_root']):
            batch=HistoryIntake(config['saved_runs_root'],run_id).read() if 'research' in config else SavedCollectionIntake(config['saved_runs_root'],run_id).read()
            snapshot=json.loads(Path(batch.provenance['input_path']).read_text())
            tracking=snapshot.get('artifact_kind')=='tracking' or snapshot.get('mode')=='tracking'
            choices=states.get(run_id,[])
            if not choices and not tracking:continue # Genuinely unseen discovery remains eligible.
            expected_recipe=RESEARCH_VERSION if 'research' in config else RECIPE_VERSION
            compatible=[r for r in choices if r[1].get('recipe_version')==expected_recipe and r[1].get('input_sha256')==batch.provenance['input_sha256']]
            older = [r for r in choices if r[1].get('input_sha256')==batch.provenance['input_sha256']]
            if not compatible and not tracking and not older:raise ValueError('Source checksum mismatch for '+run_id+'; hold rollback')
            identity={'service':service,'input_sha256':batch.provenance['input_sha256'],'source_run_id':run_id,'recipe_version':expected_recipe,
                      'model':config['model'],'model_digest':config.get('model_digest'),'sample_size':config['sample_size'],
                      'research_policy':config.get('research'),'paid_policy':config.get('paid'),
                      'history_sha256':hashlib.sha256(json.dumps(batch.metadata.get('history'),sort_keys=True).encode()).hexdigest()}
            key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();folder=output/service/key
            if (folder/'state.json').exists():
                previous=json.loads((folder/'state.json').read_text())
                if previous.get('input_sha256')!=identity['input_sha256']:raise ValueError('Legacy receipt collision')
                mapping.append({'source_run_id':run_id,'service':service,'legacy_job_id':key,'status':'existing_receipt'});continue
            parked_prior = not tracking and not compatible
            if tracking or parked_prior:
                state={'job_id':key,**identity,'analysis_status':'failed','delivery_status':'delivered','delivery_id':key,
                       'rollback_note':'Prior revision requires explicit review before running legacy recipe' if parked_prior else 'Tracking deliberately parked; never auto-analyze tracking with legacy watcher','finished_at':now()}
                payload={'schema_version':1,'service':service,'status':'held_prior_revision' if parked_prior else 'ignored_tracking','delivery_id':key,'source_run_id':run_id,'recommendations_applied':False}
            else:
                compatible.sort(key=lambda r:(r[1]['analysis_status']!='completed',r[0].name));path,state=compatible[0]
                state={**state,'rollback_original_job_id':state['job_id'],'rollback_legacy_job_id':key}
                if state['analysis_status']=='budget_waiting':state.update(analysis_status='failed',delivery_status='delivered',rollback_note='Budget waiting requires explicit operator recovery')
                outbound=path.parent/'outbound.json'
                payload=json.loads(outbound.read_text()) if outbound.exists() else None
                if state['analysis_status'] not in ('completed','failed','running'):raise ValueError('Unknown analysis state; hold rollback')
            folder.mkdir(parents=True,exist_ok=True)
            # Output first, terminal state last. A crash before state cannot imply
            # completed generation; deployment is held until bridge proof passes.
            if payload is not None:write_json(folder/'outbound.json',payload)
            write_json(folder/'state.json',state)
            mapping.append({'source_run_id':run_id,'service':service,'legacy_job_id':key,'original_job_id':state.get('job_id'),'status':'tracking_parked' if tracking else 'prior_revision_parked' if parked_prior else 'compatible_receipt_created'})
    manifest={'schema_version':1,'at':now(),'legacy_code':str(Path(legacy_code).resolve()),'mapping':mapping,
              'external_calls':0,'source_data_modified':False,'quota_or_paid_ledgers_restored':False}
    write_json(output/'lifecycle'/'rollback-bridge.json',manifest);return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Bridge completed analysis receipts before code rollback')
    parser.add_argument('--config',required=True);parser.add_argument('--output',required=True);parser.add_argument('--legacy-code',required=True)
    args=parser.parse_args();config_path=Path(args.config)
    if config_path.suffix!='.json' or config_path.is_symlink() or any(p.startswith('.env') for p in config_path.parts):raise ValueError('Independent nonsecret config required')
    value=json.loads(config_path.read_text());print(json.dumps(bridge(value,args.output,args.legacy_code)))
