#!/usr/bin/env python3
import argparse, base64, json, pathlib, shutil, socket, subprocess, sys, threading, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Offline Hebrew Studio workflow smoke: synthetic raster/text providers, temporary loopback server and existing Firefox/geckodriver. No paid/Etsy/SMTP calls.')
parser.add_argument('--output',required=True);parser.add_argument('--lifestyle',action='store_true');parser.add_argument('--targeted-refinement',action='store_true');args=parser.parse_args();OUT=pathlib.Path(args.output).resolve()
if OUT.is_relative_to(ROOT):raise ValueError('Browser artifacts must stay outside source control')
OUT.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(ROOT/'services/studio'),str(ROOT/'services/studio/tests')]
from studio_service.core import Studio
from studio_service.server import Server
from test_production_workflow import Pixels,Copy

def free():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
state=OUT/('browser-state-'+str(int(time.time())));images=Pixels();extra={}
if args.lifestyle:
 from test_lifestyle import Scenes
 from studio_service.providers import PlanningFailure
 from studio_service.model_roles import ModelRoles
 if args.targeted_refinement:
  from test_targeted_refinement import Refiner
  scene_port=Refiner()
 else:scene_port=Scenes()
 original_plan=scene_port.mockup_plan;first_plan=[True]
 def first_incomplete(*a,**k):
  if first_plan[0]:
   first_plan[0]=False;raise PlanningFailure({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]},'mockup_planning','synthetic text')
  time.sleep(3)  # Offline planning latency exercises progress polling.
  return original_plan(*a,**k)
 scene_port.mockup_plan=first_incomplete
 roles=ModelRoles({'openai':['mockup_planning','mockup_sketches','mockup_final_images']},available=lambda p:True)
 roles.register_final('fixture-a','Synthetic professional A','openai',scene_port,tier='top_tier',capability='image_edit')
 roles.register_final('fixture-b','Synthetic professional B','openai',scene_port,tier='top_tier',capability='image_edit')
 extra={'mockup_planner':scene_port,'mockup_drafts':scene_port,'mockup_finals':scene_port,'model_roles':roles}
studio=Studio(state,sketches=images,professional=images,copywriter=Copy(),development=args.lifestyle,**extra)
http=Server(('127.0.0.1',0),studio);http.start_worker();threading.Thread(target=http.serve_forever,daemon=True).start()
port=free();driver=subprocess.Popen([shutil.which('geckodriver') or 'geckodriver','--host','127.0.0.1','--port',str(port)],stdout=(OUT/'geckodriver.log').open('w'),stderr=subprocess.STDOUT)
BASE='http://127.0.0.1:'+str(port);session=None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(method,path,value=None):
 req=urllib.request.Request(BASE+path,data=None if value is None else json.dumps(value).encode(),method=method,headers={'Content-Type':'application/json'})
 try:
  with opener.open(req,timeout=60) as r:return json.load(r).get('value')
 except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode()) from None

def js(code):return request('POST',session+'/execute/sync',{'script':code,'args':[]})
def wait(code,timeout=40):
 end=time.time()+timeout
 while time.time()<end:
  if js('return '+code):return
  time.sleep(.15)
 raise AssertionError('UI timeout: '+code+'; '+str(js("return document.querySelector('#message').textContent")))
