'use strict';
let boardProject=null,boardKey='',boardFetch=0;
window.mockupFeedback=()=>{const board=project.workflow.mockup_design?.board;return {count:Number($('mockup-count').value),comments:$('mockup-comments').value,cards:[...$('mockup-concepts').querySelectorAll('[data-card]')].map(box=>{
 const card=board.cards.find(c=>c.id===box.dataset.card);const scene=card.scene?{...card.scene,description:box.querySelector('[data-description]').value,image_prompt:box.querySelector('[data-prompt]').value}:null;
 return {id:card.id,scene,comments:box.querySelector('[data-comments]').value};})};};
async function boardAction(name,extra={}){const result=action(name,{...window.mockupFeedback(),...extra});window.renderLifestyle();await result;}
async function drawBoard(board,key){
 const ticket=++boardFetch,id=project.id,response=await request('/api/projects/'+id+'/files');
 if(project?.id!==id||ticket!==boardFetch||boardKey!==key)return;
 $('mockup-concepts').replaceChildren();
 for(const card of board.cards){const box=node('article',undefined,'mockup-scene-card');box.dataset.card=card.id;
  const header=node('div',undefined,'mockup-card-header'),remove=node('button','×','mockup-remove');remove.type='button';remove.title='הסרת המוקאף';remove.setAttribute('aria-label','הסרת '+(card.scene?.title||'מוקאף'));remove.dataset.remove='true';remove.onclick=()=>boardAction('delete_mockup_card',{card_id:card.id});header.append(node('strong',card.scene?.title||'מוקאף חדש'),remove);box.append(header);
  const candidate=card.candidate,file=candidate&&response.files.find(f=>f.candidate_id===candidate.id||f.role==='mockup'&&f.sha256===candidate.sha256);
  if(file){const image=node('img');image.src='/api/projects/'+id+'/files/'+file.id;image.alt=card.scene?.title||'מוקאף';image.onclick=()=>preview(image.src);box.append(image);}else box.append(node('div','הדוגמה תופיע כאן לאחר יצירה','mockup-placeholder'));
  if(candidate?.placement_status==='needs_revision')box.append(node('p','נדרש תיקון למשטח המוצר: '+candidate.placement_reason,'error'));
  if(card.scene){const [label,input]=field('תיאור הסצנה הזו',card.scene.description,'textarea');input.dataset.description='true';input.maxLength=1800;input.rows=3;
   const details=node('details'),summary=node('summary','הנחיות התמונה לדוגמה הזו'),prompt=node('textarea');prompt.value=card.scene.image_prompt;prompt.dataset.prompt='true';prompt.maxLength=3500;prompt.rows=5;prompt.dir='auto';details.append(summary,prompt);box.append(label,details);}
  const approve=node('button',card.locked?'✓ מאושר · נעול':'אישור ונעילה',card.locked?'mockup-lock selected':'mockup-lock');approve.dataset.lock='true';approve.setAttribute('aria-pressed',String(card.locked));approve.onclick=()=>boardAction('toggle_mockup_lock',{card_id:card.id});box.append(approve);
  const [label,comments]=field(board.stage==='final'?'תיקונים קטנים לדוגמה הזו':'הערות לדוגמה הזו',card.comments,'textarea');comments.dataset.comments='true';comments.maxLength=1800;comments.rows=3;comments.placeholder=board.stage==='final'?'למשל: לתקן את האצבעות ולחדד את מרקם הנייר':'מה לשנות בסצנה הזו?';box.append(label);const status=node('p',card.needs_render?'ההנחיות השתנו · צרו דוגמה חדשה לפני נעילה.':'','hint');box.append(status);for(const input of box.querySelectorAll('textarea'))input.addEventListener('input',()=>{status.textContent='עריכה ממתינה · צרו דוגמה חדשה כדי להחיל אותה.';approve.disabled=true;});$('mockup-concepts').append(box);
 }
 if(board.stage==='concept'){const add=node('button','＋\nהוספת מוקאף','mockup-add-card');add.id='add-mockup-card';add.onclick=()=>boardAction('add_mockup_card');$('mockup-concepts').append(add);}
 updateBoardControls(board);
}
function updateBoardControls(board){const pending=!!project.workflow.pending,disabled=busy||pending||project.phase==='approved',final=board.stage==='final';
 for(const box of $('mockup-concepts').querySelectorAll('[data-card]')){const card=board.cards.find(c=>c.id===box.dataset.card);if(!card){for(const input of box.querySelectorAll('button,textarea'))input.disabled=true;continue;}box.classList.toggle('locked',card.locked);
  for(const input of box.querySelectorAll('textarea'))input.disabled=disabled||card.locked||(final&&input.dataset.comments===undefined);
  const lock=box.querySelector('[data-lock]');lock.textContent=card.locked?'✓ מאושר · נעול':'אישור ונעילה';lock.setAttribute('aria-pressed',String(card.locked));lock.classList.toggle('selected',card.locked);lock.disabled=disabled||!card.candidate||card.candidate.placement_status!=='ready'||(!card.locked&&(card.needs_render||final&&card.candidate.quality!=='final'));
  box.querySelector('[data-remove]').disabled=disabled;
 }
 const add=$('add-mockup-card');if(add)add.disabled=disabled||board.cards.length>=10;
 const open=board.cards.filter(c=>!c.locked),all=board.cards.length>0&&open.length===0;
 $('mockup-concept-hint').textContent=board.cards.length+' מוקאפים · '+(board.cards.length-open.length)+' נעולים · '+open.length+' פתוחים לשינוי';
 $('mockup-comments').disabled=disabled||all;
 for(const id of ['save-mockup-notes','plan-mockup-scenes','make-mockup-concepts','final-mockup-scenes','back-mockup-concepts'])$(id).disabled=disabled;
 show('plan-mockup-scenes',!final);show('make-mockup-concepts',!final);$('plan-mockup-scenes').disabled=disabled||all;$('make-mockup-concepts').disabled=disabled||!open.length||open.some(c=>!c.scene);
 show('final-mockup-scenes',final||all);$('final-mockup-scenes').textContent=final?'הפקת הדוגמאות הפתוחות · ליטוש סופי יקר':'כל הקונספטים אושרו · מעבר לליטוש סופי';$('final-mockup-scenes').disabled=disabled||(final?!open.length:!all);
 $('approve-mockups').hidden=!final;$('approve-mockups').disabled=disabled||!all||board.cards.some(c=>c.needs_render||c.candidate?.quality!=='final');
}
window.renderLifestyle=()=>{const w=project?.workflow;if(!w)return;const live=project.lifestyle_mockups===true;
 show('mockup-workbench',live);show('lifestyle-actions',live);show('legacy-mockups',!live);if(!live){$('approve-mockups').hidden=false;return;}
 const design=w.mockup_design||{},board=design.board;if(!board)return;
 const final=board.stage==='final';$('mockups-panel').classList.toggle('final-refinement',final);$('mockup-heading').textContent=final?'ליטוש סופי · איכות ופרטים':'המוקאפים שלכם · קונספט וקומפוזיציה';show('mockup-final-warning',final);show('mockup-initial-count',!board.cards.length);
 $('mockup-final-provider').textContent='מודל הליטוש: '+(project.mockup_final_model||'הספק המקצועי המוגדר');$('mockup-mode-hint').textContent=final?'הקומפוזיציה נעולה. התמקדו בתיקונים קטנים. כל יצירה נוספת בתשלום; אפשר לחזור לקונספטים.':'אישור נועל דוגמה ומוציא אותה מהסבב הזול הבא. לחצו שוב כדי לפתוח אותה. × מסיר מהסט.';
 if(boardProject!==project.id){boardProject=project.id;boardKey='';$('mockup-comments').value=design.comments||'';$('mockup-count').value=design.count||3;}
 const key=project.id+JSON.stringify([board.stage,board.cards.map(c=>[c.id,c.scene,c.candidate?.id,c.comments])]);
 if(key!==boardKey){boardKey=key;drawBoard(board,key).catch(e=>{boardKey='';notify(e.message,true);});}
 $('mockup-plan-explanation').textContent=board.explanation||'';
 const allowance=project.spending.stage_budgets?.mockups;$('mockup-budget-hint').textContent=allowance?'נותרו $'+allowance.remaining_usd.toFixed(3)+' מתוך $'+allowance.limit_usd+' למוקאפים · חלק מתקציב הניסוי הכולל.':'כל הקריאות מחויבות לתקציב הסטודיו הקיים.';
 show('abandon-mockup-job',!!w.pending&&project.phase==='generation_failed');updateBoardControls(board);
 if(project.phase==='generating_mockups')$('generation').querySelector('p').textContent=(final?'ליטוש סופי בתשלום':'מכינים סצנות')+' · '+(w.mockup_progress?.completed||0)+' מתוך '+(w.mockup_progress?.total||board.cards.length);
};
$('save-mockup-notes').onclick=()=>boardAction('save_mockup_board');
$('plan-mockup-scenes').onclick=()=>{if(confirm('לתכנן מחדש רק את המוקאפים הפתוחים באמצעות LLM זול? דוגמאות נעולות יישמרו.'))boardAction('plan_mockup_board');};
$('make-mockup-concepts').onclick=()=>{if(confirm('ליצור רק את הדוגמאות שאינן נעולות באמצעות המודל הזול?'))boardAction('render_mockup_board');};
$('final-mockup-scenes').onclick=()=>{const final=project.workflow.mockup_design.board.stage==='final';if(!final)boardAction('enter_mockup_final');else if(confirm('סבב ליטוש יקר: רק הדוגמאות הפתוחות יישלחו למודל המקצועי. לשמור קומפוזיציה ולתקן פרטים?'))boardAction('render_mockup_board',{consent_expensive:true});};
$('back-mockup-concepts').onclick=()=>boardAction('return_mockup_concepts');
$('abandon-mockup-job').onclick=()=>{if(confirm('לסגור את הסבב שנכשל ולהשאיר היסטוריה וחיובים? תוצאות כספיות לא ידועות נשארות חסומות.'))action('abandon_mockup_job');};
