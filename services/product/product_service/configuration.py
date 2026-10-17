"""Independent definition promotion policy; disabled until exact product-person review."""
import json
from pathlib import Path
from .core import reject_secrets
from .definition import VERSION, digest, OllamaDefinition

RUBRIC = {
 'audience_and_job':'Named customer and a specific usable task, consistent with source brief',
 'architecture':'Three concrete content units with tasks and source sample citations',
 'package':'Explicit end-user deliverables, editable studio source and print/use constraints',
 'quality':'Testable acceptance, accessibility and language/RTL review requirements',
 'visuals':'Two visibly distinct, concept-specific original directions with safe readable wireframes',
 'evidence':'Observed examples separate from proposed choices; missing performance remains review pending',
 'scope':'No actual product production, verified demand or launch approval'}


def load(path):
    path=Path(path)
    if path.is_symlink() or path.suffix!='.json' or any(p.startswith('.env') for p in path.parts) or path.stat().st_size>16384:raise ValueError('Independent bounded JSON definition configuration required')
    config=json.loads(path.read_text());reject_secrets(config)
    if set(config)-{'mail','studio_delivery','briefing','visual_references'}!={'enhanced_enabled','model','ollama_url','qualification_root','promotion_review'} or type(config['enhanced_enabled']) is not bool:raise ValueError('Explicit definition feature flag required')
    from .visual_references import policy as visual_policy
    config['visual_references']=visual_policy(config.get('visual_references'))
    from .paid import policy as briefing_policy
    # Existing enhanced promotion hashes retain their exact legacy identity.
    if 'briefing' in config:config['briefing']=briefing_policy(config['briefing'])
    from pipeline_mail import policy
    config['mail']=policy(config.get('mail'))
    from .studio_delivery import policy as studio_policy
    config['studio_delivery']=studio_policy(config.get('studio_delivery'))
    OllamaDefinition(config['model'],config['ollama_url']) # Validate local endpoint without a request.
    if config['enhanced_enabled']:
        review=config['promotion_review'] or {}
        identity={k:v for k,v in config.items() if k not in ('promotion_review','mail','studio_delivery','briefing','visual_references')}
        if review.get('approved') is not True or review.get('configuration_sha256')!=digest(identity) or review.get('rubric_sha256')!=digest(RUBRIC) or review.get('recipe')!=VERSION or not review.get('reviewer') or not review.get('preview_manifest_sha256'):
            raise ValueError('Exact definition configuration, preview and product-person rubric approval required')
        preview=Path(review.get('preview_manifest_path',''))
        if not preview.is_file() or preview.is_symlink() or preview.suffix!='.json' or any(p.startswith('.env') for p in preview.parts) or preview.stat().st_size>100000:
            raise ValueError('Reviewed saved preview manifest required')
        sample=json.loads(preview.read_text());reject_secrets(sample)
        if digest(sample)!=review['preview_manifest_sha256'] or sample.get('recipe')!=VERSION:
            raise ValueError('Reviewed preview changed or recipe mismatch')
    return config
