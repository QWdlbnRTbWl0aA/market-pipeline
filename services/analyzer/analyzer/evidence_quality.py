"""Mechanical evidence context, never inferred sales or a market success score."""
from collections import defaultdict
import datetime as dt
import hashlib
import math
import re
import statistics


def instant(value):
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp if stamp.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def metric(row, name):
    value = next((m.get('value') for m in row.get('metrics', [])
                  if m.get('scope') == 'listing' and m.get('name') == name), None)
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def description_context(description, limit=3000):
    """Keep bounded verbatim sections, including specifications late in long copy.

    Offsets and SHA refer to the normalized saved description. Ellipses indicate
    omitted sections. No generated summary can silently replace source wording.
    """
    description = description or ''
    if len(description) <= limit:
        return {'text': description, 'truncated': False, 'characters': len(description),
                'sha256': hashlib.sha256(description.encode()).hexdigest()}
    sentences = list(re.finditer(r'[^\n.!?]+[.!?]?', description))
    selected = [(0, min(600, len(description)))]; remaining = limit - 620
    terms = r'\b(include\w*|page\w*|sheet\w*|card\w*|mat\w*|pdf|size\w*|letter|a4|knife|scissor\w*|assemble\w*|instruction\w*|color\w*|colour\w*|inch\w*|cm|cut\w*|use\w*|age\w*|watercolor|watercolour|style|font\w*|editable|dpi)\b'
    ranked = sorted(sentences, key=lambda m: (-len(re.findall(terms, m.group(), re.I)), m.start()))
    for match in ranked:
        start, end = match.span()
        if any(start < b and end > a for a, b in selected):
            continue
        length = min(end-start, 650, remaining-20)
        if length <= 0: break
        selected.append((start, start+length)); remaining -= length+20
    selected.sort()
    return {'text': '\n[…]\n'.join(description[a:b] for a,b in selected), 'truncated': True,
            'characters': len(description), 'selected_spans': selected,
            'sha256': hashlib.sha256(description.encode()).hexdigest()}


def profile(rows, as_of):
    stamp = instant(as_of); ages = []; by_shop = defaultdict(lambda: {'favorites': 0, 'views': 0})
    listing_favorites = []; unknown = 0; young = 0
    for row in rows:
        original = instant(row.get('original_created_at'))
        age = (stamp-original).total_seconds()/86400 if stamp and original and original <= stamp else None
        if age is None: unknown += 1
        else:
            ages.append(age); young += age < 30
        for name in ('favorites', 'views'):
            value = metric(row, name)
            if value is not None and row.get('seller_id'): by_shop[row['seller_id']][name] += value
        listing_favorites.append(metric(row, 'favorites') or 0)
    total = sum(listing_favorites)
    leader = max(by_shop, key=lambda shop: by_shop[shop]['favorites'], default=None)
    remaining = [r for r in rows if r.get('seller_id') != leader] if leader else []
    return {'original_age_days_median': statistics.median(ages) if ages else None,
            'age_known': len(ages), 'age_unknown': unknown, 'younger_than_30_days': young,
            'top_listing_favorite_share': max(listing_favorites, default=0)/total if total else None,
            'top_shop_favorite_share': by_shop[leader]['favorites']/total if total and leader else None,
            'favorite_positive_shops': sum(s['favorites'] > 0 for s in by_shop.values()),
            'leave_leading_shop_out': {'excluded_shop_id': leader, 'listings': len(remaining),
                'shops': len({r['seller_id'] for r in remaining if r.get('seller_id')}),
                'favorites': sum(metric(r, 'favorites') or 0 for r in remaining),
                'views': sum(metric(r, 'views') or 0 for r in remaining),
                'favorite_positive_shops': len({r['seller_id'] for r in remaining if r.get('seller_id') and (metric(r, 'favorites') or 0)>0})},
            'scope': 'Cumulative engagement, original listing age and seller replication; age is exposure context, not a sales velocity estimate. Missing metrics remain unknown.'}
