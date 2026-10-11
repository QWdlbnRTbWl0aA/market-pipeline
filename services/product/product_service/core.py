"""Deterministic stage-one studio brief composer; source recommendations stay intact."""
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
import textwrap

VERSION = 'studio-brief-v1'
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
    rows = payload.get('report', {}).get('recommendations')
    if payload.get('report',{}).get('status')=='insufficient_evidence' and rows==[]:return []
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        raise ValueError('One to twelve model-authored recommendations required')
    identities = set()
    for row in rows:
        identity = text(row.get('candidate_id'))
        if identity in identities:
            raise ValueError('Duplicate candidate identity')
        identities.add(identity)
        text(row.get('rationale'))
        brief = row.get('product_brief', {})
        text(brief.get('product_concept'))
        for name in ('intended_customer', 'customer_job', 'differentiation'):
            text(brief.get(name, {}).get('text'))
        if not isinstance(brief.get('deliverables'), list) or not 1 <= len(brief['deliverables']) <= 20:
            raise ValueError('Concrete source deliverables required')
        for item in brief['deliverables']:
            text(item.get('text'))
        for name in ('acceptance_checks', 'validation_plan', 'risks'):
            if not isinstance(brief.get(name), list) or not 1 <= len(brief[name]) <= 20:
                raise ValueError('Source checks, validation and risks required')
            for item in brief[name]:
                text(item)
    return rows


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


def svg_text(x, y, value, size=17, width=68, fill='#243d39'):
    lines = textwrap.wrap(value, width=width)[:4]
    return '<text x="%s" y="%s" font-family="Arial,sans-serif" font-size="%s" fill="%s">%s</text>' % (
        x, y, size, fill, ''.join('<tspan x="%s" dy="%s">%s</tspan>' % (x, 0 if i == 0 else size * 1.4, html.escape(line)) for i, line in enumerate(lines)))


