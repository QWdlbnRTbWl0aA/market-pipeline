"""Reviewed cohorts with independent bounded schedules, not analyzer configuration writes."""
import datetime as dt
from zoneinfo import ZoneInfo
from .storage import digest, event, Guard, identity, now, read, write, run_identity


def prepare(controller, market_report):
    payload = read(market_report,5_000_000)
    if payload.get('service') != 'market_insights' or payload.get('status') != 'completed': raise ValueError('Successful saved market analysis required')
    source, sha = controller.source_snapshot(payload['source_run_id'])
    if payload.get('source',{}).get('input_sha256') != sha: raise ValueError('Source provenance mismatch')
    rows = {str(r['listing_id']): r for q in source['queries'] for r in q.get('listings',[])}
    selected = []
    for row in payload.get('report',{}).get('recommendations',[]):
        for sample in row.get('evidence_excerpts',[]):
            key = str(sample.get('listing_id',sample.get('id',''))).removeprefix('etsy:listing:')
            if key not in rows: raise ValueError('Unknown tracked citation')
            if key not in selected and rows[key].get('digital') is True: selected.append(key)
    selected = selected[:10];shops=list(dict.fromkeys(str(rows[k]['shop_id']) for k in selected if rows[k].get('shop_id')))[:5]
    selected=[k for k in selected if str(rows[k].get('shop_id')) in shops]
    if not selected or not shops: raise ValueError('No supported saved cohort')
    manifest={'schema_version':1,'source_run_id':source['run_id'],'source_sha256':sha,'market_delivery_id':payload['delivery_id'],
              'listing_ids':selected,'shop_ids':shops,'days':None,'daily_time':'09:30','timezone':'Asia/Jerusalem',
              'requests_per_day':len(selected)+len(shops),'maximum_requests':None,'capture_images':False,
              'rationale':'Citation-matched digital listings from saved candidate groups; a disclosed observation cohort, not verified winners.',
              'trend_gate':{'minimum_comparable_observations':3,'minimum_span_days':7,'preferred_span_days':None},
              'created_at':now()}
    key=digest({k:v for k,v in manifest.items() if k!='created_at'});target=controller.root/'cohorts'/(key+'.json')
    if target.exists():return read(target)
    row={'cohort_id':key,'manifest':manifest,'manifest_sha256':digest(manifest),'status':'awaiting_approval','approval':None}
    with Guard(controller.root):write(controller.root/'cohorts'/(key+'.json'),row);event(controller.root,'cohort_proposed',key,{'manifest_sha256':row['manifest_sha256']})
    return row


def decide(controller,key,action,sha,reviewer):
    identity(key)
    if action not in ('approve','pause','cancel') or not isinstance(reviewer,str) or not reviewer.strip():raise ValueError('Explicit cohort decision required')
    with Guard(controller.root):
        path=controller.root/'cohorts'/(key+'.json');row=read(path)
        if sha!=row['manifest_sha256']:raise ValueError('Review exact cohort/bounds')
        if action=='approve':
            if row['status']=='active':return row
            if row.get('approval'):raise ValueError('Paused cohort needs a new manifest; do not reset its observation window')
            m=row['manifest'];local=dt.datetime.now(ZoneInfo(m['timezone']));start=local.date()+dt.timedelta(days=1)
            row['approval']={'by':reviewer[:100],'at':now(),'manifest_sha256':sha,'start_day':start.isoformat(),'end_day':(start+dt.timedelta(days=m['days']-1)).isoformat() if m['days'] is not None else None}
        row['status']={'approve':'active','pause':'paused','cancel':'cancelled'}[action]
        write(path,row);event(controller.root,'cohort_decided',key,{'action':action,'manifest_sha256':sha,'by':reviewer[:100]});return row


def tick(controller, submit, instant=None):
    if not controller.settings['execution_enabled']:return []
    results=[]
    for path in sorted((controller.root/'cohorts').glob('*.json')):
        with Guard(controller.root):
            row=read(path)
            if row['status']!='active':continue
            # A saved challenge ends admissions for this cohort, including later
            # days. Restarting the controller must not retry an access challenge.
            challenged=[]
            for receipt_path in (controller.root/'tracking-jobs').glob('*.json'):
                receipt_value=read(receipt_path)
                if receipt_value.get('request',{}).get('lineage',{}).get('cohort_id')!=row['cohort_id']:continue
                run_id=receipt_value.get('result',{}).get('run_id')
                if not run_id:continue
                try:
                    run_identity(run_id);snapshot_path=controller.source/run_id/'snapshot.json'
                    if snapshot_path.resolve().parent.parent!=controller.source:raise ValueError('Source escape')
                    saved=read(snapshot_path,100_000_000)
                except (FileNotFoundError,ValueError):continue
                responses=saved.get('queries',[])+saved.get('tracked_listings',[])+saved.get('shops',[])
                if any(r.get('http_status') in (401,403,429) for r in responses):challenged.append(run_id)
            if challenged:
                row.update(status='paused_access_challenge',challenge_run_ids=challenged)
                write(path,row);event(controller.root,'cohort_access_challenge',row['cohort_id'],{'run_ids':challenged});continue
            m=row['manifest'];local=(instant or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(m['timezone']));day=local.date().isoformat();approval=row['approval']
            if approval.get('end_day') and day>approval['end_day']:
                row['status']='completed_window';write(path,row);continue
            if day<approval['start_day'] or local.time().replace(tzinfo=None)<dt.time.fromisoformat(m['daily_time']):continue
            key=digest({'cohort_id':row['cohort_id'],'day':day});receipt=controller.root/'tracking-jobs'/(key+'.json')
            if receipt.exists():continue # Unknown outcome remains reserved, never resent.
            expires=(dt.datetime.combine(local.date(),dt.time(23,59),local.tzinfo)).isoformat()
            request={'schema_version':1,'job_id':key,'manifest_sha256':row['manifest_sha256'],'kind':'tracking',
                     'lineage':{'root_cycle_id':m['source_run_id'],'parent_run_id':m['source_run_id'],'cohort_id':row['cohort_id'],'iteration':0},
                     'parameters':{'listing_ids':m['listing_ids'],'shop_ids':m['shop_ids']},
                     'bounds':{'max_requests':m['requests_per_day'],'max_pages':1,'max_shops':0},
                     'approval':{'manifest_sha256':row['manifest_sha256'],'reviewed_by':approval['by'],'expires_at':expires}}
            write(receipt,{'status':'submitting','day':day,'request':request,'reserved_requests':m['requests_per_day']})
        try:result=submit(request);status='submitted'
        except Exception as e:result={'error_type':type(e).__name__};status='submission_unknown'
        write(receipt,{'status':status,'day':day,'request':request,'result':result,'automatic_retry':False});results.append(key)
    return results
