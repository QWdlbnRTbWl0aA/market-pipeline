#!/usr/bin/env python3
"""Offline browser smoke with actual image adapter and synthetic HTTP transport.

Uses only a temporary fixture server and installed Firefox/geckodriver.
No credential files, paid provider, Etsy, email or live Studio state are accessed.
"""
import argparse,base64,json,pathlib,shutil,socket,subprocess,sys,threading,time,urllib.request
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=pathlib.Path(args.output).resolve()
if OUT.is_relative_to(ROOT):raise ValueError('Browser artifacts must stay outside source control')
OUT.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(ROOT/'services/studio'),str(ROOT/'services/studio/tests')]
from test_direct_edit import Flow,COMMENT
from studio_service.model_roles import ModelRoles
from studio_service.server import Server
fixture=Flow();fixture.setUp();fixture.final_ready();studio=fixture.studio;project=fixture.project
roles=ModelRoles({'openai':['mockup_planning','mockup_sketches','mockup_final_images']},available=lambda p:True)
roles.register_final('fixture-direct','Synthetic direct image model','openai',studio.mockup_finals,tier='top_tier',capability='image_edit');studio.model_roles=roles
http=Server(('127.0.0.1',0),studio);http.start_worker();threading.Thread(target=http.serve_forever,daemon=True).start()
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
log=(OUT/'geckodriver.log').open('w');driver=subprocess.Popen([shutil.which('geckodriver') or 'geckodriver','--host','127.0.0.1','--port',str(port)],stdout=log,stderr=subprocess.STDOUT)
BASE='http://127.0.0.1:'+str(port);session=None;opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(method,path,value=None):
    req=urllib.request.Request(BASE+path,data=None if value is None else json.dumps(value).encode(),method=method,headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=60) as response:return json.load(response).get('value')
def js(code):return request('POST',session+'/execute/sync',{'script':code,'args':[]})
def wait(code,timeout=35):
    end=time.time()+timeout
    while time.time()<end:
        if js('return '+code):return
        time.sleep(.15)
    raise AssertionError(code+'; '+str(js("return document.querySelector('#message').textContent")))
def click(selector):js('document.querySelector('+json.dumps(selector)+').click()')
try:
    for _ in range(100):
        try:request('GET','/status');break
        except OSError:time.sleep(.1)
    data=request('POST','/session',{'capabilities':{'alwaysMatch':{'browserName':'firefox','moz:firefoxOptions':{'args':['-headless'],'prefs':{'network.proxy.type':0}}}}});session='/session/'+data['sessionId']
    request('POST',session+'/window/rect',{'width':390,'height':844})
    request('POST',session+'/url',{'url':'http://127.0.0.1:'+str(http.server_port)+'/'})
    wait("document.querySelectorAll('#projects button').length===1");click('#projects button')
    wait("document.querySelectorAll('#mockup-concepts [data-card]').length===1 && document.querySelectorAll('#generated-images-list img').length===1")
    assert js("return document.querySelector('#mockup-concepts [data-description]')===null && document.querySelector('#mockup-concepts [data-prompt]')===null")
    assert js("return document.querySelector('#budget').textContent.includes('$25')")
    assert js("return !document.querySelector('#generated-images-panel').closest('details')")
    js("document.querySelector('#mockup-concepts [data-comments]').value="+json.dumps(COMMENT))
    click('#apply-mockup-comments');request('POST',session+'/alert/accept',{})
    wait("document.querySelectorAll('#generated-images-list img').length===2 && !document.querySelector('#apply-mockup-comments').disabled")
    assert fixture.wires[-1]['prompt']==COMMENT
    js("document.querySelector('#generated-images-panel').scrollIntoView()")
    wait("document.querySelectorAll('#generated-images-list img')[0].complete && document.querySelectorAll('#generated-images-list img')[0].naturalWidth>0")
    click('#mockup-concepts [data-lock]');request('POST',session+'/alert/accept',{})
    wait("document.querySelector('#mockup-concepts [data-lock]').getAttribute('aria-pressed')==='true'")
    assert studio.get(project)['workflow']['mockup_design']['board']['cards'][0]['candidate']['human_approval']['visual_and_product_review_confirmed']
    click('#mockup-concepts [data-lock]');wait("document.querySelector('#mockup-concepts [data-lock]').getAttribute('aria-pressed')==='false'")
    # Return a valid image with wrong dimensions: job fails but raw result stays visible.
    def wrong_size(req,timeout):
        value=json.loads(req.data);value['size']='512x512'
        return fixture.wire(urllib.request.Request(req.full_url,data=json.dumps(value).encode()),timeout)
    studio.mockup_finals.transport=wrong_size
    js("document.querySelector('#mockup-concepts [data-comments]').value='Keep the vehicle printing'")
    click('#apply-mockup-comments');request('POST',session+'/alert/accept',{})
    wait("!document.querySelector('#failure').hidden && document.querySelectorAll('#generated-images-list img').length===3")
    js("document.querySelector('#generated-images-panel').scrollIntoView()")
    wait("[...document.querySelectorAll('#generated-images-list img')].every(i=>i.complete&&i.naturalWidth>0)")
    assert js('return document.documentElement.scrollWidth<=window.innerWidth')
    (OUT/'mobile.png').write_bytes(base64.b64decode(request('GET',session+'/screenshot')))
    (OUT/'results.json').write_text(json.dumps({'passed':True,'checks':['Hidden final scene controls','Budget visible','Original output gallery open','Exact Hebrew correction','No-refresh successful output','Explicit human approval and unlock','No-refresh output despite dimension failure','All returned images previewable','Mobile layout'],'paid_calls':0},indent=2)+'\n')
    print('PASS: direct-edit browser smoke; nine checks; no paid calls')
finally:
    if session:
        try:request('DELETE',session)
        except Exception:pass
    driver.terminate();driver.wait(timeout=10);log.close();http.shutdown();http.server_close();fixture.doCleanups()
