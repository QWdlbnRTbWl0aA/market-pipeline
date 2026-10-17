"""Durable independent product definition; immutable source recommendations."""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

VERSION = 'product-handoff-v4.2-visual-references'
MAX_BYTES = 5_000_000


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clean_environment():
    if any(n.upper().startswith(('ETSY', 'OPENAI', 'ANTHROPIC', 'SMTP')) for n in os.environ):
        raise ValueError('Use the clean standalone launcher; provider credentials are forbidden')


def reject_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key).lower()
            if name in {'api_key', 'api_secret', 'authorization', 'credentials', 'access_token', 'password', 'smtp_password'} or name.endswith(('_api_key', '_api_secret')):
                raise ValueError('Credential fields forbidden')
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)


def valid_key(key):
    if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('Invalid delivery identity')
    return key


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 12000:
        raise ValueError('Nonempty bounded source text required')
    return value


def validate(payload):
    reject_secrets(payload)
    if not isinstance(payload, dict) or payload.get('service') != 'market_insights':
        raise ValueError('Market insights payload required')
    valid_key(payload.get('delivery_id'))
    envelope = payload.get('envelope')
    if envelope is not None and (not isinstance(envelope, dict) or envelope.get('schema_version') != 1 or envelope.get('event_type') != 'analysis_completed'):
        raise ValueError('Unsupported analysis envelope')
    if payload.get('status') != 'completed':
        return []  # Preserve failures, never turn them into product ideas.
    report = payload.get('report')
    if not isinstance(report, dict):
        raise ValueError('Structured analysis report required')
    rows = report.get('recommendations')
    if report.get('status')=='insufficient_evidence' and rows==[]:return []
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        raise ValueError('One to twelve model-authored recommendations required')
    identities = set()
    awaiting = False
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Structured recommendation required')
        identity = text(row.get('candidate_id'))
        if identity in identities:
            raise ValueError('Duplicate candidate identity')
        identities.add(identity)
        text(row.get('rationale'))
        brief = row.get('product_brief')
        if brief is None and report.get('status') == 'local_preview' and report.get('final_model_completed') is False:
            awaiting = True
            continue
        if not isinstance(brief, dict):
            raise ValueError('Structured product brief required')
        text(brief.get('product_concept'))
        for name in ('intended_customer', 'customer_job', 'differentiation'):
            if not isinstance(brief.get(name), dict):
                raise ValueError('Structured brief statement required')
            text(brief[name].get('text'))
        if not isinstance(brief.get('deliverables'), list) or not 1 <= len(brief['deliverables']) <= 20:
            raise ValueError('Concrete source deliverables required')
        for item in brief['deliverables']:
            if not isinstance(item, dict):
                raise ValueError('Structured deliverable required')
            text(item.get('text'))
        for name in ('acceptance_checks', 'validation_plan', 'risks'):
            if not isinstance(brief.get(name), list) or not 1 <= len(brief[name]) <= 20:
                raise ValueError('Source checks, validation and risks required')
            for item in brief[name]:
                text(item)
    return [] if awaiting else rows


def waiting_for_brief(payload):
    report = payload.get('report') or {}
    if not isinstance(report, dict) or not isinstance(report.get('recommendations'), list):
        return False
    return (report.get('status') == 'local_preview' and report.get('final_model_completed') is False
            and any(r.get('product_brief') is None for r in report.get('recommendations', [])))


class SavedReportIntake:
    """Replaceable intake: local saved analysis JSON only, no URLs or source clients."""
    def read(self, path):
        path = Path(path)
        if path.suffix != '.json' or path.is_symlink() or any(p.startswith('.env') for p in path.parts):
            raise ValueError('Regular saved analysis JSON required')
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Saved report too large')
        body = path.read_bytes()
        validate(json.loads(body))
        return body


