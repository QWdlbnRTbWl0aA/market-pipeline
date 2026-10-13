"""Versioned market assessments, novelty and age-aware evidence qualification.

Observations support a business-validation decision, never invented listing sales.
All input is saved data; this module has no credentials or network transport.
"""
from collections import Counter
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
from .security import reject_secrets

VERSION='commercial-assessments-v1'
DEFAULT={'enabled':True,'initial_candidates':80,'maximum_opportunities':10,'minimum_target':5,
         'minimum_shops':3,'minimum_active_sales_shops':2,'minimum_history_days':7,
         'minimum_shop_age_days':90,'minimum_inventory_coverage':.8,'minimum_content_similarity':.35,
         'minimum_inventory_sales_per_year':1.0,'maximum_cheap_share':.6,'maximum_shop_share':.5,
         'assessment_half_life_days':30,'maximum_images':10,'minimum_known_price_share':.8,'minimum_query_match_share':.8}


def instant(value):
    try:
        value=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        return value if value.tzinfo else None
    except (ValueError,TypeError,AttributeError):return None


def key(candidate):
    tokens=sorted(set(re.findall(r'[^\W\d_]+',candidate['phrase'].casefold())))
    return hashlib.sha256(json.dumps(tokens,ensure_ascii=False).encode()).hexdigest()


def policy(value=None):
    value={**DEFAULT,**(value or {})}
    if set(value)!=set(DEFAULT) or type(value['enabled']) is not bool:raise ValueError('Invalid opportunity policy')
    for name in ('initial_candidates','maximum_opportunities','minimum_target','minimum_shops','minimum_active_sales_shops','minimum_history_days','minimum_shop_age_days','assessment_half_life_days','maximum_images'):
        if type(value[name]) is not int or not 1<=value[name]<=200:raise ValueError('Invalid opportunity bound')
    if not 5<=value['maximum_opportunities']<=10 or not 1<=value['minimum_target']<=value['maximum_opportunities'] or value['maximum_images']>10:raise ValueError('Invalid report/image bounds')
    for name in ('minimum_inventory_coverage','minimum_content_similarity','maximum_cheap_share','maximum_shop_share','minimum_known_price_share','minimum_query_match_share'):
        if type(value[name]) not in (float,int) or not 0<=value[name]<=1:raise ValueError('Invalid qualification threshold')
    if type(value['minimum_inventory_sales_per_year']) not in (float,int) or not math.isfinite(value['minimum_inventory_sales_per_year']) or value['minimum_inventory_sales_per_year']<0:raise ValueError('Invalid shop activity threshold')
    return value


def previous(root, dataset):
    as_of=instant(dataset['metadata'].get('refresh_as_of') or dataset['metadata'].get('finished_at'))
    current=dataset['metadata'].get('source_run_id');rows=[]
    for path in (Path(root)/'market-assessments').glob('*.json'):
        if path.name=='offers.json':continue
        if path.is_symlink() or path.stat().st_size>20_000_000:raise ValueError('Unsafe assessment artifact')
        row=json.loads(path.read_text());reject_secrets(row)
        stamp=instant(row.get('source_finished_at'))
        if stamp and as_of and stamp<as_of and row.get('source_run_id')!=current:rows.append(row)
    # Bootstrap old completed report history without altering its artifacts.
    seen={r['source_run_id'] for r in rows}
    for path in (Path(root)/'market_insights').glob('*/outbound.json'):
        if path.is_symlink() or path.stat().st_size>20_000_000:continue
        payload=json.loads(path.read_text());reject_secrets(payload)
        source=payload.get('source_run_id');stamp=instant(payload.get('finished_at'))
        if not as_of or not stamp or stamp>=as_of or source==current or source in seen or payload.get('status')!='completed':continue
        candidates=[]
        for rec in payload.get('report',{}).get('recommendations',[]):
            phrase=rec.get('facts',{}).get('phrase')
            if phrase:candidates.append({'key':key({'phrase':phrase}),'phrase':phrase,'listing_ids':[e.get('id') or e.get('listing_id') for e in rec.get('evidence_excerpts',[])],
                'score':None,'qualified':False,'suggested':True,'legacy':True})
        rows.append({'source_run_id':source,'source_finished_at':payload['finished_at'],'candidates':candidates});seen.add(source)
    latest={}
    for row in rows:
        source=row['source_run_id']
        if source not in latest or row.get('assessed_at',row['source_finished_at'])>latest[source].get('assessed_at',latest[source]['source_finished_at']):latest[source]=row
    return sorted(latest.values(),key=lambda r:r['source_finished_at'])


