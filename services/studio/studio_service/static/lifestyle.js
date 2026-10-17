'use strict';
let boardProject=null,boardKey='',boardFetch=0,chosenFinalModel=null;
window.mockupFeedback=()=>{const board=project.workflow.mockup_design?.board;return {count:Number($('mockup-count').value),comments:$('mockup-comments').value,cards:[...$('mockup-concepts').querySelectorAll('[data-card]')].map(box=>{
 const card=board.cards.find(c=>c.id===box.dataset.card);const scene=card.scene?{...card.scene,description:box.querySelector('[data-description]').value,image_prompt:box.querySelector('[data-prompt]').value}:null;
 return {id:card.id,scene,comments:box.querySelector('[data-comments]').value};})};};
async function boardAction(name,extra={}){const result=action(name,{...window.mockupFeedback(),...extra});window.renderLifestyle();await result;}
async function drawBoard(board,key){
 const ticket=++boardFetch,id=project.id,response=await request('/api/projects/'+id+'/files');
 if(project?.id!==id||ticket!==boardFetch||boardKey!==key)return;
 $('mockup-concepts').replaceChildren();
 for(const card of board.cards){const box=node('article',undefined,'mockup-scene-card');box.dataset.card=card.id;
  const header=node('div',undefined,'mockup-card-header'),remove=node('button','×','mockup-remove');remove.type='button';remove.title='הסרת המוק-אפ';remove.setAttribute('aria-label','הסרת '+(card.scene?.title||'מוק-אפ'));remove.dataset.remove='true';remove.onclick=()=>boardAction('delete_mockup_card',{card_id:card.id});header.append(node('strong',card.scene?.title||'מוק-אפ חדש'),remove);box.append(header);
  const candidate=card.candidate,file=candidate&&response.files.find(f=>f.candidate_id===candidate.id||f.role==='mockup'&&f.sha256===candidate.sha256);
  if(file){const image=node('img');image.src='/api/projects/'+id+'/files/'+file.id;image.alt=card.scene?.title||'מוק-אפ';image.onclick=()=>preview(image.src);box.append(image);}else box.append(node('div','הדוגמה תופיע כאן לאחר יצירה','mockup-placeholder'));
  if(candidate?.placement_status==='needs_revision')box.append(node('p','הקומפוזיציה זמינה לאישור. התאמת עמודי המוצר עדיין דורשת בדיקה לפני אישור סופי: '+candidate.placement_reason,'hint'));
  if(card.scene){const [label,input]=field('תיאור הסצנה הזו',card.scene.description,'textarea');input.dataset.description='true';input.maxLength=1800;input.rows=3;
   const details=node('details'),summary=node('summary','הנחיות התמונה לדוגמה הזו'),prompt=node('textarea');prompt.value=card.scene.image_prompt;prompt.dataset.prompt='true';prompt.maxLength=3500;prompt.rows=5;prompt.dir='auto';details.append(summary,prompt);box.append(label,details);}
  const approve=node('button',card.locked?'✓ מאושר · נעול':'אישור ונעילה',card.locked?'mockup-lock selected':'mockup-lock');approve.dataset.lock='true';approve.setAttribute('aria-pressed',String(card.locked));approve.onclick=()=>{const current=project.workflow.mockup_design.board,liveCard=current.cards.find(c=>c.id===card.id);const concept=current.stage==='concept'&&!liveCard.locked&&liveCard.candidate?.placement_status!=='ready';if(concept&&!confirm('לאשר ולנעול את הקומפוזיציה הקיימת בלבד? התאמת עמודי המוצר עדיין לא אושרה. הדוגמה תישמר ללא יצירה או חיוב נוסף.'))return;boardAction('toggle_mockup_lock',{card_id:card.id,concept_review_confirmed:concept});};box.append(approve);
  const [label,comments]=field(board.stage==='final'?'תיקונים קטנים לדוגמה הזו':'הערות לדוגמה הזו',card.comments,'textarea');comments.dataset.comments='true';comments.maxLength=1800;comments.rows=3;comments.placeholder=board.stage==='final'?'למשל: לתקן את האצבעות ולחדד את מרקם הנייר':'מה לשנות בסצנה הזו?';box.append(label);const status=node('p',card.needs_render?(board.stage==='concept'?'ההערות נשמרות להמשך. אפשר לנעול את הקומפוזיציה הקיימת.':'ההנחיות השתנו · צרו דוגמה חדשה לפני נעילה.'):'','hint');box.append(status);for(const input of box.querySelectorAll('textarea'))input.addEventListener('input',()=>{status.textContent=board.stage==='concept'&&input.dataset.comments!==undefined?'הערה להמשך · אפשר לנעול ללא יצירה נוספת.':'עריכה ממתינה · צרו דוגמה חדשה כדי להחיל אותה.';if(board.stage==='final'||input.dataset.comments===undefined)disabledHint(approve,'יש להחיל את שינוי הסצנה לפני אישור הדוגמה');});$('mockup-concepts').append(box);
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
  disabledHint(lock,blocked||(card.locked?'':!card.candidate?'יש ליצור דוגמה לפני אישור':!final&&sceneChanged?'תיאור הסצנה השתנה; יש להחיל או לשחזר אותו לפני אישור התמונה הקיימת':final&&card.candidate.placement_status!=='ready'?'נדרש תיקון למשטח המוצר לפני אישור סופי':final&&card.needs_render?'יש להחיל את ההערות וליצור דוגמה מעודכנת':final&&card.candidate.quality!=='final'?'יש להפיק דוגמה מקצועית לפני אישור':''));
  disabledHint(box.querySelector('[data-remove]'),blocked);
 }
 const add=$('add-mockup-card');if(add)disabledHint(add,blocked||(board.cards.length>=10?'ניתן לשמור עד עשרה מוק-אפים; הסירו דוגמה כדי להוסיף אחרת':''));
 const open=board.cards.filter(c=>!c.locked),all=board.cards.length>0&&open.length===0;
 $('mockup-concept-hint').textContent=board.cards.length+' מוק-אפים · '+(board.cards.length-open.length)+' נעולים · '+open.length+' פתוחים לשינוי';$('mockup-comments').disabled=!!blocked||all;
 const cheapMissing=project.mockup_models?.planning?.available===false||project.mockup_models?.sketches?.available===false;
 disabledHint($('save-mockup-notes'),blocked);disabledHint($('back-mockup-concepts'),blocked);
 $('apply-mockup-comments').textContent=final?'החלת תיקונים במודל שנבחר · סבב יקר':'החלת הערות ויצירת סקיצות';
 disabledHint($('apply-mockup-comments'),blocked||(!open.length?'פתחו דוגמה נעולה או הוסיפו מוק-אפ חדש':final&&!chosenFinalModel?'בחרו מודל מקצועי מורשה עם מפתח זמין':!final&&cheapMissing?'מפתח או הרשאות התכנון והסקיצות אינם זמינים':''));
 show('final-mockup-scenes',!final);disabledHint($('final-mockup-scenes'),blocked||(!all?'יש לאשר ולנעול את כל הדוגמאות לפני הפקה מקצועית':!chosenFinalModel?'אין מודל תמונה מקצועי מורשה עם מפתח זמין':''));
 show('suggest-mockup-controls',!final);const number=Number($('suggest-mockup-count').value),slots=10-board.cards.length;$('suggest-mockup-count').max=Math.max(1,slots);$('suggest-mockups').textContent=number===1?'הצעה ויצירת מוק-אפ נוסף':'הצעה ויצירת '+number+' מוק-אפים נוספים';
 disabledHint($('suggest-mockups'),blocked||(cheapMissing?'מפתח או הרשאות התכנון והסקיצות אינם זמינים':slots===0?'הסט מלא: הסירו מוק-אפ לפני הוספת רעיון':!Number.isInteger(number)||number<1||number>slots?'בחרו כמות בין 1 ל-'+slots+' בהתאם למקום הפנוי':''));
 $('approve-mockups').hidden=!final;disabledHint($('approve-mockups'),blocked||(!all||board.cards.some(c=>c.needs_render||c.candidate?.quality!=='final')?'יש להפיק ולאשר את כל הדוגמאות המקצועיות לפני המשך':''));
 for(const button of $('mockup-model-buttons').querySelectorAll('button'))disabledHint(button,blocked);
}
window.renderLifestyle=()=>{const w=project?.workflow;if(!w)return;const live=project.lifestyle_mockups===true;
 show('mockup-workbench',live);show('lifestyle-actions',live);show('legacy-mockups',!live);if(!live){$('approve-mockups').hidden=false;return;}
 const design=w.mockup_design||{},board=design.board;if(!board)return;
 const final=board.stage==='final';$('mockups-panel').classList.toggle('final-refinement',final);$('mockup-heading').textContent=final?'ליטוש סופי · איכות ופרטים':'המוק-אפים שלכם · קונספט וקומפוזיציה';show('mockup-final-warning',final);
 $('mockup-final-provider').textContent='מודל הליטוש: '+(project.mockup_final_model||'הספק המקצועי המוגדר');$('mockup-mode-hint').textContent=final?'הקומפוזיציה נעולה. התמקדו בתיקונים קטנים. כל יצירה נוספת בתשלום; אפשר לחזור לקונספטים.':'אישור נועל דוגמה ומוציא אותה מהסבב הזול הבא. לחצו שוב כדי לפתוח אותה. × מסיר מהסט.';
 if(boardProject!==project.id){boardProject=project.id;boardKey='';chosenFinalModel=board.final_model_id||null;$('mockup-comments').value=design.comments||'';$('mockup-count').value=design.count||3;}
 const key=project.id+JSON.stringify([board.stage,board.cards.map(c=>[c.id,c.scene,c.candidate?.id,c.comments])]);
 if(key!==boardKey){boardKey=key;drawBoard(board,key).catch(e=>{boardKey='';notify(e.message,true);});}
 $('mockup-plan-explanation').textContent=board.explanation||'';
 const allowance=project.spending.stage_budgets?.mockups;$('mockup-budget-hint').textContent=allowance?'נותרו $'+allowance.remaining_usd.toFixed(3)+' מתוך $'+allowance.limit_usd+' למוק-אפים · חלק מתקציב הניסוי הכולל.':'כל הקריאות מחויבות לתקציב הסטודיו הקיים.';
 show('abandon-mockup-job',false);modelPicker();updateBoardControls(board);if(project.phase==='generation_failed'&&project.mockup_recovery?.can_replace){$('generation-error').textContent='הסבב הקודם נעצר והנתונים נשמרו. לחצו על החלת הערות או הצעת רעיונות כדי להתחיל סבב מתוקן.';show('retry',false);}else show('retry',true);
 if(project.phase==='generating_mockups')$('generation').querySelector('p').textContent=(final?'ליטוש סופי בתשלום':'מכינים סצנות')+' · '+(w.mockup_progress?.completed||0)+' מתוך '+(w.mockup_progress?.total||board.cards.length);
};
$('save-mockup-notes').onclick=()=>boardAction('save_mockup_board');
$('apply-mockup-comments').onclick=()=>{const final=project.workflow.mockup_design.board.stage==='final';if(confirm(final?'סבב מקצועי בתשלום: להחיל תיקונים רק על הדוגמאות הפתוחות במודל שנבחר?':'להבין את ההערות וליצור סקיצות מעודכנות רק לדוגמאות הפתוחות או החדשות?'))boardAction('apply_mockup_comments',{model_id:chosenFinalModel,consent_expensive:final});};
$('final-mockup-scenes').onclick=()=>{if(confirm('הקונספטים אושרו. להתחיל את הסבב המקצועי הראשון בתשלום במודל שנבחר?'))boardAction('finalize_mockup_board',{model_id:chosenFinalModel,consent_expensive:true});};
$('suggest-mockups').onclick=()=>{const number=Number($('suggest-mockup-count').value);if(confirm('להציע '+number+' רעיונות חדשים וליצור עבורם סקיצות? הדוגמאות הקיימות לא ייווצרו שוב.'))boardAction('suggest_mockups',{additional_count:number});};
$('suggest-mockup-count').oninput=()=>window.renderLifestyle();
$('back-mockup-concepts').onclick=()=>boardAction('return_mockup_concepts');
$('abandon-mockup-job').onclick=()=>{if(confirm('לסגור את הסבב שנכשל ולהשאיר היסטוריה וחיובים? תוצאות כספיות לא ידועות נשארות חסומות.'))action('abandon_mockup_job');};
