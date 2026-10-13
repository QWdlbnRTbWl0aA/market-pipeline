'use strict';
const $=id=>document.getElementById(id);
let project=null,editing=false,busy=false,draft={},round=null,chosen=null,references=[],lastSpending='',pending=null;
const fields=['concept','audience','purpose','deliverables','visual_direction','requirements'];
const phases={needs_information:'נשלים כמה פרטים',sketch_review:'בוחרים כיוון',professional_review:'מלטשים את היצירה',generating_sketch:'מבינים ויוצרים',generating_professional:'מכינים דוגמאות מקצועיות',generation_failed:'היצירה נעצרה',approved:'היצירה אושרה'};
try{pending=JSON.parse(sessionStorage.getItem('studio-pending')||'null');}catch(_){}
function show(id,visible){$(id).hidden=!visible;}
function notify(message,error=false){$('message').textContent=message;$('message').classList.toggle('error',error);}
async function request(path,body,key){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)}:{cache:'no-store'});const result=await response.json();if(!response.ok)throw Error(result.error||'הפעולה לא הושלמה');return result;}
async function projects(){const data=await request('/api/projects');$('projects').replaceChildren();for(const item of data.projects){const button=document.createElement('button');button.textContent=item.title;button.onclick=()=>load(item.id);$('projects').append(button);}}
async function load(id){try{project=(await request('/api/projects/'+id)).project;editing=false;render();await projects();}catch(e){notify(e.message,true);}}
function fillBrief(brief={}){for(const field of fields)$('brief-form').elements[field].value=Array.isArray(brief[field])?brief[field].join('\n'):brief[field]||'';}
function render(){
 show('intake',!project||editing);show('reference-input',!project);show('project',!!project&&!editing);if(!project||editing)return;
 $('title').textContent=project.title;$('phase').textContent=phases[project.phase]||'יצירה';$('round-info').textContent='סבב '+project.epoch;
 const generating=project.phase.startsWith('generating_'),professional=project.phase.includes('professional'),frame=project.rounds.at(-1);
 show('generation',generating);show('review',!!frame&&project.phase!=='approved');show('missing',project.phase==='needs_information');show('failure',project.phase==='generation_failed');show('expensive',professional);show('approved',project.phase==='approved');show('final',!professional);show('approve',professional);
 $('generation-error').textContent=project.generation_error||'';$('download').href='/api/projects/'+project.id+'/download';
 $('questions').replaceChildren();for(const item of project.missing_information){const li=document.createElement('li');li.textContent=item.question;$('questions').append(li);}
 if(frame){
  const key=project.id+frame.id;
  if(round!==key){round=key;draft={...frame.reviews};$('batch-comments').value=frame.comments||'';chosen=null;}
  $('samples').replaceChildren();
  for(const candidate of frame.candidates.slice(0,3)){
   const card=document.createElement('article');card.className='sample';card.dataset.candidate=candidate.id;
   const controls=document.createElement('div');controls.className='controls';const visual=document.createElement('div');visual.className='visual';
   const image=document.createElement('img');image.src='/api/projects/'+project.id+'/asset/'+candidate.id;image.alt=candidate.metadata?.description||candidate.label;visual.append(image);
   for(const [decision,label] of [['reject','לא אהבתי'],['accept','אהבתי']]){
    const button=document.createElement('button');button.className=decision;button.textContent=label;button.disabled=generating||busy;
    button.setAttribute('aria-pressed',String(draft[candidate.id]?.decision===decision));
    button.onclick=()=>{draft[candidate.id]={decision,comment:''};if(decision==='accept')chosen=candidate.id;render();};controls.append(button);
   }card.append(controls,visual);$('samples').append(card);
  }
  $('regenerate').disabled=generating||busy||frame.candidates.slice(0,3).some(c=>!draft[c.id]);
 }
 const accepted=project.accepted_samples||[];show('accepted',accepted.length>0);$('accepted-samples').replaceChildren();
 for(const sample of accepted.slice(-6)){const image=document.createElement('img');image.src='/api/projects/'+project.id+'/asset/'+sample.id;image.alt='כיוון שאושר';$('accepted-samples').append(image);}
 $('understanding').textContent=project.understanding?.summary||'סמנו את שלוש הדוגמאות והוסיפו הערה משותפת כדי לדייק את הכיוון.';
 $('history').textContent=project.archives.length+' התחלות קודמות שמורות.';$('notification').textContent=project.notification?.message||'';
 $('brief-details').textContent=fields.map(field=>field+': '+(Array.isArray(project.brief[field])?project.brief[field].join(', '):project.brief[field]||'')).join('\n');
 const spending=project.spending;show('reasoning',!!spending?.development);$('budget').textContent=spending?.development?'פיתוח: $'+spending.product_usd.toFixed(4)+' ליצירה · $'+spending.remaining_usd.toFixed(4)+' נותרו מתוך $1.':'';
 if(spending?.development){const marker=JSON.stringify([project.id,spending]);if(marker!==lastSpending){console.log('[Studio development] OpenAI cumulative spend per product',{product_id:project.id,product_usd:spending.product_usd,total_charged_or_reserved_usd:spending.charged_or_reserved_usd,remaining_usd:spending.remaining_usd});lastSpending=marker;}}
 for(const id of ['final','approve','start-over','back'])$(id).disabled=generating||busy;
}
async function submit(path,payload){
 if(busy)return;busy=true;const serialized=JSON.stringify({path,payload});
 if(!pending||pending.serialized!==serialized)pending={serialized,key:crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random().toString(16).slice(2)};
 try{sessionStorage.setItem('studio-pending',JSON.stringify(pending));}catch(_){}
 try{const result=await request(path,payload,pending.key);pending=null;sessionStorage.removeItem('studio-pending');project=result.project;editing=false;notify('');}
 catch(error){notify(error.message,true);}
 finally{busy=false;if(project)await load(project.id);}
}
function feedback(){const ids=project.rounds.at(-1).candidates.slice(0,3).map(c=>c.id);return {reviews:Object.fromEntries(ids.filter(id=>draft[id]).map(id=>[id,draft[id]])),comments:$('batch-comments').value};}
async function action(name,extra={}){if(project)await submit('/api/projects/'+project.id+'/actions/'+name,{revision:project.revision,...feedback(),...extra});}
async function compress(file){
 if(!/^image\/(png|jpeg|webp)$/.test(file.type)||file.size>20_000_000)throw Error('בחרו תמונה עד 20MB בפורמט PNG, JPEG או WebP.');
 const bitmap=await createImageBitmap(file);if(bitmap.width*bitmap.height>20_000_000){bitmap.close();throw Error('התמונה גדולה מדי.');}
 const factor=Math.min(1,512/Math.max(bitmap.width,bitmap.height));const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*factor));canvas.height=Math.max(1,Math.round(bitmap.height*factor));
 const context=canvas.getContext('2d');context.fillStyle='white';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();
 let value=canvas.toDataURL('image/jpeg',.75);if(value.length>110000)value=canvas.toDataURL('image/jpeg',.5);if(value.length>110000)throw Error('הקובץ עדיין גדול מדי.');return value;
}
function renderReferences(){$('reference-previews').replaceChildren();for(const [index,value] of references.entries()){const box=document.createElement('div'),image=document.createElement('img'),remove=document.createElement('button');image.src=value;image.alt='דוגמת סגנון';remove.type='button';remove.textContent='הסרה';remove.onclick=()=>{references.splice(index,1);renderReferences();};box.append(image,remove);$('reference-previews').append(box);}}
async function addReferences(files){try{for(const file of files){if(references.length>=3)throw Error('עד שלוש תמונות לדוגמה.');references.push(await compress(file));}renderReferences();}catch(e){notify(e.message,true);}}
$('reference-files').onchange=e=>addReferences([...e.target.files]);
$('reference-paste').onpaste=e=>{const data=e.clipboardData;const files=[...(data?.items||[])].filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();addReferences(files);}else notify('לא נמצאה תמונה בלוח. אפשר להשתמש בכפתור העלאת התמונה.');};
$('new-project').onclick=()=>{project=null;round=null;draft={};references=[];editing=false;fillBrief();renderReferences();render();};
$('brief-form').onsubmit=async event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.target));data.deliverables=data.deliverables.split('\n').map(x=>x.trim()).filter(Boolean);
 if(project)await action('update_brief',{brief:data});else await submit('/api/briefs',{...data,reference_images:references});};
