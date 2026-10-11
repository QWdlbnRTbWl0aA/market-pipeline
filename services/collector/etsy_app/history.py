"""Versioned offline recovery and an atomic JSON index over immutable run history."""
import hashlib
import json
from pathlib import Path
import urllib.parse
from .core import atomic_json, now
from .entities import VERSION, parse_listings, parse_shop
from .quality import check


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def recover(store):
    results = []
    for path in sorted(store.runs.glob('*/snapshot.json')):
        try:
            original = json.loads(path.read_text())
            if original.get('status') == 'running':
                results.append({'run_id': original['run_id'], 'status': 'incomplete_skipped'})
                continue
            directory = path.parent
            run = json.loads(path.read_text())
            signatures = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('raw-*') if p.is_file()}
            version = digest({'snapshot': hashlib.sha256(path.read_bytes()).hexdigest(), 'raw': signatures, 'normalization': VERSION})
            destination = store.directory / 'derived' / run['run_id'] / version / 'snapshot.json'
            if destination.exists():
                atomic_json(destination.parent.parent / 'current.json', {'version': version})
                results.append({'run_id': run['run_id'], 'status': 'already_recovered'})
                continue
            recovered_fields = 0
            for query in run['queries']:
                if query['source'] != 'api':
                    continue
                candidates = {}
                for response in query.get('pages') or [query]:
                    if response.get('http_status') != 200 or not response.get('raw_file'):
                        continue
                    raw = (directory / response['raw_file']).read_bytes()
                    if hashlib.sha256(raw).hexdigest() != response['raw_sha256']:
                        raise ValueError('raw checksum mismatch; recovery refused')
                    parameters = response.get('effective_parameters') or dict(urllib.parse.parse_qsl(urllib.parse.urlparse(response.get('source_url', '')).query))
                    provenance = {'run_id': run['run_id'], 'raw_file': response['raw_file'], 'raw_sha256': response['raw_sha256'],
                                  'source_url': response.get('source_url'), 'effective_parameters': parameters,
                                  'requested_at': response['requested_at'], 'request_id': response.get('request_id'), 'recovered_offline': True}
                    for row in parse_listings(raw, response['requested_at'], provenance):
                        candidates.setdefault(row['listing_id'], row)
                for index, previous in enumerate(query['listings']):
                    recovered = candidates.get(previous['listing_id'])
                    if recovered:
                        recovered_fields += sum(previous.get(k) is None and value is not None for k, value in recovered.items())
                        recovered['observed_at'] = previous.get('observed_at') or recovered['observed_at']
                        query['listings'][index] = recovered
                if not query.get('effective_search') and query.get('source_url'):
                    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(query['source_url']).query))
                    query['effective_search'] = {'endpoint': query['source_url'].split('?')[0],
                                                 'parameters': {k: v for k, v in params.items() if k not in {'limit', 'offset'}},
                                                 'page_size': params.get('limit'), 'max_pages': 1, 'listing_limit': len(query['listings']),
                                                 'recovered_from_source_url': True}
            for record in run.get('tracked_listings', []) + run.get('shops', []):
                if record.get('status') != 'success' or not record.get('raw_file'):
                    continue
                body = (directory / record['raw_file']).read_bytes()
                if hashlib.sha256(body).hexdigest() != record['raw_sha256']:
                    raise ValueError('raw checksum mismatch; recovery refused')
                provenance = {**(record.get('shop') or record.get('listing') or {}).get('provenance', {}), 'run_id': run['run_id'], 'raw_file': record['raw_file'], 'raw_sha256': record['raw_sha256'], 'source_url': record.get('source_url'), 'request_id': record.get('request_id'), 'recovered_offline': True}
                if record.get('shop'):
                    record['shop'] = parse_shop(body, record['requested_at'], provenance)
                elif record.get('listing'):
                    record['listing'] = parse_listings(body, record['requested_at'], provenance)[0]
            run.update(normalization_version=VERSION, reprocessed_at=now(),
                       original_snapshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            run['dqa'] = check(run, directory)
            atomic_json(destination, run)
            atomic_json(destination.parent / 'dqa.json', run['dqa'])
            atomic_json(destination.parent.parent / 'current.json', {'version': version})
            results.append({'run_id': run['run_id'], 'status': 'recovered', 'new_nonmissing_fields': recovered_fields})
        except (ValueError, KeyError, OSError, TypeError) as error:
            results.append({'run_id': path.parent.name, 'status': 'failed', 'error': str(error) if isinstance(error, ValueError) else type(error).__name__})
    rebuild_index(store)
    return results


def rebuild_index(store):
    index = {key: {} for key in ('runs', 'by_date', 'by_query', 'by_keywords', 'by_search', 'by_listing', 'by_shop')}
    for info in store.list_runs():
        if info['status'] == 'corrupt':
            continue
        run = store.read(info['run_id'])
        identity = run['run_id']
        index['runs'][identity] = {'status': run['status'], 'started_at': run['started_at'], 'mode': run.get('mode', 'search'),
                                   'reprocessed_at': run.get('reprocessed_at')}
        day = run['started_at'][:10]
        index['by_date'].setdefault(day, []).append(identity)
        for query_index, query in enumerate(run['queries']):
            query_key = digest(query['niche'])
            effective = query.get('effective_search') or {'source_url': query.get('source_url'), 'source': query['source']}
            search_key = digest(effective)
            ref = {'run_id': identity, 'query_index': query_index, 'niche': query['niche'], 'effective_search': effective,
                   'query_key': query_key, 'search_key': search_key, 'status': query['status']}
            index['by_query'].setdefault(query_key, []).append(ref)
            index['by_keywords'].setdefault(query['niche']['keywords'], []).append(ref)
            index['by_search'].setdefault(search_key, []).append(ref)
            for item_index, row in enumerate(query['listings']):
                entry = {'run_id': identity, 'record_type': 'listing', 'pointer': f'queries/{query_index}/listings/{item_index}',
                         'query_key': query_key, 'search_key': search_key, **{k: row.get(k) for k in
                         ('listing_id', 'shop_id', 'title', 'observed_at', 'listing_views', 'listing_favorites', 'price', 'currency', 'state', 'original_created_at', 'provenance')}}
                index['by_listing'].setdefault(row['listing_id'], []).append(entry)
                if row.get('shop_id'):
                    index['by_shop'].setdefault(row['shop_id'], []).append(entry)
        for item_index, record in enumerate(run.get('tracked_listings', [])):
            row = record.get('listing')
            if row:
                entry = {'run_id': identity, 'record_type': 'listing', 'pointer': f'tracked_listings/{item_index}/listing', 'tracking': True,
                         **{k: row.get(k) for k in ('listing_id', 'shop_id', 'title', 'observed_at', 'listing_views', 'listing_favorites', 'price', 'currency', 'state', 'original_created_at', 'provenance')}}
                index['by_listing'].setdefault(row['listing_id'], []).append(entry)
                if row.get('shop_id'):
                    index['by_shop'].setdefault(row['shop_id'], []).append(entry)
        for item_index, record in enumerate(run.get('shops', [])):
            row = record.get('shop')
            if row:
                entry = {'run_id': identity, 'record_type': 'shop', 'pointer': f'shops/{item_index}/shop',
                         **{k: row.get(k) for k in ('shop_id', 'shop_name', 'observed_at', 'transaction_sold_count', 'listing_active_count', 'shop_favorites', 'provenance')}}
                index['by_shop'].setdefault(row['shop_id'], []).append(entry)
        for kind, records in [('listing', run.get('tracked_listings', [])), ('shop', run.get('shops', []))]:
            for item_index, record in enumerate(records):
                if record.get(kind):
                    continue
                entity_id = record.get(kind + '_id')
                if entity_id:
                    entry = {'run_id': identity, 'record_type': kind, kind + '_id': entity_id,
                             'observed_at': record.get('requested_at'), 'status': record['status'], 'error': record.get('error'),
                             'provenance': {'raw_file': record.get('raw_file'), 'raw_sha256': record.get('raw_sha256'), 'source_url': record.get('source_url')}}
                    index['by_' + kind].setdefault(entity_id, []).append(entry)
    atomic_json(store.directory / 'index.json', index)
    return {'runs': len(index['runs']), 'listings': len(index['by_listing']), 'shops': len(index['by_shop']), 'queries': len(index['by_query']), 'searches': len(index['by_search'])}
