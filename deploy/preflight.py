#!/usr/bin/env python3
"""Read-only deployment checks. Never opens keys or generates model/source requests."""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import urllib.request

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user',default='market-pipeline')
    p.add_argument('--state',default='/var/lib/market-pipeline')
    p.add_argument('--configs',default='/etc/market-pipeline')
    args=p.parse_args();checks=[]
    try:
        account=pwd.getpwnam(args.user);checks.append({'check':'application_account','ok':account.pw_uid!=0})
    except KeyError:checks.append({'check':'application_account','ok':False,'action':'Administrator must provision the dedicated account'})
    source=Path(__file__).resolve().parents[1]
    validators={'collector':'from etsy_app.core import config; config(sys.argv[1])',
                'analyzer':'from analyzer.services import load_config; load_config(sys.argv[1])',
                'controller':'from pipeline_control.controller import config; config(sys.argv[1])',
                'product':'from product_service.configuration import load; load(sys.argv[1])',
                'studio':'from studio_service.server import configuration; configuration(sys.argv[1])'}
    for component in validators:
        file=Path(args.state)/'collector'/'config.json' if component=='collector' else Path(args.configs)/(component+'.json')
        valid=False
        if file.is_file():
            result=subprocess.run([sys.executable,'-c','import sys; '+validators[component],str(file)],
                                  cwd=source/'services'/component,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'},
                                  capture_output=True,timeout=10)
            valid=result.returncode==0
        checks.append({'check':'configuration_valid','component':component,'path':str(file),'ok':valid})
    analyzer_path=Path(args.configs)/'analyzer.json'
    if analyzer_path.is_file():
        try:
            config=json.loads(analyzer_path.read_text());policy=config['paid']
            correct=policy['total_usd']==2 and policy['daily_usd'] is None and policy['daily_calls'] is None
            checks.append({'check':'development_total_budget_policy','ok':correct})
            path=Path(policy['ledger_root'])/'budget.json'
            valid=not policy['enabled']
            if path.exists():
                ledger=json.loads(path.read_text())
                spent=sum(row['charged_usd'] for row in ledger['calls'].values())
                valid=spent<=2 and not any(row['status']=='reserved_unknown' for row in ledger['calls'].values()) and not ledger.get('blocked')
            checks.append({'check':'paid_accounting_ready','ok':valid})
        except (ValueError,KeyError,OSError,TypeError):checks.append({'check':'paid_accounting_ready','ok':False})
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:11434/api/tags',timeout=5) as response:
            models=json.load(response)
        checks.append({'check':'local_ollama_model','ok':any(x.get('name')=='gemma3:4b' for x in models['models'])})
    except Exception as error:checks.append({'check':'local_ollama_model','ok':False,'error_type':type(error).__name__})
    print(json.dumps({'ready':all(x['ok'] for x in checks),'checks':checks},indent=2))
    raise SystemExit(0 if all(x['ok'] for x in checks) else 1)
