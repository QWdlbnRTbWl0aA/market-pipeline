"""Human-reviewed product-aware lifestyle mockups; independent provider ports."""
import hashlib
import math
from .storage import Invalid,Conflict,read,write,write_bytes,digest,now,guard
from . import production
from .mockup_board import Board, ACTIONS as BOARD_ACTIONS

ACTIONS=BOARD_ACTIONS|{'plan_mockups','generate_mockup_concepts','finalize_mockups','save_mockup_feedback','abandon_mockup_job','refresh_mockup_geometry'}
MAX_COUNT=10


def count(value):
    if type(value) is not int or not 1<=value<=MAX_COUNT:raise Invalid('Choose one to ten mockups')
    return value


def schema(number):
    return {'type':'object','additionalProperties':False,'required':['product_understanding','direction','scenes'],'properties':{
        'product_understanding':{'type':'string'},'direction':{'type':'string'},'scenes':{'type':'array','minItems':number,'maxItems':number,'items':{
            'type':'object','additionalProperties':False,'required':['title','description','image_prompt','page_id','scene_type'],
            'properties':{**{k:{'type':'string'} for k in ('title','description','image_prompt','page_id')},'scene_type':{'type':'string','enum':['usage','spread','storyboard','stack','hero']}}}}}}


def checked_plan(value,number,ids):
    if not isinstance(value,dict) or set(value)!={'product_understanding','direction','scenes'}:raise Invalid('Complete product-aware scene plan required')
    for key in ('product_understanding','direction'):
        if not isinstance(value[key],str) or not 1<=len(value[key])<=2000:raise Invalid('Bounded scene explanation required')
    if not isinstance(value['scenes'],list) or len(value['scenes'])!=count(number):raise Invalid('Scene count must match the chosen quantity')
    for scene in value['scenes']:
        if not isinstance(scene,dict) or not {'title','description','image_prompt','page_id'}<=set(scene)<={'title','description','image_prompt','page_id','scene_type'}:raise Invalid('Complete scene description required')
        if 'scene_type' in scene and scene['scene_type'] not in ('usage','spread','storyboard','stack','hero'):raise Invalid('Unknown scene type')
        for k,limit in (('title',120),('description',1800),('image_prompt',3500)):
            if not isinstance(scene[k],str) or not 1<=len(scene[k])<=limit:raise Invalid('Bounded scene text required')
        if not isinstance(scene['page_id'],str) or scene['page_id'] not in ids:raise Invalid('Scenes must refer to actual finished product pages')
    return value


def checked_surface(value):
    if not isinstance(value,dict):raise Invalid('A structured product-surface assessment is required')
    if value.get('usable') is not True:raise Invalid('The scene has no clear product surface: '+str((value or {}).get('reason','manual scene review required'))[:180])
    quad=value.get('quad')
    if not isinstance(quad,list) or len(quad)!=4 or any(not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not .01<=v<=.99 for v in p) for p in quad):raise Invalid('Four bounded product-surface corners required')
    crosses=[]
    for i in range(4):
        a,b,c=quad[i],quad[(i+1)%4],quad[(i+2)%4];crosses.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
    area=sum(quad[i][0]*quad[(i+1)%4][1]-quad[(i+1)%4][0]*quad[i][1] for i in range(4))/2
    if min(crosses)<=0 or not .06<=area<=.8:raise Invalid('Product surface must be convex, clockwise and large enough to inspect')
    return quad


