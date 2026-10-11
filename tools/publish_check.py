#!/usr/bin/env python3
"""Offline publication guard: scan all Git objects and reject runtime artifacts."""
import argparse
import json
from pathlib import Path
import subprocess
from secret_audit import audit

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS={'data','runtime','runs','reports','test-output','credentials','secrets','__pycache__','.venv','inventories'}
FORBIDDEN_SUFFIXES={'.env','.pem','.key','.pyc','.log','.eml','.png','.jpg','.jpeg','.pdf'}


def check(root=ROOT):
    root=Path(root)
    result=audit(root)
    files=subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0')
    issues=[]
    for name in filter(None,files):
        path=Path(name)
        if FORBIDDEN_PARTS.intersection(path.parts) or path.name.startswith('.env') or path.suffix in FORBIDDEN_SUFFIXES:
            issues.append({'path':name,'rule':'runtime_or_secret_artifact'})
        if path.parts[0]=='config' and path.suffix=='.json' and not path.name.endswith('.example.json'):
            issues.append({'path':name,'rule':'live_configuration'})
        if path.name in ('environment.json','environment-inventory.json'):
            issues.append({'path':name,'rule':'private_environment_inventory'})
        if (root/path).is_file() and (root/path).stat().st_size>1_000_000:
            issues.append({'path':name,'rule':'oversized_publication_file'})
    status=subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True)
    if status:issues.append({'rule':'uncommitted_files'})
    if (root/'.git'/'objects'/'info'/'alternates').exists():issues.append({'rule':'legacy_object_alternates'})
    result['publication_issues']=issues
    result['clean']=result['clean'] and not issues
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output');args=parser.parse_args()
    result=check()
    if args.output:
        path=Path(args.output).resolve()
        if path.is_relative_to(ROOT):raise ValueError('Keep generated audit reports outside the repository')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'clean':result['clean'],'working_files_scanned':result['working_files_scanned'],
                      'git_objects_scanned':result['all_git_objects_scanned'],'findings':result['findings'],
                      'publication_issues':result['publication_issues']}))
    raise SystemExit(0 if result['clean'] else 1)
