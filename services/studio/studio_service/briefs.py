"""Deterministic sufficiency and adapters for Product handoffs and direct briefs."""
from .storage import Invalid, reject_secrets

QUESTIONS = {
    'concept': 'איזה מוצר ניצור?',
    'audience': 'למי מיועד המוצר?',
    'purpose': 'מה המוצר מאפשר לעשות?',
    'deliverables': 'אילו תמונות, עמודים או קבצים כלולים?',
    'visual_direction': 'איזה סגנון או כיוון חזותי תרצו?'}
PLACEHOLDERS = {'tbd', 'unknown', 'n/a', 'todo', 'not specified'}


def text(value, maximum=8000):
    if isinstance(value, dict): value = value.get('text')
    if value is None: return ''
    if not isinstance(value, str) or len(value) > maximum: raise Invalid('Brief fields must be bounded text')
    return value.strip()


def normalize(document):
    if not isinstance(document, dict): raise Invalid('Brief object required')
    reject_secrets(document)
    source = document.get('source_requirements', document.get('product_brief', document))
    if not isinstance(source, dict): raise Invalid('Structured brief required')
    deliverables = source.get('deliverables', document.get('deliverables', []))
    if not isinstance(deliverables, list) or len(deliverables) > 30: raise Invalid('At most thirty deliverables required')
    directions = document.get('design_directions')
    visual = source.get('visual_direction', document.get('visual_direction'))
    if visual is None and isinstance(directions, list) and directions:
        visual = ' / '.join(text(d.get('name') or d.get('title')) for d in directions if isinstance(d, dict))
    return {'concept': text(source.get('concept') or source.get('product_concept') or document.get('vision')),
            'audience': text(source.get('audience') or source.get('intended_customer') or document.get('customer')),
            'purpose': text(source.get('purpose') or source.get('customer_job') or document.get('customer_job')),
            'deliverables': [text(d) for d in deliverables], 'visual_direction': text(visual),
            'requirements': text(source.get('requirements', document.get('requirements')))}


def missing(brief):
    result = []
    for name in QUESTIONS:
        value = brief[name]
        if name == 'deliverables': good = bool(value) and all(v and v.casefold() not in PLACEHOLDERS for v in value)
        else: good = bool(value) and value.casefold() not in PLACEHOLDERS
        if not good: result.append({'field': name, 'question': QUESTIONS[name]})
    return result


def settings(value):
    if not isinstance(value, dict) or set(value) != {'width', 'height', 'unit', 'dpi', 'format', 'color_mode', 'bleed_mm'}:
        raise Invalid('Complete final size, resolution and format settings required')
    for name in ('width', 'height'):
        if type(value[name]) not in (int, float) or not 0 < value[name] <= 8192: raise Invalid('Invalid final dimensions')
    if value['unit'] not in ('px', 'mm', 'in') or type(value['dpi']) is not int or not 72 <= value['dpi'] <= 600:
        raise Invalid('Invalid units or resolution')
    if value['format'] not in ('svg','png') or value['color_mode'] not in ('color', 'grayscale'):
        raise Invalid('The mock provider supports SVG with color or grayscale')
    if type(value['bleed_mm']) not in (int, float) or not 0 <= value['bleed_mm'] <= 10: raise Invalid('Invalid bleed')
    scale = 1 if value['unit'] == 'px' else value['dpi'] / (25.4 if value['unit'] == 'mm' else 1)
    pixels = [round(value[name] * scale) for name in ('width', 'height')]
    if any(n < 64 or n > 8192 for n in pixels): raise Invalid('Final dimensions must resolve to 64–8192 pixels')
    return {**value, 'pixel_width': pixels[0], 'pixel_height': pixels[1]}
