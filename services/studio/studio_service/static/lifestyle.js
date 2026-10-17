'use strict';
let boardProject=null,boardStage=null,boardKey='',boardFetch=0,chosenFinalModel=null,galleryKey='',galleryTicket=0;
window.mockupFeedback=()=>{const board=project.workflow.mockup_design?.board;return {count:Number($('mockup-count').value),comments:board.stage==='final'?project.workflow.mockup_design.comments:$('mockup-comments').value,...(board.stage==='final'?{final_comments:$('mockup-comments').value}:{}),cards:[...$('mockup-concepts').querySelectorAll('[data-card]')].map(box=>{
 const card=board.cards.find(c=>c.id===box.dataset.card);const scene=card.scene?{...card.scene,description:box.querySelector('[data-description]')?.value??card.scene.description,image_prompt:box.querySelector('[data-prompt]')?.value??card.scene.image_prompt}:null;
 return {id:card.id,scene,comments:box.querySelector('[data-comments]').value,edit_box:JSON.parse(box.dataset.editBox||'null')};})};};
async function boardAction(name,extra={}){const result=action(name,{...window.mockupFeedback(),...extra});window.renderLifestyle();await result;}
async function drawBoard(board,key){
 const ticket=++boardFetch,id=project.id,response=await request('/api/projects/'+id+'/files');
 if(project?.id!==id||ticket!==boardFetch||boardKey!==key)return;
 $('mockup-concepts').replaceChildren();
 for(const card of board.cards){const box=node('article',undefined,'mockup-scene-card');box.dataset.card=card.id;box.dataset.editBox=JSON.stringify(card.edit_box||null);
  const header=node('div',undefined,'mockup-card-header'),remove=node('button','×','mockup-remove');remove.type='button';remove.title='הסרת המוק-אפ';remove.setAttribute('aria-label','הסרת '+(card.scene?.title||'מוק-אפ'));remove.dataset.remove='true';remove.onclick=()=>boardAction('delete_mockup_card',{card_id:card.id});header.append(node('strong',card.scene?.title||'מוק-אפ חדש'),remove);box.append(header);
  const candidate=card.candidate,file=candidate&&(response.files.find(f=>f.candidate_id===candidate.id&&f.sha256===candidate.sha256)||response.files.find(f=>f.role==='mockup'&&f.sha256===candidate.sha256));
  if(file){const image=node('img');image.src='/api/projects/'+id+'/files/'+file.id;image.alt=card.scene?.title||'מוק-אפ';image.onclick=()=>{if(!image.dataset.selecting)preview(image.src);};const host=node('div',undefined,'edit-region-host');host.append(image);box.append(host);if(board.stage==='final'&&!directModel()&&card.refinement_failure?.code==='invalid_correction_plan')regionSelector(box,host,image,card);}else box.append(node('div','הדוגמה תופיע כאן לאחר יצירה','mockup-placeholder'));
  if(card.refinement_failure)box.append(node('p',(card.refinement_failure.code==='invalid_correction_plan'?'תכנון אזור התיקון נכשל; לא נוצרה תמונה חדשה לדוגמה הזו. סמנו אזור בתמונה או שנו את ההערה. ':'התיקון לא עבר בדיקה; הדוגמה הקודמת נשמרה. ')+card.refinement_failure.summary+(card.refinement_failure.placement_reason?' · '+card.refinement_failure.placement_reason:''),'error'));
  if(card.refinement_failure){const rejected=response.files.find(f=>f.candidate_id===card.refinement_failure.candidate_id);if(rejected){const details=node('details'),summary=node('summary','צפייה בתיקון שלא עבר בדיקה'),image=node('img');image.src='/api/projects/'+id+'/files/'+rejected.id;image.alt='ניסיון תיקון שנשמר בהיסטוריה ולא החליף את הדוגמה';image.onclick=()=>preview(image.src);details.append(summary,image);box.append(details);}}
  if(candidate?.renderer_version==='direct-edit-v1')box.append(node('p','תשובת המודל המקורית · ממתינה לאישור שלכם; ללא חיתוך או הרכבת תמונה.','hint'));
  if(candidate?.refinement){const details=node('details'),summary=node('summary','מה השתנה ומה נבדק'),text=node('p',candidate.refinement.plan.instruction+' · '+candidate.refinement.review.summary);details.append(summary,text);box.append(details);}
  if(candidate?.placement_status==='needs_revision')box.append(node('p','הקומפוזיציה זמינה לאישור. התאמת עמודי המוצר עדיין דורשת בדיקה לפני אישור סופי: '+candidate.placement_reason,'hint'));
  if(card.scene&&board.stage!=='final'){const [label,input]=field('תיאור הסצנה הזו',card.scene.description,'textarea');input.dataset.description='true';input.maxLength=1800;input.rows=3;
   const details=node('details'),summary=node('summary','הנחיות התמונה לדוגמה הזו'),prompt=node('textarea');prompt.value=card.scene.image_prompt;prompt.dataset.prompt='true';prompt.maxLength=3500;prompt.rows=5;prompt.dir='auto';details.append(summary,prompt);box.append(label,details);}
  if(board.stage==='final'&&(candidate?.direct_edit?.reference_id||candidate?.refinement?.reference_id)){const previous=node('button','שימוש בתמונה הקודמת לתיקון · ללא חיוב','secondary');previous.dataset.previous='true';previous.onclick=()=>boardAction('previous_mockup_image',{card_id:card.id});box.append(previous);}
  const approve=node('button',card.locked?'✓ מאושר · נעול':'אישור ונעילה',card.locked?'mockup-lock selected':'mockup-lock');approve.dataset.lock='true';approve.setAttribute('aria-pressed',String(card.locked));approve.onclick=()=>{const current=project.workflow.mockup_design.board,liveCard=current.cards.find(c=>c.id===card.id);const concept=current.stage==='concept'&&!liveCard.locked&&liveCard.candidate?.placement_status!=='ready';if(concept&&!confirm('לאשר ולנעול את הקומפוזיציה הקיימת בלבד? התאמת עמודי המוצר עדיין לא אושרה. הדוגמה תישמר ללא יצירה או חיוב נוסף.'))return;const human=current.stage==='final'&&!liveCard.locked&&liveCard.candidate?.renderer_version==='direct-edit-v1';if(human&&!confirm('לאשר שהדוגמה נראית תקינה, שהתיקון בוצע ותוכן המוצר תואם למוצר האמיתי? זהו אישור אנושי, ללא יצירה או חיוב.'))return;boardAction('toggle_mockup_lock',{card_id:card.id,concept_review_confirmed:concept,human_review_confirmed:human});};box.append(approve);
  const [label,comments]=field(board.stage==='final'?'תיקונים קטנים לדוגמה הזו':'הערות לדוגמה הזו',card.comments,'textarea');comments.dataset.comments='true';comments.maxLength=1800;comments.rows=3;comments.placeholder=board.stage==='final'?'למשל: לתקן את האצבעות ולחדד את מרקם הנייר':'מה לשנות בסצנה הזו?';box.append(label);const status=node('p',card.needs_render?(board.stage==='concept'?'ההערות נשמרות להמשך. אפשר לנעול את הקומפוזיציה הקיימת.':'ההנחיות השתנו · צרו דוגמה חדשה לפני נעילה.'):'','hint');box.append(status);for(const input of box.querySelectorAll('textarea'))input.addEventListener('input',()=>{status.textContent=board.stage==='concept'&&input.dataset.comments!==undefined?'הערה להמשך · אפשר לנעול ללא יצירה נוספת.':'עריכה ממתינה · צרו דוגמה חדשה כדי להחיל אותה.';updateBoardControls(project.workflow.mockup_design.board);if(board.stage==='final'||input.dataset.comments===undefined)disabledHint(approve,'יש להחיל את שינוי הסצנה לפני אישור הדוגמה');});$('mockup-concepts').append(box);
 }
 if(board.stage==='concept'){const add=node('button','＋\nהוספת מוק-אפ','mockup-add-card');add.id='add-mockup-card';add.onclick=()=>boardAction('add_mockup_card');$('mockup-concepts').append(add);}
 updateBoardControls(board);
}
function disabledHint(button,reason=''){
 button.disabled=!!reason;button.title=reason;button.dataset.disabledReason=reason;
 let host=button.parentElement;if(!host.classList.contains('disabled-hint')){host=node('span',undefined,'disabled-hint');button.replaceWith(host);host.append(button);}
 host.dataset.tip=reason;host.tabIndex=reason?0:-1;host.setAttribute('aria-label',reason||button.textContent);
}
function modelPicker(){const options=project.mockup_models?.finals||[];if(!options.some(m=>m.id===chosenFinalModel))chosenFinalModel=options[0]?.id||null;
 const key=JSON.stringify([options,chosenFinalModel]);if($('mockup-model-buttons').dataset.key!==key){$('mockup-model-buttons').dataset.key=key;$('mockup-model-buttons').replaceChildren();
  for(const model of options){const button=node('button',model.label,'secondary');button.setAttribute('aria-pressed',String(model.id===chosenFinalModel));button.classList.toggle('selected',model.id===chosenFinalModel);button.onclick=()=>{chosenFinalModel=model.id;window.renderLifestyle();};$('mockup-model-buttons').append(button);}
  if(!options.length)$('mockup-model-buttons').append(node('p','אין מודל תמונה מקצועי זמין: נדרשים מפתח מוגדר והרשאת mockup_final_images.','hint'));
 }
 const models=project.mockup_models||{};$('mockup-role-summary').textContent='תכנון והבנת הערות: '+(models.planning?.model||'לא מוגדר')+' · סקיצות: '+(models.sketches?.model||'לא מוגדר')+' · ליטוש מקצועי: '+(options.find(m=>m.id===chosenFinalModel)?.label||'לא זמין');
}
function updateBoardControls(board){const pending=!!project.workflow.pending&&!project.mockup_recovery?.can_replace,final=board.stage==='final';
 const blocked=busy?'הבקשה נשלחת כעת':project.spending.unknown_outcomes?'יש חיוב שתוצאתו אינה ידועה; נדרש בירור לפני יצירה נוספת':pending?'היצירה עדיין מתבצעת':project.phase==='approved'?'הסט כבר אושר סופית':'';
 for(const box of $('mockup-concepts').querySelectorAll('[data-card]')){const card=board.cards.find(c=>c.id===box.dataset.card);if(!card){for(const input of box.querySelectorAll('button,textarea'))input.disabled=true;continue;}box.classList.toggle('locked',card.locked);
  for(const input of box.querySelectorAll('textarea'))input.disabled=!!blocked||card.locked||(final&&input.dataset.comments===undefined);
  const lock=box.querySelector('[data-lock]');lock.textContent=card.locked?'✓ מאושר · נעול':'אישור ונעילה';lock.setAttribute('aria-pressed',String(card.locked));lock.classList.toggle('selected',card.locked);
  const sceneChanged=card.candidate?.scene&&JSON.stringify(card.candidate.scene)!==JSON.stringify(card.scene);
  disabledHint(lock,blocked||(card.locked?'':!card.candidate?'יש ליצור דוגמה לפני אישור':!final&&sceneChanged?'תיאור הסצנה השתנה; יש להחיל או לשחזר אותו לפני אישור התמונה הקיימת':final&&card.candidate.renderer_version!=='direct-edit-v1'&&card.candidate.placement_status!=='ready'?'נדרש תיקון למשטח המוצר לפני אישור סופי':final&&card.needs_render?'יש להחיל את ההערות וליצור דוגמה מעודכנת':final&&card.candidate.quality!=='final'?'יש להפיק דוגמה מקצועית לפני אישור':''));
  disabledHint(box.querySelector('[data-remove]'),blocked);const previous=box.querySelector('[data-previous]');if(previous)disabledHint(previous,blocked);const region=box.querySelector('[data-region]');if(region)disabledHint(region,blocked||(card.locked?'יש לפתוח את הדוגמה לפני סימון אזור':''));
 }
 const add=$('add-mockup-card');if(add)disabledHint(add,blocked||(board.cards.length>=10?'ניתן לשמור עד עשרה מוק-אפים; הסירו דוגמה כדי להוסיף אחרת':''));
 const open=board.cards.filter(c=>!c.locked),all=board.cards.length>0&&open.length===0;
 $('mockup-concept-hint').textContent=board.cards.length+' מוק-אפים · '+(board.cards.length-open.length)+' נעולים · '+open.length+' פתוחים לשינוי';$('mockup-comments').disabled=!!blocked||all;
 const changed=c=>c.needs_render||document.querySelector('[data-card="'+c.id+'"] [data-comments]')?.value!==c.comments||$('mockup-comments').value!==(board.stage==='final'?board.final_comments||'':project.workflow.mockup_design.comments);
 const targets=open.some(changed)?open.filter(changed):open;
 const invalidRegion=!directModel()&&targets.length>0&&targets.every(c=>c.refinement_failure?.code==='invalid_correction_plan'&&!JSON.parse(document.querySelector('[data-card="'+c.id+'"]')?.dataset.editBox||'null')&&document.querySelector('[data-card="'+c.id+'"] [data-comments]')?.value===c.comments&&$('mockup-comments').value===(board.stage==='final'?board.final_comments||'':project.workflow.mockup_design.comments));
 const cheapMissing=project.mockup_models?.planning?.available===false||project.mockup_models?.sketches?.available===false;
 disabledHint($('save-mockup-notes'),blocked);disabledHint($('back-mockup-concepts'),blocked);
 $('apply-mockup-comments').textContent=final?'החלת תיקונים · רזולוציית עבודה · בתשלום':'החלת הערות ויצירת סקיצות';
 disabledHint($('apply-mockup-comments'),blocked||(invalidRegion?'סמנו אזור תיקון בתמונה שנכשלה או שנו את ההערה':!open.length?'פתחו דוגמה נעולה או הוסיפו מוק-אפ חדש':final&&!chosenFinalModel?'בחרו מודל מקצועי מורשה עם מפתח זמין':!final&&cheapMissing?'מפתח או הרשאות התכנון והסקיצות אינם זמינים':''));
 show('export-mockups',final);disabledHint($('export-mockups'),blocked||(!all?'יש לאשר ולנעול את כל הדוגמאות לפני ייצוא':!chosenFinalModel?'בחרו מודל תמונה מקצועי':board.cards.every(c=>c.candidate?.render_profile==='export')?'כל הדוגמאות כבר יוצאו':''));
 show('final-mockup-scenes',!final);disabledHint($('final-mockup-scenes'),blocked||(!all?'יש לאשר ולנעול את כל הדוגמאות לפני הפקה מקצועית':!chosenFinalModel?'אין מודל תמונה מקצועי מורשה עם מפתח זמין':''));
 show('suggest-mockup-controls',!final);const number=Number($('suggest-mockup-count').value),slots=10-board.cards.length;$('suggest-mockup-count').max=Math.max(1,slots);$('suggest-mockups').textContent=number===1?'הצעה ויצירת מוק-אפ נוסף':'הצעה ויצירת '+number+' מוק-אפים נוספים';
 disabledHint($('suggest-mockups'),blocked||(cheapMissing?'מפתח או הרשאות התכנון והסקיצות אינם זמינים':slots===0?'הסט מלא: הסירו מוק-אפ לפני הוספת רעיון':!Number.isInteger(number)||number<1||number>slots?'בחרו כמות בין 1 ל-'+slots+' בהתאם למקום הפנוי':''));
 $('approve-mockups').hidden=!final;disabledHint($('approve-mockups'),blocked||(!all||board.cards.some(c=>c.needs_render||c.candidate?.quality!=='final')?'יש להפיק ולאשר את כל הדוגמאות המקצועיות לפני המשך':''));
 for(const button of $('mockup-model-buttons').querySelectorAll('button'))disabledHint(button,blocked);
}
window.renderLifestyle=()=>{const w=project?.workflow;if(!w)return;loadGeneratedImages();const live=project.lifestyle_mockups===true;
 show('mockup-workbench',live);show('lifestyle-actions',live);show('legacy-mockups',!live);if(!live){$('approve-mockups').hidden=false;return;}
 const design=w.mockup_design||{},board=design.board;if(!board)return;
 const final=board.stage==='final';$('mockups-panel').classList.toggle('final-refinement',final);$('mockup-heading').textContent=final?'ליטוש מדויק · רזולוציית עבודה':'המוק-אפים שלכם · קונספט וקומפוזיציה';show('mockup-final-warning',final);
 $('mockup-final-provider').textContent='מודל הליטוש: '+(project.mockup_final_model||'הספק המקצועי המוגדר');$('mockup-mode-hint').textContent=final?'המודל מקבל את התמונה המלאה ואת ההערה שלכם. התוצאה מוצגת ללא חיתוך או הרכבה. כל תמונה שהתקבלה מוצגת גם בהיסטוריית התוצאות; האישור הסופי שלכם. ייצוא באיכות גבוהה הוא אופציונלי ובתשלום.':'אישור נועל דוגמה ומוציא אותה מהסבב הזול הבא. לחצו שוב כדי לפתוח אותה. × מסיר מהסט.';
 if(boardProject!==project.id||boardStage!==board.stage){boardProject=project.id;boardStage=board.stage;boardKey='';chosenFinalModel=board.final_model_id||null;$('mockup-comments').value=final?board.final_comments||'':design.comments||'';$('mockup-count').value=design.count||3;}
 const key=project.id+JSON.stringify([board.stage,board.cards.map(c=>[c.id,c.scene,c.candidate?.id,c.candidate?.sha256,c.comments,c.edit_box,c.refinement_failure])]);
 if(key!==boardKey){boardKey=key;drawBoard(board,key).catch(e=>{boardKey='';notify(e.message,true);});}
 $('mockup-plan-explanation').textContent=final?'':board.explanation||'';
 const allowance=project.spending.stage_budgets?.mockups;$('mockup-budget-hint').textContent=allowance?'נותרו $'+allowance.remaining_usd.toFixed(3)+' מתוך $'+allowance.limit_usd+' למוק-אפים · חלק מתקציב הניסוי הכולל.':'כל הקריאות מחויבות לתקציב הסטודיו הקיים.';
 show('recover-saved-mockups',!!project.mockup_recovery?.can_recover_saved);disabledHint($('recover-saved-mockups'),busy?'הבקשה נשלחת כעת':'');
 show('abandon-mockup-job',false);modelPicker();updateBoardControls(board);if(project.phase==='generation_failed'&&project.mockup_recovery?.can_replace){$('generation-error').textContent='הסבב נעצר: '+(project.generation_error||'ראו את פרטי השגיאה')+'. התוצאות שכבר נוצרו נשמרו; אפשר לשחזר אותן ללא חיוב.';show('retry',false);}else show('retry',true);
 if(project.phase==='generating_mockups')$('generation').querySelector('p').textContent=(final?'ליטוש סופי בתשלום':'מכינים סצנות')+' · '+(w.mockup_progress?.completed||0)+' מתוך '+(w.mockup_progress?.total||board.cards.length);
};
$('save-mockup-notes').onclick=()=>boardAction('save_mockup_board');
$('apply-mockup-comments').onclick=()=>{const final=project.workflow.mockup_design.board.stage==='final';if(confirm(final?'סבב מקצועי בתשלום: להחיל תיקונים רק על הדוגמאות הפתוחות במודל שנבחר?':'להבין את ההערות וליצור סקיצות מעודכנות רק לדוגמאות הפתוחות או החדשות?'))boardAction('apply_mockup_comments',{model_id:chosenFinalModel,consent_expensive:final});};
$('final-mockup-scenes').onclick=()=>{if(confirm('הקונספטים אושרו. להתחיל את הסבב המקצועי הראשון בתשלום במודל שנבחר?'))boardAction('finalize_mockup_board',{model_id:chosenFinalModel,consent_expensive:true});};
$('suggest-mockups').onclick=()=>{const number=Number($('suggest-mockup-count').value);if(confirm('להציע '+number+' רעיונות חדשים וליצור עבורם סקיצות? הדוגמאות הקיימות לא ייווצרו שוב.'))boardAction('suggest_mockups',{additional_count:number});};
$('suggest-mockup-count').oninput=()=>window.renderLifestyle();
$('back-mockup-concepts').onclick=()=>boardAction('return_mockup_concepts');
$('abandon-mockup-job').onclick=()=>{if(confirm('לסגור את הסבב שנכשל ולהשאיר היסטוריה וחיובים? תוצאות כספיות לא ידועות נשארות חסומות.'))action('abandon_mockup_job');};