def fit_paper(background,seed_quad):
    """Use the model only as a seed; fit actual blank-paper edges locally."""
    from PIL import Image,ImageFilter
    from collections import deque
    image=background.copy();image.thumbnail((512,512));w,h=image.size
    mask=Image.new('L',image.size);mask.putdata([255 if min(rgb)>=180 and max(rgb)-min(rgb)<=32 else 0 for rgb in image.convert('RGB').getdata()])
    mask=mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3));data=mask.tobytes()
    cx=round(sum(x for x,y in seed_quad)*w/4);cy=round(sum(y for x,y in seed_quad)*h/4)
    options=[(dx*dx+dy*dy,(cy+dy)*w+cx+dx) for dy in range(-12,13) for dx in range(-12,13) if 0<=cx+dx<w and 0<=cy+dy<h and data[(cy+dy)*w+cx+dx]]
    if not options:raise Invalid('No blank paper found near the model surface; revise the scene')
    seed=min(options)[1];queue=deque([seed]);seen=bytearray(w*h);seen[seed]=1;rows={};area=0
    while queue:
        i=queue.popleft();x=i%w;y=i//w;area+=1
        left,right=rows.get(y,(x,x));rows[y]=(min(left,x),max(right,x))
        for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if not 0<=nx<w or not 0<=ny<h:continue
            j=ny*w+nx
            if not seen[j] and data[j]:seen[j]=1;queue.append(j)
    points=sorted(set((x,y) for y,(left,right) in rows.items() for x in (left,right)))
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower=[]
    for point in points:
        while len(lower)>=2 and cross(lower[-2],lower[-1],point)<=0:lower.pop()
        lower.append(point)
    upper=[]
    for point in reversed(points):
        while len(upper)>=2 and cross(upper[-2],upper[-1],point)<=0:upper.pop()
        upper.append(point)
    hull=lower[:-1]+upper[:-1]
    while len(hull)>4:
        index=min(range(len(hull)),key=lambda i:abs(cross(hull[i-1],hull[i],hull[(i+1)%len(hull)])));hull.pop(index)
    if len(hull)!=4:raise Invalid('The paper boundary is not a clear quadrilateral')
    start=min(range(4),key=lambda i:hull[i][0]+hull[i][1]);hull=hull[start:]+hull[:start]
    quad=[[x/w,y/h] for x,y in hull];checked_surface({'usable':True,'quad':quad})
    polygon_area=abs(sum(hull[i][0]*hull[(i+1)%4][1]-hull[(i+1)%4][0]*hull[i][1] for i in range(4)))/2
    if not .94<=area/max(1,polygon_area)<=1.08:raise Invalid('The detected paper has occlusions or ambiguous edges; revise the scene')
    return quad