def draft_svg(brief, kind):
    """Original layout wireframes. No competitor artwork, remote links or executable SVG."""
    title = brief['product_concept'].removeprefix('Design hypothesis: ')
    header = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 794 1123" role="img"><title>%s</title><rect width="794" height="1123" fill="#fffdf8"/><rect x="0" y="0" width="794" height="12" fill="#376458"/>' % html.escape(kind + ' rough layout')
    content = svg_text(44, 56, 'ROUGH LAYOUT / ' + kind.upper(), 14, 70, '#59766b')
    content += svg_text(44, 99, title, 23, 51)
    if kind == 'cover':
        content += '<rect x="44" y="250" width="706" height="480" rx="18" fill="#e3ece5" stroke="#91aa9c" stroke-dasharray="8 6"/>'
        content += svg_text(125, 465, 'Original illustration / product preview area', 22, 38)
        content += svg_text(125, 530, 'Studio to create artwork; no competitor assets', 16, 48)
        content += svg_text(44, 790, brief['intended_customer']['text'], 20, 58)
        content += svg_text(44, 930, 'Title, audience, file format and usage summary', 18, 60)
    elif kind == 'activity':
        content += svg_text(44, 245, 'Instruction and reviewed content placeholder', 20, 58)
        coloring = 'coloring' in title.lower()
        if coloring:
            content += '<rect x="44" y="300" width="706" height="535" rx="16" fill="none" stroke="#718a7e" stroke-width="3"/>'
            content += svg_text(145, 530, 'Original outline illustration goes here', 22, 38)
            content += svg_text(145, 595, 'Simple open shapes / generous coloring space', 17, 42)
        else:
            for index in range(6):
                x = 44 + (index % 2) * 367
                y = 300 + (index // 2) * 177
                content += '<rect x="%s" y="%s" width="339" height="154" rx="12" fill="%s" stroke="#718a7e" stroke-dasharray="5 4"/>' % (x, y, ['#e5efdf', '#f5e2db', '#e0e8f4'][index // 2])
                content += svg_text(x + 22, y + 53, 'Illustration placeholder', 16, 25)
                content += svg_text(x + 22, y + 99, 'Reviewed vocabulary + symbol', 15, 28)
        content += svg_text(44, 895, 'Prompt / practice / conversation area', 20, 62)
        content += '<path d="M44 950H750 M44 990H750" stroke="#a4b1a7"/>'
    elif kind == 'guide':
        for index, name in enumerate(('Setup and materials', 'How to use the product', 'Editorial and print checks')):
            y = 245 + index * 230
            content += svg_text(44, y, str(index + 1) + '. ' + name, 23, 52)
            value = brief['deliverables'][min(index, len(brief['deliverables']) - 1)]['text'] if index < 2 else brief['acceptance_checks'][0]
            content += svg_text(44, y + 47, value, 17, 77)
            content += '<path d="M44 %sH750" stroke="#b7c7be"/>' % (y + 160)
    else:
        raise ValueError('Unknown draft type')
    return header + content + svg_text(44, 1080, 'STUDIO CONCEPT — layout only; not a finished or sale-ready product', 13, 90) + '</svg>'


def studio_brief(row, source):
    brief = row['product_brief']
    return {'schema_version': 1, 'recipe_version': VERSION, 'candidate_id': row['candidate_id'],
            'source': source, 'stage': 'concept_for_studio', 'launch_approved': False,
            'vision': brief['product_concept'], 'customer': brief['intended_customer'],
            'customer_job': brief['customer_job'], 'why_selected': row['rationale'],
            'differentiation': brief['differentiation'], 'deliverables': brief['deliverables'],
            'acceptance_checks': brief['acceptance_checks'], 'validation_plan': brief['validation_plan'],
            'risks': brief['risks'], 'samples': row.get('evidence_excerpts', []),
            'production_defaults': {'basis': 'studio_process_defaults_not_market_evidence',
                'print_formats': ['A4', 'US Letter'], 'source_editability': 'Editable studio source plus print-ready PDF',
                'assets': 'Original or appropriately licensed; competitor samples are references only',
                'text_review': 'Audience expert review; check Hebrew RTL where applicable',
                'print_check': 'Legibility, margins, grayscale usability and no clipping'},
            'drafts': ['draft-cover.svg', 'draft-activity.svg', 'draft-guide.svg']}


def markdown(product):
    lines = ['# Studio product brief', '', product['vision'], '', '## Audience', '', product['customer']['text'],
             '', '## Customer job', '', product['customer_job']['text'], '', '## Why it was selected', '', product['why_selected'],
             '', '## Proposed distinction', '', product['differentiation']['text']]
    for name in ('deliverables', 'acceptance_checks', 'validation_plan', 'risks'):
        lines += ['', '## ' + name.replace('_', ' ').title(), '']
        lines += ['- ' + (v['text'] if isinstance(v, dict) else v) for v in product[name]]
    lines += ['', '## Studio defaults', '']
    lines += ['- ' + key.replace('_', ' ').title() + ': ' + (', '.join(value) if isinstance(value, list) else value) for key, value in product['production_defaults'].items() if key != 'basis']
    lines += ['', '## Rough drafts', '', 'Three original SVG layouts: cover, activity page and guide. These are wireframes for studio interpretation, not finished products.',
              '', '## Provenance', '', 'Source delivery: ' + product['source']['delivery_id'], 'Input SHA256: ' + product['source']['input_sha256'],
              '', 'Concept requires validation before launch. Evidence and source wording are retained in product.json and the saved input.']
    return '\n'.join(lines) + '\n'


def process(body, output_root):
    clean_environment()
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
            if previous['status'] in ('completed', 'ignored_failed_analysis', 'ignored_insufficient_evidence'):
                return {**previous, 'duplicate': True, 'directory': str(directory)}
        source = {'delivery_id': payload['delivery_id'], 'source_run_id': payload.get('source_run_id'),
                  'analysis_job_id': payload.get('job_id'), 'input_sha256': digest, 'envelope': payload.get('envelope')}
        write_json(directory / 'input.json', payload)
        write_json(state, {**source, 'status': 'processing', 'started_at': now()})
        products = []
        try:
            for index, row in enumerate(rows, 1):
                product = studio_brief(row, source)
                folder = directory / ('product-%02d' % index)
                folder.mkdir(exist_ok=True)
                write_json(folder / 'product.json', product)
                (folder / 'brief.md').write_text(markdown(product))
                for kind in ('cover', 'activity', 'guide'):
                    (folder / ('draft-' + kind + '.svg')).write_text(draft_svg(row['product_brief'], kind))
                products.append({'directory': folder.name, 'vision': product['vision'], 'candidate_id': product['candidate_id']})
            write_json(directory / 'studio-handoff.json', {'source': source, 'products': products, 'delivery': 'local_studio_outbox', 'finished_products_generated': False})
            links = ''.join('<article><h2>' + html.escape(x['vision']) + '</h2><p><a href="' + x['directory'] + '/brief.md">Text brief</a> · <a href="' + x['directory'] + '/product.json">Specification JSON</a></p>' + ''.join('<a href="' + x['directory'] + '/draft-' + k + '.svg"><img alt="' + k + ' draft" src="' + x['directory'] + '/draft-' + k + '.svg"></a>' for k in ('cover', 'activity', 'guide')) + '</article>' for x in products)
            (directory / 'index.html').write_text('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Studio handoff</title><style>body{font:16px/1.5 system-ui;margin:24px;background:#f4f7f5}article{background:white;padding:20px;margin:20px 0;border-radius:12px}img{width:30%;min-width:180px;max-width:320px;margin:1%}a{color:#17634b}</style></head><body><h1>Studio concepts</h1><p>Layout drafts and textual specifications for studio interpretation.</p>' + links + '</body></html>')
            result = {**source, 'status': 'completed' if rows else 'ignored_insufficient_evidence' if payload.get('status')=='completed' else 'ignored_failed_analysis',
                      'products': len(products), 'drafts_per_product': 3, 'finished_at': now(), 'duplicate': False}
        except Exception as error:
            write_json(state, {**source, 'status': 'failed', 'error_type': type(error).__name__, 'finished_at': now()})
            raise
        write_json(state, result)
        return {**result, 'directory': str(directory)}