def memory(candidate, prior, as_of, settings):
    identity=key(candidate);ids=set(candidate['listing_ids']);matches=[];duplicate=False
    for report in prior:
        stamp=instant(report['source_finished_at'])
        for row in report['candidates']:
            old=set(row.get('listing_ids',[]));overlap=len(ids&old)/max(1,len(ids|old))
            if row['key']!=identity and overlap<.85:continue
            days=max(0,(as_of-stamp).total_seconds()/86400)
            matches.append({'source_run_id':report['source_run_id'],'at':report['source_finished_at'],'weight':2**(-days/settings['assessment_half_life_days']),
                            'score':row.get('score'),'qualified':row.get('qualified',False),'suggested':row.get('suggested',False)})
            duplicate|=row.get('suggested',False)
    scored=[r for r in matches if type(r['score']) in (float,int)]
    weighted=sum(r['score']*r['weight'] for r in scored)/sum(r['weight'] for r in scored) if scored else None
    return {'assessments':matches,'weighted_prior_score':weighted,'previously_suggested':duplicate,
            'previous_assessments':len({r['source_run_id'] for r in matches}),'weight_method':'Exponential recency decay of observed assessments; not a sales prediction'}


def tokens(row):
    return set(re.findall(r'[^\W\d_]{2,}',(row.get('title','')+' '+' '.join(row.get('tags') or [])).casefold()))-set('printable digital download instant file pdf png template templates'.split())


