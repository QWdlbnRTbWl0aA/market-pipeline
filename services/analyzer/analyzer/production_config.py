"""Explicit deployment and spending policy, validated before any model calls."""
import math
from pathlib import Path
from .adapters.openai import RATES

def number(value,low,high):return type(value) in (int,float) and math.isfinite(value) and low<=value<=high

def validate_policy(config):
    research=config['research'];paid=config.get('paid')
    if not isinstance(research,dict) or set(research)!={'min_group_listings','max_candidates','cheap_price_reference'}:
        raise ValueError('Explicit research policy required')
    for field,low,high in [('min_group_listings',1,100),('max_candidates',1,20)]:
        if type(research[field]) is not int or not low<=research[field]<=high:raise ValueError('Invalid research bound')
    references=research['cheap_price_reference']
    if isinstance(references,dict):
        if not references or any(not isinstance(k,str) or len(k)!=3 or not k.isascii() or not k.isupper() or not number(v,0,1000) for k,v in references.items()):raise ValueError('Invalid currency references')
    elif not number(references,0,1000):raise ValueError('Invalid price reference')
    required={'enabled','cheap_model','final_model','daily_usd','total_usd','daily_calls','max_output_tokens','max_input_token_bound','ledger_root'}
    if not isinstance(paid,dict) or set(paid)-{'development'}!=required or type(paid['enabled']) is not bool:raise ValueError('Explicit paid policy required')
    if 'development' in paid:
        import re
        envelope=paid['development']
        if not isinstance(envelope,dict) or set(envelope)!={'id','total_usd'} or not isinstance(envelope['id'],str) or not re.fullmatch('[a-z0-9-]{1,80}',envelope['id']) or not number(envelope['total_usd'],0,.5):raise ValueError('Invalid development envelope')
    if paid['cheap_model']!='gpt-6-luna' or paid['final_model']!='gpt-6.1-sol':raise ValueError('Priced stage allowlist required')
    for name in ('daily_usd','total_usd'):
        if name=='daily_usd' and paid[name] is None:continue
        if not number(paid[name],0,100):raise ValueError('Invalid paid budget')
    for name,low,high in [('daily_calls',0,100),('max_output_tokens',512,4000),('max_input_token_bound',2048,100000)]:
        if name=='daily_calls' and paid[name] is None:continue
        if type(paid[name]) is not int or not low<=paid[name]<=high:raise ValueError('Invalid paid token/call bound')
    ledger=Path(paid['ledger_root']).resolve();source=Path(config['saved_runs_root']).resolve()
    if ledger==source or ledger.is_relative_to(source) or source.is_relative_to(ledger):raise ValueError('Paid ledger must be separate from source')
