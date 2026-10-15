#!/usr/bin/env python3
"""Preview/apply Product passive-library delivery; no services, credentials or requests."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services'/'product'))
from product_service.studio_delivery import policy
from pipeline_mail import write

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',default='/etc/market-pipeline/product.json');parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    path=Path(args.config)
    if path.is_symlink() or path.resolve().is_relative_to(ROOT):raise ValueError('Independent regular runtime configuration required')
    before=json.loads(path.read_text());after={**before,'studio_delivery':policy({**before.get('studio_delivery',{}),'enabled':True})}
    changed=before!=after
    if args.apply and changed:
        backup=path.with_suffix('.json.before-studio-library')
        if backup.exists():raise ValueError('Backup exists; review prior enablement before changing settings')
        write(backup,before);write(path,after,preserve=True)
    print(json.dumps({'applied':args.apply,'changed':changed,'studio_delivery':after['studio_delivery'],'inference_triggered':False}))
