"""Studio-owned, bounded image direction compiled from its validated understanding."""
import json
from .storage import Invalid


def compose(request):
    value={'brief':request['brief'],'source_context':request.get('source_context',{}),'direction':request.get('understanding',{}).get('next_direction'),
           'preferences':request.get('understanding',{}).get('preferences',[]),
           'shared_batch_comments':request['feedback_context'].get('whole_set_comments',[])[-8:],
           'reference_interpretation':request['feedback_context'].get('reference_understanding'),
           'accepted':[{'metadata':r.get('metadata',{}),'review':r.get('review',{})} for r in request['accepted'][-8:]],
           'rejected':[{'metadata':r.get('metadata',{}),'review':r.get('review',{})} for r in request['rejected'][-8:]],
           'negative_context':request['negative_summary'],'production_settings':request.get('settings'),
           'reference_images':'Use analyzed reference traits as guidance for original work; do not copy examples.' if request.get('reference_images') else None,
           'instruction':'Use the concrete subjects, content units and visual requirements in the brief and source context. Current edited brief and latest explicit feedback override conflicting original details. Missing fields are optional: choose a plausible initial direction without inventing user requirements. Do not return a generic template or wireframe. Create one original coherent concept board for the entire product bundle, with balanced panels for its deliverables. Honor explicit comments over weak inferred preferences. No watermark or invented text. Vary composition across samples; this is a draft.'}
    prompt=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    if len(prompt.encode())>20_000:raise Invalid('Optimized image prompt exceeds bound')
    return prompt
