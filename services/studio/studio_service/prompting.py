"""Studio-owned, bounded image direction compiled from its validated understanding."""
import json
from .storage import Invalid


def compose(request):
    plan=request.get('production_plan')
    brief=request['brief']
    # Collector/Analyzer evidence is provenance, not an image-design instruction.
    # Keep it in the immutable intake/request files, never duplicate it in prompts.
    source=request.get('source_context') or {}
    relevant={k:source[k] for k in ('visual_reference_guidance','visual_basis','content_units','design_directions','first_sketch','production_defaults') if k in source}
    if plan:
        brief={k:v for k,v in brief.items() if k not in ('requirements','deliverables','visual_direction')}
    definition=source.get('definition') or {}
    constraints={}
    if plan:
        try:constraints=json.loads(plan.get('constraints',''))
        except (ValueError,TypeError):pass
    relevant.update({k:definition[k] for k in ('first_sketch','reference_interpretation')
                    if k in definition and (not isinstance(constraints,dict) or constraints.get(k)!=definition[k])})
    value={'brief':brief,'source_context':relevant,'direction':request.get('understanding',{}).get('next_direction'),
           'preferences':request.get('understanding',{}).get('preferences',[]),
           'shared_batch_comments':request['feedback_context'].get('whole_set_comments',[])[-8:],
           'reference_interpretation':request['feedback_context'].get('reference_understanding'),
           'accepted':[{'metadata':r.get('metadata',{}),'review':r.get('review',{})} for r in request['accepted'][-8:]],
           'rejected':[{'metadata':r.get('metadata',{}),'review':r.get('review',{})} for r in request['rejected'][-8:]],
           'negative_context':request['negative_summary'],'production_settings':request.get('settings'),
           'production_plan':request.get('production_plan'),'representative_unit':request.get('representative_unit'),'preference_memory':request.get('preference_memory',[]),
           'reference_images':'Use analyzed reference traits as guidance for original work; do not copy examples.' if request.get('reference_images') else None,
           'instruction':'Use the concrete subjects, content units and visual requirements in the brief and source context. Current edited production inventory/style/constraints and latest explicit feedback override conflicting original brief details. Missing fields are optional: choose a plausible initial direction without inventing user requirements. Create ONE representative unit/page identified above, comparing directions for that SAME subject. Do not create a bundle collage, cover, mockup, template or wireframe even if an older brief requests a whole-bundle board. Follow explicit comments over weak inferred preferences; this product brief overrides recurring preference memory. Preserve accepted pixels/features during edits. Typography is rendered separately by code. No watermark or invented text.'}
    prompt=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    if len(prompt.encode())>20_000:raise Invalid('פרטי העיצוב והמשוב חורגים ממגבלת הבקשה (20KB). יש לצמצם אותם לפני ניסיון נוסף; לא נשלחה בקשת תמונה.')
    return prompt
