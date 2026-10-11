"""Offline run statistics, bounded request estimates and single-file raw export."""
import collections
import hashlib
import json
import math
import statistics
from .core import now


def summarize(run):
    queries = run.get('queries', [])
    observations = [r for q in queries for r in q.get('listings', [])]
    observations += [r['listing'] for r in run.get('tracked_listings', []) if r.get('listing')]
    listings = {r['listing_id']: r for r in observations}
    rows = list(listings.values())
    shops = {str(r['shop_id']): r['shop'] for r in run.get('shops', []) if r.get('shop')}
    categories = collections.Counter(r.get('taxonomy_id') for r in rows)
    shop_counts = collections.Counter(r.get('shop_id') for r in rows)
    estimates = []
    for query in queries:
        count = query.get('provider_result_count')
        size = query.get('effective_search', {}).get('page_size') or run.get('settings', {}).get('page_size') or 100
        pages = query.get('pages') or [query]
        returned = query.get('source_rows_returned', sum(p.get('returned_count', 0) for p in pages))
        remaining = max(0, count - returned) if isinstance(count, int) else None
        last_offset = max((p.get('effective_parameters', {}).get('offset', 0) for p in pages), default=0)
        next_offset = last_offset + (pages[-1].get('returned_count', 0) if pages else 0)
        accessible_pages = max(0, (12000 - next_offset) // size + 1)
        limit = query.get('effective_search', {}).get('listing_limit')
        configured_remaining = max(0, limit - len(query.get('listings', []))) if isinstance(limit, int) else remaining
        local_filter = query.get('keyword_filter', '').startswith('local')
        estimates.append({'keywords': query['niche']['keywords'], 'shop_id': query.get('shop_id'),
                          'reported_available': count, 'reported_count_scope': query.get('reported_count_scope', 'Etsy keyword matches'),
                          'source_rows_returned': returned, 'matching_listings_fetched': len(query.get('listings', [])),
                          'listing_pages_remaining_for_full_reported_query': math.ceil(remaining / size) if remaining is not None else None,
                          'listing_pages_remaining_within_provider_offset': min(math.ceil(remaining / size), accessible_pages) if remaining is not None else None,
                          'listing_pages_remaining_for_result_limit': math.ceil(configured_remaining / size) if configured_remaining is not None and not local_filter else None,
                          'keyword_filtered_locally': local_filter})
    known = set(str(r.get('shop_id')) for r in rows if r.get('shop_id')) | set(map(str, run.get('settings', {}).get('shop_ids', [])))
    pending_shops = len(known - set(shops))
    unqueried_selected_shops = len(set(map(str, run.get('settings', {}).get('shop_ids', []))) - {str(q.get('shop_id')) for q in queries if q.get('shop_id') is not None})
    all_counts_known = bool(estimates) and all(e['reported_available'] is not None for e in estimates)
    full_pages = sum(e['listing_pages_remaining_for_full_reported_query'] or 0 for e in estimates) if all_counts_known else None
    price_groups = collections.defaultdict(list)
    for row in rows:
        if isinstance(row.get('price'), (int, float)) and row.get('currency'):
            price_groups[row['currency']].append(row['price'])
    return {'computed_at': now(), 'listing_observations': len(observations), 'unique_listings': len(rows),
            'reported_available': sum(e['reported_available'] for e in estimates) if all_counts_known else None,
            'reported_available_scope': 'Queried sources only; inventories of unqueried selected shops are unknown',
            'selected_shop_initial_search_requests_remaining': unqueried_selected_shops, 'query_estimates': estimates, 'estimated_remaining_listing_requests_full_query': full_pages,
            'known_shop_detail_requests_remaining': pending_shops,
            'estimated_following_requests_lower_bound': full_pages + pending_shops + unqueried_selected_shops if full_pages is not None else None,
            'estimate_note': 'Estimate from last reported counts. Unseen shop count is unknown; full totals may exceed Etsy offset/quota bounds. Totals for selected shops not yet queried are unknown.',
            'selected_shop_search_coverage': run.get('selected_shop_search_coverage'),
            'distinct_shops_in_returned_listings': len([s for s in shop_counts if s is not None]), 'shops_fetched': len(shops),
            'categories': [{'taxonomy_id': k, 'listing_count': v} for k, v in sorted(categories.items(), key=lambda x: -x[1])],
            'shops': [{'shop_id': k, 'shop_name': shops.get(str(k), {}).get('shop_name'), 'listing_count': v} for k, v in sorted(shop_counts.items(), key=lambda x: -x[1])],
            'digital': {'digital': sum(r.get('digital') is True for r in rows), 'physical': sum(r.get('digital') is False for r in rows), 'unknown': sum(r.get('digital') is None for r in rows)},
            'prices_by_currency': {currency: {'count': len(values), 'minimum': min(values), 'maximum': max(values), 'median': statistics.median(values)} for currency, values in price_groups.items()},
            'statistic_scope': 'Observed unique returned listings only. Taxonomy IDs are source categories; missing taxonomy/shop identity stays unknown. No commercial scoring.'}


def compose_export(store, run_id):
    """Read-only export; original and derived snapshots/raw files remain unchanged."""
    from .quality import check
    run = store.read(run_id)
    directory = store.runs / run_id
    original = (directory / 'snapshot.json').read_bytes()
    raw = []
    for path in sorted(directory.glob('raw-*')):
        body = path.read_bytes()
        try:
            payload, kind = json.loads(body), 'json'
        except (ValueError, UnicodeDecodeError):
            payload, kind = body.decode('utf-8', errors='replace'), 'text'
        raw.append({'file': path.name, 'sha256': hashlib.sha256(body).hexdigest(), 'byte_count': len(body), 'format': kind, 'payload': payload})
    events = []
    for path in (store.directory / 'requests').glob('*.json'):
        try:
            event = json.loads(path.read_text())
            if event.get('run_id') == run_id:
                events.append(event)
        except (OSError, ValueError):
            continue
    return {'export_schema_version': 1, 'exported_at': now(), 'run_id': run_id,
            'metadata': {k: v for k, v in run.items() if k not in {'queries', 'shops', 'tracked_listings', 'dqa'}},
            'search_parameters': {'settings': run.get('settings'), 'queries': [{k: v for k, v in q.items() if k != 'listings'} for q in run.get('queries', [])]},
            'results': {'listings': [r for q in run.get('queries', []) for r in q.get('listings', [])], 'shops': run.get('shops', []), 'tracked_listings': run.get('tracked_listings', [])},
            'summary': summarize(run), 'requests': sorted(events, key=lambda e: e['started_at']),
            'raw_responses': raw, 'dqa': check(run, directory),
            'provenance': {'source_snapshot_sha256': hashlib.sha256(original).hexdigest(), 'method': 'Offline saved-file export; DQA reparses retained source, no new API calls', 'run_status': run['status']}}
