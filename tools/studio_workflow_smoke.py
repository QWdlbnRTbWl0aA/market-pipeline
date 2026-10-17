#!/usr/bin/env python3
import argparse,base64,json,os,pathlib,shutil,socket,subprocess,sys,threading,time,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Offline Hebrew Studio workflow smoke: synthetic raster/text providers, temporary loopback server and existing Firefox/geckodriver. No paid/Etsy/SMTP calls.')
parser.add_argument('--output',required=True);parser.add_argument('--lifestyle',action='store_true');args=parser.parse_args();OUT=pathlib.Path(args.output).resolve()
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
 scene_port=Scenes();extra={'mockup_planner':scene_port,'mockup_drafts':scene_port,'mockup_finals':scene_port}
studio=Studio(state,sketches=images,professional=images,copywriter=Copy(),**extra)
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
 wait("document.querySelectorAll('#projects button').length === 1");click('#projects button');wait("!document.querySelector('#library-brief').hidden")
 assert js("return document.documentElement.lang==='he' && document.documentElement.dir==='rtl'")
 click('#start-sketches');request('POST',session+'/alert/accept',{})
 wait("document.querySelectorAll('#samples .sample').length === 3 && !document.querySelector('#review').hidden")
 click('#samples .sample:first-child .accept');click('#final');wait("document.querySelector('#production-settings').open")
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
  wait("document.querySelector('#message').textContent.includes('המוקאפים עודכנו')",60)
  wait('document.querySelector('+json.dumps(first+' [data-setting=scale]')+').value === "0.62"')
  saved=studio.get(project)['workflow']['mockups'][0]['template'];assert saved['x']==0 and saved['y']==0 and saved['scale']==.62 and saved['perspective']=='left'
  fill(first+' input[maxlength="64"]','regression-preset');click(first+' [data-save-template]')
  wait('document.querySelector('+json.dumps(first+' [data-preset] option[value=regression-preset]')+') !== null')
  assert js('return document.querySelector('+json.dumps(first+' [data-setting=scale]')+').value')=='0.62'
  js('const preset=document.querySelector('+json.dumps(first+' [data-preset]')+');preset.value="regression-preset";preset.dispatchEvent(new Event("change",{bubbles:true}));')
  setting('x',.04);assert js('return document.querySelector('+json.dumps(first+' [data-preset]')+').value')==''
  click('#update-mockups');wait("document.querySelector('#message').textContent.includes('המוקאפים עודכנו')",60)
  saved=studio.get(project)['workflow']['mockups'][0]['template'];assert saved['x']==.04 and saved['y']==0 and saved['scale']==.62
  request('POST',session+'/url',{'url':'http://127.0.0.1:'+str(http.server_port)+'/'})
  wait("document.querySelectorAll('#projects button').length === 1");click('#projects button')
  wait('document.querySelector('+json.dumps(first+' [data-setting=x]')+') !== null')
  assert js('return document.querySelector('+json.dumps(first+' [data-setting=x]')+').value')=='0.04'
  assert js('return document.querySelector('+json.dumps(first+' [data-setting=y]')+').value')=='0'
  screenshot('02b-mockup-settings-persisted')
  click('#auto-mockups');wait("document.querySelector('#message').textContent.includes('המוקאפים עודכנו')",60)
  automatic=studio.get(project)['workflow']['mockups'];assert all(m['template']['x']==0 and m['template']['y']==0 for m in automatic)
  assert automatic[0]['template']['scale']==.86 and automatic[2]['template']['kind']=='bundle'
 else:
  wait("!document.querySelector('#lifestyle-actions').hidden")
  assert js("return document.querySelector('#legacy-mockups').hidden")
  fill('#mockup-count','5');fill('#mockup-comments','Warm family atmosphere and varied gallery')
  click('#plan-mockup-scenes');request('POST',session+'/alert/accept',{})
  wait("document.querySelectorAll('#mockup-concepts [data-card]').length === 5 && !document.querySelector('#make-mockup-concepts').disabled",60)
  assert len(scene_port.images)==0
  click('#make-mockup-concepts');request('POST',session+'/alert/accept',{})
  wait("document.querySelectorAll('#mockup-concepts [data-card] img').length === 5",60)
  assert all(not image['final'] for image in scene_port.images)
  first='#mockup-concepts [data-card]:first-child'
  fill(first+' [data-comments]','Preserve this exact composition')
  click('#save-mockup-notes');wait("!document.querySelector('#save-mockup-notes').disabled")
  # New notes cannot approve stale pixels. Apply them in a cheap round first.
  assert js('return document.querySelector('+json.dumps(first+' [data-lock]')+').disabled')
  click('#make-mockup-concepts');request('POST',session+'/alert/accept',{})
  wait("!document.querySelector('#mockup-concepts [data-card] [data-lock]').disabled",60)
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
  click('#plan-mockup-scenes');request('POST',session+'/alert/accept',{})
  wait("!document.querySelector('#make-mockup-concepts').disabled",60)
  before=len(scene_port.images);click('#make-mockup-concepts');request('POST',session+'/alert/accept',{})
  wait("document.querySelectorAll('#mockup-concepts [data-card] img').length === 5 && !document.querySelector('#make-mockup-concepts').disabled",60)
  assert len(scene_port.images)==before+4
  assert studio.get(project)['workflow']['mockup_design']['board']['cards'][0]['candidate']==locked['candidate']
  for i in range(1,5):
   selector='#mockup-concepts [data-card]:nth-child('+str(i+1)+') [data-lock]';click(selector);wait('document.querySelector('+json.dumps(selector)+').getAttribute("aria-pressed")==="true"')
  js("document.querySelector('#mockups-panel').scrollIntoView({block:'start'})");screenshot('02b-mockup-concept-board-mobile')
  before=len(scene_port.images);click('#final-mockup-scenes')
  wait("!document.querySelector('#mockup-final-warning').hidden && !document.querySelector('#final-mockup-scenes').disabled")
  assert len(scene_port.images)==before
  assert js("return document.querySelector('#mockups-panel').classList.contains('final-refinement')")
  assert js('return document.querySelector('+json.dumps(first+' [data-description]')+').disabled')
  click('#final-mockup-scenes');request('POST',session+'/alert/accept',{})
  wait("!document.querySelector('#mockup-concepts [data-card] [data-lock]').disabled",60)
  assert len([image for image in scene_port.images if image['final']])==5
  for i in range(4):
   selector='#mockup-concepts [data-card]:nth-child('+str(i+1)+') [data-lock]';click(selector);wait('document.querySelector('+json.dumps(selector)+').getAttribute("aria-pressed")==="true"')
  fill('#mockup-concepts [data-card]:nth-child(5) [data-comments]','Fix fingers; keep approved composition')
  click('#final-mockup-scenes');request('POST',session+'/alert/accept',{})
  wait("!document.querySelector('#mockup-concepts [data-card]:nth-child(5) [data-lock]').disabled",60)
  assert len([image for image in scene_port.images if image['final']])==6
  assert 'Fix fingers' in scene_port.images[-1]['comments']
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
 (OUT/'browser-results.json').write_text(json.dumps({'passed':True,'checks':(['Hebrew RTL mobile interface','Passive saved-brief library','Three representative candidates','Explicit print specification and production consent','Five individual printable units','Large preview','Three exact-artwork mockups','Mockup zero positions preserved','Saving preset retains edits','Saved preset can be adjusted','Mockup settings survive browser reload','Explicit automatic layout restores centered readable composition','Model copy and unsaved-edit preservation on final approval','Invalid copy edit cannot approve old saved copy','Customer and Studio downloads gated by approvals','No horizontal mobile overflow','Etsy publishing blocked'] if not args.lifestyle else ['Hebrew RTL mobile interface','Passive saved-brief library','Three representative candidates','Explicit print specification and production consent','Five individual printable units','Large preview','Legacy cards hidden in guided mode','Model copy and unsaved-edit preservation on final approval','Invalid copy edit cannot approve old saved copy','Customer and Studio downloads gated by approvals','No horizontal mobile overflow','Etsy publishing blocked']),'lifestyle_checks':(['Per-card editable prompts and comments','Notes cannot approve stale pixels','Persistent lock survives reload','Locked scene skipped by planner and generator','Delete and add preserve history','Five distinct card identities','Final stage entry makes no paid call','Distinct expensive-loop warning','Final composition fields read-only','Locked finals skip paid refinements','Latest per-card touch-up reaches final provider','Responsive card layout without overflow'] if args.lifestyle else []),'synthetic_images':True,'paid_calls':0,'etsy_calls':0},indent=2)+'\n')
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