$('export-mockups').onclick=()=>{if(confirm('ייצוא אופציונלי בתשלום: להפיק את הסט המאושר ב־1536×1024 באיכות גבוהה? לא נדרש להמשך אם איכות העבודה מספיקה.'))boardAction('export_mockup_board',{model_id:chosenFinalModel,consent_expensive:true});};

$('recover-saved-mockups').onclick=()=>action('recover_mockup_results');

function regionSelector(box,host,image,card){
 const button=node('button',card.edit_box?'שינוי אזור התיקון':'סימון אזור התיקון בתמונה','secondary'),outline=node('div',undefined,'edit-region-outline'),hint=node('p',card.edit_box?'אזור התיקון נשמר. החלת תיקונים היא פעולה נפרדת בתשלום.':'לחצו על סימון ואז גררו מלבן סביב האזור לתיקון. הסימון והשמירה ללא חיוב.','hint');button.dataset.region='true';host.append(outline);box.append(button,hint);
 const contentRect=()=>{const r=image.getBoundingClientRect(),ratio=(image.naturalWidth||1)/(image.naturalHeight||1),width=Math.min(r.width,r.height*ratio),height=width/ratio;return {left:r.left+(r.width-width)/2,top:r.top+(r.height-height)/2,width,height};};
 const draw=area=>{outline.hidden=!area;if(area){const r=contentRect(),h=host.getBoundingClientRect();outline.style.left=(r.left-h.left+area[0]*r.width)+'px';outline.style.top=(r.top-h.top+area[1]*r.height)+'px';outline.style.width=(area[2]-area[0])*r.width+'px';outline.style.height=(area[3]-area[1])*r.height+'px';}};draw(card.edit_box);image.addEventListener('load',()=>draw(JSON.parse(box.dataset.editBox||'null')));
 let start=null;const point=e=>{const r=contentRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
 button.onclick=()=>{image.dataset.selecting='true';image.classList.add('selecting-region');hint.textContent='גררו מלבן סביב האזור לתיקון; אין חיוב על הסימון.';};
 image.onpointerdown=e=>{if(!image.dataset.selecting)return;e.preventDefault();start=point(e);image.setPointerCapture(e.pointerId);};
 image.onpointermove=e=>{if(!start)return;const p=point(e);draw([Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])]);};
 image.onpointerup=e=>{if(!start)return;const p=point(e),area=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];start=null;image.releasePointerCapture(e.pointerId);if(area[2]-area[0]<.02||area[3]-area[1]<.02){hint.textContent='האזור קטן מדי. גררו מלבן גדול יותר.';return;}box.dataset.editBox=JSON.stringify(area);draw(area);image.classList.remove('selecting-region');boardAction('save_mockup_board');};
 image.onpointercancel=()=>{start=null;};
}

