#!/usr/bin/env python3
"""Optional local Firefox/WebDriver smoke test; stdlib only, mock Studio only.

Start geckodriver separately. Reports/screenshots must stay outside source.
"""
import argparse
import base64
import json
from pathlib import Path
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]


def run(url, driver, output):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT): raise ValueError('Browser artifacts must be outside source')
    output.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def http(method, path, payload=None):
        request = urllib.request.Request(driver+path, data=json.dumps(payload).encode() if payload is not None else None,
                                         headers={'Content-Type':'application/json'}, method=method)
        try:
            with opener.open(request, timeout=40) as response: result = json.load(response)['value']
        except urllib.error.HTTPError as error:
            result = json.load(error)['value']
        if isinstance(result, dict) and result.get('error'): raise RuntimeError(result['message'])
        return result
    session = http('POST', '/session', {'capabilities':{'alwaysMatch':{'browserName':'firefox', 'moz:firefoxOptions':{'args':['-headless']}}}})['sessionId']
    base = '/session/'+session
    checks = []
    def js(script, *args): return http('POST',base+'/execute/sync',{'script':script,'args':list(args)})
    def click(selector):
        wait("document.querySelector("+json.dumps(selector)+") !== null && !document.querySelector("+json.dumps(selector)+").disabled")
        element=http('POST',base+'/element',{'using':'css selector','value':selector})['element-6066-11e4-a52e-4f735466cecf']
        http('POST',base+'/element/'+element+'/click',{})
    def fill(selector,value):js("const e=document.querySelector(arguments[0]); e.value=arguments[1]; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));",selector,value)
    def wait(expression):
        end=time.monotonic()+15
        while time.monotonic()<end:
            if js('return '+expression):return
            time.sleep(.15)
        raise AssertionError('UI did not reach expected state: '+expression)
    def capture(name):
        (output/(name+'.png')).write_bytes(base64.b64decode(http('GET',base+'/screenshot')))
    def accept():
        fill('.sample .decision','accept_with_comments'); fill('.sample .candidate-comment','Keep spacious writing areas')
    def alert():http('POST',base+'/alert/accept',{})
    try:
        http('POST',base+'/window/rect',{'width':390,'height':844})
        http('POST',base+'/url',{'url':url})
        wait("document.querySelector('#brief-form') !== null")
        fill('[name=concept]','Browser smoke planner '+str(time.time_ns()));click('#brief-form button[type=submit]')
        wait("!document.querySelector('#missing').hidden")
        # Reload the saved project to read its broker receipt, independently of generation polling.
        time.sleep(.6);click('#projects button');wait("document.querySelector('#notification').textContent.includes('recorded')")
        checks.append('Missing brief -> durable human-readable broker message');capture('01-information-mobile')
        click('#edit-brief')
        for name,value in {'audience':'Busy families','purpose':'Plan meals','deliverables':'Weekly grid\nShopping list','visual_direction':'Warm minimal layout'}.items():fill('[name='+name+']',value)
        click('#brief-form button[type=submit]');wait("document.querySelectorAll('.sample').length === 10")
        wait("[...document.querySelectorAll('.sample img')].every(i=>i.complete && i.naturalWidth>0)")
        js("document.querySelector('#samples').scrollIntoView({block:'start'})")
        checks.append('Completed brief -> 10 sketches');capture('02-sketches-mobile')
        assert js('return document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
        assert js("return [...document.querySelectorAll('.sample img')].every(i=>i.complete && i.naturalWidth>0)"), 'Images failed to render'
        accept();fill('#comments','Preserve white space');click('#save');wait("document.querySelector('#message').textContent === 'Saved.'")
        http('POST',base+'/refresh',{});wait("document.querySelector('#projects button') !== null");click('#projects button')
        wait("document.querySelector('.sample .decision')?.value === 'accept_with_comments'")
        checks.append('Feedback persists across browser refresh')
        # Simulate a lost response: save a browser request already accepted by
        # the backend, then refresh. It must restore the same receipt/revision.
        browser_project=js("return document.querySelector('#download').href.split('/')[5]")
        with opener.open(url.rstrip('/')+'/api/projects/'+browser_project,timeout=3) as response: saved_state=json.load(response)['project']
        replay_path='/api/projects/'+browser_project+'/actions/save_feedback'
        replay_payload={'revision':saved_state['revision'],'reviews':saved_state['rounds'][-1]['reviews'],'comments':'Lost-response fixture'}
        replay_key='browser-lost-'+str(time.time_ns())
        req=urllib.request.Request(url.rstrip('/')+replay_path,data=json.dumps(replay_payload).encode(),headers={'Content-Type':'application/json','Idempotency-Key':replay_key})
        with opener.open(req,timeout=3) as response: receipt=json.load(response)['project']
        pending={'serialized':json.dumps({'path':replay_path,'payload':replay_payload},separators=(',',':')),'key':replay_key}
        # JS serialization order must match the saved pending fingerprint.
        js("const pending=arguments[0];pending.serialized=JSON.stringify(JSON.parse(pending.serialized));sessionStorage.setItem('studio-pending',JSON.stringify(pending));",pending)
        http('POST',base+'/refresh',{});wait("document.querySelector('#message').textContent.includes('Previously saved action restored')")
        with opener.open(url.rstrip('/')+'/api/projects/'+browser_project,timeout=3) as response: replayed=json.load(response)['project']
        assert replayed['revision']==receipt['revision'], 'Refresh duplicated completed browser action'
        checks.append('Lost-response request resumes after refresh without duplicate work')
        fill('.sample:nth-child(2) .decision','reject');fill('.sample:nth-child(2) .candidate-comment','Too crowded');click('#next')
        wait("document.querySelector('#round-info').textContent.includes('2 rounds') && document.querySelectorAll('.sample').length === 10")
        checks.append('Accepted + rejected references -> next 10 sketches')
        click('#start-over');alert();wait("document.querySelector('#round-info').textContent.includes('Start 2') && document.querySelectorAll('.sample').length === 10 && !document.querySelector('#review').hidden")
        checks.append('Start over -> archived negative example + fresh 10')
        accept();click('#final');wait("document.querySelector('#settings').open")
        capture('03-settings-mobile');click('#consent');click('#settings-form button[type=submit]')
        wait("document.querySelectorAll('.sample').length === 3 && !document.querySelector('#expensive').hidden")
        checks.append('Final settings + consent -> 3 samples + expensive warning');capture('04-professional-mobile')
        accept();click('#next');alert();wait("document.querySelector('#round-info').textContent.includes('3 rounds') && document.querySelectorAll('.sample').length === 3")
        checks.append('Professional iteration -> another 3 samples')
        click('#back');wait("document.querySelectorAll('.sample').length === 10 && document.querySelector('#expensive').hidden")
        checks.append('Return to sketch area')
        accept();click('#final');click('#consent');click('#settings-form button[type=submit]')
        wait("document.querySelectorAll('.sample').length === 3 && !document.querySelector('#expensive').hidden")
        accept();click('.final-choice input');click('#approve');alert();wait("!document.querySelector('#approved').hidden")
        checks.append('Final human approval -> saved artifact, blocked listing handoff');capture('05-approved-mobile')
        download=js("return document.querySelector('#download').href")
        with opener.open(download,timeout=3) as response:
            assert response.headers['Content-Type']=='application/zip'
            (output/'approved-product.zip').write_bytes(response.read())
        checks.append('Approved ZIP downloaded')
        http('POST',base+'/window/rect',{'width':1440,'height':1000});capture('06-approved-desktop')
        report={'passed':True,'checks':checks,'providers':'mock','etsy_calls':0,'paid_calls':0}
        (output/'browser-results.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
    except Exception:
        capture('failure');raise
    finally:http('DELETE',base)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8096/');parser.add_argument('--driver',default='http://127.0.0.1:4446')
    parser.add_argument('--output',required=True);args=parser.parse_args();run(args.url,args.driver,args.output)
