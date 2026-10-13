"""Named research profiles and conservative weekly collection admission.

This schedules saved-artifact collection, not the deferred weekly trend report.
Unknown submissions and access challenges hold the cycle for explicit recovery.
"""
import datetime as dt
import re
from .controller import phrase
from .storage import Guard, digest, event, identity, now, read, write


def stamp(value):
    result=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('Aware cycle timestamp required')
    return result


def create(controller,value,instant=None):
    if not isinstance(value,dict) or set(value)!={'name','keywords','shop_ids','limit'}:raise ValueError('Named keywords, shops and limit required')
    name=value['name']
    if not isinstance(name,str) or not 2<=len(name.strip())<=100 or re.search(r'[\x00-\x1f<>]',name):raise ValueError('Readable cycle name required')
    if not isinstance(value['keywords'],list) or not 1<=len(value['keywords'])<=4:raise ValueError('One to four searches per cycle')
    keywords=list(dict.fromkeys(phrase(k) for k in value['keywords']))
    if not isinstance(value['shop_ids'],list) or len(value['shop_ids'])>5 or any(not isinstance(s,str) or not re.fullmatch('[0-9]{1,20}',s) for s in value['shop_ids']):raise ValueError('Up to five numeric shop IDs')
    if value['limit'] is not None and (type(value['limit']) is not int or not 1<=value['limit']<=100000):raise ValueError('Invalid result cap')
    current=instant or dt.datetime.now(dt.timezone.utc)
    parameters={'niches':[{'category':name.strip(),'keywords':k} for k in keywords],'shop_ids':list(dict.fromkeys(value['shop_ids'])),
                'limit':value['limit'],'exclude_fetched_listings':False,'exclude_fetched_shops':False}
    paths=len(keywords)*max(1,len(parameters['shop_ids']))
    bounds={'max_requests':100,'max_pages':min(10,80//paths),'max_shops':20}
    manifest={'name':name.strip(),'parameters':parameters,'bounds':bounds}
    key=digest(manifest);path=controller.root/'cycles'/(key+'.json')
    with Guard(controller.root):
        if path.exists():return read(path)
        row={'cycle_id':key,'manifest':manifest,'manifest_sha256':digest(manifest),'status':'active','cadence':'daily','manual_override':None,
             'created_at':current.isoformat(),'next_due_at':(current+dt.timedelta(days=1)).isoformat(),'observations':[],
             'exhaustion':{'detected':False,'reason':'Insufficient complete stable history'},'weekly_trend_report_enabled':False}
        write(path,row);event(controller.root,'cycle_created',key,{'name':manifest['name'],'manifest_sha256':row['manifest_sha256']})
        return row


def decide(controller,key,value,instant=None):
    identity(key)
    if not isinstance(value,dict) or set(value)!={'action','manifest_sha256'} or value['action'] not in ('auto','daily','weekly','pause','finalize','reconcile'):raise ValueError('Invalid cycle operation')
    if value['action']=='reconcile':
        row=read(controller.root/'cycles'/(key+'.json'))
        if value['manifest_sha256']!=row['manifest_sha256']:raise ValueError('Cycle profile changed')
        job=row.get('pending_job')
        if not job:raise ValueError('No reserved cycle job')
        path=controller.root/'cycle-jobs'/(job+'.json');receipt=read(path)
        result=controller.send_job(receipt['request'],lookup=True)
        if result.get('request_sha256')!=digest(receipt['request']):raise ValueError('Collector saved request checksum mismatch')
        from .storage import run_identity
        run_identity(result.get('run_id'))
        with Guard(controller.root):
            row=read(controller.root/'cycles'/(key+'.json'))
            receipt.update(status='submitted',result=result,reconciled_at=now());write(path,receipt)
            if row['status']=='submission_unknown':row['status']='active'
            write(controller.root/'cycles'/(key+'.json'),row);event(controller.root,'cycle_submission_reconciled',key,{'job_id':job,'source_calls':0})
            return row
    with Guard(controller.root):
        path=controller.root/'cycles'/(key+'.json');row=read(path)
        if value['manifest_sha256']!=row['manifest_sha256']:raise ValueError('Cycle profile changed')
        current=instant or dt.datetime.now(dt.timezone.utc)
        if value['action']=='pause':row['status']='paused'
        elif value['action']=='finalize':
            if row['status'] in ('submission_unknown','paused_access_challenge'):raise ValueError('Reconcile saved source outcome before finalizing')
            row.update(status='finalized',cadence='weekly',manual_override='weekly',finalized_at=current.isoformat())
        else:
            if row['status'] in ('submission_unknown','paused_access_challenge'):raise ValueError('Reconcile saved source outcome before resuming')
            row.update(status='active',manual_override=None if value['action']=='auto' else value['action'])
            row['cadence']=row['manual_override'] or ('weekly' if row['exhaustion']['detected'] else 'daily')
        if value['action']!='pause':row['next_due_at']=(current+dt.timedelta(days=7 if row['cadence']=='weekly' else 1)).isoformat()
        write(path,row);event(controller.root,'cycle_decided',key,value);return row


def observe(controller,payload):
    if payload.get('status')!='completed':return
    source,sha=controller.source_snapshot(payload['source_run_id'])
    if payload.get('source',{}).get('input_sha256')!=sha:raise ValueError('Cycle source checksum mismatch')
    key=(source.get('lineage') or {}).get('cycle_id')
    if not key:return
    identity(key)
    with Guard(controller.root):
        path=controller.root/'cycles'/(key+'.json');row=read(path);parameters=row['manifest']['parameters'];settings=source.get('settings') or {}
        if any(settings.get(k)!=v for k,v in parameters.items()):return
        if source.get('manifest_sha256')!=row['manifest_sha256']:return
        if any(o['source_run_id']==source['run_id'] for o in row['observations']):return
        queries=source.get('queries') or []
        def words(text):return set(re.findall(r'[^\W\d_]{2,}',text.casefold()))
        scopes=[words(n['keywords'])-set('printable print digital download downloads instant file files pdf png jpg'.split()) for n in parameters['niches']]
        scopes=[s for s in scopes if s]
        listings=[r for q in queries for r in q.get('listings',[]) if r.get('digital') is True and (not scopes or any(s<=words((r.get('title') or '')+' '+' '.join(r.get('tags') or [])+' '+(r.get('description') or '')) for s in scopes))]
        # All query paths must be represented, not just one completed page.
        expected={(q['keywords'],s) for q in parameters['niches'] for s in (parameters['shop_ids'] or [None])}
        actual={((q.get('niche') or {}).get('keywords'),str(q['shop_id']) if q.get('shop_id') is not None else None) for q in queries}
        complete=bool(queries) and expected==actual and all(q.get('collection_complete') is True for q in queries)
        suggestions=sorted({' '.join(r.get('keywords','').casefold().split()) for r in payload.get('report',{}).get('recommendations',[]) if isinstance(r.get('keywords'),str) and r['keywords'].strip()})
        observation={'source_run_id':source['run_id'],'source_sha256':sha,'at':source['finished_at'],'complete':complete,
                     'listing_ids':sorted({str(r['listing_id']) for r in listings}),
                     'shop_ids':sorted({str(r['shop_id']) for r in listings if r.get('shop_id')}),'suggestions':suggestions}
        folder=controller.root/'cycle-observations'/key;target=folder/(source['run_id']+'.json')
        if target.exists():
            if read(target)!=observation:raise ValueError('Saved cycle observation collision')
        else:write(target,observation)
        from .storage import run_identity
        observations=[o if 'listing_ids' in o else read(folder/(run_identity(o['source_run_id'])+'.json')) for o in row['observations']]+[observation]
        observations.sort(key=lambda o:stamp(o['at']))
        known=set();shops=set();points=[]
        for observation in observations:
            ids=set(observation['listing_ids']);sellers=set(observation['shop_ids'])
            points.append({**observation,'new_listing_fraction':len(ids-known)/max(1,len(ids)),
                           'new_shop_fraction':len(sellers-shops)/max(1,len(sellers))})
            if observation['complete']:known|=ids;shops|=sellers
        # Keep the profile small; identity sets live in immutable per-run files.
        row['observations']=[{k:v for k,v in point.items() if k not in ('listing_ids','shop_ids')} | {
            'listing_count':len(point['listing_ids']),'shop_count':len(point['shop_ids'])} for point in points]
        recent=[]
        for point in reversed(points):
            recent.insert(0,point)
            if len({o['at'][:10] for o in recent})>=3 and (stamp(recent[-1]['at'])-stamp(recent[0]['at'])).total_seconds()>=7*86400:break
        exhausted=(len(recent)>=3 and all(o['complete'] and o['listing_ids'] and o['suggestions'] and o['new_listing_fraction']<=.02 and o['new_shop_fraction']<=.02 for o in recent)
                   and len({o['at'][:10] for o in recent})>=3 and (stamp(recent[-1]['at'])-stamp(recent[0]['at'])).total_seconds()>=7*86400
                   and all(o['suggestions']==recent[0]['suggestions'] for o in recent))
        row['exhaustion']={'detected':exhausted,'reason':'At least three complete low-novelty stable assessments spanning seven days' if exhausted else 'Insufficient complete stable low-novelty evidence',
                           'recent':[{'source_run_id':o['source_run_id'],'complete':o['complete'],'new_listing_fraction':o['new_listing_fraction'],'new_shop_fraction':o['new_shop_fraction']} for o in recent]}
        desired=row['manual_override'] or ('weekly' if exhausted else 'daily')
        if desired!=row['cadence']:
            row['cadence']=desired;row['next_due_at']=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=7 if desired=='weekly' else 1)).isoformat()
            event(controller.root,'cycle_cadence_changed',key,{'cadence':desired,'automatic':True,'evidence':row['exhaustion']})
        write(path,row)


