"""Targeted mockup edits: cached interpretation, exact pixels, layered pages and review.

Working renders are independent of optional export. No automatic retries or image
promotion on failed checks. Every provider step belongs to the durable job key.
"""
import copy
import hashlib
import math
from PIL import Image, ImageDraw, ImageOps
from .storage import Invalid, read, write, write_bytes, now, digest, guard
from . import production

WORK_SIZE=(1152,768)
EXPORT_SIZE=(1536,1024)


def object_schema(properties):
    return {'type':'object','additionalProperties':False,'required':list(properties),'properties':properties}


def strings():return {'type':'array','minItems':1,'maxItems':8,'items':{'type':'string','minLength':1,'maxLength':400}}
def box_schema():return {'type':'array','minItems':4,'maxItems':4,'items':{'type':'number','minimum':0,'maximum':1}}
def polygon_schema():return {'type':'array','minItems':3,'maxItems':12,'items':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'number','minimum':0,'maximum':1}}}
REGION_SCHEMA=object_schema({'left':{'type':'number','minimum':0,'maximum':.98},'top':{'type':'number','minimum':0,'maximum':.98},'width':{'type':'number','minimum':.02,'maximum':1},'height':{'type':'number','minimum':.02,'maximum':1}})
PLAN_SCHEMA=object_schema({'instruction':{'type':'string','minLength':1,'maxLength':1800},'change':strings(),'preserve':strings(),'checks':strings(),'edit_region':REGION_SCHEMA,'protected_regions':{'type':'array','maxItems':12,'items':polygon_schema()}})
REVIEW_SCHEMA=object_schema({'checks':{'type':'array','minItems':1,'maxItems':8,'items':object_schema({'requirement':{'type':'string','maxLength':400},'passed':{'type':'boolean'},'evidence':{'type':'string','maxLength':400}})},'product_matches_sources':{'type':'boolean'},'preserved_content':{'type':'boolean'},'summary':{'type':'string','minLength':1,'maxLength':800}})


def box(value):
    if not isinstance(value,list) or len(value)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in value):raise Invalid('Bounded edit rectangle required')
    if value[2]-value[0]<.02 or value[3]-value[1]<.02:raise Invalid('Edit rectangle is empty or too small')
    return value


def polygon(value):
    if not isinstance(value,list) or not 3<=len(value)<=12:raise Invalid('Bounded protection polygon required')
    for p in value:
        if not isinstance(p,list) or len(p)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in p):raise Invalid('Invalid protection point')
    return value


def checked_plan(plan):
    if isinstance(plan,dict) and 'edit_region' in plan:
        plan=copy.deepcopy(plan);region=plan.pop('edit_region')
        if not isinstance(region,dict) or set(region)!={'left','top','width','height'} or any(type(v) not in (int,float) or not math.isfinite(v) for v in region.values()):raise Invalid('Explicit finite correction region required')
        if min(region['width'],region['height'])<.02:raise Invalid('Edit rectangle is empty or too small')
        plan['edit_box']=[region['left'],region['top'],region['left']+region['width'],region['top']+region['height']]
    expected=(set(PLAN_SCHEMA['properties'])-{'edit_region'})|{'edit_box'}
    if not isinstance(plan,dict) or set(plan)!=expected:raise Invalid('Complete correction plan required')
    if not isinstance(plan['instruction'],str) or not 1<=len(plan['instruction'])<=1800:raise Invalid('Bounded correction instruction required')
    for name in ('change','preserve','checks'):
        if not isinstance(plan[name],list) or not 1<=len(plan[name])<=8 or any(not isinstance(s,str) or not 1<=len(s)<=400 for s in plan[name]):raise Invalid('Explicit change, preserve and check lists required')
    box(plan['edit_box'])
    if not isinstance(plan['protected_regions'],list) or len(plan['protected_regions'])>12:raise Invalid('Bounded protected regions required')
    for p in plan['protected_regions']:polygon(p)
    return plan


