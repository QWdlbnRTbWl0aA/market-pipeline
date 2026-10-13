"""Mail the complete exact saved Studio briefs, one message per source collection."""
import html
import json
from pathlib import Path
from pipeline_mail import enqueue,tick


def prepare(result,root,settings):
    if not settings.get('enabled'):return
    folder=Path(result['directory']);handoff=folder/'studio-handoff.json'
    if not handoff.exists():raise ValueError('A saved Studio handoff is required for Product mail')
    attachments=[('studio-handoff.json',handoff.read_bytes())];sections=[]
    if isinstance(result.get('products'),list):
        paths=[Path(p['directory'])/'product.json' for p in result['products'] if p.get('directory')]
    else:paths=sorted(folder.glob('product-*/product.json'))
    for index,path in enumerate(paths,1):
        if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):raise ValueError('Saved Product brief escaped its data root')
        if not path.exists():continue
        body=path.read_bytes();value=json.loads(body)
        attachments.append((f'studio-brief-{index:02d}.json',body))
        # Full specification, not a shortened replacement or a filesystem link.
        brief=path.parent/'brief.md'
        sections.append((brief.read_text()+'\n\n' if brief.exists() and not brief.is_symlink() else '')+json.dumps(value,ensure_ascii=False,indent=2))
    text='Product → Studio brief — '+str(result['source_run_id'])+'\n\n'+('\n\n---\n\n'.join(sections) if sections else 'No complete Studio brief was produced. Status: '+result['status']+'\n\n'+handoff.read_text())
    markup='<html><body><h1>Product → Studio brief</h1><pre style="white-space:pre-wrap">'+html.escape(text)+'</pre></body></html>'
    return enqueue(Path(root)/'mail-outbox','product',result['source_run_id'],'Studio briefs — '+result['source_run_id'],text,markup,attachments,settings)


def deliver(root,settings,**kwargs):return tick(Path(root)/'mail-outbox',settings,**kwargs)
