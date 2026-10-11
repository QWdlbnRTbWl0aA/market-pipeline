"""Read only finalized saved collection artifacts, never collector configuration."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from .adapters.json_file import etsy_export
from .ports import IntakeBatch
from .security import reject_secrets


class SavedCollectionIntake:
    def __init__(self, root, run_id):
        self.root = Path(root).resolve()
        if not run_id or Path(run_id).name != run_id or run_id in {'.', '..'}:
            raise ValueError('Invalid saved run identity')
        self.directory = self.root / run_id
        if self.directory.resolve().parent != self.root:
            raise ValueError('Run must reside inside configured saved-artifact root')

    def _read(self, name):
        path = self.directory / name
        if path.resolve().parent != self.directory.resolve() or path.is_symlink():
            raise ValueError('Artifact symlinks/escapes forbidden')
        if path.stat().st_size > 100_000_000:
            raise ValueError('Artifact exceeds 100 MB limit')
        body = path.read_bytes()
        value = json.loads(body)
        reject_secrets(value)
        return value, body

    def read(self):
        snapshot, body = self._read('snapshot.json')
        dqa, _ = self._read('dqa.json')
        if snapshot.get('trigger')=='count-probe' or any(q.get('niche',{}).get('category')=='Refiner count probe' for q in snapshot.get('queries',[])):
            raise ValueError('Count-only probes are not analysis datasets')
        if snapshot.get('run_id') != self.directory.name or snapshot.get('status') != 'success' or not snapshot.get('finished_at'):
            raise ValueError('Only finalized successful cycles are eligible')
        finished = dt.datetime.fromisoformat(snapshot['finished_at'].replace('Z', '+00:00'))
        if finished.tzinfo is None:
            raise ValueError('Finalization timestamp must include timezone')
        if not isinstance(snapshot.get('dqa'), dict) or snapshot['dqa'] != dqa:
            raise ValueError('Finalization incomplete: saved DQA must match snapshot DQA')
        records, metadata = etsy_export(snapshot)
        # Project only query context, not arbitrary source configuration.
        settings = snapshot.get('settings', {})
        metadata['query_context'] = {k: settings.get(k) for k in ('niches', 'limit', 'shop_ids', 'search_parameters', 'page_size', 'max_pages', 'exclude_fetched_listings', 'exclude_fetched_shops')}
        metadata['finished_at'] = snapshot['finished_at']
        metadata['artifact_kind'] = snapshot.get('artifact_kind') or ('tracking' if snapshot.get('mode') == 'tracking' else 'discovery')
        metadata['lineage'] = snapshot.get('lineage', {})
        metadata['query_coverage'] = [{k:q.get(k) for k in ('niche','shop_id','provider_result_count','reported_count_scope','collection_complete','pagination_stop')} for q in snapshot.get('queries',[])]
        metadata['source_dqa'] = dqa
        metadata['shops'] = [r['shop'] for r in snapshot.get('shops', []) if r.get('shop')]
        # Include successful daily-tracked listings as well as search listings.
        tracked = [r['listing'] for r in snapshot.get('tracked_listings', []) if r.get('status') == 'success' and r.get('listing')]
        if tracked:
            records += etsy_export({'listings': tracked})[0]
        # A collector may save images as relative local artifacts. URLs are retained
        # as provenance, but never fetched by this component.
        for row in records:
            row['images'] = row.get('images') or []
        return IntakeBatch(records, metadata, {'input_path': str(self.directory / 'snapshot.json'),
                           'input_sha256': hashlib.sha256(body).hexdigest(), 'input_bytes': len(body),
                           'decoder': 'finalized-saved-collection-v1', 'artifact_directory': str(self.directory)})


_DISCOVERY_CACHE = {}

def discover(root):
    root=Path(root).resolve();candidates=[];present=set()
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.is_symlink():continue
        key=str(directory);present.add(key)
        try:
            signature=tuple((p.stat().st_mtime_ns,p.stat().st_size) for p in (directory/'snapshot.json',directory/'dqa.json'))
            prior=_DISCOVERY_CACHE.get(key)
            if prior and prior['signature']==signature:
                finished=prior['finished']
            else:
                try:
                    batch=SavedCollectionIntake(root,directory.name).read();finished=batch.metadata['finished_at'];eligible=batch.metadata.get('artifact_kind')!='tracking'
                except (OSError,ValueError,TypeError,KeyError):finished=None;eligible=False
                _DISCOVERY_CACHE[key]={'signature':signature,'finished':finished,'eligible':eligible}
            if finished and _DISCOVERY_CACHE[key].get('eligible',True):candidates.append((finished,directory.name))
        except OSError:continue
    for key in list(_DISCOVERY_CACHE):
        if Path(key).parent==root and key not in present:del _DISCOVERY_CACHE[key]
    return [identity for _,identity in sorted(candidates)]

def finalization_time(root,identity):
    key=str(Path(root).resolve()/identity)
    if key not in _DISCOVERY_CACHE:discover(root)
    return _DISCOVERY_CACHE[key]['finished']
