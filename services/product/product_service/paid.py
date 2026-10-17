"""Optional Product-only credentials/policy. No collector/analyzer imports."""
import math
import os
from pathlib import Path
import shlex
import stat
from .core import clean_environment


def key():
    clean_environment()
    path=Path(os.environ.get('PIPELINE_PRODUCT_OPENAI_KEY_FILE','/etc/market-pipeline/credentials/openai.env'))
    if path.name!='openai.env':raise ValueError('Dedicated OpenAI file required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode&(stat.S_IWGRP|stat.S_IRWXO) or info.st_size>8192:raise ValueError('Protected bounded OpenAI file required')
        body=os.read(fd,8193)
        if len(body)>8192:raise ValueError('Credential file too large')
    finally:os.close(fd)
    lines=[v.strip().removeprefix('export ') for v in body.decode().splitlines() if v.strip() and not v.lstrip().startswith('#')]
    if len(lines)!=1 or not lines[0].startswith('OPENAI_API_KEY='):raise ValueError('Only literal OpenAI assignment allowed')
    values=shlex.split(lines[0].split('=',1)[1],comments=False)
    if len(values)!=1 or not values[0] or any(c.isspace() or c in '$`' for c in values[0]):raise ValueError('Invalid OpenAI key')
    return values[0]


def policy(settings=None):
    default={'provider':'ollama','model':'gemma3:4b','ollama_url':'http://127.0.0.1:11434'}
    if settings is None:return default
    if not isinstance(settings,dict) or settings.get('provider') not in ('ollama','openai'):raise ValueError('Explicit Product provider required')
    if settings['provider']=='ollama':
        if set(settings)!=set(default):raise ValueError('Invalid local Product provider policy')
        from .briefing import OllamaBrief
        OllamaBrief(settings['model'],settings['ollama_url'])
    else:
        if set(settings)!={'provider','model','paid'} or settings['model'] not in ('gpt-6.1-sol','gpt-6-astra'):raise ValueError('Priced Product model required')
        p=settings['paid']
        required={'enabled','daily_usd','daily_calls','total_usd','ledger_root','max_output_tokens','max_input_token_bound'}
        if not isinstance(p,dict) or set(p)-{'development','reasoning_effort','timeout_seconds','allow_held_unknown'}!=required or type(p['enabled']) is not bool:raise ValueError('Explicit shared paid policy required')
        if type(p.get('allow_held_unknown',False)) is not bool:raise ValueError('Explicit held-reservation policy required')
        if type(p.get('timeout_seconds',240)) is not int or not 30<=p.get('timeout_seconds',240)<=300:raise ValueError('Invalid provider timeout')
        def number(v,maximum):return type(v) in (int,float) and math.isfinite(v) and 0<=v<=maximum
        if not number(p['total_usd'],2) or (p['daily_usd'] is not None and not number(p['daily_usd'],2)):raise ValueError('Invalid total budget')
        if p['daily_calls'] is not None and (type(p['daily_calls']) is not int or not 0<=p['daily_calls']<=100):raise ValueError('Invalid daily calls')
        if type(p['max_output_tokens']) is not int or not 512<=p['max_output_tokens']<=12000 or type(p['max_input_token_bound']) is not int or not 2048<=p['max_input_token_bound']<=100000:raise ValueError('Invalid token bounds')
        if 'development' in p:
            import re
            d=p['development']
            if not isinstance(d,dict) or set(d)!={'id','total_usd'} or not isinstance(d['id'],str) or not re.fullmatch('[a-z0-9-]{1,80}',d['id']) or not number(d['total_usd'],2):raise ValueError('Invalid shared development envelope')
        if not isinstance(p['ledger_root'],str) or not Path(p['ledger_root']).is_absolute():raise ValueError('Absolute shared ledger required')
        if p.get('reasoning_effort','medium') not in ('low','medium','high'):raise ValueError('Invalid reasoning effort')
    return settings
