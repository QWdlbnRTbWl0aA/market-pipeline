"""Deterministic normalized observations; Etsy counters retain their entity scope."""
import datetime as dt
import html
import json

VERSION = 3
LISTING_FIELDS = ('description', 'rich_description', 'tags', 'materials', 'language', 'state',
                  'listing_type', 'taxonomy_id', 'quantity', 'who_made', 'when_made', 'is_supply',
                  'is_customizable', 'is_personalizable', 'has_variations', 'file_data', 'style',
                  'creation_timestamp', 'created_timestamp', 'original_creation_timestamp',
                  'last_modified_timestamp', 'updated_timestamp', 'ending_timestamp', 'state_timestamp',
                  'images', 'converted_price', 'skus', 'featured_rank', 'suggested_title',
                  'shop_section_id', 'shipping_profile_id', 'return_policy_id', 'processing_min', 'processing_max')


def timestamp(value):
    if type(value) not in (int, float) or value <= 0:
        return None
    try:
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def parse_listings(body, observed_at=None, provenance=None):
    from .core import listing, safe_url
    payload = json.loads(body)
    items = payload.get('results') if 'results' in payload else [payload]
    if not isinstance(items, list):
        raise ValueError('API response has no results array')
    rows = []
    for item in items:
        identity = item.get('listing_id')
        if not identity or not isinstance(item.get('title'), str):
            raise ValueError('API listing missing stable ID or title')
        money = item.get('price') or {}
        divisor, amount = money.get('divisor'), money.get('amount')
        price = amount / divisor if type(amount) in (int, float) and type(divisor) in (int, float) and divisor > 0 else None
        kind = item.get('listing_type')
        row = listing(identity, item['title'], safe_url(item.get('url'), identity), 'etsy_api',
                      price, money.get('currency_code'), True if kind == 'download' else False if kind == 'physical' else None)
        row.update({field: item.get(field) for field in LISTING_FIELDS})
        row.update(listing_views=item.get('views'), listing_favorites=item.get('num_favorers'),
                   shop_id=str(item['shop_id']) if item.get('shop_id') is not None else None,
                   digital_evidence=f'listing_type={kind}' if kind else None,
                   original_created_at=timestamp(item.get('original_creation_timestamp')),
                   created_at=timestamp(item.get('created_timestamp', item.get('creation_timestamp'))),
                   updated_at=timestamp(item.get('updated_timestamp', item.get('last_modified_timestamp'))),
                   normalization_version=VERSION)
        # Renewal/creation dates are retained separately; never substitute them for original age.
        row['metric_scope'].update(listing_views='listing observed', listing_favorites='listing observed',
                                   original_creation_timestamp='listing original creation; distinct from renewal',
                                   shop_sales='not copied into listing; consult linked shop observation')
        if observed_at:
            row['observed_at'] = observed_at
        if provenance:
            row['provenance'] = provenance
        rows.append(row)
    return rows


def parse_shop(body, observed_at, provenance):
    item = json.loads(body)
    if not item.get('shop_id'):
        raise ValueError('API shop missing stable ID')
    return {'shop_id': str(item['shop_id']), 'shop_name': item.get('shop_name'), 'url': item.get('url'),
            'transaction_sold_count': item.get('transaction_sold_count'),
            'listing_active_count': item.get('listing_active_count'), 'digital_listing_count': item.get('digital_listing_count'),
            'shop_favorites': item.get('num_favorers'), 'review_count': item.get('review_count'),
            'review_average': item.get('review_average'), 'currency_code': item.get('currency_code'),
            'languages': item.get('languages'), 'is_vacation': item.get('is_vacation'),
            'created_timestamp': item.get('created_timestamp', item.get('create_date')),
            'created_at': timestamp(item.get('created_timestamp', item.get('create_date'))),
            'country_iso': item.get('shop_location_country_iso'), 'observed_at': observed_at,
            'source': 'etsy_api', 'provenance': provenance, 'normalization_version': VERSION,
            'metric_scope': {'transaction_sold_count': 'shop-wide Etsy transaction-sold counter; not listing sales or revenue',
                             'listing_active_count': 'shop-wide active listings at observation',
                             'shop_favorites': 'shop-wide favorites; distinct from listing favorites'}}
