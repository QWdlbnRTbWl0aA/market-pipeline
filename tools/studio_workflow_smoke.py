#!/usr/bin/env python3
import argparse,base64,json,os,pathlib,shutil,socket,subprocess,sys,threading,time,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Offline Hebrew Studio workflow smoke: synthetic raster/text providers, temporary loopback server and existing Firefox/geckodriver. No paid/Etsy/SMTP calls.')
parser.add_argument('--output',required=True);args=parser.parse_args();OUT=pathlib.Path(args.output).resolve()
if OUT.is_relative_to(ROOT):raise ValueError('Browser artifacts must stay outside source control')
OUT.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(ROOT/'services/studio'),str(ROOT/'services/studio/tests')]
from studio_service.core import Studio
from studio_service.server import Server
from test_production_workflow import Pixels,Copy

def free():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
state=OUT/('browser-state-'+str(int(time.time())));images=Pixels();studio=Studio(state,sketches=images,professional=images,copywriter=Copy())
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
 wait("document.querySelectorAll('#mockup-files img').length === 3");screenshot('02-mockups-mobile')
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
 (OUT/'browser-results.json').write_text(json.dumps({'passed':True,'checks':['Hebrew RTL mobile interface','Passive saved-brief library','Three representative candidates','Explicit print specification and production consent','Five individual printable units','Large preview','Three exact-artwork mockups','Model copy and unsaved-edit preservation on final approval','Invalid copy edit cannot approve old saved copy','Customer and Studio downloads gated by approvals','No horizontal mobile overflow','Etsy publishing blocked'],'synthetic_images':True,'paid_calls':0,'etsy_calls':0},indent=2)+'\n')
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