def composite(background,page,quad):
    from PIL import Image,ImageFilter,ImageChops
    from .production import perspective_coefficients
    w,h=background.size;destination=[(x*w,y*h) for x,y in quad];coeff=perspective_coefficients(destination,[(0,0),(page.width,0),(page.width,page.height),(0,page.height)])
    warped=page.convert('RGBA').transform(background.size,Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
    mask=warped.getchannel('A');lighting=background.convert('L').point(lambda v:max(180,v)).convert('RGB');lit=ImageChops.multiply(warped.convert('RGB'),lighting).convert('RGBA');lit.putalpha(mask);warped=lit
    result=background.convert('RGBA');shifted=Image.new('L',background.size);shifted.paste(mask,(2,3))
    shadow=Image.new('RGBA',background.size,(30,25,20,0));shadow.putalpha(shifted.filter(ImageFilter.GaussianBlur(2)).point(lambda a:round(a*.20)));result.alpha_composite(shadow);result.alpha_composite(warped)
    return result.convert('RGB')


class Lifestyle:
    def __init__(self,workflow):self.workflow=workflow;self.studio=workflow.studio;self.board=Board(self)
    def enabled(self):return all((self.studio.mockup_planner,self.studio.mockup_drafts,self.studio.mockup_finals))
    def design(self,state):
        return state['workflow'].setdefault('mockup_design',{'version':1,'count':3,'comments':'','rounds':[],'feedback_events':[],'plan':None,'status':'not_started'})
    def feedback(self,state,payload):
        design=self.design(state);comments=payload.get('comments',design['comments']);number=count(payload.get('count',design['count']))
        if not isinstance(comments,str) or len(comments)>4000:raise Invalid('Mockup comments must be bounded text')
        current=design['rounds'][-1] if design['rounds'] else None;reviews=payload.get('mockup_reviews',current.get('reviews',{}) if current else {})
        ids={c['id'] for c in current['candidates']} if current else set()
        if not isinstance(reviews,dict) or set(reviews)-ids or any(v not in ('accept','reject') for v in reviews.values()):raise Invalid('Like/dislike must refer to current mockup concepts')
        if current:current['reviews']=reviews
        design.update(comments=comments,count=number)
        design['feedback_events'].append({'at':now(),'round_id':current['id'] if current else None,'comments':comments,'reviews':reviews,'count':number})
        return design
    def remembered(self,state):
        family=state['workflow']['plan']['family'];words=set(state['brief']['concept'].casefold().split())-{'the','and','for','printable','digital','product','collection','bundle','pack'};matches=[]
        for path in sorted((self.studio.root/'scene-memory').glob('*.json'),reverse=True)[:100]:
            if path.is_symlink():continue
            value=read(path)
            if (family and value['family']==family) or len(words&set(value['concept'].casefold().split()))>=2:
                matches.append({k:value[k] for k in ('scene','comments','family','concept')})
            if len(matches)==3:break
        return matches
    def remember(self,state):
        workflow=state['workflow'];design=self.design(state)
        for record in workflow['mockups']:
            if record.get('origin')!='generative_lifestyle':continue
            value={'family':workflow['plan']['family'],'concept':state['brief']['concept'],'product_id':record['product_id'],
                'scene':record['scene'] if 'scene' in record else next(r for r in design['rounds'] if any(c['scene_index']==record['scene_index'] for c in r['candidates']) and r.get('plan')==design['plan'])['plan']['scenes'][record['scene_index']],
                'comments':design['comments'],'background_file':record['background_file'],'background_sha256':record['background_sha256'],
                'source_project_id':state['id'],'human_approved_at':now(),'kind':'approved_scene_example_not_global_preference'}
            path=self.studio.root/'scene-memory'/(digest({'project':state['id'],'background':record['background_sha256']})+'.json')
            if not path.exists():write(path,value)
    def command(self,directory,state,action,payload):
        if action in BOARD_ACTIONS:return self.board.command(directory,state,action,payload)
        workflow=state['workflow']
        if action=='abandon_mockup_job':
            pending=workflow.get('pending');folder=directory/'workflow-jobs'/str(pending)
            if not pending or read(folder/'operation.json')['status']!='failed' or not read(folder/'request.json')['kind'].startswith('mockup_'):raise Conflict('Only a failed mockup job can be abandoned')
            write(folder/'abandoned.json',{'at':now(),'paid_reservations_preserved':True});workflow['pending']=None;state['phase']='mockup_review';return
        manifest=self.workflow.require_product(directory,workflow)
        if action=='plan_mockups':
            checkpoint=directory/'recovery'/'before-lifestyle'/'state.json'
            if not checkpoint.exists():write(checkpoint,state)
        design=self.feedback(state,payload)
        if action=='save_mockup_feedback':return
        if action=='refresh_mockup_geometry':
            if not design['rounds']:raise Invalid('No saved lifestyle concepts to refine')
            original=design['rounds'][-1]
            if original['product_id']!=manifest['id']:raise Invalid('Saved concept belongs to an older product')
            identifier=digest({'round':original['id'],'geometry_version':2});target=directory/'lifestyle'/identifier;pages=self.pages(directory,workflow,manifest);records=[]
            for old in original['candidates']:
                body=(directory/old['background_file']).read_bytes()
                if hashlib.sha256(body).hexdigest()!=old['background_sha256']:raise Invalid('Saved background changed')
                issue=old.get('placement_reason');quad=None
                try:
                    if old.get('quad') is None:raise Invalid(issue or 'Surface needs a new scene')
                    quad=fit_paper(production.raster(body),old['quad']);issue=None
                except Invalid as error:issue=str(error)
                page=pages[old['source_page_id']];image=composite(production.raster(body),production.raster(page['body']),quad) if quad else production.raster(body)
                file=target/f"mockup-{old['scene_index']}.png";write_bytes(file,production.png(image));record={**old,'id':identifier+'-scene-'+str(old['scene_index']),
                    'file':str(file.relative_to(directory)),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'quad':quad,'geometry_version':2,
                    'placement_status':'ready' if quad else 'needs_revision','placement_reason':issue,'source_composited':quad is not None};records.append(record)
            result={**original,'id':identifier,'candidates':records,'reviews':{},'created_at':now(),'refined_from':original['id'],'paid_calls':0}
            write(target/'round.json',result);self.apply(state,'mockup_concepts',result);return
        if not self.enabled():raise Invalid('Configure real mockup planner and image providers before paid scene generation')
        if action=='plan_mockups':
            context={'current_scene_plan':payload.get('scene_plan',design.get('plan')),'brief':{k:state['brief'][k] for k in ('concept','audience','purpose')},'requirements':workflow['plan']['constraints'],
                'inventory':manifest['units'],'comments':design['comments'],'prior_assessments':[{'plan':r['plan'],'reviews':r.get('reviews',{}),'candidate_map':[{'id':c['id'],'scene_index':c['scene_index']} for c in r['candidates']]} for r in design['rounds'][-2:]],'previous_failures':design.get('failures',[])[-3:],'approved_related_scene_examples':self.remembered(state),
                'preferences':self.studio.preferences.context(state['id'],workflow['plan']['family'])}
            feedback_images=[]
            if design['rounds']:
                latest=design['rounds'][-1];candidates=latest['candidates'];ordered=[c for c in candidates if latest.get('reviews',{}).get(c['id'])=='accept'][:1]+[c for c in candidates if latest.get('reviews',{}).get(c['id'])=='reject'][:1]+candidates
                for candidate in ordered:
                    if candidate['id'] not in {c['id'] for c in feedback_images}:feedback_images.append({**candidate,'decision':latest.get('reviews',{}).get(candidate['id'],'unmarked')})
                    if len(feedback_images)==3:break
            context['image_roles']={'first_images':'up to three actual finished product pages','following_feedback_images':[{'id':c['id'],'decision':c['decision'],'scene_index':c['scene_index']} for c in feedback_images]}
            self.workflow.queue(directory,state,'mockup_plan',{'manifest_id':manifest['id'],'context':context,'count':design['count'],'feedback_images':feedback_images})
        elif action=='generate_mockup_concepts':
            value=payload.get('scene_plan',design.get('plan'));value=checked_plan(value,design['count'],{u['id'] for u in manifest['units']})
            if design.get('plan_product_id')!=manifest['id']:raise Invalid('Plan scenes again for the current product version')
            design['plan']=value
            self.workflow.queue(directory,state,'mockup_concepts',{'manifest_id':manifest['id'],'plan':value,'comments':design['comments'],'previous':design['rounds'][-1] if design['rounds'] else None})
        elif action=='finalize_mockups':
            if payload.get('consent_expensive') is not True:raise Invalid('Explicit consent is required before final mockup generation')
            if not design['rounds']:raise Conflict('Generate and review cheap concepts first')
            current=design['rounds'][-1]
            if current['product_id']!=manifest['id'] or digest(current['plan'])!=digest(design['plan']):raise Invalid('Generate concepts for the current scene plan/product before final generation')
            selected=[c for c in current['candidates'] if current.get('reviews',{}).get(c['id'])=='accept']
            if not selected:raise Invalid('Like at least one concept before final generation')
            if any(c.get('placement_status')!='ready' for c in selected):raise Invalid('A scene without safe artwork placement must be revised, not promoted')
            if len(current.get('reviews',{}))!=len(current['candidates']):raise Invalid('Mark all concepts before final generation')
            self.workflow.queue(directory,state,'mockup_final',{'manifest_id':manifest['id'],'plan':current['plan'],'selected':selected,'comments':design['comments']})
        else:raise Invalid('Unknown lifestyle action')
    def pages(self,directory,workflow,manifest):
        root=directory/workflow['products'][-1]['directory'];paper=manifest['settings']['formats'][0]
        return {f['unit_id']:{'record':f,'body':(root/f['file']).read_bytes()} for f in manifest['files'] if f.get('role')=='print_page' and f['format']==paper}
    def run(self,directory,folder,request):
        if request['kind'].startswith('mockup_board_'):return self.board.run(directory,folder,request)
        state=read(directory/'state.json');workflow=state['workflow'];manifest=self.workflow.require_product(directory,workflow);value=request['value']
        if manifest['id']!=value['manifest_id']:raise Invalid('Product changed during scene generation')
        pages=self.pages(directory,workflow,manifest)
        if request['kind']=='mockup_plan':
            path=folder/'response.json'
            if path.exists():result=read(path)
            else:
                images=[p['body'] for p in list(pages.values())[:3]]
                for record in value.get('feedback_images',[]):
                    body=(directory/record['file']).read_bytes()
                    if hashlib.sha256(body).hexdigest()!=record['sha256']:raise Invalid('Feedback scene changed')
                    images.append(body)
                result=self.studio.mockup_planner.mockup_plan(value['context'],value['count'],request['id'],state['id'],images)
                write(path,result)
            return checked_plan(result,value['count'],set(pages))
        final=request['kind']=='mockup_final';scenes=value['plan']['scenes'];selected=value.get('selected') or [{'scene_index':i} for i in range(len(scenes))];records=[]
        target=directory/'lifestyle'/request['id'];provider=self.studio.mockup_finals if final else self.studio.mockup_drafts
        for index,selection in enumerate(selected):
            scene_index=selection['scene_index'];scene=scenes[scene_index];key=f"{request['id']}-scene-{scene_index}";path=target/f'scene-{scene_index}.json'
            with guard(directory):
                current=read(directory/'state.json');current['workflow']['mockup_progress']={'completed':index,'total':len(selected),'title':scene['title']};self.studio.save(directory,current)
            if path.exists():record=read(path)
            else:
                background=target/f'background-{scene_index}.png';surface=target/f'surface-{scene_index}.json'
                reference=selection if final else None
                if not final and value.get('previous'):
                    previous=value['previous'];reference=next((c for c in previous['candidates'] if c['scene_index']==scene_index and previous.get('reviews',{}).get(c['id'])=='accept'),None)
                if not background.exists():
                    asset=provider.mockup_scene(scene,value['comments'],key,state['id'],final,reference)
                    if asset.media_type!='image/png':raise Invalid('Real mockup scene must return PNG')
                    production.raster(asset.content);write_bytes(background,asset.content)
                body=background.read_bytes()
                if not surface.exists():write(surface,self.studio.mockup_planner.mockup_surface(body,key+'-surface',state['id']))
                page=pages[scene['page_id']];issue=None
                try:quad=fit_paper(production.raster(body),checked_surface(read(surface)))
                except Invalid as error:quad=None;issue=str(error)
                image=composite(production.raster(body),production.raster(page['body']),quad) if quad else production.raster(body)
                file=target/f'mockup-{scene_index}.png';write_bytes(file,production.png(image))
                record={'id':key,'scene_index':scene_index,'scene_title':scene['title'],'scene_description':scene['description'],'file':str(file.relative_to(directory)),
                    'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'background_file':str(background.relative_to(directory)),'background_sha256':hashlib.sha256(body).hexdigest(),
                    'product_id':manifest['id'],'source_page_id':scene['page_id'],'source_page_sha256':page['record']['sha256'],'quad':quad,
                    'geometry_version':2,'placement_status':'needs_revision' if issue else 'ready','placement_reason':issue,'source_composited':quad is not None,
                    'renderer_version':'lifestyle-v1','origin':'generative_lifestyle','quality':'final' if final else 'concept','review_required':True,'comments_sha256':digest(value['comments'])}
                write(path,record)
            for filename,sha in (('file','sha256'),('background_file','background_sha256')):
                if hashlib.sha256((directory/record[filename]).read_bytes()).hexdigest()!=record[sha]:raise Invalid('Saved mockup asset changed')
            records.append(record)
        return {'id':request['id'],'product_id':manifest['id'],'plan':value['plan'],'comments':value['comments'],'candidates':records,'reviews':{},'created_at':now()}
    def apply(self,state,kind,result):
        if kind.startswith('mockup_board_'):return self.board.apply(state,kind,result)
        workflow=state['workflow'];design=self.design(state)
        if kind=='mockup_plan':
            design.update(plan=result,plan_product_id=workflow['products'][-1]['id'],status='plan_review')
            workflow['approvals'].pop('mockups',None);workflow['approvals'].pop('listing',None)
        elif kind=='mockup_concepts':
            if not any(r['id']==result['id'] for r in design['rounds']):design['rounds'].append(result)
            design['status']='concept_review'
        else:
            workflow['mockups']=result['candidates'];workflow['approvals'].pop('mockups',None);design.update(status='final_review',final_round_id=result['id'],final_comments_sha256=digest(result['comments']))
        if kind!='mockup_plan':workflow['mockup_progress']={'completed':len(result['candidates']),'total':len(result['candidates']),'title':None}
        workflow['stage']='mockups';state['phase']='mockup_review'
