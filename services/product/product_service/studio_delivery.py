"""Durable delivery of exact saved Product briefs to passive Studio intake only."""
import hashlib
import http.client
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pipeline_mail import write,read
from .core import reject_secrets,clean_environment

DEFAULT={'enabled':False,'endpoint':'http://127.0.0.1:8096/api/library/briefs','max_attempts':5,'retry_seconds':60}


def policy(value=None):
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-set(DEFAULT):raise ValueError('Invalid Studio delivery settings')
    result={**DEFAULT,**value};url=urlsplit(result['endpoint'])
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','::1','localhost') or not url.port or url.path!='/api/library/briefs' or url.query or url.fragment or url.username or url.password:raise ValueError('Only local passive Studio intake is allowed')
    if type(result['enabled']) is not bool or type(result['max_attempts']) is not int or not 1<=result['max_attempts']<=100:raise ValueError('Invalid Studio delivery attempt bound')
    if type(result['retry_seconds']) not in (int,float) or not 1<=result['retry_seconds']<=86400:raise ValueError('Invalid Studio delivery interval')
    return result


def prepare(result,root,settings):
    clean_environment();settings=policy(settings)
    if not settings['enabled']:return []
    root=Path(root).resolve();folder=Path(result['directory']).resolve()
    if not folder.is_relative_to(root):raise ValueError('Product result outside saved root')
    if result.get('status') not in ('completed','completed_drafts'):return []
    paths=([Path(p['directory'])/'product.json' for p in result['products'] if p.get('directory')]
           if isinstance(result.get('products'),list) else sorted(folder.glob('product-*/product.json')))
    queued=[]
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size>900000:raise ValueError('Unsafe or oversized saved Product brief')
        body=path.read_bytes();value=json.loads(body);reject_secrets(value)
        if not isinstance(value,dict) or not (value.get('vision') or value.get('concept')):raise ValueError('Saved Product brief required')
        key=hashlib.sha256(body).hexdigest();outbox=root/'studio-delivery'/key
        if (root/'studio-delivery').is_symlink() or outbox.is_symlink():raise ValueError('Symlink delivery outbox forbidden')
        outbox.mkdir(parents=True,exist_ok=True)
        # Immutable identity is the exact saved brief, not a newly inferred version.
        with (outbox/'.lock').open('a') as lock:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX)
            if any((outbox/name).is_symlink() for name in ('payload.json','delivery.json')):raise ValueError('Symlink delivery artifact forbidden')
            if (outbox/'payload.json').exists():
                if (outbox/'payload.json').read_bytes()!=body:raise ValueError('Studio brief identity collision')
            else:write(outbox/'payload.json',body)
            if not (outbox/'delivery.json').exists():write(outbox/'delivery.json',{'status':'pending','attempts':0,'endpoint':settings['endpoint'],'payload_sha256':key,'source_run_id':result.get('source_run_id')})
        queued.append(key)
    return queued


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def tick(root,settings,transport=None,at=None):
    settings=policy(settings);clean_environment()
    if not settings['enabled']:return []
    at=time.time() if at is None else at;results=[]
    transport=transport or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open
    for directory in sorted((Path(root)/'studio-delivery').glob('*')):
        if directory.is_symlink() or not directory.is_dir():continue
        import fcntl
        with (directory/'.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:continue
            if not (directory/'delivery.json').exists():continue
            if (directory/'delivery.json').is_symlink():raise ValueError('Symlink delivery state forbidden')
            state=read(directory/'delivery.json')
            if state['status'] in ('delivered','permanent_failure','retries_exhausted') or state.get('next_at',0)>at:continue
            if state.get('generation_attempts',state['attempts'])>=settings['max_attempts']:
                state['status']='retries_exhausted';write(directory/'delivery.json',state)
                write(directory/'failure-event.json',{'event_type':'studio_brief_delivery_failed','brief_id':directory.name,'status':state['status'],'attempts':state['attempts'],'recovery':'Explicit delivery-only retry'})
                continue
            state['generation_attempts']=state.get('generation_attempts',state['attempts'])+1
            state['attempts']+=1;write(directory/'delivery.json',state)
            record={'attempt':state['attempts'],'at':at};permanent=False
            try:
                if (directory/'payload.json').is_symlink():raise ValueError('Symlink payload forbidden')
                body=(directory/'payload.json').read_bytes()
                if hashlib.sha256(body).hexdigest()!=state['payload_sha256']:raise ValueError('Saved payload checksum mismatch')
                endpoint=policy({**settings,'endpoint':state['endpoint']})['endpoint']
                request=urllib.request.Request(endpoint,data=body,headers={'Content-Type':'application/json','Idempotency-Key':state['payload_sha256']},method='POST')
                with transport(request,timeout=5) as response:
                    reply=json.loads(response.read(1000001))
                project=reply.get('project') or {}
                if project.get('library_import') is not True or not re.fullmatch('[a-f0-9]{32}',project.get('id','')):raise ValueError('Receiver did not confirm passive library intake')
                state.update(status='delivered',project_id=project['id']);record.update(delivered=True,project_id=project['id'])
            except Exception as error:
                code=getattr(error,'code',None);record.update(delivered=False,error_type=type(error).__name__,http_status=code)
                permanent=(code is not None and code not in (408,425,429) and (not 500<=code<=599 or code in (501,505))) or not isinstance(error,(OSError,http.client.HTTPException))
                state['status']='permanent_failure' if permanent else 'retries_exhausted' if state['generation_attempts']>=settings['max_attempts'] else 'pending'
                state['next_at']=at+settings['retry_seconds']
            write(directory/f'attempt-{state["attempts"]:04d}.json',record)
            write(directory/'delivery.json',state)
            if state['status'] in ('permanent_failure','retries_exhausted'):
                write(directory/'failure-event.json',{'event_type':'studio_brief_delivery_failed','brief_id':directory.name,'status':state['status'],'attempts':state['attempts'],'recovery':'Explicit delivery-only retry; preserve saved payload and all receipts'})
            results.append(state)
    return results


def backfill(root,settings):
    """Queue already-completed local briefs without definition, inference or mail."""
    root=Path(root);queued=[]
    for name in ('studio-outbox','definition-outbox'):
        for state in sorted((root/name).glob('*/state.json')):
            if state.is_symlink() or state.parent.is_symlink():continue
            result=read(state);result['directory']=str(state.parent)
            queued.extend(prepare(result,root,settings))
    return queued


def recover(root,key,settings,reason):
    if not re.fullmatch('[a-f0-9]{64}',key) or not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError('Explicit brief identity and recovery reason required')
    directory=Path(root)/'studio-delivery'/key
    if directory.is_symlink():raise ValueError('Symlink outbox forbidden')
    import fcntl
    with (directory/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);state=read(directory/'delivery.json')
        if state['status'] not in ('permanent_failure','retries_exhausted'):raise ValueError('Only terminal failures can be explicitly recovered')
        write(directory/f'recovery-after-{state["attempts"]:04d}.json',{'prior_state':state,'reason':reason,'at':time.time()})
        state.update(status='pending',generation_attempts=0,next_at=0,endpoint=policy(settings)['endpoint'])
        write(directory/'delivery.json',state)
