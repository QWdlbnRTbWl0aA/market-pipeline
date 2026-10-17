'use strict';
let inventoryKey='',filesKey='',listingKey='',memoryRevision=0,editingPreference=null,workflowView=null,viewProject=null,observedStage=null;
const node=(tag,text,className)=>{const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element;};
const field=(label,value,tag='input')=>{const box=node('label',label),input=node(tag);input.value=value??'';box.append(input);return [box,input];};
function preview(url){$('large-preview-image').src=url;$('large-preview').showModal();}
$('close-preview').onclick=()=>$('large-preview').close();
function inventory(plan){
 const key=project.id+':'+plan.version;if(key===inventoryKey)return;inventoryKey=key;
 $('product-family').value=plan.family;$('plan-style').value=plan.style;$('plan-assumptions').value=plan.assumptions.join('\n');$('inventory-units').replaceChildren();
 for(const unit of plan.units){const box=node('article',undefined,'inventory-unit');box.dataset.unit=unit.id;
  const [title,titleInput]=field('שם הפריט',unit.title);titleInput.dataset.field='title';titleInput.maxLength=120;
  const [description,descriptionInput]=field('מה בדיוק יופיע בו?',unit.description,'textarea');descriptionInput.dataset.field='description';descriptionInput.maxLength=4000;
  const [visible,visibleInput]=field('טקסט שיודפס בנפרד מהאיור · אפשר להשאיר ריק',unit.visible_text,'textarea');visibleInput.dataset.field='visible_text';
  const kind=node('select');for(const [value,label] of [['illustration','איור מקורי'],['text','עמוד הוראות וטקסט']]){const option=node('option',label);option.value=value;kind.append(option);}kind.value=unit.kind;kind.dataset.field='kind';
  box.append(title,description,visible,kind);$('inventory-units').append(box);
 }
}
$('save-plan').onclick=()=>{const p=structuredClone(project.workflow.plan);p.family=$('product-family').value;p.style=$('plan-style').value;p.assumptions=$('plan-assumptions').value.split('\n').filter(Boolean);
 p.units=p.units.map(unit=>{const box=[...$('inventory-units').children].find(c=>c.dataset.unit===unit.id);for(const input of box.querySelectorAll('[data-field]'))unit[input.dataset.field]=input.value;return unit;});action('save_plan',{plan:p});};
