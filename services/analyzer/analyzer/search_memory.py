"""Saved-query novelty, without scheduler writes or source requests."""
import hashlib
import json
from .saved_intake import SavedCollectionIntake, discover
from .assessments import instant
from .normalize import normalize
from .research import words,STOP


def observation(batch):
    normalized=normalize(batch);records=normalized['records']
    context=batch.metadata.get('query_context',{})
    scopes=[set(words(n.get('keywords','')))-STOP for n in (context.get('niches') or [])]
    scopes=[s for s in scopes if s]
    records=[r for r in records if r.get('digital') is True and (not scopes or any(s<=set(words(r['title']+' '+' '.join(r['tags'])+' '+r['description'])) for s in scopes))]
    scope=hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    coverage=batch.metadata.get('query_coverage') or []
    complete=bool(coverage) and all(q.get('collection_complete') is True for q in coverage)
    expected={(n.get('keywords'),str(s) if s is not None else None) for n in (context.get('niches') or []) for s in (context.get('shop_ids') or [None])}
    actual={((q.get('niche') or {}).get('keywords'),str(q['shop_id']) if q.get('shop_id') is not None else None) for q in coverage}
    complete &= expected==actual and not normalized['dqa']['rejected_records'] and not any(r['conflicting'] for r in normalized['dqa']['duplicate_records'])
    complete &= context.get('exclude_fetched_listings') is False and context.get('exclude_fetched_shops') is False
    return {'source_run_id':batch.metadata['source_run_id'],'at':batch.metadata['finished_at'],'scope_sha256':scope,
            'complete':complete,'listing_ids':sorted({r['id'] for r in records if r.get('digital') is True}),
            'shop_ids':sorted({r['seller_id'] for r in records if r.get('digital') is True and r.get('seller_id')})}


def analyze(root,batch):
    current=observation(batch);prior=[];as_of=instant(current['at'])
    for run in discover(root):
        if run==current['source_run_id']:continue
        other=SavedCollectionIntake(root,run).read();row=observation(other)
        if row['scope_sha256']==current['scope_sha256'] and instant(row['at'])<as_of:prior.append(row)
    prior.sort(key=lambda r:r['at']);known=set();shops=set();points=[]
    for row in prior+[current]:
        ids=set(row['listing_ids']);sellers=set(row['shop_ids'])
        points.append({k:v for k,v in row.items() if k not in ('listing_ids','shop_ids')} | {
            'relevant_listings':len(ids),'shops':len(sellers),'new_listing_fraction':len(ids-known)/max(1,len(ids)),
            'new_shop_fraction':len(sellers-shops)/max(1,len(sellers))})
        if row['complete']:known|=ids;shops|=sellers
    recent=[]
    for point in reversed(points):
        recent.insert(0,point)
        if len({r['at'][:10] for r in recent})>=3 and (instant(recent[-1]['at'])-instant(recent[0]['at'])).total_seconds()>=7*86400:break
    settled=(len(recent)>=3 and all(r['complete'] and r['relevant_listings']>0 and r['new_listing_fraction']<=.02 and r['new_shop_fraction']<=.02 for r in recent)
             and (instant(recent[-1]['at'])-instant(recent[0]['at'])).total_seconds()>=7*86400
             and len({r['at'][:10] for r in recent})>=3)
    return {'schema_version':1,'scope_sha256':current['scope_sha256'],'observations':points,
            'low_novelty_evidence_ready':settled,'recommendation':'consider_weekly_only_if_assessments_stable' if settled else 'continue_daily',
            'automatic_settings_changes':False,'notes':'Complete comparable searches only; truncated or exclusion-based results cannot prove exhaustion.'}