def tick(controller,submit,instant=None):
    if not controller.settings['execution_enabled']:return []
    current=instant or dt.datetime.now(dt.timezone.utc);results=[]
    for path in sorted((controller.root/'cycles').glob('*.json')):
        with Guard(controller.root):
            row=read(path)
            if row['status'] not in ('active','finalized'):continue
            # Resolve the preceding reserved collection before admitting another.
            if row.get('pending_job'):
                receipt=read(controller.root/'cycle-jobs'/(row['pending_job']+'.json'))
                run=receipt.get('result',{}).get('run_id')
                if not run:continue
                from .storage import run_identity
                run_identity(run);saved=controller.source/run/'snapshot.json'
                if not saved.exists():continue
                snapshot=read(saved,100_000_000)
                if not snapshot.get('finished_at'):continue
                responses=(snapshot.get('queries') or [])+(snapshot.get('shops') or [])
                if any(r.get('http_status') in (401,403,429) for r in responses):
                    row.update(status='paused_access_challenge',challenge_run_id=run);write(path,row);continue
                row.pop('pending_job');write(path,row)
            if current<stamp(row['next_due_at']):continue
            slot=row['next_due_at'];key=digest({'cycle_id':row['cycle_id'],'slot':slot});receipt=controller.root/'cycle-jobs'/(key+'.json')
            if receipt.exists():continue
            request={'schema_version':1,'job_id':key,'manifest_sha256':row['manifest_sha256'],'kind':'cycle_search',
                     'lineage':{'root_cycle_id':row['cycle_id'],'parent_run_id':row['cycle_id'],'cycle_id':row['cycle_id'],'iteration':0},
                     'parameters':row['manifest']['parameters'],'bounds':row['manifest']['bounds'],
                     'approval':{'manifest_sha256':row['manifest_sha256'],'reviewed_by':'named cycle operator','expires_at':(current+dt.timedelta(hours=23)).isoformat()}}
            write(receipt,{'status':'submitting','slot':slot,'request':request,'automatic_retry':False})
            row['pending_job']=key;row['next_due_at']=(current+dt.timedelta(days=7 if row['cadence']=='weekly' else 1)).isoformat();write(path,row)
        try:result=submit(request);status='submitted'
        except Exception as error:result={'error_type':type(error).__name__};status='submission_unknown'
        with Guard(controller.root):
            write(receipt,{'status':status,'slot':slot,'request':request,'result':result,'automatic_retry':False})
            if status=='submission_unknown':row=read(path);row['status']=status;write(path,row)
        results.append(key)
    return results
