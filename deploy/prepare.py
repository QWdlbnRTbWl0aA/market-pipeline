#!/usr/bin/env python3
"""Create independent runtime configurations outside the source repository. No requests."""
import argparse
import json
from pathlib import Path
import os
import secrets

ROOT = Path(__file__).resolve().parents[1]


def prepare(state, configs):
    state, configs = Path(state).resolve(), Path(configs).resolve()
    if state.is_relative_to(ROOT) or configs.is_relative_to(ROOT):
        raise ValueError('Runtime files must remain outside the publication repository')
    os.umask(0o077)
    for part in ('collector/runs','analyzer','product','studio','controller/operations','controller/cohorts','controller/qualifications','paid-ledger','local-cache'):
        (state/part).mkdir(parents=True,exist_ok=True)
    configs.mkdir(parents=True,exist_ok=True)
    def rewrite(value):
        if isinstance(value, str): return value.replace('/var/lib/market-pipeline',str(state))
        if isinstance(value, dict): return {k:rewrite(v) for k,v in value.items()}
        if isinstance(value, list): return [rewrite(v) for v in value]
        return value
    for name in ('collector','analyzer','controller','product','studio'):
        target = state/'collector'/'config.json' if name == 'collector' else configs/(name+'.json')
        # Existing saved settings, cursors, quotas and ledgers are never reset.
        if target.exists(): continue
        content = rewrite(json.loads((ROOT/'config'/(name+'.example.json')).read_text()))
        if name == 'analyzer': content['paid']['enabled'] = False
        with target.open('x') as output: json.dump(content,output,indent=2);output.write('\n')
    token = state/'control-auth'
    if not token.exists():
        with token.open('x') as output: output.write(secrets.token_hex(32)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',required=True);p.add_argument('--configs',required=True)
    args=p.parse_args();prepare(args.state,args.configs)
