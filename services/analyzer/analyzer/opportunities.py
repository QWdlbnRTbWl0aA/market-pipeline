"""History-aware candidate qualification and novel product-team reports."""
import fcntl
import hashlib
import json
from pathlib import Path
from .assessments import VERSION, key, policy, previous, qualify
from .io import write_json, now
from .ports import ModelResponse
from .research import build_evidence, model_request, validate_selection, local_request, validate_local
from .product_briefs import request as brief_request, validate as validate_brief, compact_cross_checks, local_design_selection


def stage(directory,name,model,request):
    folder=directory/('stage-'+name);folder.mkdir(exist_ok=True)
    signature=hashlib.sha256(json.dumps({'system':request.system,'prompt':request.prompt,'schema':request.schema,'images':request.images},sort_keys=True).encode()).hexdigest()
    saved=folder/'request.json'
    if saved.exists() and json.loads(saved.read_text())['fingerprint']!=signature:raise ValueError('Stage inputs changed; create a new recipe job')
    write_json(saved,{'system':request.system,'prompt':request.prompt,'schema':request.schema,'image_count':len(request.images),'fingerprint':signature})
    response=folder/'response.json'
    if response.exists():
        value=json.loads(response.read_text());return ModelResponse(value['text'],{**value['metadata'],'cached_stage':True},value['raw'])
    if (folder/'started.json').exists():raise RuntimeError('Interrupted model outcome; no automatic inference retry')
    write_json(folder/'started.json',{'fingerprint':signature});result=model.generate(request)
    write_json(response,{'text':result.text,'metadata':result.metadata,'raw':result.raw});return result


def summary(assessment):
    return {k:v for k,v in assessment.items() if k not in ('shops','assessment_history')} | {
        'shop_examples':assessment['shops'][:5],
        'assessment_history':{k:v for k,v in assessment['assessment_history'].items() if k!='assessments'},
        'full_evidence_artifact':'candidate-assessments.json'}


def facts(candidate):
    result={k:v for k,v in candidate.items() if k not in ('evidence','listing_ids','shop_observations','performance_cross_check','commercial_assessment')}
    result['commercial_assessment']=summary(candidate['commercial_assessment'])
    result['performance_cross_check']=compact_cross_checks(candidate['performance_cross_check'])
    result['historical_engagement']=result.get('historical_engagement',[])[-3:]
    return result