def qualify(candidate,dataset,prior,settings):
    as_of=instant(dataset['metadata'].get('refresh_as_of') or dataset['metadata'].get('finished_at'))
    if not as_of:raise ValueError('Finalized as-of time required')
    identities=set(candidate['listing_ids'])
    rows=[r for r in dataset['records'] if r['id'] in identities];shops=[]
    for seller in sorted({r['seller_id'] for r in rows if r['seller_id']}):
        group=[r for r in rows if r['seller_id']==seller];saved=[r for r in dataset['records'] if r['seller_id']==seller]
        observations=[s for s in dataset['metadata'].get('shops',[]) if str(s['shop_id'])==seller]
        for report in dataset['metadata'].get('history',{}).get('related_observations',[]):observations.extend(s for s in report['shops'] if str(s['shop_id'])==seller)
        by_time={};conflict=False
        for row in observations:
            stamp=instant(row.get('observed_at'));count=row.get('transaction_sold_count')
            if stamp and stamp<=as_of and type(count) in (int,float) and math.isfinite(count) and count>=0:
                if stamp in by_time and any(by_time[stamp].get(k)!=row.get(k) for k in ('transaction_sold_count','listing_active_count','created_at')):conflict=True
                by_time.setdefault(stamp,row)
        ordered=sorted(by_time.items());latest=ordered[-1][1] if ordered else {}
        active=latest.get('listing_active_count');coverage=min(1,len(group)/active) if type(active) in (int,float) and active>0 else None
        created=instant(latest.get('created_at'));age=(as_of-created).total_seconds()/86400 if created and created<=as_of else None
        comparisons=[len(tokens(a)&tokens(b))/max(1,len(tokens(a)|tokens(b))) for i,a in enumerate(group[:30]) for b in group[:30][i+1:]]
        similarity=sum(comparisons)/len(comparisons) if comparisons else 0
        categories=Counter(r['category'] for r in group if r.get('category'));consistent=max(categories.values())/len(group) if categories else 0
        days=(ordered[-1][0]-ordered[0][0]).total_seconds()/86400 if len(ordered)>1 else 0
        reset=any(b['transaction_sold_count']<a['transaction_sold_count'] for (_,a),(_,b) in zip(ordered,ordered[1:]))
        growth=latest.get('transaction_sold_count',0)-ordered[0][1]['transaction_sold_count'] if len(ordered)>1 and not reset else None
        intensity=growth/days*365.25/active if growth is not None and days>=settings['minimum_history_days'] and type(active) in (int,float) and active>0 else None
        # Historical similarity coverage is required, not just today's inventory.
        historic=[]
        for report in dataset['metadata'].get('history',{}).get('related_observations',[]):
            profile=report.get('shop_inventory_profiles',{}).get(seller,[])
            active_old=next((s.get('listing_active_count') for s in report['shops'] if str(s['shop_id'])==seller),None)
            current_by_id={r['id']:r for r in group}
            matched=[r for r in profile if r['id'] in current_by_id and r.get('digital') is True and r.get('category')==current_by_id[r['id']]['category']
                     and len(tokens(r)&tokens(current_by_id[r['id']]))/max(1,len(tokens(r)|tokens(current_by_id[r['id']])))>=settings['minimum_content_similarity']]
            if type(active_old) in (int,float) and active_old>0:historic.append(min(1,len(matched)/active_old))
        historical_coverage=min(historic) if historic else None
        strong=(not conflict and len(ordered)>=3 and days>=settings['minimum_history_days'] and growth is not None and growth>0 and
                age is not None and age>=settings['minimum_shop_age_days'] and coverage is not None and coverage>=settings['minimum_inventory_coverage'] and
                historical_coverage is not None and historical_coverage>=settings['minimum_inventory_coverage'] and similarity>=settings['minimum_content_similarity'] and
                consistent>=.8 and intensity is not None and intensity>=settings['minimum_inventory_sales_per_year'])
        shops.append({'shop_id':seller,'shop_age_days':age,'observations':len(ordered),'observed_span_days':days,'actual_shop_counter_growth':growth,
            'active_listings':active,'saved_listings':len(saved),'candidate_listings':len(group),'inventory_coverage_lower_bound':coverage,
            'historical_inventory_coverage_lower_bound':historical_coverage,'content_similarity':similarity,'category_consistency':consistent,
            'shop_inventory_normalized_activity_per_year':intensity,'counter_reset':reset,'duplicate_timestamp_conflicts':conflict,'qualified_group_sales_context':strong,
            'scope':'Whole-shop transactions relative to current inventory; neither allocated listing sales nor group purchase counts'})
    histories=dataset['metadata'].get('history',{}).get('listing_series',{})
    supported=[r for r in rows if histories.get(r['id'],{}).get('trend_status')=='engagement_proxy_ready']
    positive=[r for r in supported if any(v.get('change',0)>0 for d in histories[r['id']].get('intervals',[]) for v in d.get('metrics',{}).values() if v.get('change') is not None)]
    positive_shops=len({r['seller_id'] for r in positive});sales_shops=sum(s['qualified_group_sales_context'] for s in shops)
    known_prices=[p for p in candidate['prices'].values() if p.get('reference_price') is not None]
    denominator=sum(p['observations'] for p in known_prices);cheap=sum(p['at_or_below_reference_price'] for p in known_prices)/denominator if denominator else None
    known_price_share=denominator/max(1,len(rows))
    from .research import words,STOP
    searches=[set(words(n.get('keywords','')))-STOP for n in (dataset['metadata'].get('query_context',{}).get('niches') or [])]
    searches=[s for s in searches if s]
    query_match_share=sum(not searches or any(s<=set(words(r['title']+' '+' '.join(r['tags'])+' '+r['description'])) for s in searches) for r in rows)/max(1,len(rows))
    reasons=[]
    if candidate['shop_count']<settings['minimum_shops']:reasons.append('insufficient_shop_diversity')
    if sales_shops<settings['minimum_active_sales_shops']:reasons.append('insufficient_age_history_activity_or_similar_inventory_sales_context')
    if positive_shops<settings['minimum_active_sales_shops']:reasons.append('insufficient_multi_shop_listing_engagement_history')
    if candidate['largest_shop_share'] is None or candidate['largest_shop_share']>settings['maximum_shop_share']:reasons.append('single_shop_concentration')
    if cheap is None or cheap>settings['maximum_cheap_share']:reasons.append('unknown_or_crowded_cheap_price_position')
    if known_price_share<settings['minimum_known_price_share']:reasons.append('insufficient_comparable_price_coverage')
    if query_match_share<settings['minimum_query_match_share']:reasons.append('insufficient_saved_content_query_match')
    prior_context=memory(candidate,prior,as_of,settings)
    components={'listing_trend':min(1,positive_shops/3),'shop_sales_context':min(1,sales_shops/3),
                'diversity':min(1,candidate['shop_count']/5)*(1-(candidate['largest_shop_share'] or 0)),
                'price_position':1-cheap if cheap is not None else 0,'history_depth':min(1,len(supported)/max(1,len(rows)))}
    current=sum(components[k]*w for k,w in [('listing_trend',.25),('shop_sales_context',.30),('diversity',.20),('price_position',.10),('history_depth',.15)])
    score=.7*current+.3*prior_context['weighted_prior_score'] if prior_context['weighted_prior_score'] is not None else current
    return {'qualified':not reasons,'hold_reasons':reasons,'score':round(score,5),'current_score':round(current,5),
            'score_delta':round(score-prior_context['weighted_prior_score'],5) if prior_context['weighted_prior_score'] is not None else None,
            'score_components':components,'score_scope':'Transparent prioritization heuristic, not probability of sales or profitability',
            'shops':shops,'positive_listing_history_shops':positive_shops,'strong_sales_context_shops':sales_shops,'cheap_share':cheap,
            'known_price_share':known_price_share,'query_content_match_share':query_match_share,'assessment_history':prior_context,
            'listing_sales':None,'verified_listing_purchase_demand':False,'marketplace_thin_supply_verified':False}
