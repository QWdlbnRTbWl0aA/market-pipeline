"""Studio-owned, bounded image direction compiled from its validated understanding."""
import json
from .storage import Invalid


def compose(request):
    value={'brief':request['brief'],'direction':request.get('understanding',{}).get('next_direction'),
           'preferences':request.get('understanding',{}).get('preferences',[]),
           'shared_batch_comments':request['feedback_context'].get('whole_set_comments',[])[-8:],
           'reference_interpretation':request['feedback_context'].get('reference_understanding'),
           'accepted':[r.get('metadata',{}) for r in request['accepted'][-8:]],
           'rejected':[r.get('metadata',{}) for r in request['rejected'][-8:]],
           'negative_context':request['negative_summary'],'production_settings':request.get('settings'),
           'reference_images':'Use analyzed reference traits as guidance for original work; do not copy examples.' if request.get('reference_images') else None,
           'instruction':'Create one original coherent concept board for the entire product bundle, with balanced panels for its deliverables. Honor explicit comments over weak inferred preferences. No watermark or invented text. Vary composition across samples; this is a draft.'}
    prompt=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    if len(prompt.encode())>20_000:raise Invalid('Optimized image prompt exceeds bound')
    return prompt
