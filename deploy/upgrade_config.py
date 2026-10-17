#!/usr/bin/env python3
"""Preview/apply additive upgrade settings; no credentials, requests, ledger resets or daemons."""
import argparse
import json
import hashlib
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services'/'common'))
from pipeline_mail import policy,write
sys.path.insert(0,str(ROOT/'services'/'product'))
from product_service.paid import policy as product_paid_policy


def plan(configs,enable_mail=False,recipients=None,enable_product_openai=False):
    directory=Path(configs).resolve()
    if directory.is_relative_to(ROOT):raise ValueError('Runtime settings must remain outside source')
    result={}
    for name in ('analyzer','product'):
        path=directory/(name+'.json')
        if path.is_symlink():raise ValueError('Configuration symlink forbidden')
        original=json.loads(path.read_text());updated=json.loads(json.dumps(original))
        mail=policy(updated.get('mail'))
        if enable_mail:mail['enabled']=True
        if recipients is not None:mail['recipients']=recipients
        updated['mail']=policy(mail)
        if name=='analyzer':
            updated.setdefault('opportunities',{'enabled':True})
            if updated.get('paid',{}).get('max_output_tokens')==2400:updated['paid']['max_output_tokens']=4000
        if name=='product' and enable_product_openai:
            source=result['analyzer']['after']['paid']
            paid={k:v for k,v in source.items() if k not in ('cheap_model','final_model')}
            paid.update(enabled=True,max_output_tokens=6000,timeout_seconds=240)
            updated['briefing']={'provider':'openai','model':source['final_model'],'paid':paid}
            product_paid_policy(updated['briefing'])
            # The legacy promoted wireframe path is a separate reviewed feature.
            if updated.get('enhanced_enabled'):raise ValueError('Review the enabled legacy Product path before selecting the new default provider')
        result[name]={'path':path,'before':original,'after':updated,'changed_fields':[k for k in updated if updated.get(k)!=original.get(k)]}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--configs',default='/etc/market-pipeline');parser.add_argument('--enable-mail',action='store_true');parser.add_argument('--recipients',help='Comma-separated addresses; omit to use SMTP_TO or preserve configured recipients');parser.add_argument('--apply',action='store_true')
    parser.add_argument('--enable-product-openai',action='store_true',help='Preview independent Product OpenAI policy using the existing Analyzer ledger and budgets; no key loading or calls')
    args=parser.parse_args();changes=plan(args.configs,args.enable_mail,args.recipients.split(',') if args.recipients else None,args.enable_product_openai)
    def backup_path(row):return row['path'].with_suffix('.json.before-config-upgrade-'+hashlib.sha256(json.dumps(row['before'],sort_keys=True).encode()).hexdigest()[:12])
    if args.apply and any(backup_path(row).exists() for row in changes.values() if row['changed_fields']):raise ValueError('Backup exists; review prior upgrade before modifying settings')
    for name,row in changes.items():
        if args.apply and row['changed_fields']:
            backup=backup_path(row)
            if backup.exists():raise ValueError('Backup exists; review prior upgrade before modifying settings')
            write(backup,row['before']);write(row['path'],row['after'],preserve=True)
    print(json.dumps({'applied':args.apply,'components':{name:{'changed_fields':row['changed_fields'],'mail_enabled':row['after']['mail']['enabled']} for name,row in changes.items()},
        'product_openai':{'enabled':args.enable_product_openai,'model':changes['product']['after'].get('briefing',{}).get('model'),
            'total_usd':changes['product']['after'].get('briefing',{}).get('paid',{}).get('total_usd'),
            'development':changes['product']['after'].get('briefing',{}).get('paid',{}).get('development')}}))
