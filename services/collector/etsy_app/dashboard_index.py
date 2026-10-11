"""Compact derived metadata and incrementally parsed request history. No DB."""
import json
import re
from pathlib import Path
import threading


def signature(path):
    value = path.stat()
    return [value.st_mtime_ns, value.st_size]


def snapshot_signature(path):
    pointer = path.parent.parent.parent/'derived'/path.parent.name/'current.json'
    return signature(path)+(signature(pointer) if pointer.exists() else [None,None])


def index_snapshot(path, run):
    """Called by snapshot writes; originals/raw files are never rewritten here."""
    from .core import atomic_json
    path = Path(path)
    if path.name != 'snapshot.json' or path.parent.parent.name != 'runs':
        return
    root = path.parent.parent.parent
    if not isinstance(run,dict) or run.get('run_id') != path.parent.name or any(key not in run for key in ('status','started_at','finished_at','trigger','listing_count')):
        raise ValueError('Invalid run metadata')
    effective = run
    pointer = root/'derived'/path.parent.name/'current.json'
    if pointer.exists():
        version = json.loads(pointer.read_text())['version']
        if not isinstance(version,str) or not re.fullmatch(r'[a-f0-9]{64}',version):
            raise ValueError('Invalid derived pointer')
        effective = json.loads((pointer.parent/version/'snapshot.json').read_text())
    card = {key: run.get(key) for key in ('run_id', 'status', 'started_at', 'finished_at', 'trigger', 'listing_count')}
    if run.get('status') == 'running':
        card['listing_count'] = sum(len(query.get('listings', [])) for query in run.get('queries', []))
    shops = [{'shop_id': str(record['shop_id']), 'shop_name': record['shop'].get('shop_name')}
             for record in effective.get('shops', []) if record.get('shop') and record.get('shop_id')]
    legacy = [{'request_id': f"legacy-{run['run_id']}-{index}", 'source': 'api', 'started_at': query.get('requested_at')}
              for index, query in enumerate(effective.get('queries', []))
              if query.get('source') == 'api' and query.get('http_status') is not None and not query.get('request_id')]
    document = {'schema_version': 1, 'source_signature': snapshot_signature(path), 'run': card, 'shops': shops, 'legacy_requests': legacy}
    atomic_json(root / 'dashboard-index' / (path.parent.name+'.json'), document)
    return document


class DashboardIndex:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self.cards = {}
        self.request_records = {}
        self.request_directory_signature = None

    def documents(self):
        with self.lock:
            documents = []
            paths = sorted((self.directory/'runs').glob('*/snapshot.json'), reverse=True)
            existing = {str(path) for path in paths}
            self.cards = {path: entry for path, entry in self.cards.items() if path in existing}
            for path in paths:
                try:
                    stamp = snapshot_signature(path)
                    cached = self.cards.get(str(path))
                    if cached and cached[0] == stamp:
                        documents.append(cached[1]);continue
                    metadata_path = self.directory/'dashboard-index'/(path.parent.name+'.json')
                    try:
                        doc = json.loads(metadata_path.read_text())
                        if doc.get('schema_version') != 1 or doc.get('source_signature') != stamp:
                            raise ValueError('Stale index')
                        if not isinstance(doc['run'], dict) or not isinstance(doc['legacy_requests'], list) or not isinstance(doc['shops'], list):
                            raise ValueError('Invalid index')
                    except (ValueError, KeyError, OSError, TypeError):
                        doc = index_snapshot(path, json.loads(path.read_text()))
                    self.cards[str(path)] = (stamp, doc)
                    documents.append(doc)
                except (ValueError, OSError, KeyError, TypeError):
                    documents.append({'run': {'run_id': path.parent.name, 'status': 'corrupt', 'listing_count': 0}, 'shops': [], 'legacy_requests': []})
            return documents

    def runs(self):
        return [document['run'] for document in self.documents()]

    def shops(self):
        known = {}
        for document in self.documents():
            for shop in document['shops']:
                known.setdefault(shop['shop_id'], shop)
        return list(known.values())

    def requests(self):
        """Atomic ledger replacement changes directory mtime; validate every read.

        New/changed/deleted records are reconciled before returning, so this
        cache does not turn dashboard polling into cached admission decisions.
        Counters and quotas are always recomputed using the caller's current time.
        """
        with self.lock:
            directory = self.directory/'requests'
            for _ in range(3):
                stamp = signature(directory) if directory.exists() else None
                if stamp == self.request_directory_signature:
                    break
                paths = list(directory.glob('*.json'))
                names = {str(path) for path in paths}
                self.request_records = {path: item for path, item in self.request_records.items() if path in names}
                for path in paths:
                    try:
                        file_stamp = signature(path)
                        cached = self.request_records.get(str(path))
                        if not cached or cached[0] != file_stamp:
                            self.request_records[str(path)] = (file_stamp, json.loads(path.read_text()))
                    except (ValueError, OSError):
                        self.request_records.pop(str(path), None)
                current = signature(directory) if directory.exists() else None
                if current == stamp:
                    self.request_directory_signature = stamp
                    break
            else:
                raise RuntimeError('Request ledger is changing; retry before admission')
            records = [item[1] for item in self.request_records.values()]
            records += [event for document in self.documents() for event in document['legacy_requests']]
            return records