def process(body, output_root, model=None, visual_settings=None, visual_fetcher=None):
    clean_environment()
    if visual_settings is not None:
        from .visual_references import policy as visual_policy,GuardedFetch
        visual_settings=visual_policy(visual_settings)
        if visual_settings['enabled']:
            from PIL import Image  # Validate the optional runtime before any inference.
        visual_fetcher=visual_fetcher or GuardedFetch(Path(output_root)/'visual-access')
    if len(body) > MAX_BYTES:
        raise ValueError('Payload too large')
    payload = json.loads(body)
    rows = validate(payload)
    digest = hashlib.sha256(body).hexdigest()
    job = hashlib.sha256((payload['delivery_id'] + VERSION).encode()).hexdigest()
    directory = Path(output_root) / job
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        state = directory / 'state.json'
        if state.exists():
            previous = json.loads(state.read_text())
            if previous['input_sha256'] != digest:
                raise ValueError('Delivery identity reused with different content')
            if previous['status'] in ('completed', 'ignored_failed_analysis', 'ignored_insufficient_evidence', 'awaiting_product_brief'):
                return {**previous, 'duplicate': True, 'directory': str(directory)}
        source = {'delivery_id': payload['delivery_id'], 'source_run_id': payload.get('source_run_id'),
                  'analysis_job_id': payload.get('job_id'), 'input_sha256': digest, 'envelope': payload.get('envelope')}
        write_json(directory / 'input.json', payload)
        write_json(state, {**source, 'status': 'processing', 'started_at': now()})
        products = []
        from . import briefing
        try:
            # Validate references for every item before starting any inference.
            for row in rows:briefing.context(row)
            if rows:model=model or briefing.default_model()
            for index, row in enumerate(rows, 1):
                folder = directory / ('product-%02d' % index)
                folder.mkdir(exist_ok=True)
                definition,samples,metadata = briefing.define(row,folder,model)
                brief=row['product_brief']
                product={'schema_version':3,'recipe_version':VERSION,'candidate_id':row['candidate_id'],
                    'source':source,'stage':'defined_for_studio','launch_approved':False,
                    'vision':definition['title'],'customer':{'text':definition['audience'],'basis':'design_hypothesis'},
                    'customer_job':{'text':definition['customer_job'],'basis':'design_hypothesis'},
                    'why_selected':row['rationale'],'analysis_direction':brief,
                    'definition':definition,'samples':samples,'evidence':samples,'market_context':row.get('facts',{}),
                    'deliverables':[{'text':c['name']+': '+'; '.join(c['content']),'basis':'design_hypothesis','evidence_ids':c['evidence_ids']} for c in definition['components']],
                    'visual_direction':definition['first_sketch']['style'],'visual_basis':'Proposed original direction from text; no competitor image inspection performed',
                    'acceptance_checks':definition['acceptance_checks'],'validation_plan':brief['validation_plan'],
                    'risks':brief['risks'],'generation':metadata,'drafts':[],
                    'artwork_status':'Not generated; exact first-sketch specification supplied to Studio'}
                # The Studio's existing adapter prioritizes source_requirements.
                # Populate it with Product's complete definition, keeping the
                # original Analyzer direction separately for auditability.
                product['source_requirements']={'product_concept':definition['title'],
                    'intended_customer':product['customer'],'customer_job':product['customer_job'],
                    'deliverables':product['deliverables'],'visual_direction':product['visual_direction'],
                    'requirements':json.dumps({'scope':definition['scope'],'product_mechanism':definition['product_mechanism'],
                        'first_sketch':definition['first_sketch'],'production_files':definition['production_files'],
                        'acceptance_checks':definition['acceptance_checks']},ensure_ascii=False,separators=(',',':'))}
                if len(product['source_requirements']['requirements'])>8000:
                    raise ValueError('Studio normalized requirements bound exceeded')
                if visual_settings is not None:
                    from .visual_references import enrich
                    product=enrich(product,folder,visual_settings,visual_fetcher)
                if len(json.dumps(product,ensure_ascii=False,indent=2).encode())>890000:
                    raise ValueError('Studio brief size bound exceeded')
                write_json(folder / 'product.json', product)
                document=briefing.document(product)
                (folder / 'brief.md').write_text(document)
                (folder / 'brief.html').write_text(briefing.html_document(document))
                products.append({'directory': folder.name, 'vision': product['vision'], 'candidate_id': product['candidate_id'],
                                 'brief':product})
            write_json(directory / 'studio-handoff.json', {'source': source, 'products': products, 'delivery': 'local_studio_outbox', 'finished_products_generated': False})
            result = {**source, 'status': 'completed' if rows else 'awaiting_product_brief' if waiting_for_brief(payload) else 'ignored_insufficient_evidence' if payload.get('status')=='completed' else 'ignored_failed_analysis',
                      'products': len(products), 'drafts_per_product': 0, 'brief_recipe':VERSION, 'finished_at': now(), 'duplicate': False}
        except Exception as error:
            write_json(state, {**source, 'status': 'failed', 'error_type': type(error).__name__, 'finished_at': now()})
            raise
        write_json(state, result)
        return {**result, 'directory': str(directory)}
