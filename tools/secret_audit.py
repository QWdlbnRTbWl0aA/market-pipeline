#!/usr/bin/env python3
"""Offline release audit. Never prints matched values; inspect all Git objects.

Optional credential comparisons happen only in this auditor process. Application
services do not import it. Report paths/rules/object IDs, never credentials.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
from environment_audit import context,findings as environment_findings

PATTERNS={
 'private_key':re.compile(rb'-----BEGIN (?:OPENSSH|RSA|EC|DSA|PRIVATE|ENCRYPTED)[^\r\n]*KEY-----\s+[A-Za-z0-9+/=]{40,}'),
 'openai_key':re.compile(rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}'),
 'github_token':re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})'),
 'aws_access':re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
 'credential_url':re.compile(rb'https?://[^\s/:]+:[^\s/@]{8,}@'),
 'literal_secret':re.compile(rb'(?i)(?:password|api[_-]?key|api[_-]?secret|access[_-]?token|client[_-]?secret)\s*[=:]\s*[\x22\x27]([A-Za-z0-9_+/=-]{20,})[\x22\x27]')}


def findings(data,secrets=(),inventory=None):
 rules=[]
 for name,pattern in PATTERNS.items():
  if pattern.search(data):rules.append(name)
 if any(secret in data for secret in secrets):rules.append('exact_local_credential')
 return rules+environment_findings(data,inventory)


def local_secrets(paths):
 values=[];missing=[]
 for path in paths:
  path=Path(path)
  try:
   if path.is_symlink():raise ValueError('Credential symlink refused')
   text=path.read_text()
   if len(text)>65536:raise ValueError('Credential input too large')
   for line in text.splitlines():
    line=line.strip().removeprefix('export ')
    if not line or line.startswith('#') or '=' not in line:continue
    key,value=line.split('=',1)
    if not any(word in key.upper() for word in ('KEY','SECRET','TOKEN','PASSWORD')):continue
    parts=shlex.split(value,comments=True)
    if len(parts)==1 and len(parts[0])>=8:
     values.append(parts[0].encode())
     if 'PASSWORD' in key.upper():values.append(parts[0].replace(' ','').encode())
  except (OSError,ValueError):missing.append(str(path))
 return list(set(values)),missing


def audit(root,secrets=(),history=True,inventory=None):
 root=Path(root).resolve();issues=[];files=0;objects=0
 if inventory is None:inventory=context(root)
 for p in root.rglob('*'):
  relative=p.relative_to(root)
  if '.git' in relative.parts or '__pycache__' in relative.parts:continue
  if p.is_symlink():issues.append({'path':str(relative),'rule':'symlink_requires_review'});continue
  if not p.is_file():continue
  if p.stat().st_size>100_000_000:issues.append({'path':str(relative),'rule':'oversize_not_scanned'});continue
  files+=1
  for rule in findings(p.read_bytes()+b'\n'+str(relative).encode(),secrets,inventory):issues.append({'path':str(relative),'rule':rule})
 if history:
  listing=subprocess.check_output(['git','-C',str(root),'cat-file','--batch-all-objects','--batch-check=%(objectname) %(objecttype) %(objectsize)'],text=True)
  for line in listing.splitlines():
   oid,kind,size=line.split();objects+=1
   if int(size)>100_000_000:issues.append({'object':oid,'rule':'oversize_not_scanned'});continue
   body=subprocess.check_output(['git','-C',str(root),'cat-file',kind,oid])
   for rule in findings(body,secrets,inventory):issues.append({'object':oid,'kind':kind,'rule':rule})
 return {'repository':str(root),'working_files_scanned':files,'all_git_objects_scanned':objects,'findings':issues,'clean':not issues,
         'scope':'working tree, filenames and every Git object, including unreachable objects; credentials, network identity and machine-path checks',
         'limitation':'Deterministic audit is not a guarantee against unknown secret formats; runtime/generated artifacts are excluded by publication policy.'}


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('repositories',nargs='+');parser.add_argument('--credential-file',action='append',default=[]);parser.add_argument('--environment-file');parser.add_argument('--output',required=True);args=parser.parse_args()
 secrets,missing=local_secrets(args.credential_file)
 rows=[audit(path,secrets,inventory=context(path,args.environment_file)) for path in args.repositories]
 result={'credential_comparison_values':len(secrets),'unreadable_credential_files':missing,'repositories':rows,'passed':not missing and all(r['clean'] for r in rows)}
 output=Path(args.output).resolve()
 if any(output.is_relative_to(Path(path).resolve()) for path in args.repositories):raise ValueError('Audit output must be outside audited repositories')
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'passed':result['passed'],'repositories':len(rows),'findings':sum(len(r['findings']) for r in rows),'unreadable_files':len(missing),'report':str(output)}))
 return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
