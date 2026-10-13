"""Identity/date indexed saved histories; no source configuration or network access."""
import datetime as dt
import json
import hashlib
from pathlib import Path
from .saved_intake import SavedCollectionIntake
from .security import reject_secrets


def instant(value):
    if not isinstance(value, str): return None
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp if stamp.tzinfo else None
    except ValueError: return None


def metric(row, name):
    return next((v.get('value') for v in row.get('metrics', []) if isinstance(v, dict) and v.get('scope') == 'listing' and v.get('name') == name), None)


def series_summary(rows, metrics, scope):
    """Duplicate timestamps and counter corrections cannot become trend evidence."""
    ordered = {}
    duplicates = []
    for row in rows:
        stamp = instant(row.get('observed_at'))
        if stamp is None: continue
        values = {k: row.get(k) if scope == 'shop' else metric(row, k) for k in metrics}
        if stamp in ordered and ordered[stamp][0] != values: duplicates.append(stamp.isoformat())
        ordered.setdefault(stamp, (values, row))
    points = sorted(ordered.items()); span = (points[-1][0] - points[0][0]).total_seconds()/86400 if len(points) > 1 else 0
    intervals = []
    for (a, (av, ar)), (b, (bv, br)) in zip(points, points[1:]):
        changes = {}
        for k in metrics:
            before, after = av[k], bv[k]
            valid = type(before) in (int, float) and type(after) in (int, float)
            reset = valid and after < before
            changes[k] = {'before': before, 'after': after, 'change': after-before if valid else None,
                          'reset_or_correction': bool(reset), 'missing': not valid,
                          'per_day': (after-before)/((b-a).total_seconds()/86400) if valid and not reset and (b-a).total_seconds() >= 86400 else None}
        price = {'before': ar.get('price'), 'after': br.get('price'), 'currency': br.get('currency'),
                 'comparable': ar.get('currency') is not None and ar.get('currency') == br.get('currency')}
        price['change'] = price['after']-price['before'] if price['comparable'] and type(price['before']) in (int,float) and type(price['after']) in (int,float) else None
        intervals.append({'from': a.isoformat(), 'to': b.isoformat(), 'days': (b-a).total_seconds()/86400,
                          'metrics': changes, 'price': price, 'state': {'before': ar.get('state'), 'after': br.get('state')},
                          'original_creation_changed': bool(ar.get('original_created_at') is not None and br.get('original_created_at') is not None and ar.get('original_created_at') != br.get('original_created_at')),
                          'source_run_ids': [ar.get('source_run_id'), br.get('source_run_id')]})
    resets = any(v['reset_or_correction'] for d in intervals for v in d['metrics'].values())
    comparable_metrics = {k: sum(type(v[0][k]) in (int,float) for v in ordered.values()) for k in metrics}
    metric_spans = {}
    for k in metrics:
        stamps = [stamp for stamp,(values,_) in points if type(values[k]) in (int,float)]
        metric_spans[k] = (stamps[-1]-stamps[0]).total_seconds()/86400 if len(stamps)>1 else 0
    creation_changed = any(v['original_creation_changed'] for v in intervals)
    ready = any(comparable_metrics[k] >= 3 and metric_spans[k] >= 7 for k in metrics) and not resets and not duplicates and not creation_changed
    return {'scope': scope, 'observations': len(points), 'span_days': span, 'comparable_metric_observations': comparable_metrics,
            'metric_span_days': metric_spans, 'original_creation_changed': creation_changed, 'minimum_observations': 3, 'minimum_span_days': 7, 'preferred_span_days': None,
            'trend_status': 'engagement_proxy_ready' if ready and scope == 'listing' else 'shop_counter_trend_ready' if ready else 'insufficient_evidence',
            'duplicate_timestamp_conflicts': duplicates, 'counter_reset_or_correction': resets, 'intervals': intervals,
            'purchase_demand_verified': False, 'listing_sales': None}


