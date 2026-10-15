"""One configured Analyzer email per saved collection, independent of HTTP delivery."""
import html
import json
from pathlib import Path
from pipeline_mail import enqueue,tick


def activate(config):
    if not config.get('mail',{}).get('enabled'):return
    from .io import write_json,now
    path=Path(config['output_root'])/'mail-activation.json'
    if not path.exists():write_json(path,{'at':now()})


def prepare(directory,config):
    settings=config.get('mail',{})
    if not settings.get('enabled'):return
    directory=Path(directory);source=directory/'outbound-wire.json'
    since=json.loads((Path(config['output_root'])/'mail-activation.json').read_text())['at']
    if json.loads((directory/'state.json').read_text()).get('started_at','')<since:return
    payload=json.loads((directory/'outbound.json').read_bytes())
    body=source.read_bytes() if source.exists() else json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    report=payload.get('report') or {}
    if report.get('recommendations') and all(r.get('product_brief') for r in report['recommendations']):
        from .email_delivery import render,render_html
        text=render(payload);markup=render_html(payload)
    else:
        text='Market analysis — '+payload['source_run_id']+'\n\n'+report.get('summary','Analysis did not produce a complete product recommendation.')+'\nStatus: '+str(payload.get('status'))+'\n\nThe attached JSON is the exact payload prepared for Product. No opportunity or product has been invented to fill an evidence gap.'
        markup='<html><body><pre>'+html.escape(text)+'</pre></body></html>'
    scope=report.get('data_scope') or {}
    if 'pooled_listing_count' in scope:
        note=f"Collection additions: {scope['current_run_listing_count']}; saved candidate pool: {scope['pooled_listing_count']} listings across {scope['shop_count']} shops. Historical observations keep their original dates."
        text=note+'\n\n'+text
        markup=markup.replace('<body>','<body><p>'+html.escape(note)+'</p>',1)
    return enqueue(Path(config['output_root'])/'mail-outbox','analyzer',payload['source_run_id'],
                   'Market analysis — '+payload['source_run_id'],text,markup,[('market-analysis.json',body)],settings)


def deliver(config,**kwargs):return tick(Path(config['output_root'])/'mail-outbox',config.get('mail'),**kwargs)