async function loadFiles(){
 const id=project.id,w=project.workflow,key=id+JSON.stringify([w.products.at(-1)?.id,w.mockups]);if(key===filesKey)return;filesKey=key;
 try{const response=await request('/api/projects/'+id+'/files');if(project?.id!==id||filesKey!==key)return;
  $('product-files').replaceChildren();$('print-downloads').replaceChildren();$('mockup-files').replaceChildren();
  const latest=w.products.at(-1)?.id,files=response.files.filter(f=>f.product_id===latest);
  const seen=new Set();for(const file of files.filter(f=>f.role==='preview')){if(seen.has(file.unit_id))continue;seen.add(file.unit_id);
   const box=node('article',undefined,'product-file');const image=node('img');image.src='/api/projects/'+id+'/files/'+file.id;image.alt=file.unit_id;image.loading='lazy';
   const full=files.find(f=>f.role==='print_page'&&f.unit_id===file.unit_id&&f.format===file.format);image.onclick=()=>preview('/api/projects/'+id+'/files/'+full.id);
   const checkbox=node('input');checkbox.type='checkbox';checkbox.value=file.unit_id;checkbox.className='unit-selection';const label=node('label',w.plan.units.find(u=>u.id===file.unit_id)?.title||file.unit_id);label.prepend(checkbox);box.append(image,label);$('product-files').append(box);
  }
  for(const file of files.filter(f=>f.role==='print_pdf')){const link=node('a','PDF · '+file.format,'button secondary');link.href='/api/projects/'+id+'/files/'+file.id;link.target='_blank';link.rel='noopener';$('print-downloads').append(link);}
  if(project.lifestyle_mockups){$('legacy-mockups').hidden=true;return;}
  let library=(await request('/api/templates')).templates;if(project?.id!==id||filesKey!==key)return;
  for(const [index,file] of response.files.filter(f=>f.role==='mockup').entries()){
   const box=node('article',undefined,'mockup-card');box.dataset.index=index;const image=node('img');image.src='/api/projects/'+id+'/files/'+file.id;image.alt='מוקאף '+(index+1);image.onclick=()=>preview(image.src);
   if(file.origin==='generative_lifestyle'){box.append(image,node('h4',file.scene_title),node('p',file.scene_description));if(file.placement_status!=='ready')box.append(node('p','נדרש תיקון לסצנה לפני אישור: '+file.placement_reason,'error'));$('mockup-files').append(box);continue;}
   const select=node('select');for(const [value,label] of [['frame','מסגרת'],['flat','דף שטוח'],['stack','ערימת דפים'],['bundle','סקירת כל החבילה']]){const option=node('option',label);option.value=value;select.append(option);}select.value=file.template.kind;select.dataset.setting='kind';
   box.append(image,select);
   const preset=node('select');preset.dataset.preset='true';box.templateDefinition=structuredClone(file.template);const empty=node('option','בחירה מהתבניות השמורות');empty.value='';preset.append(empty);
   for(const item of library){const option=node('option',item.name);option.value=item.name;preset.append(option);}box.append(preset);
   const perspective=node('select');for(const [value,label] of [['straight','מבט ישר'],['left','פרספקטיבה שמאלה'],['right','פרספקטיבה ימינה']]){const option=node('option',label);option.value=value;perspective.append(option);}perspective.value=file.template.perspective??'straight';perspective.dataset.setting='perspective';box.append(perspective);
   for(const [setting,title,min,max,step,defaultValue] of [['scale','גודל',.3,1,.01,.82],['x','מיקום לרוחב',-.15,.15,.01,0],['y','מיקום לגובה',-.15,.15,.01,0]]){const label=node('label',title),input=node('input'),value=node('output');input.type='range';input.min=min;input.max=max;input.step=step;input.value=String(file.template[setting]??defaultValue);input.dataset.setting=setting;value.textContent=Math.round(Number(input.value)*100)+'%';input.addEventListener('input',()=>{value.textContent=Math.round(Number(input.value)*100)+'%';});label.append(input,value);box.append(label);}
   const status=node('small','','mockup-edit-status');box.append(status);
   for(const input of box.querySelectorAll('[data-setting]'))input.addEventListener('input',()=>{preset.value='';status.textContent='שינויים ממתינים לעדכון התצוגה';});
   const [label,name]=field('שם תבנית לשימוש חוזר','');name.maxLength=64;box.append(label);const save=node('button','שמירת תבנית','quiet');save.dataset.saveTemplate='true';save.onclick=async()=>{const id=project.id;if(!await action('save_template',{name:name.value,template:templateValue(box)}))return;if(project?.id!==id)return;const latest=(await request('/api/templates')).templates;library=latest;for(const target of $('mockup-files').querySelectorAll('[data-preset]')){const selected=target.value;target.replaceChildren();const blank=node('option','בחירה מהתבניות השמורות');blank.value='';target.append(blank);for(const item of latest){const option=node('option',item.name);option.value=item.name;target.append(option);}target.value=selected;}notify('התבנית נשמרה. העריכות נשמרו בתצוגה.');};preset.onchange=()=>{const item=library.find(t=>t.name===preset.value);if(!item)return;applyTemplate(box,item.template);status.textContent='התבנית נטענה · לחצו על עדכון לתצוגה חדשה';};box.append(save);$('mockup-files').append(box);
  }
 }catch(error){filesKey='';notify(error.message,true);}
}
function templateValue(box){const value=structuredClone(box.templateDefinition||{});for(const input of box.querySelectorAll('[data-setting]'))value[input.dataset.setting]=['kind','perspective'].includes(input.dataset.setting)?input.value:Number(input.value);return value;}
function applyTemplate(box,template){box.templateDefinition=structuredClone(template);const defaults={kind:'frame',perspective:'straight',scale:.82,x:0,y:0};for(const input of box.querySelectorAll('[data-setting]')){input.value=String(template[input.dataset.setting]??defaults[input.dataset.setting]);const output=input.parentElement.querySelector('output');if(output)output.textContent=Math.round(Number(input.value)*100)+'%';}}
window.renderWorkflow=()=>{
 const w=project?.workflow;if(!w)return;
 show('memory-panel',true);
 if(viewProject!==project.id){viewProject=project.id;workflowView=null;filesKey='';observedStage=null;}
 if(observedStage!==w.stage){observedStage=w.stage;workflowView=null;}
 const view=workflowView||w.stage;
 const stages=[['brief','בריף'],['direction','כיוון עיצובי'],['product','מוצר'],['mockups','מוקאפים'],['listing','טקסט למכירה'],['delivery','הורדה']];$('stage-nav').replaceChildren();
 for(const [id,label] of stages){const badge=node('button',label,'stage-step');badge.classList.toggle('active',view===id);badge.disabled=stages.findIndex(s=>s[0]===id)>stages.findIndex(s=>s[0]===w.stage);badge.onclick=()=>{workflowView=id;window.renderWorkflow();};$('stage-nav').append(badge);}
 const reviewing=['sketch_review','professional_review'].includes(project.phase);
 show('review',(reviewing||project.phase==='generation_failed'&&!w.pending)&&view==='direction');show('inventory-panel',!w.direction&&['brief_ready','sketch_review','professional_review'].includes(project.phase));
 show('production-panel',view==='product'&&w.products.length>0);show('mockups-panel',view==='mockups'&&(w.mockups.length>0||project.lifestyle_mockups));show('listing-panel',view==='listing');
 show('library-brief',view==='brief');
 if(!$('production-panel').hidden){$('production-checks').textContent='הפקה '+w.products.length+' · '+w.plan.units.length+' פריטים · '+w.print_settings.formats.join(' / ')+' · '+w.print_settings.dpi+' DPI. נדרש אישור חזותי; בדיקות הקוד אינן מאשרות איכות תוכן.';}
 $('approve-files').hidden=project.phase!=='product_review';$('final').textContent='אישור הכיוון והפקת החבילה';
 const bound=project.next_action_estimate_usd;const illustrations=w.plan.units.filter(u=>u.kind==='illustration').length;
 if(project.phase==='generating_product')$('generation').querySelector('p').textContent='מפיקים את קובצי המוצר · '+(w.progress?.completed||0)+' מתוך '+w.plan.units.length+(w.progress?.current?' · '+w.progress.current:'');
 else if(project.phase==='generating_listing')$('generation').querySelector('p').textContent='מכינים טקסט מתוך הקבצים שאושרו…';
 else $('generation').querySelector('p').textContent='מכינים שלושה כיוונים לפריט מייצג אחד…';
 $('next-cost').textContent=bound===null?'הערכת העלות תהיה זמינה לאחר בחירת ספק אמיתי.':'שמירה מרבית משוערת להפקת איור: $'+bound.toFixed(3)+' · '+illustrations+' איורים בחבילה. החיוב בפועל עשוי להיות נמוך יותר.';
 $('generate-copy').disabled=busy||!!w.pending||project.phase==='approved';$('approve-copy').disabled=!w.listing||busy||project.phase==='approved';
 for(const id of ['save-copy','approve-mockups','update-mockups','auto-mockups','revise-units','return-direction'])$(id).disabled=busy||project.phase==='approved'||!!w.pending;
 if(w.listing){const key=project.id+w.listing.at;if(key!==listingKey){listingKey=key;$('listing-title-1').value=w.listing.copy.titles[0];$('listing-title-2').value=w.listing.copy.titles[1];$('listing-description').value=w.listing.copy.description;$('listing-tags').value=w.listing.copy.tags.join('\n');}}
 show('customer-download',project.phase==='approved'&&w.stage==='delivery');$('customer-download').href='/api/projects/'+project.id+'/customer-download';
 if(project.phase==='approved'&&w.stage==='delivery')$('download').textContent='הורדת קובצי המוצר, המוקאפים והטקסט';
 inventory(w.plan);if(w.products.length||w.mockups.length)loadFiles();if(window.renderLifestyle)window.renderLifestyle();
};
$('final').onclick=()=>{const candidate=chosen||Object.keys(draft).find(id=>draft[id].decision==='accept')||project.accepted_samples.at(-1)?.id;if(!candidate){notify('בחרו כיוון שאהבתם לפני ההפקה.');return;}
 $('production-estimate').textContent=$('next-cost').textContent;$('production-settings').showModal();};