def checked_review(review,plan):
    if not isinstance(review,dict) or set(review)!=set(REVIEW_SCHEMA['properties']):raise Invalid('Complete visual comparison required')
    rows=review['checks']
    if not isinstance(rows,list) or len(rows)!=len(plan['checks']):raise Invalid('Compare every correction check')
    for row,expected in zip(rows,plan['checks']):
        if not isinstance(row,dict) or set(row)!={'requirement','passed','evidence'} or row['requirement']!=expected or type(row['passed']) is not bool or not isinstance(row['evidence'],str) or len(row['evidence'])>400:raise Invalid('Comparison must match the exact correction checks')
    if any(type(review[k]) is not bool for k in ('product_matches_sources','preserved_content')) or not isinstance(review['summary'],str) or not 1<=len(review['summary'])<=800:raise Invalid('Invalid visual comparison')
    return all(r['passed'] for r in rows) and review['product_matches_sources'] and review['preserved_content']


def cached(path,fn):
    if path.exists():return read(path)
    result=fn();write(path,result);return result


def bytes_for(directory,record):
    path=directory/record['file']
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):raise Invalid('Invalid refinement reference')
    body=path.read_bytes()
    if hashlib.sha256(body).hexdigest()!=record['sha256']:raise Invalid('Refinement reference changed')
    return body


def working_size(image,pixels=1152*768):
    scale=(pixels/(image.width*image.height))**.5
    return tuple(max(256,round(v*scale/16)*16) for v in image.size)


def pixels_box(value,size):return tuple(round(v*size[i%2]) for i,v in enumerate(value))

