"""Offline identities from retained history and raw-response identity receipts."""
import json

def prior_identities(store):
    listings, shops = set(), set()
    # Read snapshots rather than trusting a potentially stale rebuilt index.
    for path in sorted(store.runs.glob('*/snapshot.json')):
        try:
            run = json.loads(path.read_text())
            receipt = run.get('fetched_identities', {})
            listings.update(map(str, receipt.get('listing_ids', [])))
            shops.update(map(str, receipt.get('shop_ids', [])))
            rows = [r for q in run.get('queries', []) for r in q.get('listings', [])]
            rows += [r['listing'] for r in run.get('tracked_listings', []) if r.get('listing')]
            listings.update(str(r['listing_id']) for r in rows)
            shops.update(str(r['shop_id']) for r in rows if r.get('shop_id'))
            shops.update(str(r['shop']['shop_id']) for r in run.get('shops', []) if r.get('shop'))
        except (OSError, ValueError, KeyError, TypeError):
            # Do not silently weaken exclusions when a history artifact is corrupt.
            raise ValueError('Cannot establish exclusions from saved history: '+path.parent.name) from None
    return listings, shops