$('mockup-comments').addEventListener('input',()=>{if(project?.workflow?.mockup_design?.board)updateBoardControls(project.workflow.mockup_design.board);});

function directModel(){return (project.mockup_models?.finals||[]).find(m=>m.id===chosenFinalModel)?.full_image_edit===true;}
async function loadGeneratedImages(){
 const id=project.id,key=id+':'+(project.generated_images_revision||project.revision);if(key===galleryKey)return;galleryKey=key;const ticket=++galleryTicket;
 try{const data=await request('/api/projects/'+id+'/generated-images');if(project?.id!==id||ticket!==galleryTicket)return;
  $('generated-images-list').replaceChildren();$('generated-images-count').textContent=data.images.length+' תמונות שהתקבלו מהמודל · מוצגות ללא קשר לבדיקות ולאישור';
  for(const item of data.images){const card=node('article',undefined,'generated-image'),url='/api/projects/'+id+'/generated-images/'+item.id;
   if(item.previewable){const image=node('img');image.src=url;image.loading='lazy';image.alt='תשובת מודל מקורית '+item.at;image.onclick=()=>preview(url);card.append(image);}
   card.append(node('p',item.at+' · '+item.stage+' · '+(item.size?item.size.join('×'):''),'hint'));
   if(item.accounting_status!=='completed')card.append(node('p','התמונה התקבלה; החיוב עדיין דורש בירור.','error'));
   if(item.warning)card.append(node('p',item.warning,'error'));
   const link=node('a','פתיחה / הורדת התמונה המקורית');link.href=url;link.target='_blank';link.rel='noopener';card.append(link);$('generated-images-list').append(card);
  }
 }catch(e){galleryKey='';notify('לא ניתן לטעון את התמונות המקוריות: '+e.message,true);}
}