def edit_canvas(original,plan):
    """Magnify the original-resolution crop; never throw away tiny hand details."""
    crop=original.crop(pixels_box(plan['edit_box'],original.size));scaled=ImageOps.contain(crop,WORK_SIZE,Image.Resampling.LANCZOS)
    canvas=Image.new('RGB',WORK_SIZE,'#808080');offset=((WORK_SIZE[0]-scaled.width)//2,(WORK_SIZE[1]-scaled.height)//2);canvas.paste(scaled,offset)
    return canvas,(*offset,offset[0]+scaled.width,offset[1]+scaled.height)


def merge_patch(original,rendered,plan,content_rect):
    size=working_size(original);base=original.resize(size,Image.Resampling.LANCZOS);rect=pixels_box(plan['edit_box'],size)
    patch=rendered.crop(content_rect).resize((rect[2]-rect[0],rect[3]-rect[1]),Image.Resampling.LANCZOS)
    mask=Image.new('L',size);d=ImageDraw.Draw(mask);d.rectangle((rect[0],rect[1],rect[2]-1,rect[3]-1),fill=255)
    for region in plan['protected_regions']:d.polygon([(round(x*size[0]),round(y*size[1])) for x,y in region],fill=0)
    edited=base.copy();edited.paste(patch,rect[:2]);return Image.composite(edited,base,mask),mask


def layers(image,pages,result):
    """Put immutable pages behind explicit foreground hands/scissors/objects."""
    from .lifestyle import checked_surface,composite
    from .mockup_geometry import overlaps
    surfaces=result.get('surfaces') if isinstance(result,dict) else None
    if not isinstance(surfaces,list) or not 1<=len(surfaces)<=4:raise Invalid('One to four identifiable product pages required')
    output=image.copy();placements=[];foreground=Image.new('L',image.size);draw=ImageDraw.Draw(foreground)
    for surface in surfaces:
        if not isinstance(surface,dict) or surface.get('page_id') not in pages:raise Invalid('Unknown source page')
        quad=checked_surface(surface)
        if any(overlaps(quad,p['quad']) for p in placements):raise Invalid('Overlapping product pages cannot be safely restored')
        regions=surface.get('foreground_regions',[])
        if not isinstance(regions,list) or len(regions)>12:raise Invalid('Bounded foreground regions required')
        for region in regions:
            polygon(region);draw.polygon([(round(x*image.width),round(y*image.height)) for x,y in region],fill=255)
        page=pages[surface['page_id']];output=composite(output,production.raster(page['body']),quad)
        placements.append({'page_id':surface['page_id'],'sha256':page['record']['sha256'],'quad':quad})
    # A whole-page foreground mask could hide invented product artwork.
    from PIL import ImageChops
    page_mask=Image.new('L',image.size);pd=ImageDraw.Draw(page_mask)
    for p in placements:pd.polygon([(round(x*image.width),round(y*image.height)) for x,y in p['quad']],fill=255)
    covered=sum(ImageChops.multiply(foreground,page_mask).histogram()[1:]);area=sum(page_mask.histogram()[1:])
    if covered>area*.4:raise Invalid('Foreground hides too much of the product to verify')
    return Image.composite(image,output,foreground),placements


def run_card(board,directory,folder,request,pages,manifest,card,i):
    studio=board.studio;value=request['value'];export=value.get('export_only',False)
    provider=studio.model_roles.select_final(value.get('model_id')) if studio.model_roles else studio.mockup_finals
    if not callable(getattr(provider,'mockup_refinement_image',None)):raise Invalid('Selected model does not support targeted refinement')
    planner=studio.mockup_planner;target=directory/'lifestyle'/request['id']
    reference=card.get('candidate')
    if not reference:raise Invalid('Review a saved concept before refinement')
    source_ids=list(dict.fromkeys([reference['source_page_id'],card['scene']['page_id'],*[p['page_id'] for p in reference.get('placements',[])],*pages]))[:3]
    source_images=[pages[identifier]['body'] for identifier in source_ids]
    path=target/(card['id']+'.json')
    with guard(directory):
        current=read(directory/'state.json');current['workflow']['mockup_progress']={'completed':i,'total':len(value['cards']),'title':card['scene']['title']};studio.save(directory,current)
    if path.exists():
        record=read(path);bytes_for(directory,record);return record
    previous=bytes_for(directory,reference);original=production.raster(previous);key=request['id']+'-'+card['id'];prefix=target/card['id']
    context={'scene':card['scene'],'shared_comments':value['comments'],'card_comments':card['comments'],'export_only':export,'source_placement_verified':reference.get('source_composited') is True,'page_ids':source_ids}
    try:
        override=card.get('refinement_failure') or {}
        if card.get('edit_box') and override.get('correction_plan') and override.get('context_sha256')==correction_identity(card,value):
            plan=copy.deepcopy(override['correction_plan']);plan.pop('edit_region',None);plan['edit_box']=box(card['edit_box']);plan=checked_plan(plan)
            write(prefix.with_suffix('.plan-override.json'),{'at':now(),'human_selected_region':plan['edit_box'],'source_plan_sha256':digest(override['correction_plan']),'new_planning_calls':0})
            write(prefix.with_suffix('.plan.json'),plan)
        else:
            if card.get('edit_box'):context['human_edit_box']=box(card['edit_box'])
            plan=cached(prefix.with_suffix('.plan.json'),lambda:planner.mockup_correction(context,[previous,*source_images],key+'-plan',request['project_id']))
        plan=checked_plan(plan)
    except Invalid as error:
        from .dev_budget import BudgetBlocked
        if isinstance(error,BudgetBlocked) or studio.budget.summary(request['project_id'])['unknown_outcomes']:raise
        raw=getattr(error,'correction_plan',None) or locals().get('plan') or read_completed_plan(studio.root,request,card)
        raise CardFailure(str(error),raw) from error
    render_size=working_size(original,1536*1024) if export else WORK_SIZE
    output_size=render_size if export else working_size(original)
    input_image,content_rect=(original,(0,0,*render_size)) if export else edit_canvas(original,plan)
    edited_path=prefix.with_suffix('.provider.png')
    if not edited_path.exists():
        asset=provider.mockup_refinement_image(production.png(input_image),plan,key,request['project_id'],export,output_size=render_size)
        if asset.media_type!='image/png':raise Invalid('PNG refinement required')
        write_bytes(edited_path,asset.content)
    rendered=production.raster(edited_path.read_bytes());expected=render_size
    if rendered.size!=expected:raise Invalid('Refinement dimensions differ from the requested size')
    base=original.resize(output_size,Image.Resampling.LANCZOS)
    image,edit_mask=(rendered,None) if export else merge_patch(original,rendered,plan,content_rect)
    # Source placement may legitimately be occluded by scissors or fingers.
    placement=None;placements=[]
    try:
        found=cached(prefix.with_suffix('.layers.json'),lambda:planner.mockup_page_layers(production.png(image),card['scene'],list(pages),key+'-layers',request['project_id']))
        image,placements=layers(image,pages,found)
        if not export:
            if reference.get('source_composited') is True:
                image=Image.composite(image,base,edit_mask)
            elif plan['protected_regions']:
                # Never label preserved, unverified old artwork as restored
                # source pixels. Fail rather than overriding a protected page.
                from .mockup_geometry import overlaps
                for region in plan['protected_regions']:
                    xs=[p[0] for p in region];ys=[p[1] for p in region]
                    bounds=[[min(xs),min(ys)],[max(xs),min(ys)],[max(xs),max(ys)],[min(xs),max(ys)]]
                    if any(overlaps(bounds,p['quad']) for p in placements):raise Invalid('Protected unverified page pixels conflict with source restoration')
                protection=Image.new('L',output_size);pd=ImageDraw.Draw(protection)
                for region in plan['protected_regions']:pd.polygon([(round(x*output_size[0]),round(y*output_size[1])) for x,y in region],fill=255)
                image=Image.composite(base,image,protection)
    except Invalid as error:placement=str(error)
    output=prefix.with_suffix('.png');write_bytes(output,production.png(image))
    if placement is not None:
        review={'checks':[{'requirement':c,'passed':False,'evidence':'Source-page geometry failed before visual comparison'} for c in plan['checks']],'product_matches_sources':False,'preserved_content':False,'summary':'Product-page placement failed; previous sample retained'}
        write(prefix.with_suffix('.review.json'),review)
    else:
        review=cached(prefix.with_suffix('.review.json'),lambda:planner.mockup_compare(plan,[previous,production.png(image),production.png(original.crop(pixels_box(plan['edit_box'],original.size))),production.png(image.crop(pixels_box(plan['edit_box'],image.size))),*source_images],key+'-review',request['project_id']))
    passed=checked_review(review,plan) and placement is None
    main=placements[0]['page_id'] if placements else reference['source_page_id']
    record={**copy.deepcopy(reference),'id':key,'card_id':card['id'],'file':str(output.relative_to(directory)),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'background_file':str(edited_path.relative_to(directory)),'background_sha256':hashlib.sha256(edited_path.read_bytes()).hexdigest(),
        'placements':placements,'quad':placements[0]['quad'] if placements else None,'source_page_id':main,'source_page_sha256':pages[main]['record']['sha256'],
        'source_composited':placement is None,'placement_status':'ready' if placement is None else 'needs_revision','placement_reason':placement,
        'quality':'final','render_profile':'export' if export else 'working','native_size':list(output_size),'renderer_version':'targeted-refinement-v1',
        'model_id':value.get('model_id'),'scene':card['scene'],'card_input_sha256':digest({'scene':card['scene'],'comments':card['comments']}),'comments_sha256':digest(value['comments']),
        'refinement':{'passed':passed,'plan':plan,'review':review,'reference_id':reference['id'],'reference_sha256':reference['sha256'],'human_review_required':True},'review_required':True}
    write(path,record);return record


class CardFailure(Invalid):
    def __init__(self,message,plan=None):
        super().__init__(message);self.correction_plan=plan


def correction_identity(card,value):
    return digest({'scene':card['scene'],'shared_comments':value['comments'],'card_comments':card['comments'],'export_only':value.get('export_only',False),'reference_sha256':card['candidate']['sha256']})


def read_completed_plan(root,request,card):
    key=request['id']+'-'+card['id']+'-plan';stage='mockup_correction';base=root/'development-openai'
    step=base/'steps'/digest({'key':key,'stage':stage,'project':request['project_id']})/'request.json'
    if not step.exists():return None
    payload=read(step)['body'];response=base/'calls'/digest({'key':key,'stage':stage,'payload':payload})/'response.json'
    if not response.exists():return None
    value=read(response)
    if value.get('status')!='completed':return None
    import json
    try:return json.loads(''.join(c['text'] for o in value.get('output',[]) if o.get('type')=='message' for c in o.get('content',[]) if c.get('type')=='output_text'))
    except (ValueError,KeyError,TypeError):return None


def failure(request,card,message,plan=None):
    return {'card_id':card['id'],'job_id':request['id'],'stage':'correction_planning','summary':message,'code':'invalid_correction_plan','correction_plan':plan,'context_sha256':correction_identity(card,request['value']),'automatic_retry':False}


def result(request,manifest,records,failures,partial=False):
    return {'id':request['id'],'product_id':manifest['id'],'candidates':records,'failures':failures,'created_at':request['created_at'],'comments':request['value']['comments'],'stage':'final','targeted_refinement':True,'export_only':request['value'].get('export_only',False),'partial':partial,'total':len(request['value']['cards'])}


def publish(board,directory,folder,request,manifest,records,failures):
    saved=result(request,manifest,records,failures,partial=True);write(folder/'partial-result.json',saved)
    with guard(directory):
        state=read(directory/'state.json')
        if state['workflow'].get('pending')!=request['id']:raise Invalid('Refinement job is no longer current')
        board.apply(state,request['kind'],saved);board.studio.save(directory,state)


def run(board,directory,folder,request,pages,manifest):
    records=[];failures=[]
    for i,card in enumerate(request['value']['cards']):
        try:records.append(run_card(board,directory,folder,request,pages,manifest,card,i))
        except CardFailure as error:failures.append(failure(request,card,str(error),error.correction_plan))
        publish(board,directory,folder,request,manifest,records,failures)
    return result(request,manifest,records,failures)


def recover_saved(board,directory,request,manifest):
    # Read/verify completed files only. Never instantiate/call a provider.
    records=[];failures=[];target=directory/'lifestyle'/request['id']
    state=read(directory/'state.json');current={c['id']:c for c in board.state(state)['cards']}
    if board.lifestyle.design(state)['comments']!=request['value']['comments']:raise Invalid('Saved job no longer matches shared comments')
    for card in request['value']['cards']:
        live=current.get(card['id'])
        if not live or live['scene']!=card['scene'] or live['comments']!=card['comments']:raise Invalid('Saved job no longer matches current cards/comments')
        path=target/(card['id']+'.json')
        if path.exists():
            record=read(path);bytes_for(directory,record)
            if record.get('card_id')!=card['id'] or record.get('product_id')!=manifest['id'] or record.get('refinement',{}).get('reference_sha256')!=card['candidate']['sha256']:raise Invalid('Saved refinement provenance does not match the job')
            if record['card_input_sha256']!=digest({'scene':live['scene'],'comments':live['comments']}):raise Invalid('Saved candidate input changed')
            records.append(record)
        else:
            plan=read_completed_plan(board.studio.root,request,card)
            try:checked_plan(plan)
            except Invalid as error:failures.append(failure(request,card,str(error),plan))
            else:failures.append(failure(request,card,'No completed image available; explicit generation consent required',plan))
    return result(request,manifest,records,failures)