def click(selector):js('document.querySelector('+json.dumps(selector)+').click()')
def fill(selector,value):js('document.querySelector('+json.dumps(selector)+').value='+json.dumps(value))
def screenshot(name):(OUT/(name+'.png')).write_bytes(base64.b64decode(request('GET',session+'/screenshot')))
try:
 for _ in range(100):
  try:request('GET','/status');break
  except Exception:time.sleep(.1)
 result=request('POST','/session',{'capabilities':{'alwaysMatch':{'browserName':'firefox','moz:firefoxOptions':{'args':['-headless'],'prefs':{'network.proxy.type':0}}}}})
 session='/session/'+result['sessionId'];request('POST',session+'/window/rect',{'width':390,'height':844})
 brief=json.loads((ROOT/'examples/studio-hanukkah-brief.example.json').read_text());project=studio.create(brief,'browser-intake')['project']['id']
 request('POST',session+'/url',{'url':'http://127.0.0.1:'+str(http.server_port)+'/'})
 wait("document.querySelectorAll('#projects button').length === 1")
 # Reference input checks migrated from the retired sample-loop runner.
 click('#new-project')
 js("const c=document.createElement('canvas');c.width=900;c.height=600;const x=c.getContext('2d');x.fillStyle='blue';x.fillRect(0,0,900,600);const bytes=Uint8Array.from(atob(c.toDataURL('image/png').split(',')[1]),v=>v.charCodeAt(0));const t=new DataTransfer();t.items.add(new File([bytes],'reference.png',{type:'image/png'}));document.querySelector('#reference-paste').onpaste({clipboardData:t,preventDefault:()=>{}});")
 wait("document.querySelectorAll('#reference-previews img').length===1")
 data=js("const c=document.createElement('canvas');c.width=750;c.height=500;return c.toDataURL('image/png').split(',')[1]")
 fixture_file=OUT/'reference-fixture.png';fixture_file.write_bytes(base64.b64decode(data))
 element=request('POST',session+'/element',{'using':'css selector','value':'#reference-files'})['element-6066-11e4-a52e-4f735466cecf']
 request('POST',session+'/element/'+element+'/value',{'text':str(fixture_file),'value':list(str(fixture_file))})
 wait("document.querySelectorAll('#reference-previews img').length===2")
 assert js("return [...document.querySelectorAll('#reference-previews img')].every(i=>i.naturalWidth<=512&&i.naturalHeight<=512)")
 click('#projects button');wait("!document.querySelector('#library-brief').hidden")
 assert js("return document.documentElement.lang==='he' && document.documentElement.dir==='rtl'")
 click('#start-sketches');request('POST',session+'/alert/accept',{})
 wait("document.querySelectorAll('#samples .sample').length === 3 && !document.querySelector('#review').hidden")
 click('#samples .sample:first-child .accept');assert js("return document.querySelector('#samples .sample:first-child .accept').getAttribute('aria-pressed')==='true'")
 click('#samples .sample:first-child .accept');assert js("return document.querySelector('#samples .sample:first-child .accept').getAttribute('aria-pressed')==='false'")
 click('#samples .sample:first-child .reject');click('#samples .sample:first-child .accept')
 assert js("return document.querySelector('#samples .sample:first-child .reject').getAttribute('aria-pressed')==='false'")
 click('#final');wait("document.querySelector('#production-settings').open")
 fill('#print-dpi','150');js("document.querySelector('#production-form input[type=checkbox]').checked=true")
 click('#production-form button[type=submit]');wait("!document.querySelector('#production-panel').hidden",60)
 wait("document.querySelectorAll('#product-files img').length === 5")
 assert js('return document.documentElement.scrollWidth <= window.innerWidth');screenshot('01-product-mobile')
 click('#product-files img');wait("document.querySelector('#large-preview').open");click('#close-preview')
 js("document.querySelector('#visual-proof').checked=true");click('#approve-files');wait("!document.querySelector('#mockups-panel').hidden")
 if not args.lifestyle:wait("document.querySelectorAll('#mockup-files img').length === 3")
 screenshot('02-mockups-mobile')
 if not args.lifestyle:
  first='#mockup-files .mockup-card:first-child'
  def setting(name,value):
   selector=first+' [data-setting='+name+']'
   js('const input=document.querySelector('+json.dumps(selector)+');input.value='+json.dumps(str(value))+';input.dispatchEvent(new Event("input",{bubbles:true}));')
  assert js('return document.querySelector('+json.dumps(first+' [data-setting=x]')+').value')=='0'
  setting('kind','stack');setting('perspective','left');setting('scale',.62);setting('x',0);setting('y',0)
  click('#update-mockups')
  wait("document.querySelector('#message').textContent.includes('המוק-אפים עודכנו')",60)
  wait('document.querySelector('+json.dumps(first+' [data-setting=scale]')+').value === "0.62"')
  saved=studio.get(project)['workflow']['mockups'][0]['template'];assert saved['x']==0 and saved['y']==0 and saved['scale']==.62 and saved['perspective']=='left'
  fill(first+' input[maxlength="64"]','regression-preset');click(first+' [data-save-template]')
  wait('document.querySelector('+json.dumps(first+' [data-preset] option[value=regression-preset]')+') !== null')
  assert js('return document.querySelector('+json.dumps(first+' [data-setting=scale]')+').value')=='0.62'
  js('const preset=document.querySelector('+json.dumps(first+' [data-preset]')+');preset.value="regression-preset";preset.dispatchEvent(new Event("change",{bubbles:true}));')
  setting('x',.04);assert js('return document.querySelector('+json.dumps(first+' [data-preset]')+').value')==''
  click('#update-mockups');wait("document.querySelector('#message').textContent.includes('המוק-אפים עודכנו')",60)
  saved=studio.get(project)['workflow']['mockups'][0]['template'];assert saved['x']==.04 and saved['y']==0 and saved['scale']==.62
  request('POST',session+'/url',{'url':'http://127.0.0.1:'+str(http.server_port)+'/'})
  wait("document.querySelectorAll('#projects button').length === 1");click('#projects button')
  wait('document.querySelector('+json.dumps(first+' [data-setting=x]')+') !== null')
  assert js('return document.querySelector('+json.dumps(first+' [data-setting=x]')+').value')=='0.04'
  assert js('return document.querySelector('+json.dumps(first+' [data-setting=y]')+').value')=='0'
  screenshot('02b-mockup-settings-persisted')
  click('#auto-mockups');wait("document.querySelector('#message').textContent.includes('המוק-אפים עודכנו')",60)
  automatic=studio.get(project)['workflow']['mockups'];assert all(m['template']['x']==0 and m['template']['y']==0 for m in automatic)
  assert automatic[0]['template']['scale']==.86 and automatic[2]['template']['kind']=='bundle'
 else:
  wait("!document.querySelector('#lifestyle-actions').hidden")
  assert js("return document.querySelector('#legacy-mockups').hidden")
  js("window.providerErrors=[];const original=console.error;console.error=(...args)=>{window.providerErrors.push(args);original(...args)}")
  # Finalization starts disabled, with a keyboard/hover explanation.
  reason=js("return document.querySelector('#final-mockup-scenes').title");assert reason
  js("document.querySelector('#final-mockup-scenes').parentElement.focus()")
  assert js("return getComputedStyle(document.querySelector('#final-mockup-scenes').parentElement,'::after').content")!='none'
  fill('#suggest-mockup-count','5');fill('#mockup-comments','Warm family atmosphere and varied gallery')
  click('#suggest-mockups');request('POST',session+'/alert/accept',{})
  wait("document.querySelector('#phase').textContent.includes('נעצרה') && !document.querySelector('#apply-mockup-comments').disabled",60)
  assert js("return window.providerErrors.some(e=>e[1]?.response?.incomplete_details?.reason==='max_output_tokens')")
  assert len(scene_port.images)==0
  js("window.progressTrace={calls:[],active:0,max:0};const realFetch=window.fetch;window.fetch=(url,options={})=>{const progress=String(url).endsWith('/progress'),t=window.progressTrace;t.calls.push({url:String(url),method:options.method||'GET'});if(progress){t.active++;t.max=Math.max(t.max,t.active);}return realFetch(url,options).then(r=>progress?new Promise(resolve=>setTimeout(()=>resolve(r),1200)):r).finally(()=>{if(progress)t.active--;});}")
  click('#apply-mockup-comments');request('POST',session+'/alert/accept',{})
  wait("document.querySelectorAll('#mockup-concepts [data-card] img').length === 5 && !document.querySelector('#apply-mockup-comments').disabled",60)
  trace=js('return window.progressTrace');assert trace['max']==1
  assert len([c for c in trace['calls'] if c['url']=='/api/projects' and c['method']=='GET'])<=7
  assert len([c for c in trace['calls'] if c['url']=='/api/projects/'+project and c['method']=='GET'])<=7
  (OUT/'polling-results.json').write_text(json.dumps({'passed':True,'max_overlapping_progress_requests':trace['max'],'requests':trace['calls'],'paid_calls':0},indent=2)+'\n')
  assert all(not image['final'] for image in scene_port.images)
  first='#mockup-concepts [data-card]:first-child'
  # A lossy planner must not overwrite authored scene text or cancel it with
  # the previous hidden image prompt. Failed saves must retain browser drafts.
  authored='תצלום של ערמת דפים איכותיים ועבים ללא אנשים, עם קצוות נייר ברורים'
  fill(first+' [data-description]',authored);fill(first+' [data-comments]','Keep the paper texture')
  click('#apply-mockup-comments');request('POST',session+'/alert/accept',{})
  wait("!document.querySelector('#apply-mockup-comments').disabled && document.querySelector('#mockup-concepts [data-description]')?.value==="+json.dumps(authored),60)
  current=studio.get(project)['workflow']['mockup_design']['board']['cards'][0]
  assert current['scene']['description']==authored and current['candidate']['scene']['image_prompt']==authored
  assert js('return document.querySelector('+json.dumps(first+' [data-comments]')+').value')=='Keep the paper texture'
  unsaved=authored+' · תיקון שטרם נשמר';fill(first+' [data-description]',unsaved);fill(first+' [data-comments]','Do not lose this comment')
  js("window.originalFetch=window.fetch;window.fetch=async(...args)=>{if(String(args[0]).includes('/actions/apply_mockup_comments')){window.fetch=window.originalFetch;return new Response(JSON.stringify({error:'Synthetic rejected edit'}),{status:409,headers:{'Content-Type':'application/json'}});}return window.originalFetch(...args);}")
  count_before_error=len(scene_port.images);click('#apply-mockup-comments');request('POST',session+'/alert/accept',{})
  wait("!document.querySelector('#apply-mockup-comments').disabled && document.querySelector('#message').textContent.includes('Synthetic rejected edit')")
  wait("document.querySelector('#mockup-concepts [data-description]')?.value==="+json.dumps(unsaved))
  assert js('return document.querySelector('+json.dumps(first+' [data-comments]')+').value')=='Do not lose this comment'
  assert len(scene_port.images)==count_before_error
  fill(first+' [data-description]',authored)
  fill(first+' [data-comments]','Preserve this exact composition')
  click('#save-mockup-notes');wait("!document.querySelector('#save-mockup-notes').disabled")
  # Concept locking approves existing pixels and retains notes for refinement.
  assert not js('return document.querySelector('+json.dumps(first+' [data-lock]')+').disabled')
  click(first+' [data-lock]');wait("document.querySelector('#mockup-concepts [data-card] [data-lock]').getAttribute('aria-pressed')==='true'")
  locked=studio.get(project)['workflow']['mockup_design']['board']['cards'][0]
  request('POST',session+'/url',{'url':'http://127.0.0.1:'+str(http.server_port)+'/'})
  wait("document.querySelectorAll('#projects button').length === 1");click('#projects button')
  wait("document.querySelector('#mockup-concepts [data-card] [data-lock]')?.getAttribute('aria-pressed')==='true'")
  assert js('return document.querySelector('+json.dumps(first+' [data-description]')+').disabled')
  # Delete an unlocked card, then add/plan a replacement. Locked pixels never repeat.
  click('#mockup-concepts [data-card]:nth-child(2) [data-remove]');wait("document.querySelectorAll('#mockup-concepts [data-card]').length === 4")
  click('#add-mockup-card');wait("document.querySelectorAll('#mockup-concepts [data-card]').length === 5")
  fill('#mockup-concepts [data-card]:nth-child(2) [data-comments]','Overhead spread, no family portrait')
  before=len(scene_port.images);click('#apply-mockup-comments');request('POST',session+'/alert/accept',{})
  wait("document.querySelectorAll('#mockup-concepts [data-card] img').length === 5 && !document.querySelector('#apply-mockup-comments').disabled",60)
  assert len(scene_port.images)==before+4
  assert studio.get(project)['workflow']['mockup_design']['board']['cards'][0]['candidate']==locked['candidate']
  for i in range(1,5):
   selector='#mockup-concepts [data-card]:nth-child('+str(i+1)+') [data-lock]';click(selector);wait('document.querySelector('+json.dumps(selector)+').getAttribute("aria-pressed")==="true"')
  js("document.querySelector('#mockups-panel').scrollIntoView({block:'start'})");screenshot('02b-mockup-concept-board-mobile')
  assert js("return document.querySelectorAll('#mockup-model-buttons button').length") == 2
  click('#mockup-model-buttons button:last-of-type')
  # Model buttons are inside hint wrappers, so select the second directly.
  js("document.querySelectorAll('#mockup-model-buttons button')[1].click()")
  before=len(scene_port.images);click('#final-mockup-scenes');request('POST',session+'/alert/accept',{})
  wait("!document.querySelector('#mockup-final-warning').hidden && !document.querySelector('#mockup-concepts [data-card] [data-lock]').disabled",60)
  assert js("return document.querySelector('#mockups-panel').classList.contains('final-refinement')")
  assert js('return document.querySelector('+json.dumps(first+' [data-description]')+') === null')
  assert len(scene_port.edits if args.targeted_refinement else [image for image in scene_port.images if image['final']])==5
  assert studio.get(project)['workflow']['mockup_design']['board']['final_model_id']=='fixture-b'
  for i in range(4):
   selector='#mockup-concepts [data-card]:nth-child('+str(i+1)+') [data-lock]';click(selector);wait('document.querySelector('+json.dumps(selector)+').getAttribute("aria-pressed")==="true"')
  fill('#mockup-concepts [data-card]:nth-child(5) [data-comments]','Fix fingers; keep approved composition')
  if args.targeted_refinement:
   from test_partial_refinement import ZERO_PLAN
   original_correction=scene_port.mockup_correction
   scene_port.mockup_correction=lambda *a,**k:json.loads(json.dumps(ZERO_PLAN))
  previous_image=js("return document.querySelector('#mockup-concepts [data-card]:nth-child(5) img').src")
  click('#apply-mockup-comments');request('POST',session+'/alert/accept',{})
  if args.targeted_refinement:
   wait("document.querySelector('#mockup-concepts [data-card]:nth-child(5) [data-region]') !== null && document.querySelector('#apply-mockup-comments').disabled",60)
   assert 'Edit rectangle' in js("return document.querySelector('#mockup-concepts [data-card]:nth-child(5)').textContent")
   before_selection=len(scene_port.edits);click('#mockup-concepts [data-card]:nth-child(5) [data-region]')
   js("document.querySelector('#mockup-concepts [data-card]:nth-child(5) .edit-region-host img').scrollIntoView({block:'center'})")
   r=js("const i=document.querySelector('#mockup-concepts [data-card]:nth-child(5) .edit-region-host img'),r=i.getBoundingClientRect(),ratio=i.naturalWidth/i.naturalHeight,w=Math.min(r.width,r.height*ratio),h=w/ratio;return {left:r.left+(r.width-w)/2,top:r.top+(r.height-h)/2,width:w,height:h}")
   x1=round(r['left']+r['width']*.2);y1=round(r['top']+r['height']*.2);x2=round(r['left']+r['width']*.55);y2=round(r['top']+r['height']*.6)
   request('POST',session+'/actions',{'actions':[{'type':'pointer','id':'region-mouse','parameters':{'pointerType':'mouse'},'actions':[{'type':'pointerMove','duration':0,'x':x1,'y':y1},{'type':'pointerDown','button':0},{'type':'pointerMove','duration':300,'x':x2,'y':y2},{'type':'pointerUp','button':0}]}]})
   wait("document.querySelector('#mockup-concepts [data-card]:nth-child(5)').dataset.editBox !== 'null' && !document.querySelector('#apply-mockup-comments').disabled")
   assert studio.get(project)['workflow']['mockup_design']['board']['cards'][4].get('edit_box')
   assert len(scene_port.edits)==before_selection
   def no_more_planning(*a,**k):raise AssertionError('Manual area must reuse the completed interpretation')
   scene_port.mockup_correction=no_more_planning
   click('#apply-mockup-comments');request('POST',session+'/alert/accept',{})
  wait("!document.querySelector('#mockup-concepts [data-card]:nth-child(5) [data-lock]').disabled",60)
  wait("document.querySelector('#mockup-concepts [data-card]:nth-child(5) img').src!=="+json.dumps(previous_image)+" && document.querySelector('#mockup-concepts [data-card]:nth-child(5) img').naturalWidth>0",60)
  assert len(scene_port.edits if args.targeted_refinement else [image for image in scene_port.images if image['final']])==6
  assert 'Fix fingers' in (studio.get(project)['workflow']['mockup_design']['board']['cards'][4]['comments'] if args.targeted_refinement else scene_port.images[-1]['comments'])
  click('#mockup-concepts [data-card]:nth-child(5) [data-lock]');wait("!document.querySelector('#approve-mockups').disabled")
  assert js('return document.documentElement.scrollWidth <= window.innerWidth')
  js("document.querySelector('#mockups-panel').scrollIntoView({block:'start'})");screenshot('02c-lifestyle-final-mobile')
  request('POST',session+'/window/rect',{'width':1440,'height':1000});js("document.querySelector('#mockups-panel').scrollIntoView({block:'start'})");screenshot('02d-lifestyle-final-desktop')
  request('POST',session+'/window/rect',{'width':390,'height':844})

 click('#approve-mockups');wait("!document.querySelector('#listing-panel').hidden")
 click('#generate-copy');request('POST',session+'/alert/accept',{})
 wait("document.querySelector('#listing-title-1').value.length > 0")
 original_description=js("return document.querySelector('#listing-description').value")
 fill('#listing-description','bad');js("document.querySelector('#copy-proof').checked=true");click('#approve-copy')
 wait("document.querySelector('#message').textContent.length>0 && !document.querySelector('#save-copy').disabled");assert studio.get(project)['phase']=='listing_review'
 fill('#listing-description',original_description)
 fill('#listing-title-1','Edited printable holiday collection');js("document.querySelector('#copy-proof').checked=true");click('#approve-copy')
 wait("!document.querySelector('#customer-download').hidden",60);screenshot('03-delivery-mobile')
 current=studio.get(project);assert current['phase']=='approved';assert current['workflow']['listing']['copy']['titles'][0]=='Edited printable holiday collection'
 assert current['listing']['etsy_api_called'] is False
 assert js('return document.documentElement.scrollWidth <= window.innerWidth')
 (OUT/'browser-results.json').write_text(json.dumps({'passed':True,'checks':(['Hebrew RTL mobile interface','Passive saved-brief library','Three representative candidates','Explicit print specification and production consent','Five individual printable units','Large preview','Three exact-artwork mockups','Mockup zero positions preserved','Saving preset retains edits','Saved preset can be adjusted','Mockup settings survive browser reload','Explicit automatic layout restores centered readable composition','Model copy and unsaved-edit preservation on final approval','Invalid copy edit cannot approve old saved copy','Customer and Studio downloads gated by approvals','No horizontal mobile overflow','Etsy publishing blocked'] if not args.lifestyle else ['Hebrew RTL mobile interface','Passive saved-brief library','Three representative candidates','Explicit print specification and production consent','Five individual printable units','Large preview','Legacy cards hidden in guided mode','Model copy and unsaved-edit preservation on final approval','Invalid copy edit cannot approve old saved copy','Customer and Studio downloads gated by approvals','No horizontal mobile overflow','Etsy publishing blocked']),'lifestyle_checks':(['Per-card editable prompts and comments','Authored description reaches generation and survives planner rewriting','Rejected action preserves unsaved description and comment','Concept lock retains pending notes without regeneration','Persistent lock survives reload','Locked scene skipped by planner and generator','Delete and add preserve history','New cards planned and sketched by one action','Single finalization action starts consented professional round','Distinct expensive-loop warning','Final composition fields read-only','Locked finals skip paid refinements','Latest per-card touch-up reaches final provider','Responsive card layout without overflow','Disabled action explanation visible','Incomplete provider payload logged to console','Known failed plan resumed by explicit apply','Dynamic final-model picker binds the chosen image route','Lightweight progress polling without overlapping requests','Full project refresh at action and card-completion boundaries','Updated final image appears without browser refresh',*(['Invalid correction region is visible','Mouse-selected correction region saves without inference','Manual region reuses saved interpretation'] if args.targeted_refinement else [])] if args.lifestyle else []),'targeted_refinement':args.targeted_refinement,'intake_checks':['Pasted reference resized','Real file input resized','Mutually exclusive and toggled sample votes'],'synthetic_images':True,'paid_calls':0,'etsy_calls':0},indent=2)+'\n')
 print('BROWSER PASS')
except Exception:
 if session:
  try:
   screenshot('failure');(OUT/'browser-error.json').write_text(json.dumps({'message':js("return document.querySelector('#message').textContent"),'body':js('return document.body.innerText')},ensure_ascii=False,indent=2))
  except Exception:pass
 raise
finally:
 if session:
  try:request('DELETE',session)
  except Exception:pass
 driver.terminate();driver.wait(timeout=10);http.shutdown();http.server_close()
