"""Rebuildable, as-of candidate pool from immutable saved collection artifacts.

No source clients, credentials or inference. A pool is not a fresh market census.
"""
import copy
import hashlib
import json
from pathlib import Path
from .saved_intake import SavedCollectionIntake
from .normalize import normalize
from .research import words

VERSION = 'saved-candidate-pool-v1'
FORMAT = set('printable print digital download downloads instant file files pdf png jpg'.split())


def matches(row, context):
    if row.get('digital') is not True:return False
    shops = context.get('shop_ids') or []
    if shops and row.get('seller_id') not in {str(s) for s in shops}:return False
    parameters = context.get('search_parameters') or {}
    for name,compare in [('min_price',lambda p,b:p>=b),('max_price',lambda p,b:p<=b)]:
        if parameters.get(name) is not None:
            if row.get('price') is None or not compare(row['price'],parameters[name]):return False
    content = set(words(row['title']+' '+' '.join(row['tags'])+' '+row['description']))
    niches = context.get('niches') or []
    # A missing legacy query intent cannot justify importing arbitrary niches.
    return any((n.get('keywords') or n.get('taxonomy_id')) and
               (not n.get('taxonomy_id') or row.get('category')=='taxonomy:'+str(n['taxonomy_id'])) and
               (set(words(n.get('keywords','')))-FORMAT)<=content for n in niches)


def extend(batch, root, finished, floor):
    from .history import instant
    context = batch.metadata.get('query_context') or {}
    current = batch.metadata['source_run_id']; sources=[];issues=[];batches=[];normalization={}
    for directory in sorted(Path(root).iterdir()):
        if not directory.is_dir() or directory.is_symlink() or directory.name==current:continue
        try:
            prior=SavedCollectionIntake(root,directory.name).read()
            stamp=instant(prior.metadata['finished_at'])
            if stamp is None or not floor<=stamp<=finished:continue
            batches.append(prior)
        except (ValueError,TypeError,KeyError,OSError) as error:
            issues.append({'run_id':directory.name,'error_type':type(error).__name__})
    # Candidate membership comes from discoveries, not an unrelated tracking job.
    # Identity-matched tracking may subsequently update the selected observations.
    selected={};original_ids={r.get('id') for r in batch.records if isinstance(r,dict)}
    def add(row, source):
        stamp=instant(row.get('observed_at')) or instant(source.metadata['finished_at'])
        if stamp is None or stamp>finished:return
        rank=(stamp,source.metadata['source_run_id']==current,source.metadata['source_run_id'])
        if row['id'] not in selected or rank>selected[row['id']][0]:selected[row['id']]=(rank,row,source)
    for source in batches+[batch]:
        if source.metadata.get('artifact_kind')=='tracking':continue
        cycle=(batch.metadata.get('lineage') or {}).get('cycle_id')
        other_cycle=(source.metadata.get('lineage') or {}).get('cycle_id')
        if cycle and other_cycle and cycle!=other_cycle:continue
        normalized=normalize(source)
        normalization[source.metadata['source_run_id']]={'input_records':normalized['dqa']['input_records'],'accepted_records':normalized['dqa']['accepted_records'],
            'rejected_count':len(normalized['dqa']['rejected_records']),'duplicate_count':len(normalized['dqa']['duplicate_records'])}
        if source is batch and normalized['dqa']['rejected_records'] and not normalized['records']:
            raise ValueError('Current saved records all failed normalization; pooling cannot conceal invalid intake')
        if normalized['dqa']['rejected_records'] or any(d['conflicting'] for d in normalized['dqa']['duplicate_records']):
            issues.append({'run_id':source.metadata['source_run_id'],'error_type':'NormalizationIssues'})
        for row in normalized['records']:
            if source is batch or matches(row,context):add(row,source)
    for source in batches:
        for row in normalize(source)['records']:
            if row['id'] in selected:add(row,source)
    chosen=[];used=set();members=[]
    for identity,(_,row,source) in sorted(selected.items()):
        # A newer saved observation may no longer satisfy the niche, shop or price bounds.
        if identity not in original_ids and not matches(row,context):continue
        row=copy.deepcopy(row);run=source.metadata['source_run_id'];used.add(run)
        row['provenance']={**row.get('provenance',{}),'artifact_run_id':run,'intake_role':'saved_candidate_pool','observation_as_of':row.get('observed_at')}
        for image in row.get('images') or []:
            if isinstance(image,dict) and image.get('local_path') and run!=current:image['artifact_run_id']=run
        chosen.append(row);members.append({'listing_id':identity,'source_run_id':run,'observed_at':row.get('observed_at')})
    sellers={r['seller_id'] for r in chosen if r.get('seller_id')};shop_latest={}
    for source in batches+[batch]:
        for shop in source.metadata.get('shops',[]):
            key=str(shop['shop_id']);stamp=instant(shop.get('observed_at'))
            if key not in sellers or stamp is None or stamp>finished:continue
            rank=(stamp,source.metadata['source_run_id'])
            # Keep conflicting same-time counters for downstream DQA, never hide them.
            if key not in shop_latest or rank[0]>shop_latest[key][0][0]:shop_latest[key]=(rank,[(shop,source)])
            elif rank[0]==shop_latest[key][0][0]:shop_latest[key][1].append((shop,source))
    shops=[]
    for _,observations in shop_latest.values():
        for shop,source in observations:
            shops.append({**shop,'source_run_id':source.metadata['source_run_id']});used.add(source.metadata['source_run_id'])
    for source in batches+[batch]:
        if source.metadata['source_run_id'] in used or any(r.get('id') in selected or r.get('seller_id') in sellers for r in source.records if isinstance(r,dict)):
            sources.append({'run_id':source.metadata['source_run_id'],'input_sha256':source.provenance['input_sha256'],'finished_at':source.metadata['finished_at']})
    batch.records=chosen;batch.metadata['shops']=shops
    manifest={'version':VERSION,'as_of':finished.isoformat(),'query_context':context,'current_run_listing_count':len(original_ids- {None}),
              'pooled_listing_count':len(chosen),'historical_listing_count':sum(r['id'] not in original_ids for r in chosen),
              'shop_count':len(sellers),'sources':sorted(sources,key=lambda s:s['run_id']),'members':members,'issues':issues,
              'source_normalization':normalization,
              'scope':'Latest saved observations matching any current niche and selected shops/bounds; not newly fetched or current marketplace supply.'}
    batch.metadata['saved_pool']=manifest
    return hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
