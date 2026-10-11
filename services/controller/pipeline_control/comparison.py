"""Mechanical comparisons over checksum-verified saved samples, never Etsy calls."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from .storage import digest, read, write


def source_rows(directory, query):
    directory = Path(directory).resolve(); rows = []
    for page in query.get('pages') or [query]:
        if page.get('http_status') != 200: raise ValueError('Incomplete source sample')
        name = page.get('raw_file')
        if not isinstance(name, str) or Path(name).name != name or not name.startswith('raw-'): raise ValueError('Unsafe raw artifact')
        path = directory / name
        if path.is_symlink() or path.stat().st_size > 8_000_000: raise ValueError('Unsafe raw response')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != page.get('raw_sha256'): raise ValueError('Raw response checksum mismatch')
        value = json.loads(body)
        if not isinstance(value.get('results'), list): raise ValueError('Missing raw listing rows')
        rows.extend(value['results'])
    return rows


def statistics(rows, required_words):
    ids, shops, categories, prices = set(), set(), Counter(), {}
    duplicates, physical, unknown, heuristic = 0, 0, 0, 0
    for row in rows:
        key = str(row.get('listing_id')); duplicates += key in ids; ids.add(key)
        if row.get('shop_id') is not None: shops.add(str(row['shop_id']))
        categories[str(row.get('taxonomy_id') or 'unknown')] += 1
        digital = row.get('is_digital') if type(row.get('is_digital')) is bool else row.get('listing_type') == 'download' if row.get('listing_type') is not None else None
        physical += digital is False; unknown += digital is None
        words = set(re.findall(r'[\w]+', ' '.join([str(row.get('title', '')), *[str(x) for x in row.get('tags', [])]]).casefold()))
        heuristic += digital is True and bool(words & set(required_words))
        price = row.get('price')
        if isinstance(price, dict) and type(price.get('amount')) in (int,float) and type(price.get('divisor')) in (int,float) and price['divisor'] > 0:
            prices.setdefault(price.get('currency_code', 'unknown'), []).append(price['amount']/price['divisor'])
    count = len(rows)
    return {'source_rows': count, 'unique_listing_ids': len(ids), 'duplicate_rows': duplicates, 'shops': len(shops), 'categories': dict(categories),
            'physical_rows': physical, 'unknown_digital_rows': unknown, 'contamination_rate': physical/count if count else None,
            'heuristic_relevant_rows': heuristic, 'heuristic_relevance_rate': heuristic/count if count else None,
            'price_statistics_by_currency': {k: {'observations': len(v), 'min': min(v), 'max': max(v), 'median': sorted(v)[len(v)//2]} for k,v in prices.items()},
            'quality_scope': 'Deterministic digital/keyword flags; semantic relevance requires blind human labels'}


def compare(source_root, run_id, manifest, output, labels=None):
    directory = Path(source_root) / run_id; snapshot = read(directory/'snapshot.json',100_000_000)
    if snapshot.get('status') != 'success' or not snapshot.get('finished_at') or snapshot.get('dqa') != read(directory/'dqa.json'): raise ValueError('Successful finalized comparison required')
    if snapshot.get('lineage', {}).get('experiment_id') != manifest['proposal_id']: raise ValueError('Comparison lineage mismatch')
    settings = snapshot['settings']
    if settings.get('limit') != 100 or settings.get('max_pages') != 1 or settings.get('exclude_fetched_listings') or settings.get('exclude_fetched_shops'): raise ValueError('Incomparable sample parameters')
    sha = hashlib.sha256((directory/'snapshot.json').read_bytes()).hexdigest()
    if labels is not None and (set(labels) != {'snapshot_sha256','reviewer','labels'} or labels['snapshot_sha256'] != sha or not isinstance(labels['reviewer'],str) or not labels['reviewer'].strip()): raise ValueError('Exact saved-sample review required')
    groups, details = {}, {}
    for query in snapshot['queries']:
        if query['status'] != 'success' or not query.get('pages') or len(query['pages']) != 1: raise ValueError('Partial or expanded sample cannot be accepted')
        params = query['pages'][0].get('effective_parameters') or {}
        if params.get('limit') != 100 or params.get('offset') != 0: raise ValueError('Matching first-page samples required')
        key = query['niche']['keywords']; groups.setdefault(key, []).extend(source_rows(directory,query))
        details.setdefault(key, []).append({'shop_id': query.get('shop_id'), 'effective_search': query.get('effective_search'), 'provider_available': query.get('provider_result_count')})
    if set(groups) != set(manifest['searches']): raise ValueError('Incomplete phrase coverage')
    sample_size=manifest['comparison_policy'].get('human_sample_per_phrase',10)
    selected_ids={key:sorted({str(r.get('listing_id')) for r in rows},key=lambda k:hashlib.sha256(k.encode()).hexdigest())[:sample_size] for key,rows in groups.items()}
    tests = []
    for proposal in manifest['phrases']:
        parent, refined = proposal['parent_keywords'], proposal['keywords']
        terms = [w for w in refined.split() if w not in {'printable','digital','download','jewish','template'}]
        baseline, followup = statistics(groups[parent],terms), statistics(groups[refined],terms)
        allowed_ids = {str(r.get('listing_id')) for rows in groups.values() for r in rows}
        human = None
        if labels is not None:
            rows = labels['labels']
            if not isinstance(rows,dict) or any(k not in allowed_ids or v not in ('relevant','irrelevant','uncertain') for k,v in rows.items()): raise ValueError('Unknown or invalid relevance labels')
            def rate(sample):
                key = parent if sample is groups[parent] else refined
                seen = set(selected_ids[key])
                selected = [rows.get(k) for k in seen]
                complete = bool(selected) and all(v in ('relevant','irrelevant') for v in selected)
                return sum(v=='relevant' for v in selected)/len(selected) if complete else None
            a,b = rate(groups[parent]),rate(groups[refined])
            human = {'baseline_rate': a, 'refined_rate': b, 'gain': b-a if a is not None and b is not None else None,
                     'sample_count':{parent:len(selected_ids[parent]),refined:len(selected_ids[refined])},'scope':'Human-labelled deterministic reference sample only, not full-query relevance or statistical significance',
                     'complete': a is not None and b is not None, 'reviewer': labels['reviewer']}
        gain = human['gain'] if human else None
        pollution_ok = baseline['contamination_rate'] is not None and followup['contamination_rate'] is not None and followup['contamination_rate'] <= baseline['contamination_rate']
        tests.append({'parent_keywords': parent, 'refined_keywords': refined, 'baseline': baseline, 'refined': followup, 'human_review': human,
                      'decision': 'accepted' if gain is not None and gain >= manifest['comparison_policy']['minimum_relevance_gain'] and pollution_ok else 'rejected' if gain is not None else 'awaiting_human_labels',
                      'coverage': {parent: details[parent], refined: details[refined]}})
    review_rows = {}
    for rows in groups.values():
        for row in rows:
            key = str(row.get('listing_id'))
            review_rows.setdefault(key, {'listing_id':key, 'title':str(row.get('title',''))[:240], 'tags':[str(t)[:80] for t in row.get('tags',[])[:13]],
                                         'is_digital':row.get('is_digital'), 'shop_id':row.get('shop_id')})
    selected_union={key for ids in selected_ids.values() for key in ids}
    blind_sample = sorted([r for k,r in review_rows.items() if k in selected_union], key=lambda r: hashlib.sha256(r['listing_id'].encode()).hexdigest())
    report = {'schema_version':1,'experiment_id':manifest['proposal_id'],'source_run_id':run_id,'snapshot_sha256':sha,
              'manifest_sha256':digest(manifest),'status':'accepted' if all(r['decision']=='accepted' for r in tests) else 'awaiting_human_labels' if any(r['decision']=='awaiting_human_labels' for r in tests) else 'rejected',
              'review_sample':blind_sample,'human_review_instructions':'Label every displayed reference identity relevant/irrelevant/uncertain for the agreed printable intent, without using query origin; uncertain prevents acceptance.',
              'comparisons':tests,'request_count':snapshot.get('request_count'),'iterations_remaining':0,
              'source_coverage_scope':'Equal maximum first-page sample bounds; available counts can differ; no full-query or demand inference'}
    version = digest(report); target=Path(output)/version/'comparison.json';write(target,report);return report
