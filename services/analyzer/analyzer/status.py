"""Read-only analyzer report and spend inspection. No models, credential reads or network."""
import argparse
import json
from pathlib import Path
from .services import load_config
from .service_reports import SERVICES
from .research import VERSION

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',default='services-production.json');args=parser.parse_args()
    config=load_config(args.config);root=Path(config['output_root']);paid=config.get('paid',{})
    result={'output_root':str(root),'paid_enabled':paid.get('enabled',False),'services':{}}
    for service in SERVICES:
        paths=[p for p in (root/service).glob('*/state.json') if json.loads(p.read_text()).get('recipe_version')==VERSION]
        if not paths:paths=[p for p in (root/'dry-runs'/service).glob('*/state.json') if json.loads(p.read_text()).get('recipe_version')==VERSION]
        if paths:
            path=max(paths,key=lambda p:p.stat().st_mtime_ns);state=json.loads(path.read_text())
            result['services'][service]={k:state.get(k) for k in ('job_id','source_run_id','analysis_status','delivery_status','finished_at')}
            result['services'][service]['report_path']=str(path.parent/'outbound.json')
            payload_path=path.parent/'outbound.json'
            if payload_path.exists():
                report=json.loads(payload_path.read_text()).get('report',{})
                result['services'][service]['report_status']=report.get('status')
                result['services'][service]['execution_mode']=report.get('execution_mode')
    if paid:
        path=Path(paid['ledger_root'])/'budget.json';ledger=json.loads(path.read_text()) if path.exists() else {'calls':{}}
        calls=list(ledger['calls'].values())
        result['paid_usage']={'requests_reserved':len(calls),'completed_requests':sum(c['status']=='completed' for c in calls),
            'estimated_completed_usd':sum(c['charged_usd'] for c in calls if c['status']=='completed'),
            'unresolved_reserved_usd':sum(c['charged_usd'] for c in calls if c['status']!='completed'),
            'daily_ceiling_usd':paid['daily_usd'],'total_ceiling_usd':paid['total_usd'],
            'blocked':ledger.get('blocked'),'cooldown_until':ledger.get('cooldown_until')}
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
