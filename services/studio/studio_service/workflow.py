"""Versioned manufacture → mockups → listing copy; human approvals bind hashes."""
import hashlib
from pathlib import Path
import uuid
from . import production
from .ports import Asset
from .storage import Invalid, Conflict, canonical, digest, guard, now, read, write, write_bytes

from .lifestyle import ACTIONS as LIFESTYLE_ACTIONS, Lifestyle, count as mockup_count

ACTIONS=LIFESTYLE_ACTIONS|{'save_plan','remember_preference','approve_direction','produce_selected','approve_product','make_mockups',
         'save_template','approve_mockups','generate_listing','save_listing','approve_listing','retry_workflow','return_to_direction'}


class Workflow:
    def __init__(self,studio):self.studio=studio;self.lifestyle=Lifestyle(self)

    def state(self,state,directory):
        if 'workflow' not in state:
            state['workflow']={'version':2,'stage':'direction' if state['rounds'] else 'brief','plan':production.plan(read(directory/'original-brief.json'),state['brief']),
                               'products':[],'mockups':[],'listing':None,'approvals':{},'pending':None}
        return state['workflow']

    def queue(self,directory,state,kind,value):
        workflow=self.state(state,directory)
        if workflow.get('pending'):raise Conflict('Wait for or recover the current operation')
        identifier=uuid.uuid4().hex;folder=directory/'workflow-jobs'/identifier
        write(folder/'request.json',{'id':identifier,'project_id':state['id'],'kind':kind,'value':value,'created_at':now()})
        write(folder/'operation.json',{'status':'queued'})
        workflow['pending']=identifier;state['phase']='generating_mockups' if kind.startswith('mockup_') else 'generating_product' if kind=='produce' else 'generating_listing'

    def candidate(self,state,identifier):
        candidate=next((c for c in self.studio.references(state) if c['id']==identifier),None)
        if not candidate:raise Invalid('Choose an accepted sample')
        return candidate

    def command(self,directory,state,action,payload,key):
        workflow=self.state(state,directory)
        if (directory/'workflow-final-reservation.json').exists() and action!='approve_listing':raise Conflict('Final approval is reserved; retry its original action')
        if workflow.get('pending') and action not in ('retry_workflow','abandon_mockup_job'):raise Conflict('Wait for the current operation')
        if action in LIFESTYLE_ACTIONS:self.lifestyle.command(directory,state,action,payload)
        elif action=='save_plan':
            if workflow.get('direction'):raise Conflict('Return to the direction stage before changing the inventory')
            value=production.checked_plan(payload.get('plan'));value={**value,'version':workflow['plan']['version']+1}
            workflow['plan']=value
        elif action=='remember_preference':
            evidence=[{'id':c['id'],'sha256':c['sha256'],'decision':c['review']['decision']} for c in self.studio.references(state)+self.studio.references(state,False)]
            self.studio.preferences.change(payload,state['id'],evidence)
        elif action=='approve_direction':
            if state['phase'] not in ('sketch_review','professional_review'):raise Conflict('Review a direction first')
            self.studio.feedback(state,payload);candidate=self.candidate(state,payload.get('candidate_id'))
            if payload.get('consent_expensive') is not True:raise Invalid('Explicit production cost consent required')
            spec=production.settings(payload.get('print_settings'));production.preflight(workflow['plan'],spec)
            workflow.update(direction={'candidate':candidate,'plan_sha256':digest(workflow['plan']),'approved_at':now()},
                            print_settings=spec,stage='product',approvals={})
            self.queue(directory,state,'produce',{'plan':workflow['plan'],'settings':spec,'direction':candidate,'previous':None,'selected':None,'comments':payload.get('comments','')})
        elif action=='produce_selected':
            if state['phase'] not in ('product_review','mockup_review','listing_review'):raise Conflict('Review product files first')
            selected=payload.get('unit_ids')
            ids={u['id'] for u in workflow['plan']['units']}
            if not isinstance(selected,list) or not selected or not set(selected)<=ids or len(set(selected))!=len(selected):raise Invalid('Choose explicit inventory items to revise')
            if payload.get('consent_expensive') is not True:raise Invalid('Explicit production cost consent required')
            comments=payload.get('comments','')
            if not isinstance(comments,str) or not comments.strip() or len(comments)>4000:raise Invalid('Explain the selected correction')
            self.queue(directory,state,'produce',{'plan':workflow['plan'],'settings':workflow['print_settings'],'direction':workflow['direction']['candidate'],
                'previous':workflow['products'][-1],'selected':selected,'comments':comments})
        elif action=='approve_product':
            if state['phase']!='product_review':raise Conflict('Review the current product files first')
            manifest=self.manifest(directory,workflow)
            if payload.get('visual_review_confirmed') is not True:raise Invalid('Confirm visual/content review of the product')
            workflow['approvals']['product']={'manifest_id':manifest['id'],'at':now(),'visual_review_confirmed':True,
                                               'physical_print_proof_confirmed':payload.get('print_proof_confirmed') is True}
            self.mockups(directory,state,payload.get('templates'),payload.get('count'))
        elif action=='make_mockups':
            if 'count' in payload:self.lifestyle.feedback(state,payload)
            self.require_product(directory,workflow);self.mockups(directory,state,payload.get('templates'),payload.get('count'))
        elif action=='save_template':
            name=payload.get('name');template=payload.get('template')
            import re
            if not isinstance(name,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',name):raise Invalid('Template name required')
            production.compose_mockup(production.raster(self.page(directory,workflow)),template)
            write(self.studio.root/'templates'/(name+'.json'),{'name':name,'template':template,'at':now()})
        elif action=='approve_mockups':
            if self.lifestyle.enabled():
                self.lifestyle.feedback(state,payload)
                design=self.lifestyle.design(state)
                if design.get('final_comments_sha256')!=digest(design['comments']):raise Invalid('New mockup comments require another reviewed final render before approval')
            self.require_product(directory,workflow)
            if state['phase']!='mockup_review' or not 1<=len(workflow['mockups'])<=10:raise Conflict('Review the current mockups')
            if self.lifestyle.enabled() and any(m.get('quality')!='final' or m.get('origin')!='generative_lifestyle' or m.get('placement_status')!='ready' for m in workflow['mockups']):raise Invalid('Review cheap lifestyle concepts and explicitly generate final mockups first')
            self.verify_mockups(directory,workflow)
            workflow['approvals']['mockups']={'product_id':workflow['products'][-1]['id'],'sha256':digest(workflow['mockups']),'at':now()}
            if self.lifestyle.enabled():self.lifestyle.remember(state)
            workflow['stage']='listing';state['phase']='listing_review'
        elif action=='generate_listing':
            self.require_mockups(directory,workflow)
            self.queue(directory,state,'copy',{'manifest_id':workflow['products'][-1]['id']})
        elif action=='save_listing':
            self.require_mockups(directory,workflow)
            value=production.factual_listing(payload.get('listing'),self.require_product(directory,workflow))
            workflow['listing']={'copy':value,'product_id':workflow['products'][-1]['id'],'at':now(),'source':'human_edited'}
            workflow['approvals'].pop('listing',None);state['phase']='listing_review'
        elif action=='approve_listing':
            self.require_mockups(directory,workflow);self.finish(directory,state,key,payload)
        elif action=='retry_workflow':
            if state['phase']!='generation_failed' or not workflow.get('pending'):raise Conflict('No failed production/copy operation')
            if payload.get('consent_expensive') is not True:raise Invalid('Explicit cost consent required for recovery')
            folder=directory/'workflow-jobs'/workflow['pending'];operation=read(folder/'operation.json')
            write(folder/'operation.json',{**operation,'status':'queued','explicit_recovery_at':now()})
            request=read(folder/'request.json');state['phase']='generating_mockups' if request['kind'].startswith('mockup_') else 'generating_product' if request['kind']=='produce' else 'generating_listing'
        elif action=='return_to_direction':
            if not state['rounds']:raise Conflict('No direction history')
            workflow['direction']=None;workflow['approvals']={};workflow['stage']='direction';workflow['listing']=None
            state['phase']=state['rounds'][-1]['mode']+'_review'
        else:raise Invalid('Unknown workflow action')

    def manifest(self,directory,workflow):
        if not workflow['products']:raise Invalid('No produced files')
        record=workflow['products'][-1];path=directory/record['directory'];manifest=read(path/'manifest.json')
        if manifest['id']!=record['id'] or digest({k:v for k,v in manifest.items() if k!='id'})!=manifest['id']:raise Invalid('Product manifest changed')
        if not manifest['automatic_checks_passed']:raise Invalid('Mechanical checks failed')
        for file in manifest['files']:
            target=path/file['file']
            if target.is_symlink() or not target.resolve().is_relative_to(path.resolve()) or hashlib.sha256(target.read_bytes()).hexdigest()!=file['sha256']:raise Invalid('Product file changed after review')
        return manifest

    def require_product(self,directory,workflow):
        manifest=self.manifest(directory,workflow)
        if workflow['approvals'].get('product',{}).get('manifest_id')!=manifest['id']:raise Invalid('Approve this exact product version first')
        return manifest

    def page(self,directory,workflow):
        manifest=self.require_product(directory,workflow)
        record=next(x for x in manifest['files'] if x.get('role')=='print_page')
        return (directory/workflow['products'][-1]['directory']/record['file']).read_bytes()

    def mockups(self,directory,state,templates,number=None):
        workflow=state['workflow'];manifest=self.require_product(directory,workflow)
        if templates is None:templates=[{'kind':'flat' if any(u['kind']=='text' for u in manifest['units']) else 'frame','scale':.86,'x':0,'y':0,'perspective':'straight'},{'kind':'stack','scale':.82,'x':0,'y':0,'perspective':'left'},{'kind':'bundle','scale':.9,'x':0,'y':0,'perspective':'straight'}]
        if number is not None:
            mockup_count(number)
            if templates is not None and len(templates)!=number:
                if len(templates)==3:templates=[templates[i%len(templates)] for i in range(number)]
                else:raise Invalid('Template count does not match chosen quantity')
        if not isinstance(templates,list):raise Invalid('Mockup template list required')
        mockup_count(len(templates))
        revision=uuid.uuid4().hex;records=[];base=directory/workflow['products'][-1]['directory']
        pages=[production.raster((base/x['file']).read_bytes()) for x in manifest['files'] if x.get('role')=='print_page' and x.get('format')==manifest['settings']['formats'][0]]
        for index,template in enumerate(templates):
            if isinstance(template,str):
                import re
                if not re.fullmatch('[A-Za-z0-9_-]{1,64}',template):raise Invalid('Invalid saved template')
                template=read(self.studio.root/'templates'/(template+'.json'))['template']
            if not isinstance(template,dict):raise Invalid('Invalid mockup template')
            image=pages[min(index,len(pages)-1)]
            if template.get('kind')=='bundle':image=production.contact_sheet(pages)
            result,provenance=production.compose_mockup(image,template,pages);body=production.png(result)
            file=f'mockups/{revision}/sample-{index+1}.png';write_bytes(directory/file,body)
            records.append({'file':file,'sha256':hashlib.sha256(body).hexdigest(),'template':template,'product_id':manifest['id'],
                            'product_page_sha256':[x['sha256'] for x in manifest['files'] if x.get('role')=='print_page'],**provenance})
        workflow['mockups']=records;workflow['stage']='mockups';workflow['approvals'].pop('mockups',None)
        state['phase']='mockup_review';write(directory/'mockups'/revision/'manifest.json',records)

    def verify_mockups(self,directory,workflow):
        for item in workflow['mockups']:
            if item['product_id']!=workflow['products'][-1]['id'] or hashlib.sha256((directory/item['file']).read_bytes()).hexdigest()!=item['sha256']:raise Invalid('Mockup is stale or changed')

    def require_mockups(self,directory,workflow):
        self.require_product(directory,workflow);self.verify_mockups(directory,workflow)
        if self.lifestyle.enabled() and (not workflow['mockups'] or any(m.get('origin')!='generative_lifestyle' or m.get('quality')!='final' or m.get('placement_status')!='ready' for m in workflow['mockups'])):raise Invalid('Finalize and approve lifestyle mockups before downstream delivery')
        if workflow['approvals'].get('mockups',{}).get('sha256')!=digest(workflow['mockups']):raise Invalid('Approve these exact mockups first')
        if self.lifestyle.enabled():
            design=workflow.get('mockup_design',{})
            if design.get('final_comments_sha256')!=digest(design.get('comments','')):raise Invalid('Latest mockup comments have not been applied to the approved finals')

    def finish(self,directory,state,key,payload):
        workflow=state['workflow'];manifest=self.require_product(directory,workflow);listing=workflow['listing']
        if not listing or listing['product_id']!=manifest['id']:raise Invalid('Generate/review copy for the current product first')
        if payload.get('copy_review_confirmed') is not True:raise Invalid('Confirm the listing accurately describes the actual files')
        production.checked_listing(listing['copy'])
        reservation=directory/'workflow-final-reservation.json'
        if reservation.exists():
            saved=read(reservation)
            if saved['key']!=key or saved['product_id']!=manifest['id'] or saved['copy_sha256']!=digest(listing['copy']):raise Conflict('Retry the original reserved final approval')
            workflow['approvals']=saved['approvals']
        else:
            workflow['approvals']['listing']={'product_id':manifest['id'],'copy_sha256':digest(listing['copy']),'at':now()}
            write(reservation,{'key':key,'product_id':manifest['id'],'copy_sha256':digest(listing['copy']),'approvals':workflow['approvals']})
        package_dir=directory/workflow['products'][-1]['directory']
        bundle=production.package(package_dir,manifest,listing['copy'],workflow['mockups']);write_bytes(directory/'product.zip',bundle)
        write_bytes(directory/'customer.zip',production.customer_package(package_dir,manifest))
        write(directory/'listing-handoff.json',{'status':'blocked_not_wired','etsy_api_called':False,'product_id':manifest['id'],
              'listing':listing['copy'],'mockups':workflow['mockups'],'approvals':workflow['approvals'],'approval_key':key})
        write(directory/'approved-product.json',{'product_id':manifest['id'],'approvals':workflow['approvals'],'at':now(),
              'sale_ready':False,'note':'Human-approved files; physical print proof remains separately recorded.'})
        workflow['stage']='delivery';state['phase']='approved';state['listing']={'status':'blocked_not_wired','etsy_api_called':False}

    def tick(self,directory):
        with guard(directory):
            state=read(directory/'state.json');workflow=state.get('workflow') or {};identifier=workflow.get('pending')
            if not identifier:return False
            folder=directory/'workflow-jobs'/identifier;operation=read(folder/'operation.json');request=read(folder/'request.json')
            if operation['status']=='failed':return True
            if operation['status']!='queued':
                state.update(phase='generation_failed',generation_error='Interrupted operation; explicit recovery required, completed assets are preserved')
                self.studio.save(directory,state);return True
            write(folder/'operation.json',{'status':'started','started_at':now()})
        try:
            result=self.lifestyle.run(directory,folder,request) if request['kind'].startswith('mockup_') else self.produce(directory,folder,request) if request['kind']=='produce' else self.copy(directory,folder,request)
            with guard(directory):
                state=read(directory/'state.json');workflow=state['workflow']
                if request['kind'].startswith('mockup_'):self.lifestyle.apply(state,request['kind'],result)
                elif request['kind']=='produce':
                    if not any(p['id']==result['id'] for p in workflow['products']):workflow['products'].append(result)
                    workflow['approvals']={};workflow['listing']=None;workflow['stage']='product';state['phase']='product_review'
                    workflow['progress']={'completed':len(workflow['plan']['units']),'total':len(workflow['plan']['units']),'current':None}
                else:workflow['listing']=result;state['phase']='listing_review'
                workflow['pending']=None;state.pop('generation_error',None);self.studio.save(directory,state)
            write(folder/'operation.json',{'status':'completed','completed_at':now()})
        except Exception as error:
            write(folder/'operation.json',{'status':'failed','error_type':type(error).__name__,'automatic_retry':False})
            with guard(directory):
                state=read(directory/'state.json')
                if request['kind'].startswith('mockup_'):self.lifestyle.design(state).setdefault('failures',[]).append({'job_id':request['id'],'kind':request['kind'],'message':str(error)[:300] if isinstance(error,Invalid) else type(error).__name__})
                state.update(phase='generation_failed',generation_error=str(error)[:300] if isinstance(error,Invalid) else 'Production failed; saved assets preserved. Explicit recovery required.')
                self.studio.save(directory,state)
        return True

    def produce(self,directory,folder,request):
        value=request['value'];identifier=request['id'];assets={};records={}
        target=directory/'products'/identifier;target.mkdir(parents=True,exist_ok=True)
        previous=value.get('previous');prior=previous.get('assets',{}) if previous else {}
        for unit_index,unit in enumerate(value['plan']['units']):
            with guard(directory):
                current=read(directory/'state.json');current['workflow']['progress']={'completed':unit_index,'total':len(value['plan']['units']),'current':unit['title']};self.studio.save(directory,current)
            if unit['kind']=='text':continue
            record_file=target/'artwork'/(unit['id']+'.json');body_file=target/'artwork'/(unit['id']+'.png')
            if record_file.exists():
                record=read(record_file);body=body_file.read_bytes()
            elif unit['id'] in prior and value['selected'] and unit['id'] not in value['selected']:
                old=prior[unit['id']];body=(directory/old['file']).read_bytes()
                if hashlib.sha256(body).hexdigest()!=old['sha256']:raise Invalid('Previously produced artwork changed')
                record={**old,'reused_from':previous['id']}
            else:
                reference=prior.get(unit['id']) or value['direction']
                result=self.studio.professional.generate({'operation_id':identifier+'-'+unit['id'],'project_id':request['project_id'],
                    'mode':'production','count':1,'brief':{'concept':unit['description'],'audience':'','purpose':'','deliverables':[unit['description']],
                        'visual_direction':value['plan']['style'],'requirements':'Generate original illustration only; text is rendered separately by code.'},
                    'production_unit':unit,'production_plan':value['plan'],'accepted':[reference], 'rejected':[],
                    'last_feedback':value['comments'],'feedback_context':{'evidence':[]},'negative_summary':{},
                    'image_size':production.image_size(value['settings']),'settings':value['settings'],
                    'preference_memory':self.studio.preferences.context(request['project_id'],value['plan']['family'])})
                if not isinstance(result,list) or len(result)!=1 or result[0].media_type!='image/png':raise Invalid('Production provider must return one real PNG per content unit')
                asset=result[0];production.raster(asset.content);body=asset.content;record={'provider':getattr(self.studio.professional,'name','custom'),'metadata':asset.metadata}
            sha=hashlib.sha256(body).hexdigest()
            if record_file.exists() and record['sha256']!=sha:raise Invalid('Saved artwork checksum mismatch')
            record={**record,'file':f'products/{identifier}/artwork/{unit["id"]}.png','sha256':sha,'unit_id':unit['id']}
            write_bytes(body_file,body);write(record_file,record);assets[unit['id']]={'content':body};records[unit['id']]=record
        manifest_file=target/'manifest.json'
        manifest=read(manifest_file) if manifest_file.exists() else production.assemble(target,value['plan'],value['settings'],assets,identifier)
        return {'id':manifest['id'],'directory':f'products/{identifier}','assets':records,'created_at':now(),'plan_sha256':digest(value['plan'])}

    def copy(self,directory,folder,request):
        state=read(directory/'state.json');workflow=state['workflow'];manifest=self.require_product(directory,workflow)
        if manifest['id']!=request['value']['manifest_id']:raise Invalid('Product changed during copy generation')
        path=folder/'response.json'
        if path.exists():value=read(path)
        else:
            if not hasattr(self.studio.copywriter,'listing'):raise Invalid('Configure a listing-copy provider before generation')
            source=read(directory/'original-brief.json')
            context={'manifest':{k:v for k,v in manifest.items() if k not in ('files','checks')},
                     'brief':state['brief'],'saved_evidence':[{'title':s.get('title'),'url':s.get('url'),'tags':s.get('tags')} for s in source.get('samples',[])[:3]],
                     'instruction':'Write two readable title options, one accurate description and exactly thirteen relevant tags. Describe only actual finished content, formats and sizes; digital download, no physical product. Do not invent performance, search volume, age suitability or included features. Tags up to 20 characters, titles up to 140.'}
            value=self.studio.copywriter.listing(context,request['id'],state['id']);write(path,value)
        value=production.factual_listing(value,manifest)
        return {'copy':value,'product_id':manifest['id'],'at':now(),'source':'configured_model','response_sha256':digest(value)}
