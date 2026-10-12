'use strict';
const $ = id => document.getElementById(id);
let project = null, editing = false, busy = false, dirty = false, pending = null;
try { pending=JSON.parse(sessionStorage.getItem('studio-pending')||'null'); } catch (_) { pending=null; }
function clearPending() { pending=null;try { sessionStorage.removeItem('studio-pending'); } catch (_) {} }
const fields = ['concept','audience','purpose','deliverables','visual_direction','requirements'];
const labels = {concept:'Product concept',audience:'Audience',purpose:'Purpose',deliverables:'Deliverables',visual_direction:'Visual direction',requirements:'Requirements'};
function notify(message, error=false) { $('message').textContent=message; $('message').classList.toggle('error',error); }
async function request(path, body, key) {
  const options = body ? {method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)} : {};
  const response = await fetch(path,options); const result = await response.json();
  if(!response.ok) throw new Error(result.error || 'Request failed'); return result;
}
async function projects() {
  const data=await request('/api/projects'); $('projects').replaceChildren();
  for(const item of data.projects) {
    const button=document.createElement('button'); button.textContent=item.title;
    const sub=document.createElement('small'); sub.textContent=item.phase.replaceAll('_',' '); button.append(sub);
    button.classList.toggle('active',item.id===project?.id);
    button.onclick=async()=>{if(dirty&&!confirm('Discard unsaved feedback?'))return; clearPending(); dirty=false; await load(item.id);};
    $('projects').append(button);
  }
}
async function load(id) { try {project=(await request('/api/projects/'+id)).project; editing=false; render();await projects();}catch(error){notify(error.message,true);} }
function show(id, visible) { $(id).hidden=!visible; }
function render() {
  show('intake',!project||editing); show('project',!!project&&!editing); if(!project||editing)return;
  $('title').textContent=project.title; $('phase').textContent=project.phase.replaceAll('_',' ');
  $('round-info').textContent=`Start ${project.epoch} · ${project.rounds.length} rounds`;
  $('brief-details').replaceChildren(); for(const field of fields){ const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=labels[field];dd.textContent=Array.isArray(project.brief[field])?project.brief[field].join('\n'):project.brief[field];$('brief-details').append(dt,dd); }
  $('history').textContent=`${project.archives.length} archived starts · ${project.negative_summary.abandoned_rounds||0} rounds compacted as negative examples. Reviews are saved on disk.`;
  $('notification').textContent=project.notification?project.notification.message+' · broker: '+(project.notification.delivery?.status||'queued'):'';
  const professional=project.phase==='professional_review', reviewing=professional||project.phase==='sketch_review';
  show('missing',project.phase==='needs_information'); show('generation',project.phase.startsWith('generating_'));
  show('failure',project.phase==='generation_failed'); $('generation-error').textContent=project.generation_error||'';
  show('review',reviewing);show('expensive',professional);show('approved',project.phase==='approved');
  $('questions').replaceChildren(); for(const q of project.missing_information){const li=document.createElement('li');li.textContent=q.question;$('questions').append(li);}
  $('download').href=`/api/projects/${project.id}/download`;
  show('final',!professional);show('approve',professional);$('next').textContent=professional?'Generate next 3 professional samples':'Generate next 10 sketches';
  if(!reviewing)return;
  const round=project.rounds.at(-1); $('comments').value=round.comments; $('samples').replaceChildren();
  for(const candidate of round.candidates) {
    const card=document.createElement('article');card.className='sample';card.dataset.candidate=candidate.id;
    const image=document.createElement('img');image.src=`/api/projects/${project.id}/asset/${candidate.id}`;image.alt=candidate.label+' mock '+round.mode;
    const title=document.createElement('h3');title.textContent=candidate.label;
    const select=document.createElement('select');select.setAttribute('aria-label','Review '+candidate.label);select.className='decision';
    for(const [value,label] of [['','Not reviewed'],['accept','Accept'],['accept_with_comments','Accept with comments'],['reject','Reject']]){const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);}
    select.value=round.reviews[candidate.id]?.decision||'';
    const comments=document.createElement('textarea');comments.className='candidate-comment';comments.placeholder='Comment for this direction';comments.maxLength=2000;comments.rows=2;comments.setAttribute('aria-label','Comments for '+candidate.label);comments.value=round.reviews[candidate.id]?.comment||'';
    const change=()=>{dirty=true;card.className='sample '+select.value;};select.onchange=change;comments.oninput=change;card.className='sample '+select.value;
    card.append(image,title,select,comments);
    if(professional){const label=document.createElement('label');label.className='final-choice';const radio=document.createElement('input');radio.type='radio';radio.name='final-choice';radio.value=candidate.id;label.append(radio,document.createTextNode('Final selection'));card.append(label);}
    $('samples').append(card);
  }
}
function feedback() {
  const reviews={}; for(const card of document.querySelectorAll('.sample')){const decision=card.querySelector('.decision').value;if(decision)reviews[card.dataset.candidate]={decision,comment:card.querySelector('.candidate-comment').value};}
  return {reviews,comments:$('comments').value};
}
async function submit(path, payload) {
  if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);
  const serialized=JSON.stringify({path,payload});if(!pending||pending.serialized!==serialized)pending={serialized,key:crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random().toString(16).slice(2)};
  try { sessionStorage.setItem('studio-pending',JSON.stringify(pending)); } catch (_) {}
  try{const result=await request(path,payload,pending.key);project=result.project;clearPending();dirty=false;editing=false;notify(result.duplicate?'Previously saved action restored.':'Saved.');render();await projects();}
  catch(error){notify(error.message+' Your feedback remains on screen.',true);}
  finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);}
}
async function action(name,extra={}) { if(!project)return; await submit(`/api/projects/${project.id}/actions/${name}`,{revision:project.revision,...feedback(),...extra}); }
function fillBrief(brief={}){for(const field of fields)$('brief-form').elements[field].value=Array.isArray(brief[field])?brief[field].join('\n'):brief[field]||'';}
$('new-project').onclick=()=>{if(dirty&&!confirm('Discard unsaved feedback?'))return;project=null;editing=false;dirty=false;clearPending();fillBrief();render();notify('');};
$('edit-brief').onclick=()=>{editing=true;fillBrief(project.brief);render();};
$('brief-form').onsubmit=async event=>{event.preventDefault();const brief={};for(const field of fields)brief[field]=$('brief-form').elements[field].value.trim();brief.deliverables=brief.deliverables.split('\n').map(s=>s.trim()).filter(Boolean);if(editing)await submit(`/api/projects/${project.id}/actions/update_brief`,{revision:project.revision,brief});else await submit('/api/briefs',brief);};
$('import').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>1000000)throw new Error('Brief exceeds 1MB');await submit('/api/briefs',JSON.parse(await file.text()));}catch(error){notify(error.message,true);}event.target.value='';};
$('comments').oninput=()=>{dirty=true;};$('save').onclick=()=>action('save_feedback');
$('next').onclick=()=>{const professional=project.phase==='professional_review';if(professional&&!confirm('Generate another set in the expensive loop?'))return;action(professional?'next_professional':'next_sketches',professional?{consent_expensive:true}:{});};
$('start-over').onclick=()=>{if(confirm('Archive this interaction as a negative example and start a new set of 10 sketches?'))action('start_over');};
$('back').onclick=()=>action('back_to_sketches');$('final').onclick=()=>{if(!Object.values(feedback().reviews).some(r=>r.decision.startsWith('accept'))){notify('Accept at least one sketch first.',true);return;}$('consent').checked=false;$('settings').showModal();};
$('cancel-settings').onclick=()=>$('settings').close();
$('settings-form').onsubmit=event=>{event.preventDefault();const settings=Object.fromEntries(new FormData(event.target));for(const key of ['width','height','dpi','bleed_mm'])settings[key]=Number(settings[key]);$('settings').close();action('generate_final',{settings,consent_expensive:true});};
$('approve').onclick=()=>{const chosen=document.querySelector('input[name="final-choice"]:checked');if(!chosen){notify('Choose an accepted final sample.',true);return;}if(confirm('Approve this final selection? Etsy publishing remains blocked.'))action('approve_final',{candidate_id:chosen.value});};
$('retry').onclick=()=>{const professional=project.final_settings!==null;if(confirm('Explicitly retry generation? A future live provider may charge again.'))action('retry_generation',professional?{consent_expensive:true}:{});};
setInterval(async()=>{if(!project||busy||dirty||editing||!project.phase.startsWith('generating_'))return;await load(project.id);},1200);
async function init() {
  if(pending) {
    // Resume the exact reserved browser request after refresh, using the same
    // key and revision. The server returns its saved result if already accepted.
    try { const saved=JSON.parse(pending.serialized);await submit(saved.path,saved.payload); }
    catch(error) { notify('Pending submission could not be restored: '+error.message,true); }
  }
  await projects();
}
init().catch(error=>notify(error.message,true));
