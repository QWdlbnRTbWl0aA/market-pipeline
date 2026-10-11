"""Mechanical DQA of persisted observations, not market or opportunity analysis."""
import collections
import hashlib
from pathlib import Path
from .entities import parse_listings, parse_shop

LISTING_CHECKS = ('listing_id', 'title', 'url', 'price', 'currency', 'digital', 'bestseller', 'listing_sales',
                  'listing_views', 'listing_favorites', 'shop_id', 'original_created_at', 'tags', 'description', 'language', 'taxonomy_id')
MATCH_FIELDS = ('title', 'price', 'currency', 'digital', 'bestseller', 'listing_views', 'listing_favorites',
                'shop_id', 'original_creation_timestamp', 'tags', 'description')


def check(run, directory):
    from .core import now, tokens, parse_public
    directory = Path(directory)
    queries = run.get('queries', [])
    tracked = run.get('tracked_listings', [])
    shop_records = run.get('shops', [])
    rows = [row for query in queries for row in query['listings']] + [item['listing'] for item in tracked if item.get('listing')]
    shops = [item['shop'] for item in shop_records if item.get('shop')]
    responses = []
    for query in queries:
        responses.extend(query.get('pages') or [query])
    responses += tracked + shop_records
    integrity, parsed, seen_files = [], {}, set()
    for response in responses:
        raw_file = response.get('raw_file')
        if not raw_file or raw_file in seen_files:
            continue
        seen_files.add(raw_file)
        try:
            body = (directory / raw_file).read_bytes()
            valid = hashlib.sha256(body).hexdigest() == response.get('raw_sha256')
            integrity.append({'raw_file': raw_file, 'sha256_matches': valid})
            if response.get('shop_id') and response.get('shop'):
                parsed[raw_file] = {'shop': parse_shop(body, response['requested_at'], {})}
            elif raw_file.endswith('.html'):
                parsed[raw_file] = {row['listing_id']: row for row in parse_public(body)}
            else:
                parsed[raw_file] = {row['listing_id']: row for row in parse_listings(body)}
        except (OSError, ValueError, KeyError, TypeError):
            if not any(item['raw_file'] == raw_file for item in integrity):
                integrity.append({'raw_file': raw_file, 'sha256_matches': False})
            parsed[raw_file] = {}
    samples, duplicates, relevance, pagination_duplicates = [], [], [], []
    for query in queries:
        words = set(tokens(query['niche']['keywords']))
        counts = collections.Counter(row['listing_id'] for row in query['listings'])
        duplicates += [identity for identity, count in counts.items() if count > 1]
        pagination_duplicates += query.get('duplicate_ids_across_pages', [])
        for row in query['listings']:
            if words and not words.intersection(tokens(row['title'])):
                relevance.append(row['listing_id'])
        for row in query['listings'][:3] + query['listings'][-1:]:
            filename = row.get('provenance', {}).get('raw_file', query.get('raw_file'))
            original = parsed.get(filename, {}).get(row['listing_id'], {})
            samples.append({'listing_id': row['listing_id'], 'raw_file': filename,
                            'matches_saved_source': bool(original) and all(row.get(field) == original.get(field) for field in MATCH_FIELDS if field in row),
                            'method': 'reparse retained source; not independent live verification'})
    for record in tracked:
        row = record.get('listing')
        if row:
            original = parsed.get(record.get('raw_file'), {}).get(row['listing_id'], {})
            samples.append({'listing_id': row['listing_id'], 'matches_saved_source': bool(original) and all(row.get(k) == original.get(k) for k in MATCH_FIELDS), 'method': 'saved tracking response'})
    shop_samples = []
    for record in shop_records:
        shop = record.get('shop')
        if shop:
            original = parsed.get(record.get('raw_file'), {}).get('shop', {})
            shop_samples.append({'shop_id': shop['shop_id'], 'matches_saved_source': bool(original) and all(shop.get(k) == original.get(k) for k in ('transaction_sold_count', 'listing_active_count', 'shop_favorites', 'shop_name'))})
    invalid = []
    for row in rows:
        for field in ('listing_views', 'listing_favorites'):
            value = row.get(field)
            if value is not None and (type(value) is not int or value < 0):
                invalid.append({'listing_id': row['listing_id'], 'field': field})
        if row.get('original_creation_timestamp') and row.get('original_created_at') is None:
            invalid.append({'listing_id': row['listing_id'], 'field': 'original_creation_timestamp'})
    for shop in shops:
        for field in ('transaction_sold_count', 'listing_active_count', 'shop_favorites'):
            value = shop.get(field)
            if value is not None and (type(value) is not int or value < 0):
                invalid.append({'shop_id': shop['shop_id'], 'field': field})
    ids = [row['listing_id'] for row in rows]
    search_ids = [row['listing_id'] for query in queries for row in query['listings']]
    good = run['status'] == 'success' and not duplicates and not invalid and all(i['sha256_matches'] for i in integrity) and all(i['matches_saved_source'] for i in samples + shop_samples)
    return {'checked_at': now(), 'file_validity': 'JSON serializable; retained raw checksums checked',
            'query_coverage': {'requested': len(queries), 'successful': sum(q['status'] == 'success' for q in queries)},
            'tracking_coverage': {'requested': len(tracked), 'successful': sum(i['status'] == 'success' for i in tracked)},
            'shop_coverage': {'requested': len(shop_records), 'successful': len(shops), **run.get('shop_coverage', {})},
            'listing_count': len(rows), 'unique_listings': len(set(ids)), 'duplicates_within_queries': duplicates,
            'pagination_duplicates_removed': pagination_duplicates,
            'cross_query_overlap': len(search_ids) - len(set(search_ids)),
            'field_completeness': {field: {'present': sum(row.get(field) is not None for row in rows), 'total': len(rows)} for field in LISTING_CHECKS},
            'shop_field_completeness': {field: {'present': sum(shop.get(field) is not None for shop in shops), 'total': len(shops)} for field in ('shop_id', 'transaction_sold_count', 'listing_active_count', 'shop_favorites')},
            'relevance_title_no_token_overlap': relevance, 'invalid_values': invalid,
            'digital_products': sum(r['digital'] is True for r in rows), 'physical_products': sum(r['digital'] is False for r in rows),
            'digital_unknown': sum(r['digital'] is None for r in rows), 'observed_bestseller_badges': sum(r['bestseller'] is True for r in rows),
            'raw_integrity': integrity, 'source_sample': samples, 'shop_source_sample': shop_samples,
            'usable_for_listing_research': bool(rows) and good, 'usable_for_shop_research': bool(shops) and good,
            'usable_for_bestseller_research': bool(rows) and good and any(r['bestseller'] is True for r in rows),
            'limitations': ['Bounded search and shop samples; no marketplace coverage claim.',
                           'Title-token relevance is a review flag, especially across languages; digital does not by itself mean printable.',
                           'Original creation and renewal timestamps stay distinct. Missing metrics stay null.',
                           'Shop transaction-sold counters are shop-wide; they are not listing sales, revenue or conversion rates.',
                           'Listing sales, demand and search volume are unavailable; API search has no bestseller evidence.',
                           'Source sampling reparses saved responses; it is not an independent live request.']}
