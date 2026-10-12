#!/usr/bin/env python3
"""Launch exactly one service with an allowlisted, credential-separated environment."""
import argparse
import os
from pathlib import Path
import shlex
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ('collector', 'search-refiner', 'market-analyst', 'controller', 'product')


def read_collector_credentials(path):
    path = Path(path)
    # open() enforces this process's actual access, including service-manager
    # delivery, groups and ACLs. Ownership is not a credential-delivery contract.
    # Nonblocking prevents a substituted FIFO from hanging before fstat rejects it.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        unsafe_permissions = stat.S_IWGRP | stat.S_IRWXO
        if not stat.S_ISREG(info.st_mode) or info.st_mode & unsafe_permissions or info.st_size > 8192:
            raise ValueError('Collector credentials require a bounded regular file without group-write or other access')
        body = os.read(descriptor, 8193)
        if len(body) > 8192:
            raise ValueError('Collector credential file too large')
        content = body.decode('utf-8')
    finally:
        os.close(descriptor)
    values = {}
    for line in content.splitlines():
        line = line.strip().removeprefix('export ')
        if not line or line.startswith('#'): continue
        name, separator, value = line.partition('=')
        if not separator or name not in ('ETSY_API_KEY', 'ETSY_API_SECRET'):
            raise ValueError('Unexpected collector credential field')
        parts = shlex.split(value, comments=True)
        if len(parts) != 1 or not parts[0] or any(c in parts[0] for c in '$`\n\r'):
            raise ValueError('Literal collector credential values required')
        values[name] = parts[0]
    if set(values) != {'ETSY_API_KEY', 'ETSY_API_SECRET'}:
        raise ValueError('Both collector credential fields required')
    return values


def command(service, config, state, port=None, bind='127.0.0.1', credential_directory=None, extra=()):
    state = Path(state).resolve()
    env = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'PYTHONUNBUFFERED':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
    component = {'search-refiner':'analyzer', 'market-analyst':'analyzer'}.get(service, service)
    cwd = ROOT/'services'/component
    if service == 'collector':
        env['PIPELINE_DASHBOARD_HOSTNAMES'] = os.environ.get('PIPELINE_DASHBOARD_HOSTNAMES','')
        if credential_directory:
            env.update(read_collector_credentials(Path(credential_directory)/'etsy.env'))
        args = ['-m','etsy_app','--config',str(config),'--data',str(state/'collector'), 'serve',
                '--host',bind,'--port',str(port or 8090),'--defer-today']
        env['PIPELINE_CONTROL_AUTH_FILE'] = str(state/'control-auth')
        env['PIPELINE_OPERATIONS_ROOT'] = str(state/'controller'/'operations')
    elif service in ('search-refiner','market-analyst'):
        if credential_directory:
            # Only the paid adapter may open this file, immediately before an admitted request.
            env['PIPELINE_OPENAI_KEY_FILE'] = str(Path(credential_directory)/'openai.env')
        env['PIPELINE_SAVED_RUNS_ROOT'] = str(state/'collector'/'runs')
        args = ['-m','analyzer.services','--config',str(config),'--watch','--service',
                'search_refinement' if service == 'search-refiner' else 'market_insights']
    elif service == 'controller':
        args = ['-m','pipeline_control','--config',str(config),'serve','--port',str(port or 8094)]
    elif service == 'product':
        args = ['-m','product_service','serve','--data',str(state/'product'),'--port',str(port or 8093),
                '--definition-config',str(config),'--operations-root',str(state/'controller'/'operations')]
    else: raise ValueError('Unknown service')
    return cwd, [sys.executable, *args, *extra], env


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('service', choices=SERVICES)
    p.add_argument('--config', required=True)
    p.add_argument('--state', default='/var/lib/market-pipeline')
    p.add_argument('--port', type=int)
    p.add_argument('--bind', default='127.0.0.1')
    p.add_argument('--credential-directory', default=os.environ.get('CREDENTIALS_DIRECTORY'))
    args, extra = p.parse_known_args()
    cwd, argv, env = command(args.service, Path(args.config).resolve(), args.state, args.port,
                             args.bind, args.credential_directory, extra)
    os.umask(0o077)
    os.chdir(cwd)
    os.execve(sys.executable, argv, env)


if __name__ == '__main__': main()
