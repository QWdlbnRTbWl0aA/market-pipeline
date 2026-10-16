"""Evidence-backed query experiments; never mutate collector configuration."""
from collections import Counter
from .research import STOP, words


def identity(text):
    # Word order, case and repeated words do not create a new experiment.
    def singular(word):
        if len(word)>4 and word.endswith('ies'):return word[:-3]+'y'
        if len(word)>4 and word.endswith('s') and not word.endswith(('ss','us','is','mas')):return word[:-1]
        return word
    return tuple(sorted({singular(w) for w in words(text)}))


def prepare(evidence, dataset, maximum):
    queries=[n.get('keywords','').strip() for n in evidence['query_context'].get('niches',[]) if n.get('keywords','').strip()]
    frequencies=Counter(w for r in dataset['records'] for w in identity(r['title']+' '+' '.join(r['tags'])))
    common={w for w,n in frequencies.items() if n>=max(1,len(dataset['records'])*.45)}
    content={r['id']:set(words(r['title']+' '+' '.join(r['tags'])+' '+r['description'][:4000])) for r in dataset['records']}
    originals={identity(q) for q in queries};seen=set(originals);plans=[];skipped=[]
    for candidate in evidence['candidates']:
        phrase=candidate['phrase'];tokens=words(phrase)
        if not queries or candidate['shop_count']<3 or len(tokens)<2:
            skipped.append({'candidate_id':candidate['candidate_id'],'reason':'missing_query_or_independent_group_support'});continue
        def query_fit(query):
            intent=set(words(query))-STOP
            supported=sum(bool(intent) and intent<=content.get(i,set()) for i in candidate['listing_ids'])
            return (supported,len(set(words(query))&set(tokens)))
        baseline=max(queries,key=query_fit)
        anchors=set(words(baseline))
        added=list(dict.fromkeys(w for w in tokens if w not in anchors and w not in STOP))
        query=' '.join([baseline,*added]);signature=identity(query)
        if not added or signature in seen or len(query)>200:
            skipped.append({'candidate_id':candidate['candidate_id'],'reason':'unchanged_duplicate_or_overlong_query'});continue
        seen.add(signature)
        distinctive=[w for w in added if not set(identity(w))<=common]
        support=f"Saved phrase '{phrase}' occurs in {candidate['listing_count']} listings from {candidate['shop_count']} shops."
        plan={'baseline_keywords':baseline,'keywords':query,'added_terms':added,
              'purpose':f"Test the '{phrase}' product subgroup while retaining the original niche terms.",
              'observed_support':support,
              'expected_effect':f"Narrow results toward listings describing {' '.join(added)}; relevance gain is unverified.",
              'success_criteria':['Compare relevant digital listing share against the baseline using the same bounded sample.',
                                  'Measure distinct relevant shops and duplicate listings per request; do not equate result count with demand.'],
              'basis':'saved_content_query_hypothesis','requires_collector_comparison':True,
              'distinctive_modifier':bool(distinctive)}
        plans.append((len(distinctive)>0,-min(len(distinctive),2),-candidate['shop_count'],candidate,plan))
    # Specific content modifiers take precedence over ubiquitous format wording.
    plans.sort(key=lambda row:(not row[0],row[1],row[2],row[3]['phrase']))
    candidates=[]
    for _,_,_,candidate,plan in plans[:maximum]:
        candidates.append({**candidate,'suggested_keywords':plan['keywords'],'search_plan':plan})
    evidence={**evidence,'candidates':candidates,'refinement_plan':{
        'unchanged_queries_removed':True,'original_queries':queries,'skipped_candidates':skipped,
        'query_identity':'Case-insensitive unordered unique words, folding simple English plurals',
        'selection_method':'Distinctive saved content modifiers first, then independent shop support; hypotheses require comparison.',
        'coverage':{'listing_count':len(dataset['records']),'semantic_scope':'Model labels cover only the selected group examples, not every listing.',
                    'complete_marketplace_query':all(q.get('collection_complete') is True for q in evidence.get('query_coverage',[])) if evidence.get('query_coverage') else False}}}
    return evidence