$('cancel-production').onclick=()=>$('production-settings').close();
$('production-form').onsubmit=async event=>{event.preventDefault();workflowView=null;const candidate=chosen||Object.keys(draft).find(id=>draft[id].decision==='accept')||project.accepted_samples.at(-1)?.id;
 $('production-settings').close();await action('approve_direction',{candidate_id:candidate,consent_expensive:true,print_settings:{formats:$('print-formats').value.split(','),dpi:Number($('print-dpi').value),margin_mm:Number($('print-margin').value),bleed_mm:Number($('print-bleed').value),color_mode:$('print-color').value}});};
$('revise-units').onclick=()=>{const selected=[...document.querySelectorAll('.unit-selection:checked')].map(i=>i.value);if(!selected.length){notify('סמנו פריטים לתיקון.');return;}if(confirm('לתקן רק את הפריטים שסומנו? הפעולה עשויה לעלות כסף.'))action('produce_selected',{unit_ids:selected,comments:$('unit-comments').value,consent_expensive:true});};
$('approve-files').onclick=()=>{workflowView=null;action('approve_product',{visual_review_confirmed:$('visual-proof').checked,print_proof_confirmed:$('physical-proof').checked});};
$('return-direction').onclick=()=>{if(confirm('חזרה לכיוון העיצובי תבטל את האישורים בשלבים הבאים, תוך שמירת הקבצים וההיסטוריה. להמשיך?'))action('return_to_direction');};
async function updateMockups(templates){const button=$('update-mockups');button.disabled=true;$('auto-mockups').disabled=true;button.textContent='מעדכנים את המוקאפים…';$('mockup-files').inert=true;try{if(await action('make_mockups',{templates,...(window.mockupFeedback?window.mockupFeedback():{})}))notify('המוקאפים עודכנו וההגדרות נשמרו.');}finally{button.textContent='עדכון המוקאפים';button.disabled=false;$('auto-mockups').disabled=false;$('mockup-files').inert=false;}}
$('update-mockups').onclick=()=>updateMockups([...$('mockup-files').children].map(templateValue));
$('auto-mockups').onclick=()=>updateMockups(null);
$('approve-mockups').onclick=()=>{workflowView=null;action('approve_mockups',window.mockupFeedback?window.mockupFeedback():{});};
$('generate-copy').onclick=()=>{if(confirm('ליצור טקסט מהמוצר שאושר באמצעות ספק הטקסט המוגדר?'))action('generate_listing');};
$('save-copy').onclick=()=>action('save_listing',{listing:{titles:[$('listing-title-1').value,$('listing-title-2').value],description:$('listing-description').value,tags:$('listing-tags').value.split('\n').map(t=>t.trim()).filter(Boolean)}});
$('approve-copy').onclick=async()=>{const listing={titles:[$('listing-title-1').value,$('listing-title-2').value],description:$('listing-description').value,tags:$('listing-tags').value.split('\n').map(t=>t.trim()).filter(Boolean)};
 const confirmed=$('copy-proof').checked;if(!await action('save_listing',{listing}))return;const saved=project.workflow.listing?.copy;
 if(!saved||JSON.stringify(saved.titles)!==JSON.stringify(listing.titles)||JSON.stringify(saved.tags)!==JSON.stringify(listing.tags)){notify('בדקו את עריכת הטקסט ושמרו לפני אישור.',true);return;}
 workflowView=null;await action('approve_listing',{copy_review_confirmed:confirmed});};
