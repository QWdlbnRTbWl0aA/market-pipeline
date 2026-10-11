"""Temporary file intake. Decoders isolate source-specific field mapping."""
import hashlib
import json
from pathlib import Path
from ..ports import IntakeBatch


def canonical(document):
    if not isinstance(document, dict) or not isinstance(document.get('records'), list):
        raise ValueError('Canonical JSON requires records and optional metadata objects')
    return document['records'], document.get('metadata', {})


def etsy_export(document):
    if not isinstance(document, dict):raise ValueError('Etsy export must be an object')
    rows = document.get('listings')
    if rows is None:rows = document.get('results', {}).get('listings')
    if rows is None and isinstance(document.get('queries'), list):
        rows = [row for query in document['queries'] for row in query.get('listings', [])]
    if not isinstance(rows, list):raise ValueError('No saved listing array in Etsy export')
    records = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            records.append(row);continue
        records.append({'id': 'etsy:listing:' + str(row['listing_id']) if row.get('listing_id') is not None else None,
                        'title': row.get('title'), 'description': row.get('description'), 'tags': row.get('tags'), 'images': row.get('images'),
                        'category': 'taxonomy:' + str(row['taxonomy_id']) if row.get('taxonomy_id') is not None else None,
                        'seller_id': str(row['shop_id']) if row.get('shop_id') is not None else None,
                        'price': row.get('price'), 'currency': row.get('currency'), 'digital': row.get('digital'),
                        'original_created_at': row.get('original_created_at'), 'last_modified_at': row.get('updated_at',row.get('last_modified_at')), 'state': row.get('state'), 'observed_at': row.get('observed_at'),
                        'metrics': [{'scope': 'listing', 'name': 'views', 'value': row.get('listing_views')},
                                    {'scope': 'listing', 'name': 'favorites', 'value': row.get('listing_favorites')}],
                        'provenance': {'record_index': index, 'source_id': row.get('listing_id'),
                                       'url': row.get('url'), 'source_provenance': row.get('provenance')}})
    metadata = document.get('metadata', document)
    return records, {'source': 'etsy', 'source_run_id': metadata.get('run_id'), 'source_status': metadata.get('status'),
                     'query_context': metadata.get('settings', document.get('search_parameters')),
                     'intake_dqa': document.get('dqa'), 'source_summary': document.get('summary')}


class JsonFileIntake:
    def __init__(self, path, decoder=canonical):
        self.path, self.decoder = Path(path), decoder

    def read(self):
        if self.path.stat().st_size > 100_000_000:raise ValueError('File intake exceeds prototype 100 MB bound')
        body = self.path.read_bytes()
        document = json.loads(body)
        records, metadata = self.decoder(document)
        if not isinstance(metadata, dict):raise ValueError('Intake metadata must be an object')
        return IntakeBatch(records, metadata, {'input_path': str(self.path.resolve()), 'input_sha256': hashlib.sha256(body).hexdigest(),
                                            'input_bytes': len(body), 'decoder': self.decoder.__name__})