def analyze(dataset,directory,config,local,cheap,good):
    settings=policy(config.get('opportunities'));root=Path(config['output_root'])/'market-assessments';root.mkdir(exist_ok=True)
    # Serialize cross-run offer reservations, not the independent search-refiner.
    with (root/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return locked(dataset,directory,config,settings,local,cheap,good)


def locked(dataset,directory,config,settings,local,cheap,good):
    evidence=build_evidence(dataset,{**config['research'],'max_candidates':settings['initial_candidates']})
    history=previous(config['output_root'],dataset);assessed=[];novel=[];suppressed=[]
    claims_path=Path(config['output_root'])/'market-assessments'/'offers.json'
    claims=json.loads(claims_path.read_text()).get('offers',{}) if claims_path.exists() else {}
    for candidate in evidence['candidates']:
        assessment=qualify(candidate,dataset,history,settings);candidate['commercial_assessment']=assessment;candidate['opportunity_key']=key(candidate)
        assessed.append({'key':key(candidate),'phrase':candidate['phrase'],'listing_ids':candidate['listing_ids'],
                         'score':assessment['score'],'qualified':assessment['qualified'],'suggested':False,'assessment':assessment})
        if assessment['assessment_history']['previously_suggested'] or (key(candidate) in claims and claims[key(candidate)]['job_id']!=directory.name):suppressed.append(candidate)
        elif assessment['qualified'] or assessment['discovery']['qualified']:novel.append(candidate)
    from collections import Counter
    from .research import words,STOP
    frequencies=Counter(w for r in dataset['records'] for w in set(words(r['title']+' '+' '.join(r['tags']))))
    query_terms=set(words(' '.join(n.get('keywords','') for n in evidence['query_context'].get('niches',[]))))
    common={w for w,n in frequencies.items() if n>=max(1,len(dataset['records'])*.45)}
    def order(candidate):
        a=candidate['commercial_assessment']
        specificity=len(set(words(candidate['phrase']))-query_terms-common-STOP)
        return (not a['qualified'],-min(2,specificity),-a['discovery']['score'] if not a['qualified'] else -a['score'],candidate['opportunity_key'])
    novel.sort(key=order)
    distinct=[];overlapping=[]
    for candidate in novel:
        ids=set(candidate['listing_ids'])
        duplicate=next((c for c in distinct if len(ids&set(c['listing_ids']))/max(1,len(ids|set(c['listing_ids'])))>.65),None)
        if duplicate:overlapping.append({'candidate_id':candidate['candidate_id'],'overlaps_candidate_id':duplicate['candidate_id'],'reason':'substantially_same_saved_listing_group'})
        else:distinct.append(candidate)
    write_json(directory/'overlapping-candidates.json',overlapping)
    novel=distinct
    write_json(directory/'evidence.json',evidence);write_json(directory/'candidate-assessments.json',assessed)
    write_json(directory/'previous-assessments.json',history)
    stages=[];visual_notes=[];shortlist=novel
    if len(novel)>settings['maximum_opportunities']:
        # At most twenty candidates enter semantic refinement; keep deterministic
        # score ordering and all rejected/overflow evidence in the saved report.
        shortlist=novel[:20]
        from .service_reports import saved_images
        from .visuals import describe_saved_images
        images,audit=saved_images([c['evidence'][0] for c in shortlist if c['evidence']],dataset,limit=settings['maximum_images'])
        write_json(directory/'image-audit.json',audit)
        mapping={e['id']:e['evidence_id'] for c in shortlist for e in c['evidence']}
        attached=[a for a in audit if a['status']=='attached']
        for index in range(0,len(images),2):
            folder=directory/f'image-batch-{index//2}';folder.mkdir(exist_ok=True)
            rows=[{**a,'image_index':i,'evidence_id':mapping[a['record_id']]} for i,a in enumerate(attached[index:index+2])]
            visual_notes.extend(describe_saved_images(local,images[index:index+2],rows,folder))
        evidence['local_image_notes_unverified']=visual_notes
        req=local_request(model_request('market_insights',evidence,shortlist[:6]),shortlist[:6])
        try:
            response=stage(directory,'opportunity-local',local,req);labels=validate_local(response.text,shortlist[:6]);evidence['local_labels']=labels['items']
            stages.append({'stage':'local','status':'completed','metadata':response.metadata})
        except Exception as error:stages.append({'stage':'local','status':'failed','error_type':type(error).__name__})
        if cheap is not None:
            req=model_request('market_insights',evidence,shortlist);req.schema['properties']['items']['maxItems']=10
            req.system=req.system.replace('zero to five','zero to ten')+' Rank evidence-qualified business-validation candidates; history, diversity, age and similarity matter. Do not infer allocated listing sales.'
            response=stage(directory,'opportunity-cheap',cheap,req);selection=validate_selection(response.text,shortlist,maximum=10)
            stages.append({'stage':'cheap','status':'completed','metadata':response.metadata})
            chosen={r['candidate_id'] for r in selection['items']};shortlist=[c for c in shortlist if c['candidate_id'] in chosen]
        shortlist=shortlist[:settings['maximum_opportunities']]
    recommendations=[]
    # A bounded local preview can exercise the handoff without paid admission.
    # Cloud production briefing remains one bounded final stage. Local briefs
    # are explicitly unverified and never masquerade as trend-supported sales.
    batches=[shortlist] if good is not None else [[c] for c in shortlist[:3]]
    by_id={c['candidate_id']:c for c in shortlist}
    for index,batch in enumerate(batches):
        if not batch:continue
        req=brief_request(model_request('market_insights',evidence,batch))
        req.schema['properties']['items']['maxItems']=10 if good is not None else 1
        req.system=req.system.replace('Select at most two focused product concepts.','Select five to ten focused product concepts when supported; select fewer when evidence is insufficient. Do not pad.' if good is not None else 'Select at most one focused product concept.')
        req.system+=' Use concise briefs: short audience/job statements, at most two deliverables and two items in each checklist. Cross-examine commercial_assessment and prior assessments. A discovery_hypothesis is a cross-sectional product experiment, not a trend-supported opportunity. Explain observed listing content and propose original deliverables. Neither tier verifies listing purchases, profit or thin marketplace supply.'
        if good is None:req.system+=' Keep every statement under twenty words and each checklist to one item.'
        name='opportunity-final' if good is not None else f'opportunity-local-brief-{index+1}'
        try:
            response=stage(directory,name,good or local,req);value=json.loads(response.text)
            if good is None:
                value=local_design_selection(value,batch)
                write_json(directory/(name+'-proposals.json'),value)
            selection,briefs=validate_brief(value,batch,maximum=10 if good is not None else 1)
            stages.append({'stage':'final' if good is not None else 'local_brief','status':'completed','metadata':response.metadata})
        except Exception as error:
            if good is not None:raise
            stages.append({'stage':'local_brief','status':'failed','error_type':type(error).__name__})
            continue
        for item in selection['items']:
            c=by_id[item['candidate_id']]
            recommendations.append({'candidate_id':c['candidate_id'],'opportunity_key':key(c),'keywords':c['suggested_keywords'],
                'rationale':item['reason'],'product_brief':briefs[c['candidate_id']],'evidence_ids':item['evidence_ids'],
                'evidence_excerpts':[e for e in c['evidence'] if e['evidence_id'] in item['evidence_ids']],
                'facts':facts(c),
                'assessment':'trend_supported_opportunity' if c['commercial_assessment']['qualified'] else 'discovery_hypothesis',
                'evidence_tier':c['commercial_assessment']['evidence_tier'],'brief_provider':'openai' if good is not None else 'ollama',
                'requires_human_review':True,
                'high_demand_verified':False,'thin_supply_verified':False,'listing_sales':None,
                'validation_needed':['Validate conversion, production cost and broad-market competition before investing.']})
    selected={r['opportunity_key'] for r in recommendations} if good is not None else set()
    for identity in selected:claims[identity]={'source_run_id':dataset['metadata']['source_run_id'],'job_id':directory.name,'at':now()}
    write_json(claims_path,{'offers':claims})
    for row in assessed:row['suggested']=row['key'] in selected
    manifest={'version':VERSION,'job_id':directory.name,'source_run_id':dataset['metadata']['source_run_id'],
              'source_finished_at':dataset['metadata'].get('refresh_as_of') or dataset['metadata']['finished_at'],
              'assessed_at':now(),'input_sha256':dataset['provenance'].get('input_sha256'),'candidates':assessed,'policy':settings,
              'query_context':dataset['metadata'].get('query_context'),
              'history_source_run_ids':[r['run_id'] for r in dataset['metadata'].get('history',{}).get('related_observations',[])],
              'previous_assessment_source_run_ids':sorted({r['source_run_id'] for r in history})}
    signature=hashlib.sha256(json.dumps({'job_id':directory.name,'source':manifest['source_run_id'],'version':VERSION,'policy':settings},sort_keys=True).encode()).hexdigest()
    target=Path(config['output_root'])/'market-assessments'/(signature+'.json')
    if target.exists():
        old=json.loads(target.read_text())
        # Preserve already reserved suggestions on explicit retry/config changes.
        known={r['key'] for r in old['candidates'] if r.get('suggested')}
        for row in assessed:row['suggested']|=row['key'] in known
    if not target.exists():write_json(target,manifest)
    return {'schema_version':4,'service':'market_insights','status':('provisional' if good is not None else 'local_preview') if recommendations else 'insufficient_evidence',
        'execution_mode':'tiered_openai' if good is not None else 'local_only',
        'recommendations':recommendations,'summary':f'{len(recommendations)} new product-validation candidates; target {settings["minimum_target"]}–{settings["maximum_opportunities"]}. Discovery hypotheses and trend-supported candidates are labeled separately.',
        'target_count_met':len(recommendations)>=settings['minimum_target'],'shortfall':max(0,settings['minimum_target']-len(recommendations)),
        'candidate_counts':{'initial':len(assessed),'previously_suggested_removed':len(suppressed),'overlapping_removed':len(overlapping),
                            'trend_supported':sum(c['commercial_assessment']['qualified'] for c in novel),
                            'discovery_hypotheses':sum(not c['commercial_assessment']['qualified'] for c in novel),
                            'qualified_novel':len(novel),'consumer':len(recommendations)},
        'preview_limit':3 if good is None else None,
        'offers_reserved':good is not None,
        'local_preview_scope':'Local product statements are design hypotheses; measured evidence is rendered deterministically, not certified by the model.' if good is None else None,
        'data_scope':{k:v for k,v in dataset['metadata'].get('saved_pool',{}).items() if k not in ('members','sources','issues','query_context','source_normalization')} | {'source_run_count':len(dataset['metadata'].get('saved_pool',{}).get('sources',[])),'pool_issue_count':len(dataset['metadata'].get('saved_pool',{}).get('issues',[]))},
        'assessment_updates':[{'key':r['key'],'phrase':r['phrase'],'qualified':r['qualified'],'assessment':summary(r['assessment'])} for r in assessed],
        'shortfall_reasons':dict(__import__('collections').Counter(reason for r in assessed for reason in r['assessment']['hold_reasons'])),
        'discovery_hold_reasons':dict(__import__('collections').Counter(reason for r in assessed for reason in r['assessment']['discovery']['hold_reasons'])),
        'final_model_completed':any(s['stage']=='final' for s in stages),'local_image_notes_unverified':visual_notes,'stages':stages,
        'quality_gate':'Deterministic commercial evidence gates and citation membership; not verified listing demand or profitability.',
        'limitations':evidence['limitations'],'recommendations_applied':False,'weekly_trend_report_implemented':False}