$('import').onchange=async event=>{try{const file=event.target.files[0];if(file.size>800000)throw Error('הבריף גדול מדי.');const data=JSON.parse(await file.text());const images=data.reference_images||[];if(!Array.isArray(images)||images.length>3||images.some(i=>typeof i!=='string'||i.length>110000||!/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(i)))throw Error('תמונות לדוגמה לא תקינות.');project=null;round=null;references=images;fillBrief(data.source_requirements||data.product_brief||data);renderReferences();render();}catch(e){notify(e.message,true);}};
$('regenerate').onclick=async()=>{const expensive=project.phase==='professional_review';if(expensive&&!confirm('זהו סבב יקר יותר. להמשיך?'))return;await action('regenerate_batch',{consent_expensive:expensive});};
$('edit-brief').onclick=()=>{editing=true;fillBrief(project.brief);references=[];render();$('reference-input').hidden=true;};
$('final').onclick=()=>{if(!Object.values(draft).some(r=>r.decision==='accept')&&!project.accepted_samples.length){notify('בחרו לפחות דוגמה אחת שאהבתם.');return;}$('settings').showModal();};
$('cancel-settings').onclick=()=>$('settings').close();
$('settings-form').onsubmit=async event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));for(const name of ['width','height','dpi','bleed_mm'])values[name]=Number(values[name]);$('settings').close();await action('generate_final',{settings:values,consent_expensive:true});};
$('back').onclick=()=>action('back_to_sketches');$('start-over').onclick=()=>{if(confirm('לשמור את הסבב כדוגמה שלילית ולהתחיל מחדש?'))action('start_over');};
$('approve').onclick=()=>{const selected=chosen||Object.keys(draft).find(id=>draft[id].decision==='accept');if(!selected){notify('בחרו דוגמה מקצועית שאהבתם.');return;}action('approve_final',{candidate_id:selected});};
$('retry').onclick=()=>{const expensive=project.final_settings!==null;if(!expensive||confirm('לנסות שוב בסבב המקצועי?'))action('retry_generation',{consent_expensive:expensive});};
$('reasoning').onclick=async()=>{try{const data=await request('/api/projects/'+project.id+'/reasoning');$('reasoning-log').textContent=JSON.stringify(data.entries,null,2);show('reasoning-log',true);}catch(e){notify(e.message,true);}};
setInterval(async()=>{if(project&&project.phase.startsWith('generating_')&&!busy)await load(project.id);},800);
projects().then(()=>{render();if(pending){notify('פעולה קודמת ממתינה לאימות. שלחו שוב עם אותם נתונים כדי לשמור על זהות הפעולה.');}}).catch(e=>notify(e.message,true));
