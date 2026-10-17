"""Versioned full-frame final edits: exact input + user text, original output.

No verbal reinterpretation, crop, page mapping, recomposition or visual-score gate.
Provider originals remain available independently through generated_images.
"""
import copy
import hashlib
from . import production
from .refinement import bytes_for,working_size,result
from .storage import read,write,write_bytes,digest,Invalid


def human_reviewed(record):
    review=record.get('human_approval') or {}
    return record.get('renderer_version')=='direct-edit-v1' and review.get('sha256')==record.get('sha256') and review.get('visual_and_product_review_confirmed') is True


def run(board,directory,folder,request,pages,manifest):
    value=request['value'];studio=board.studio
    provider=studio.model_roles.select_final(value.get('model_id')) if studio.model_roles else studio.mockup_finals
    if not callable(getattr(provider,'mockup_direct_image',None)):raise Invalid('Selected image adapter does not support full-image editing')
    records=[]
    for card in value['cards']:
        prefix=directory/'lifestyle'/request['id']/card['id'];path=prefix.with_suffix('.json')
        if path.exists():record=read(path);bytes_for(directory,record)
        else:
            reference=card.get('candidate')
            if not reference:raise Invalid('Select an existing image before final editing')
            original=bytes_for(directory,reference);image=production.raster(original);export=value.get('export_only',False)
            size=working_size(image,1536*1024 if export else 1152*768)
            receipt={'reference_id':reference['id'],'reference_sha256':reference['sha256'],'exact_card_comments':card['comments'],
                     'exact_batch_comments':value.get('final_comments',''),'export_only':export,'output_size':list(size),'scene_description_sent':False,
                     'crop':False,'recomposition':False,'automatic_visual_approval':False}
            write(prefix.with_suffix('.input.json'),receipt)
            # The adapter persists its provider response before validating it.
            asset=provider.mockup_direct_image(original,card['comments'],value.get('final_comments',''),request['id']+'-'+card['id'],request['project_id'],export,output_size=size)
            output=prefix.with_suffix('.png');write_bytes(output,asset.content)
            if asset.media_type!='image/png' or production.raster(asset.content).size!=size:raise Invalid('Received image is available in original outputs; expected output format/dimensions differ')
            record={**copy.deepcopy(reference),'id':request['id']+'-'+card['id'],'card_id':card['id'],'file':str(output.relative_to(directory)),
                'sha256':hashlib.sha256(asset.content).hexdigest(),'background_file':str(output.relative_to(directory)),'background_sha256':hashlib.sha256(asset.content).hexdigest(),
                'quality':'final','render_profile':'export' if export else 'working','native_size':list(size),'renderer_version':'direct-edit-v1','model_id':value.get('model_id'),
                'scene':card['scene'],'card_input_sha256':digest({'scene':card['scene'],'comments':card['comments']}),'comments_sha256':digest(value['comments']),
                'final_comments_sha256':digest(value.get('final_comments','')),'source_composited':False,'placements':[],'quad':None,'placement_status':'human_review_required',
                'placement_reason':None,'review_required':True,'direct_edit':receipt}
            record.pop('refinement',None);record.pop('human_approval',None);write(path,record)
        records.append(record)
        saved=result(request,manifest,records,[],partial=True);saved.update(direct_edit=True,targeted_refinement=False)
        # Share only independent persistence/publication, not legacy image transforms.
        write(folder/'partial-result.json',saved)
        from .storage import guard
        with guard(directory):
            state=read(directory/'state.json')
            if state['workflow'].get('pending')!=request['id']:raise Invalid('Image job is no longer current')
            board.apply(state,request['kind'],saved);studio.save(directory,state)
    saved=result(request,manifest,records,[]);saved.update(direct_edit=True,targeted_refinement=False)
    return saved
