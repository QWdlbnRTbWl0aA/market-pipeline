#!/usr/bin/env python3
"""Manage external Studio provider files locally; never authenticate or print keys."""
import argparse
import getpass
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services'/'studio'))
from studio_service.credentials import read_key

FILES={'openai':('studio-openai.env','OPENAI_API_KEY'),'google':('studio-google.env','GEMINI_API_KEY')}


def manage(directory,operation,provider=None,value=None):
    directory=Path(directory)
    if any(p.is_symlink() for p in (directory,*directory.parents)) or any((p/'.git').exists() for p in (directory,*directory.parents)):raise ValueError('Credential directory must be external to source control, without symlinks')
    if operation=='list':return {'providers':[name for name,(filename,assignment) in FILES.items() if (directory/filename).is_file()]}
    if provider not in FILES:raise ValueError('Choose an implemented provider')
    filename,assignment=FILES[provider];path=directory/filename
    if path.is_symlink():raise ValueError('Credential symlinks forbidden')
    if operation=='check':read_key(path,assignment);return {'provider':provider,'local_format_valid':True,'network_requests':0}
    if operation=='remove':
        if not path.is_file():raise ValueError('Provider key does not exist')
        path.unlink();return {'provider':provider,'removed':True,'restart_required':True}
    if operation not in ('add','update') or (operation=='add' and path.exists()) or (operation=='update' and not path.is_file()):raise ValueError('Use add for new keys and update for existing keys')
    if not isinstance(value,str) or not value or len(value)>8000 or any(c.isspace() or c in '$`\'"\\' for c in value):raise ValueError('A single literal key is required')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.credential-',dir=directory)
    try:
        with os.fdopen(descriptor,'w') as stream:stream.write(assignment+'='+value+'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return {'provider':provider,'saved':True,'restart_required':True,'network_requests':0}


def main():
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('add','update','remove','list','check'));parser.add_argument('--provider',choices=FILES)
    parser.add_argument('--directory',required=True);parser.add_argument('--stdin',action='store_true');parser.add_argument('--local',action='store_true')
    args=parser.parse_args()
    if args.operation=='check' and not vars(args)['local']:parser.error('Only check --local is implemented; it performs no provider call')
    value=None
    if args.operation in ('add','update'):
        value=sys.stdin.read(8193).strip() if args.stdin else getpass.getpass('API key (hidden): ')
    try:print(json.dumps(manage(args.directory,args.operation,args.provider,value)))
    except (ValueError,OSError):parser.exit(1,'Key operation failed: check directory, provider, protected-file format and add/update choice. No key values are printed.\n')


if __name__=='__main__':main()
