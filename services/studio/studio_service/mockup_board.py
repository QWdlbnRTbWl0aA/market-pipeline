"""Stable per-scene cards, explicit locks and separate final-refinement loop."""
import copy
import hashlib
import uuid
from .storage import Invalid, Conflict, canonical, digest, now, read, write, write_bytes, guard
from . import production

ACTIONS={'save_mockup_board','add_mockup_card','delete_mockup_card','toggle_mockup_lock','plan_mockup_board','render_mockup_board','enter_mockup_final','return_mockup_concepts','apply_mockup_comments','suggest_mockups','finalize_mockup_board','export_mockup_board','restore_mockup_round','recover_mockup_results','previous_mockup_image'}


class Board:
    def __init__(self,lifestyle):self.lifestyle=lifestyle;self.workflow=lifestyle.workflow;self.studio=lifestyle.studio
    def state(self,state):
        design=self.lifestyle.design(state)
        product_id=state['workflow']['products'][-1]['id'] if state['workflow']['products'] else None
        if design.get('board') and design['board']['product_id']!=product_id:
            design.setdefault('board_history',[]).append(copy.deepcopy(design.pop('board')))
        if 'board' not in design:
            plan=design.get('plan') if design.get('plan_product_id')==product_id else None;latest=design['rounds'][-1] if design['rounds'] else None;cards=[]
            for i,scene in enumerate(plan['scenes'] if plan else []):
                candidate=next((c for c in (latest or {}).get('candidates',[]) if c['scene_index']==i),None)
                cards.append({'id':digest({'project':state['id'],'initial_scene':i})[:32],'scene':copy.deepcopy(scene),'comments':'','locked':False,'candidate':copy.deepcopy(candidate)})
            design['board']={'version':2,'stage':'concept','cards':cards,'deleted':[],'events':[],'product_id':product_id}
        return design['board']
    def changed(self,state):
        w=state['workflow'];w['approvals'].pop('mockups',None);w['approvals'].pop('listing',None)
    def replaceable(self,directory,state):
        pending=state['workflow'].get('pending')
        if not pending or state['phase']!='generation_failed' or self.studio.budget.summary(state['id'])['unknown_outcomes']:return False
        folder=directory/'workflow-jobs'/pending
        return read(folder/'operation.json')['status']=='failed' and read(folder/'request.json')['kind'].startswith('mockup_')
    def scene_overrides(self,card):
        # Human text is durable input; compiled scene prose is a separate output.
        candidate=card.get('candidate') or {};baseline=candidate.get('requested_scene',candidate.get('scene'))
        overrides=copy.deepcopy(candidate.get('scene_overrides',{}))
        if not baseline and card.get('scene'):overrides.update(card['scene'])
        if baseline and card.get('scene'):
            overrides.update({k:v for k,v in card['scene'].items() if v!=baseline.get(k)})
        return overrides
    def context(self,state,manifest,cards):
        board=self.state(state);design=self.lifestyle.design(state)
        return {'brief':{k:state['brief'][k] for k in ('concept','audience','purpose')},'requirements':state['workflow']['plan']['constraints'],'inventory':manifest['units'],
                'comments':design['comments'],'cards_to_plan':[{'scene':c['scene'],'comments':c['comments'],'latest_scene_edits':self.scene_overrides(c)} for c in cards],
                'locked_scenes':[c['scene'] for c in board['cards'] if c['locked']],
                'other_gallery_scenes':[c['scene'] for c in board['cards'] if c['id'] not in {a['id'] for a in cards}],
                'deleted_scenes':[c['scene'] for c in board['deleted'][-10:]],'approved_related_scene_examples':self.lifestyle.remembered(state)}
    def queue_update(self,directory,state,cards,manifest,*,final=False,model=None,export=False):
        board=self.state(state);design=self.lifestyle.design(state)
        if not final:model=None  # Final-picker changes never invalidate cheap work.
        if self.studio.model_roles:
            if final:
                self.studio.model_roles.select_final(model)
                if model is None:model=self.studio.model_roles.final_options()[0]['id']
            else:self.studio.model_roles.require_cheap()
        previous=[c for c in board['cards'] if c.get('candidate')][:3]
        value={'manifest_id':manifest['id'],'cards':copy.deepcopy(cards),'comments':design['comments'],'stage':'final' if final else 'concept',
               'model_id':model,'context':self.context(state,manifest,cards),'feedback_images':[c['candidate'] for c in previous]}
        adapter=(self.studio.model_roles.select_final(model) if self.studio.model_roles else self.studio.mockup_finals) if final else None
        if final and callable(getattr(adapter,'mockup_direct_image',None)):
            value.update(refinement_version=2,export_only=export,final_comments=board.get('final_comments',''))
            for c in cards:c['needs_render']=True
        elif final and callable(getattr(self.studio.mockup_planner,'mockup_correction',None)):
            if self.studio.model_roles and not self.studio.model_roles.permitted('openai','mockup_planning'):raise Invalid('Correction planning role is unavailable')
            value.update(refinement_version=1,export_only=export)
        kind='mockup_board_final' if final else 'mockup_board_update'
        if state['workflow'].get('pending'):
            if not self.replaceable(directory,state):raise Conflict('Current job cannot be replaced; recover unknown billing first')
            old=state['workflow']['pending'];folder=directory/'workflow-jobs'/old;original=read(folder/'request.json')
            comparable=copy.deepcopy(original['value'])
            if comparable.get('stage')=='concept':comparable['model_id']=None
            same_direct=False
            if value.get('refinement_version')==comparable.get('refinement_version')==2:
                # Completed siblings may now have newer candidates. Resume the
                # original job if every remaining correction is unchanged.
                previous={c['id']:c for c in comparable['cards']}
                same_direct=all(value.get(k)==comparable.get(k) for k in ('manifest_id','model_id','final_comments','export_only')) and all(
                    c['id'] in previous and all(c.get(k)==previous[c['id']].get(k) for k in ('scene','comments','candidate')) for c in cards)
            if original['kind']==kind and (comparable==value or same_direct):
                operation=read(folder/'operation.json')
                write(folder/('recovery-'+uuid.uuid4().hex+'.json'),{'at':now(),'previous_operation':operation,'explicit_apply_same_inputs':True})
                write(folder/'operation.json',{**operation,'status':'queued','explicit_recovery_at':now()});state['phase']='generating_mockups';return
            write(folder/'replaced.json',{'at':now(),'by_explicit_user_action':True,'paid_history_preserved':True});state['workflow']['pending']=None
        if final:board['final_model_id']=model
        self.workflow.queue(directory,state,kind,value)
        state['workflow']['mockup_progress']={'completed':0,'total':len(cards),'title':None}
    def feedback(self,state,payload):
        board=self.state(state);patches=payload.get('cards',[])
        if not isinstance(patches,list) or len(patches)>10:raise Invalid('Bounded mockup cards required')
        seen=set()
        for patch in patches:
            if not isinstance(patch,dict) or set(patch)-{'id','scene','comments','edit_box'} or patch.get('id') in seen:raise Invalid('Invalid card edits')
            seen.add(patch.get('id'));card=self.card(board,patch.get('id'))
            comments=patch.get('comments',card['comments'])
            if not isinstance(comments,str) or len(comments)>1800:raise Invalid('Bounded card comments required')
            region=patch.get('edit_box',card.get('edit_box'))
            if region is not None:
                from .refinement import box
                box(region)
            scene=patch.get('scene',card['scene'])
            if scene is not None:
                from .lifestyle import checked_plan
                checked_plan({'product_understanding':'Card','direction':'Card','scenes':[scene]},1,{u['id'] for u in state['workflow']['plan']['units']})
            if card['locked'] and (scene!=card['scene'] or comments!=card['comments'] or region!=card.get('edit_box')):raise Invalid('Unlock the sample before editing its prompt/comments')
            if board['stage']=='final' and scene!=card['scene']:raise Invalid('Return to concepts to change composition; final loop accepts touch-up comments only')
            if scene!=card['scene'] or comments!=card['comments'] or region!=card.get('edit_box'):self.changed(state);card['needs_render']=True
            card.update(scene=copy.deepcopy(scene),comments=comments)
            if region is not None:card['edit_box']=copy.deepcopy(region)
            else:card.pop('edit_box',None)
        if 'comments' in payload:
            value=payload['comments']
            if not isinstance(value,str) or len(value)>4000:raise Invalid('Bounded shared comments required')
            if value!=self.lifestyle.design(state)['comments']:self.changed(state)
            if value!=self.lifestyle.design(state)['comments'] and board['cards'] and all(c['locked'] for c in board['cards']):raise Invalid('Unlock a sample before changing shared instructions')
            if value!=self.lifestyle.design(state)['comments']:
                for card in board['cards']:
                    if not card['locked']:card['needs_render']=True
            self.lifestyle.design(state)['comments']=value
        if 'final_comments' in payload:
            text=payload['final_comments']
            if board['stage']!='final' or not isinstance(text,str) or len(text)>4000:raise Invalid('Bounded final batch comments required')
            if text!=board.get('final_comments',''):
                if board['cards'] and all(c['locked'] for c in board['cards']):raise Invalid('Unlock a card before changing final batch comments')
                board['final_comments']=text;self.changed(state)
                for c in board['cards']:
                    if not c['locked']:c['needs_render']=True
        return board
    def card(self,board,identifier):
        result=next((c for c in board['cards'] if c['id']==identifier),None)
        if result is None:raise Invalid('Choose an active mockup card')
        return result
    def command(self,directory,state,action,payload):
        manifest=self.workflow.require_product(directory,state['workflow']);board=self.feedback(state,payload)
        if board['product_id'] not in (None,manifest['id']):raise Invalid('Mockup board belongs to an older product; return to product approval')
        board['product_id']=manifest['id'];design=self.lifestyle.design(state)
        if action=='save_mockup_board':return
        if action in ('apply_mockup_comments','suggest_mockups','finalize_mockup_board'):
            if not self.lifestyle.enabled():raise Invalid('Configure scene providers first')
            if action=='suggest_mockups':
                if board['stage']!='concept':raise Invalid('Return to sketches for new ideas')
                from .lifestyle import count
                number=count(payload.get('additional_count',1))
                if len(board['cards'])+number>10:raise Invalid('At most ten active mockups')
                cards=[{'id':uuid.uuid4().hex,'scene':None,'comments':'','locked':False,'candidate':None} for _ in range(number)];board['cards'].extend(cards)
                self.queue_update(directory,state,cards,manifest)
            else:
                final=action=='finalize_mockup_board' or board['stage']=='final'
                if final:
                    if payload.get('consent_expensive') is not True:raise Invalid('Explicit consent required for every final-image round')
                    if self.studio.model_roles:self.studio.model_roles.select_final(payload.get('model_id'))
                if action=='finalize_mockup_board':
                    if board['stage']!='concept' or not board['cards'] or any(not c['locked'] for c in board['cards']):raise Invalid('Lock every concept first')
                    board['concept_cards']=copy.deepcopy(board['cards']);board['stage']='final'
                    for card in board['cards']:card.update(locked=False,needs_render=True)
                cards=[c for c in board['cards'] if not c['locked']]
                if final and action=='apply_mockup_comments' and any(c.get('needs_render') for c in cards):cards=[c for c in cards if c.get('needs_render')]
                from .refinement import correction_identity
                adapter=(self.studio.model_roles.select_final(payload.get('model_id')) if self.studio.model_roles else self.studio.mockup_finals) if final else None
                direct=callable(getattr(adapter,'mockup_direct_image',None))
                blocked=[c for c in cards if not direct and (c.get('refinement_failure') or {}).get('code')=='invalid_correction_plan' and not c.get('edit_box') and c['refinement_failure'].get('context_sha256')==correction_identity(c,{'comments':design['comments'],'export_only':False})]
                cards=[c for c in cards if c not in blocked]
                if not cards:
                    if blocked:raise Invalid('Select a correction area or change the comments before retrying the invalid plan; no request sent')
                    raise Invalid('Unlock or add a mockup first')
                self.queue_update(directory,state,cards,manifest,final=final,model=payload.get('model_id'))
            self.changed(state);board['events'].append({'action':action,'at':now()});state['workflow']['stage']='mockups';return
        if action=='previous_mockup_image':
            card=self.card(board,payload.get('card_id'));current=card.get('candidate') or {}
            reference=(current.get('direct_edit') or current.get('refinement') or {}).get('reference_id')
            previous=next((c for r in design['rounds'] for c in r['candidates'] if c['id']==reference and c.get('card_id')==card['id']),None)
            if previous is None:raise Invalid('No previous saved version for this card')
            from .refinement import bytes_for
            bytes_for(directory,previous)
            board['events'].append({'action':action,'at':now(),'card_id':card['id'],'from':current['id'],'to':previous['id']})
            card.update(candidate=copy.deepcopy(previous),locked=False,needs_render=True);card.pop('refinement_failure',None)
            state['workflow']['mockups']=[c['candidate'] for c in board['cards'] if c.get('candidate')];self.changed(state);return
        if action=='recover_mockup_results':
            pending=state['workflow'].get('pending')
            if not pending or state['phase']!='generation_failed':raise Invalid('No failed mockup job to recover')
            folder=directory/'workflow-jobs'/pending;operation=read(folder/'operation.json');request=read(folder/'request.json')
            if operation['status']!='failed' or request['value'].get('refinement_version')!=1:raise Invalid('Only a failed targeted-refinement job can be recovered without inference')
            if request['value']['manifest_id']!=manifest['id']:raise Invalid('Product changed since the saved job')
            from .refinement import recover_saved
            result=recover_saved(self,directory,request,manifest)
            self.apply(state,request['kind'],result);state['workflow']['pending']=None
            state.pop('generation_error',None);state.pop('generation_diagnostic',None)
            write(folder/'saved-results-recovery.json',{'at':now(),'completed_candidates':[c['id'] for c in result['candidates']],'failures':result['failures'],'paid_calls':0})
            write(folder/'operation.json',{**operation,'status':'recovered_saved_results','recovered_at':now(),'automatic_retry':False})
            return
        if action=='export_mockup_board':
            self.require_final(state)
            if payload.get('consent_expensive') is not True:raise Invalid('Explicit export cost consent required')
            cards=[c for c in board['cards'] if c['candidate'].get('render_profile')!='export']
            if not cards:raise Invalid('These mockups are already exported')
            self.queue_update(directory,state,cards,manifest,final=True,model=payload.get('model_id'),export=True)
            self.changed(state);return
        if action=='restore_mockup_round':
            if state['workflow'].get('pending'):raise Conflict('Cannot restore while a job is pending')
            chosen=next((r for r in design['rounds'] if r['id']==payload.get('round_id') and r.get('stage')=='final'),None)
            if not chosen or chosen['product_id']!=manifest['id']:raise Invalid('Choose a saved final round for this product')
            candidates={c.get('card_id'):c for c in chosen['candidates']}
            if set(candidates)!={c['id'] for c in board['cards']}:raise Invalid('Saved round does not match the active cards')
            from .refinement import bytes_for
            for c in candidates.values():bytes_for(directory,c)
            board.setdefault('restorations',[]).append({'at':now(),'round_id':chosen['id'],'previous_cards':copy.deepcopy(board['cards']),'previous_stage':board['stage'],'previous_mockups':copy.deepcopy(state['workflow']['mockups']),'previous_shared_comments':design['comments']})
            original=read(directory/'workflow-jobs'/chosen['id']/'request.json')['value']
            saved={c['id']:c for c in original['cards']}
            for card in board['cards']:
                card.update(candidate=copy.deepcopy(candidates[card['id']]),scene=copy.deepcopy(candidates[card['id']]['scene']),comments=saved[card['id']]['comments'],locked=False,needs_render=False)
                card.pop('refinement_failure',None)
            board['stage']='final';design['comments']=original['comments'];design['final_comments_sha256']=digest(design['comments'])
            state['workflow']['mockups']=[c['candidate'] for c in board['cards']];state['phase']='mockup_review';state['workflow']['stage']='mockups'
            board['events'].append({'action':action,'round_id':chosen['id'],'at':now()});self.changed(state);return
        if action=='toggle_mockup_lock':
            card=self.card(board,payload.get('card_id'))
            if not card['locked']:
                c=card.get('candidate')
                if not c:raise Invalid('Generate a sample before locking it')
                file=directory/c['file']
                if file.is_symlink() or not file.resolve().is_relative_to(directory.resolve()) or hashlib.sha256(file.read_bytes()).hexdigest()!=c['sha256']:raise Invalid('Saved sample changed; review its integrity before locking')
                if board['stage']=='concept':
                    if c.get('scene') and c.get('requested_scene',c['scene'])!=card['scene']:raise Invalid('Apply or revert changed scene instructions before approving the existing composition')
                    if c.get('placement_status')!='ready' and payload.get('concept_review_confirmed') is not True:raise Invalid('Confirm concept-only approval; final product placement remains unresolved')
                    card['concept_approval']={'candidate_id':c['id'],'sha256':c['sha256'],'at':now(),'placement_review_required':c.get('placement_status')!='ready','pending_notes':bool(card.get('needs_render'))}
                elif c.get('renderer_version')=='direct-edit-v1':
                    if c.get('quality')!='final' or c.get('card_input_sha256')!=digest({'scene':card['scene'],'comments':card['comments']}):raise Invalid('Review the current final image before approval')
                    if card.get('needs_render') or c.get('final_comments_sha256')!=digest(board.get('final_comments','')):raise Invalid('Apply the edited comments before approval')
                    if payload.get('human_review_confirmed') is not True:raise Invalid('Confirm visual quality and actual product content before approval')
                    c['human_approval']={'sha256':c['sha256'],'visual_and_product_review_confirmed':True,'at':now()}
                    state['workflow']['mockups']=[x['candidate'] for x in board['cards'] if x.get('candidate')]
                else:
                    if c.get('placement_status')!='ready' or c.get('source_composited') is not True:raise Invalid('Final product placement must be validated before approval')
                    if card.get('needs_render'):raise Invalid('Render the changed instructions before locking this sample')
                    if c['quality']!='final':raise Invalid('Generate a high-quality sample before final approval')
                    if c.get('card_input_sha256') and c['card_input_sha256']!=digest({'scene':card['scene'],'comments':card['comments']}):raise Invalid('Render the edited sample before locking it')
            card['locked']=not card['locked'];self.changed(state)
        elif action=='delete_mockup_card':
            card=self.card(board,payload.get('card_id'));board['cards'].remove(card);board['deleted'].append({**copy.deepcopy(card),'deleted_at':now(),'stage':board['stage']});self.changed(state)
            if board['stage']=='final':state['workflow']['mockups']=[c['candidate'] for c in board['cards'] if c.get('candidate')]
        elif action=='add_mockup_card':
            if board['stage']!='concept':raise Invalid('Return to concepts before adding a new composition')
            if len(board['cards'])>=10:raise Invalid('At most ten mockups')
            board['cards'].append({'id':uuid.uuid4().hex,'scene':None,'comments':'','locked':False,'candidate':None});self.changed(state)
        elif action=='enter_mockup_final':
            if board['stage']!='concept' or not board['cards'] or any(not c['locked'] for c in board['cards']):raise Invalid('Lock every concept before final refinement')
            board['concept_cards']=copy.deepcopy(board['cards']);board['stage']='final'
            for card in board['cards']:card.update(locked=False,needs_render=True)
            self.changed(state)
        elif action=='return_mockup_concepts':
            if board['stage']!='final':raise Invalid('Already reviewing concepts')
            board['previous_finals']=copy.deepcopy(board['cards']);board['cards']=board.pop('concept_cards');board['stage']='concept';self.changed(state)
        elif action in ('plan_mockup_board','render_mockup_board'):
            if not self.lifestyle.enabled():raise Invalid('Configure real scene providers first')
            if action=='plan_mockup_board' and not board['cards']:
                from .lifestyle import count
                for _ in range(count(payload.get('count',3))):board['cards'].append({'id':uuid.uuid4().hex,'scene':None,'comments':'','locked':False,'candidate':None})
            unlocked=[c for c in board['cards'] if not c['locked']]
            if not unlocked:raise Invalid('Unlock or add a mockup; approved samples are never regenerated')
            if action=='plan_mockup_board':
                if board['stage']!='concept':raise Invalid('Final refinement preserves approved compositions; return to concepts to replan')
                context={'brief':{k:state['brief'][k] for k in ('concept','audience','purpose')},'requirements':state['workflow']['plan']['constraints'],'inventory':manifest['units'],
                    'comments':design['comments'],'cards_to_plan':[{'scene':c['scene'],'comments':c['comments']} for c in unlocked],
                    'locked_scenes':[c['scene'] for c in board['cards'] if c['locked']],'prior_assessments':[{'scene':c['scene'],'comments':c['comments'],'locked':c['locked']} for c in board['cards']],
                    'deleted_scenes':[c['scene'] for c in board['deleted'][-10:]],'approved_related_scene_examples':self.lifestyle.remembered(state)}
                prior=[c for c in sorted(board['cards'],key=lambda c:not c['locked']) if c.get('candidate')][:3]
                context['feedback_image_order']=[{'id':c['id'],'locked':c['locked'],'scene':c['scene'],'comments':c['comments']} for c in prior]
                self.workflow.queue(directory,state,'mockup_board_plan',{'manifest_id':manifest['id'],'card_ids':[c['id'] for c in unlocked],'count':len(unlocked),'context':context,'feedback_images':[c['candidate'] for c in prior]})
            else:
                if any(not c['scene'] for c in unlocked):raise Invalid('Plan the new cards before generating samples')
                final=board['stage']=='final'
                if final and payload.get('consent_expensive') is not True:raise Invalid('Explicit expensive-loop consent required for every final round')
                if final and any(not c.get('candidate') for c in unlocked):raise Invalid('Approved concept reference required for final refinement')
                if final and self.studio.model_roles:self.studio.model_roles.select_final(payload.get('model_id'))
                self.workflow.queue(directory,state,'mockup_board_final' if final else 'mockup_board_concepts',{'manifest_id':manifest['id'],'cards':copy.deepcopy(unlocked),'comments':design['comments'],'stage':board['stage'],'model_id':payload.get('model_id')})
        else:raise Invalid('Unknown mockup board action')
        board['events'].append({'action':action,'card_id':payload.get('card_id'),'at':now()})
        state['workflow']['stage']='mockups'
        if not state['workflow'].get('pending'):state['phase']='mockup_review'
    def run(self,directory,folder,request):
        state=read(directory/'state.json');w=state['workflow'];manifest=self.workflow.require_product(directory,w);value=request['value']
        if manifest['id']!=value['manifest_id']:raise Invalid('Product changed during generation')
        pages=self.lifestyle.pages(directory,w,manifest)
        if value.get('refinement_version')==2:
            from .direct_edit import run
            return run(self,directory,folder,request,pages,manifest)
        if value.get('refinement_version')==1:
            from .refinement import run
            return run(self,directory,folder,request,pages,manifest)
        if request['kind']=='mockup_board_update':
            # One human action owns planning + sketching. Cache its plan so an
            # interrupted image step never repeats completed planning/inference.
            planned=folder/'compiled-plan.json'
            if planned.exists():plan=read(planned)
            else:
                if self.studio.model_roles:self.studio.model_roles.require_cheap()
                images=[p['body'] for p in list(pages.values())[:3]]
                for candidate in value.get('feedback_images',[]):
                    body=(directory/candidate['file']).read_bytes()
                    if hashlib.sha256(body).hexdigest()!=candidate['sha256']:raise Invalid('Feedback image changed')
                    images.append(body)
                plan=self.studio.mockup_planner.mockup_plan(value['context'],len(value['cards']),request['id']+'-plan',state['id'],images)
                from .lifestyle import checked_plan
                checked_plan(plan,len(value['cards']),set(pages));write(planned,plan)
            value=copy.deepcopy(value)
            for card,scene in zip(value['cards'],plan['scenes']):
                requested=copy.deepcopy(card['scene'] or scene);overrides=self.scene_overrides(card)
                card['requested_scene']=requested;card['scene_overrides']=overrides
                scene=copy.deepcopy(scene);scene.update(overrides)
                if 'description' in overrides and 'image_prompt' not in overrides:
                    # Do not let a stale hidden English prompt cancel a human
                    # description edit. Image providers accept the exact text.
                    scene['image_prompt']=overrides['description']
                card['scene']=scene
        if request['kind']=='mockup_board_plan':
            path=folder/'response.json'
            if path.exists():result=read(path)
            else:
                images=[p['body'] for p in list(pages.values())[:3]]
                for candidate in value.get('feedback_images',[]):
                    body=(directory/candidate['file']).read_bytes()
                    if hashlib.sha256(body).hexdigest()!=candidate['sha256']:raise Invalid('Saved feedback image changed')
                    images.append(body)
                result=self.studio.mockup_planner.mockup_plan(value['context'],value['count'],request['id'],state['id'],images);write(path,result)
            from .lifestyle import checked_plan
            return {'plan':checked_plan(result,value['count'],set(pages)),'card_ids':value['card_ids']}
        from .lifestyle import composite,fit_paper,checked_surface
        final=request['kind']=='mockup_board_final';provider=(self.studio.model_roles.select_final(value.get('model_id')) if self.studio.model_roles else self.studio.mockup_finals) if final else self.studio.mockup_drafts;target=directory/'lifestyle'/request['id'];records=[]
        for i,card in enumerate(value['cards']):
            scene=card['scene'];key=request['id']+'-'+card['id'];path=target/(card['id']+'.json');comments=value['comments']+'\n'+card['comments']
            if card.get('scene_overrides'):comments=canonical({'shared_gallery_defaults':value['comments'],'latest_card_comments':card['comments'],'explicit_scene_edits':card['scene_overrides'],'priority':'Apply per-card comments and explicit scene edits before shared defaults or older prompt text.'}).decode()
            with guard(directory):
                current=read(directory/'state.json');current['workflow']['mockup_progress']={'completed':i,'total':len(value['cards']),'title':scene['title']};self.studio.save(directory,current)
            if path.exists():record=read(path)
            else:
                background=target/(card['id']+'-background.png');surface=target/(card['id']+'-surface.json')
                if not background.exists():
                    asset=provider.mockup_scene(scene,comments,key,state['id'],final,card.get('candidate'))
                    if asset.media_type!='image/png':raise Invalid('PNG mockup required')
                    production.raster(asset.content);write_bytes(background,asset.content)
                body=background.read_bytes()
                if not surface.exists():
                    multi=getattr(self.studio.mockup_planner,'mockup_surfaces',None)
                    found=multi(body,scene,list(pages),key+'-surface',state['id']) if multi else {'surfaces':[{'page_id':scene['page_id'],**self.studio.mockup_planner.mockup_surface(body,key+'-surface',state['id'])}]}
                    write(surface,found)
                found=read(surface);image=production.raster(body);placements=[];issue=None
                try:
                    surfaces=found.get('surfaces')
                    if not isinstance(surfaces,list) or not 1<=len(surfaces)<=4:raise Invalid('One to four visible product surfaces required')
                    if scene.get('scene_type') in ('spread','storyboard') and len(surfaces)<2:raise Invalid('This composition needs multiple visible product surfaces')
                    for item in surfaces:
                        if item.get('page_id') not in pages:raise Invalid('Surface refers to an unknown product page')
                        quad=fit_paper(production.raster(body),checked_surface(item));page=pages[item['page_id']]
                        # Separate surfaces cannot share the same pixels or hide one another.
                        from .mockup_geometry import overlaps
                        if any(overlaps(quad,p['quad']) for p in placements):raise Invalid('Product surfaces overlap; regenerate a clear composition')
                        placements.append({'page_id':item['page_id'],'sha256':page['record']['sha256'],'quad':quad})
                    for item in placements:image=composite(image,production.raster(pages[item['page_id']]['body']),item['quad'])
                except Invalid as error:issue=str(error);image=production.raster(body);placements=[]
                main_id=placements[0]['page_id'] if placements else scene['page_id']
                file=target/(card['id']+'-mockup.png');write_bytes(file,production.png(image));first=pages[main_id]
                record={'id':key,'card_id':card['id'],'scene_index':i,'scene_title':scene['title'],'scene_description':scene['description'],'file':str(file.relative_to(directory)),
                    'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'background_file':str(background.relative_to(directory)),'background_sha256':hashlib.sha256(body).hexdigest(),
                    'product_id':manifest['id'],'source_page_id':main_id,'source_page_sha256':first['record']['sha256'],'placements':placements,'quad':placements[0]['quad'] if placements else None,
                    'geometry_version':3,'placement_status':'needs_revision' if issue else 'ready','placement_reason':issue,'source_composited':not issue,
                    'renderer_version':'lifestyle-board-v2','origin':'generative_lifestyle','quality':'final' if final else 'concept','review_required':True,
                    'model_id':value.get('model_id') if final else getattr(provider,'image_model','synthetic'),
                    'provider':getattr(provider,'name','configured'),
                    'comments_sha256':digest(value['comments']),'card_input_sha256':digest({'scene':card.get('requested_scene',scene),'comments':card['comments']}),'scene':scene,
                    **({'requested_scene':card['requested_scene'],'scene_overrides':card['scene_overrides']} if 'requested_scene' in card else {})}
                write(path,record)
            for name,sha in (('file','sha256'),('background_file','background_sha256')):
                if hashlib.sha256((directory/record[name]).read_bytes()).hexdigest()!=record[sha]:raise Invalid('Saved mockup asset changed')
            records.append(record)
        return {'id':request['id'],'product_id':manifest['id'],'candidates':records,'created_at':now(),'comments':value['comments'],'stage':value['stage']}
    def apply(self,state,kind,result):
        w=state['workflow'];design=self.lifestyle.design(state);board=self.state(state)
        if kind=='mockup_board_plan':
            for identifier,scene in zip(result['card_ids'],result['plan']['scenes']):
                card=self.card(board,identifier)
                if card['locked']:raise Conflict('Cannot change a locked concept')
                if card['scene']!=scene:card['needs_render']=True
                card['scene']=scene
            board['explanation']=result['plan']['product_understanding'];design['status']='plan_review'
        else:
            # A durable round grows as independently completed cards arrive.
            previous=next((r for r in design['rounds'] if r['id']==result['id']),None)
            if previous is None:design['rounds'].append(copy.deepcopy(result))
            else:previous.update(copy.deepcopy(result))
            for candidate in result['candidates']:
                card=self.card(board,candidate['card_id'])
                if result.get('direct_edit') and card['locked'] and (card.get('candidate') or {}).get('id')==candidate['id'] and card['candidate']['sha256']==candidate['sha256']:continue
                if result.get('targeted_refinement'):
                    attempts=card.setdefault('refinement_attempts',[])
                    if any(c['id']==candidate['id'] for c in attempts):continue
                    attempts.append(copy.deepcopy(candidate))
                    if not candidate['refinement']['passed']:
                        card['refinement_failure']={'candidate_id':candidate['id'],'summary':candidate['refinement']['review']['summary'],'placement_reason':candidate.get('placement_reason')};card['needs_render']=True
                        continue
                card.pop('refinement_failure',None)
                card.pop('edit_box',None)  # A human-selected region applies to this correction only.
                card.update(candidate=candidate,scene=copy.deepcopy(candidate.get('requested_scene',candidate['scene'])),locked=False,needs_render=False)
            for issue in result.get('failures',[]):
                card=self.card(board,issue['card_id']);card['refinement_failure']=copy.deepcopy(issue);card['needs_render']=True
            design['status']='final_review' if result['stage']=='final' else 'concept_review'
            if result['stage']=='final':w['mockups']=[c['candidate'] for c in board['cards'] if c.get('candidate')];design['final_comments_sha256']=digest(result['comments'])
            w['mockup_progress']={'completed':len(result['candidates'])+len(result.get('failures',[])),'total':result.get('total',len(result['candidates'])),'title':None}
        self.changed(state);w['stage']='mockups'
        if not result.get('partial'):state['phase']='mockup_review'
    def require_final(self,state):
        board=self.state(state);cards=board['cards']
        from .direct_edit import human_reviewed
        if board['stage']!='final' or not cards or any(not c['locked'] or c.get('needs_render') or not c.get('candidate') or c['candidate']['quality']!='final' or c['candidate'].get('card_input_sha256')!=digest({'scene':c['scene'],'comments':c['comments']}) for c in cards):raise Invalid('Lock every current high-quality final; apply new comments before approval')
        if any(c['candidate'].get('renderer_version')=='direct-edit-v1' and (not human_reviewed(c['candidate']) or c['candidate'].get('final_comments_sha256')!=digest(board.get('final_comments',''))) for c in cards):raise Invalid('Confirm human review of every current full-image result')
        expected=[c['candidate'] for c in cards]
        if state['workflow']['mockups']!=expected:raise Invalid('Final mockup set changed; review and lock the current set')