class HistoryIntake:
    def __init__(self, root, run_id, limit=None, days=None, cohort_root=None, as_of=None):
        self.current = SavedCollectionIntake(root, run_id); self.days = days; self.cohort_root=Path(cohort_root) if cohort_root else None; self.as_of=as_of
        if days is not None and (type(days) is not int or not 7 <= days <= 90): raise ValueError('Invalid explicit history date window')

    def floor(self, finished):
        return finished-dt.timedelta(days=self.days) if self.days is not None else dt.datetime.min.replace(tzinfo=dt.timezone.utc)

    def candidates(self, records, sellers, finished):
        root = self.current.root; floor = self.floor(finished)
        index_path = root.parent/'index.json'
        candidates = set(); indexed = False
        if index_path.exists() and not index_path.is_symlink() and index_path.stat().st_size <= 100_000_000:
            index = json.loads(index_path.read_bytes()); reject_secrets(index)
            for kind, ids in [('by_listing', {k.removeprefix('etsy:listing:') for k in records}), ('by_shop', sellers)]:
                for key in ids:
                    for row in index.get(kind, {}).get(key, []):
                        stamp = instant(row.get('observed_at'))
                        if stamp and floor <= stamp <= finished and isinstance(row.get('run_id'), str): candidates.add(row['run_id'])
            indexed = True
        # Fallback is date bounded, never the newest N directories. The index is
        # rebuildable and may be stale: scan compact run metadata for missing runs.
        for directory in root.iterdir():
            if not directory.is_dir() or directory.is_symlink() or directory.name == self.current.directory.name: continue
            try:
                card = root.parent/'dashboard-index'/(directory.name+'.json')
                if card.exists() and not card.is_symlink(): stamp = instant(json.loads(card.read_text()).get('run', {}).get('finished_at'))
                else:
                    saved, _ = SavedCollectionIntake(root, directory.name)._read('snapshot.json'); stamp = instant(saved.get('finished_at'))
                if stamp and floor <= stamp <= finished: candidates.add(directory.name)
            except (ValueError, TypeError, KeyError, OSError): continue
        candidates.discard(self.current.directory.name)
        return sorted(candidates), indexed

    def cohort_records(self, batch, finished):
        ids=set();signatures=[]
        if not self.cohort_root:return
        for path in self.cohort_root.glob('*.json'):
            if path.is_symlink() or path.stat().st_size>100000:raise ValueError('Unsafe cohort artifact')
            value=json.loads(path.read_text());reject_secrets(value)
            if value.get('status') not in ('active','completed_window') or not value.get('approval'):continue
            manifest=value['manifest'];sha=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            if sha!=value.get('manifest_sha256') or value['approval'].get('manifest_sha256')!=sha:raise ValueError('Cohort approval/hash mismatch')
            ids.update('etsy:listing:'+str(k) for k in manifest['listing_ids']);signatures.append(sha)
        if not ids:return
        selected={};shop_rows={};used=[]
        # Successful saved snapshots only, as of the discovery finalization or
        # an explicit report refresh. No controller/collector configuration reads.
        for directory in self.current.root.iterdir():
            if not directory.is_dir() or directory.is_symlink():continue
            try:
                old=SavedCollectionIntake(self.current.root,directory.name).read();stamp=instant(old.metadata['finished_at'])
                if stamp is None or not self.floor(finished)<=stamp<=finished:continue
                matched=False
                for row in old.records:
                    if row.get('id') not in ids:continue
                    observed=instant(row.get('observed_at'))
                    if observed is None or observed>finished:continue
                    if row['id'] not in selected or observed>selected[row['id']][0]:selected[row['id']]=(observed,row,directory.name)
                    matched=True
                if matched:
                    used.append({'source_run_id':directory.name,'input_sha256':old.provenance['input_sha256']})
                    for shop in old.metadata.get('shops',[]):
                        observed=instant(shop.get('observed_at'));key=str(shop['shop_id'])
                        if observed and observed<=finished and (key not in shop_rows or observed>shop_rows[key][0]):shop_rows[key]=(observed,shop)
            except (ValueError,OSError,TypeError,KeyError):continue
        existing={r['id'] for r in batch.records if isinstance(r,dict) and r.get('id')};added=[]
        for key,(_,row,run_id) in selected.items():
            if key in existing:continue
            row=json.loads(json.dumps(row))
            for image in row.get('images') or []:
                if isinstance(image,dict) and image.get('local_path'):image['artifact_run_id']=run_id
            row['provenance']={**row.get('provenance',{}),'intake_role':'approved_tracked_cohort_context','artifact_run_id':run_id}
            batch.records.append(row);added.append(key)
        sellers={r.get('seller_id') for r in batch.records if isinstance(r,dict)}
        existing_shops={str(s['shop_id']) for s in batch.metadata.get('shops',[])}
        batch.metadata.setdefault('shops',[]).extend(shop for key,(_,shop) in shop_rows.items() if key in sellers and key not in existing_shops)
        batch.metadata['cohort_context']={'selected_listing_ids':sorted(ids),'added_listing_ids':added,'sources':sorted(used,key=lambda r:r['source_run_id']),
            'manifest_sha256s':sorted(signatures),'as_of':finished.isoformat(),'scope':'Approved tracked identities from saved artifacts; separate from new discovery rows and current query supply.'}

    def read(self):
        batch = self.current.read()
        finished = instant(batch.metadata['finished_at'])
        if self.as_of:
            refresh=instant(self.as_of)
            if refresh is None or refresh<finished or refresh>dt.datetime.now(dt.timezone.utc):raise ValueError('Explicit refresh time must be between source finalization and now')
            finished=refresh;batch.metadata['refresh_as_of']=refresh.isoformat()
        self.cohort_records(batch,finished)
        batch.metadata['semantic_context']={'refresh_as_of':batch.metadata.get('refresh_as_of'),'cohort_context_sha256':hashlib.sha256(json.dumps(batch.metadata.get('cohort_context'),sort_keys=True).encode()).hexdigest() if batch.metadata.get('cohort_context') else None}
        records = {r['id']: r for r in batch.records if isinstance(r,dict) and r.get('id')}
        sellers = {r.get('seller_id') for r in records.values() if r.get('seller_id')}
        candidates, indexed = self.candidates(records, sellers, finished)
        related, exact, issues = [], [], []
        for run_id in candidates:
            try:
                prior = SavedCollectionIntake(self.current.root, run_id).read(); stamp = instant(prior.metadata['finished_at'])
                if stamp is None or stamp > finished or stamp < self.floor(finished): continue
                selected = [r for r in prior.records if r.get('id') in records]
                shops = [r for r in prior.metadata.get('shops', []) if str(r.get('shop_id')) in sellers]
                if not selected and not shops: continue
                related.append({'run_id': run_id, 'input_sha256': prior.provenance['input_sha256'], 'finished_at': prior.metadata['finished_at'],
                    'artifact_kind': prior.metadata.get('artifact_kind'), 'shops': shops,
                    'shop_inventory_profiles':{seller:[{k:r.get(k) for k in ('id','title','tags','category','digital')} for r in prior.records if r.get('seller_id')==seller] for seller in sellers},
                    'listings': [{k: r.get(k) for k in ('id', 'seller_id', 'observed_at', 'metrics', 'price', 'currency', 'state', 'original_created_at', 'last_modified_at', 'images', 'provenance')} for r in selected]})
                if prior.metadata['query_context'] == batch.metadata['query_context']:
                    deltas = []
                    for row in selected:
                        for name in ('views','favorites'):
                            before, after = metric(row,name), metric(records[row['id']],name)
                            if type(before) in (int,float) and type(after) in (int,float):
                                deltas.append({'listing_id': row['id'], 'metric': name, 'before': before, 'after': after, 'change': after-before,
                                               'negative_change': after < before, 'days': (finished-stamp).total_seconds()/86400})
                    exact.append({'run_id': run_id, 'input_sha256': prior.provenance['input_sha256'], 'finished_at': prior.metadata['finished_at'], 'matched_query': True, 'listing_deltas': deltas})
                for row in selected:
                    for image in row.get('images') or []:
                        if isinstance(image,dict) and image.get('local_path'):
                            saved = {**image, 'artifact_run_id': run_id}
                            if saved not in (records[row['id']].get('images') or []): records[row['id']].setdefault('images',[]).append(saved)
            except (OSError,ValueError,TypeError,KeyError) as error: issues.append({'run_id': run_id, 'error_type': type(error).__name__})
        listing_series = {key: [{**row, 'source_run_id': batch.metadata['source_run_id']}] for key,row in records.items()}
        shop_series = {str(s['shop_id']): [{**s, 'source_run_id': batch.metadata['source_run_id']}] for s in batch.metadata.get('shops', []) if str(s.get('shop_id')) in sellers}
        for observation in related:
            for row in observation['listings']: listing_series[row['id']].append({**row, 'source_run_id': observation['run_id']})
            for row in observation['shops']: shop_series.setdefault(str(row['shop_id']), []).append({**row, 'source_run_id': observation['run_id']})
        batch.metadata['history'] = {'method': 'Identity index plus date-window completeness scan, frozen at current finalization',
            'window_days': self.days, 'as_of': finished.isoformat(), 'indexed': indexed, 'checked_directories': len(candidates),
            'observations': exact, 'related_observations': related, 'issues': issues,
            'listing_series': {k: series_summary(v, ('views','favorites'), 'listing') for k,v in listing_series.items()},
            'shop_series': {k: series_summary(v, ('transaction_sold_count','listing_active_count','shop_favorites'), 'shop') for k,v in shop_series.items()},
            'scope': 'Listing engagement and whole-shop counters remain separate; purchases/demand unverified.',
            'related_scope': 'Identity-matched saved observations across all queries and tracking within the date window; missing days stay missing.'}
        return batch