$('retry').onclick=()=>{if(project.workflow?.pending){if(confirm('ניסיון חוזר מפורש: ייעשה שימוש חוזר בתוצאות שנשמרו. תוצאה כספית לא ידועה נשארת חסומה.'))action('retry_workflow',{consent_expensive:true});}else action('retry_generation',{consent_expensive:true});};
async function loadMemory(){const memory=await request('/api/preferences');memoryRevision=memory.revision;$('memory-items').replaceChildren();for(const item of memory.items){const box=node('article');box.append(node('p',item.text),node('small',item.scope+' · '+(item.family||item.project_id)));
 const edit=node('button','עריכה','quiet');edit.onclick=()=>{editingPreference=item.id;$('memory-text').value=item.text;$('memory-scope').value=item.scope;};
 const remove=node('button','הסרה','quiet');remove.onclick=async()=>{await action('remember_preference',{operation:'delete',preference_id:item.id,memory_revision:memoryRevision});loadMemory();};box.append(edit,remove);$('memory-items').append(box);}}
$('load-memory').onclick=()=>loadMemory().catch(e=>notify(e.message,true));
$('save-memory').onclick=async()=>{try{const memory=await request('/api/preferences');await action('remember_preference',{operation:'save',preference_id:editingPreference,memory_revision:memory.revision,text:$('memory-text').value,scope:$('memory-scope').value,family:project.workflow.plan.family});editingPreference=null;await loadMemory();}catch(e){notify(e.message,true);}};

request('/api/runtime').then(runtime=>{if(runtime.mockup_flow_version!==2)return;const script=document.createElement('script');script.src='/lifestyle.js';script.onload=()=>{if(project)window.renderWorkflow();};document.head.append(script);}).catch(e=>notify(e.message,true));
