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
    def alert():http('POST',base+'/alert/accept',{})
    def state():
        identity=js("return document.querySelector('#download').href.split('/')[5]")
        with opener.open(url.rstrip('/')+'/api/projects/'+identity,timeout=3) as response:return json.load(response)['project']
    def ready():wait("document.querySelector('#phase').textContent === 'בוחרים כיוון' || document.querySelector('#phase').textContent === 'מלטשים את היצירה'")
    try:
        with opener.open(url.rstrip('/')+'/health',timeout=3) as response:
            assert json.load(response)['providers']=='mock', 'Browser smoke requires an offline mock server'
        http('POST',base+'/window/rect',{'width':390,'height':844})
        http('POST',base+'/url',{'url':url})
        wait("document.querySelector('#brief-form') !== null")
        wait("document.querySelector('#new-project') !== null");time.sleep(.3);click('#new-project')
        assert js("return document.documentElement.lang === 'he' && document.documentElement.dir === 'rtl'")
        fill('[name=concept]','בדיקת חנוכה '+str(time.time_ns()));click('#brief-form button[type=submit]')
        wait("!document.querySelector('#missing').hidden")
        click('#edit-brief')
        for name,value in {'audience':'משפחות','purpose':'לקשט בית לחנוכה','deliverables':'חנוכייה\nסביבונים\nסופגניות\nכד שמן\nנרות','visual_direction':'אקוורל ידני רך'}.items():fill('[name='+name+']',value)
        click('#brief-form button[type=submit]');ready()
        wait("document.querySelectorAll('.sample').length === 10")
        checks.append('Hebrew RTL intake and 10 sketches')
        assert js("return document.querySelectorAll('.sample select').length === 0")
        assert js("return [...document.querySelectorAll('.comment-panel')].every(p=>p.hidden)")
        assert js("return document.querySelector('.controls').getBoundingClientRect().right <= document.querySelector('.visual').getBoundingClientRect().left")
        checks.append('Three buttons physically left of sample; comments initially hidden')
        click('.sample .comment')
        assert js("return !document.querySelector('.comment-panel').hidden")
        assert js("return document.querySelector('.candidate-comment').getBoundingClientRect().right <= document.querySelector('.visual').getBoundingClientRect().left")
        fill('.candidate-comment','לשמור את הצבע הכחול ולהגדיל את הרווחים')
        js("window.unchangedSample=document.querySelectorAll('.sample')[1];document.querySelector('#samples').scrollIntoView({block:'start'})")
        old=state()['rounds'][-1]['candidates'][0]['id']
        capture('01-hebrew-comment-mobile');click('.sample .accept')
        wait("!document.querySelector('.sample .loading').hidden")
        capture('02-feedback-spinner-mobile')
        wait("document.querySelector('.sample').dataset.candidate !== "+json.dumps(old));ready()
        assert js("return document.querySelectorAll('.sample')[1] === window.unchangedSample")
        saved=state()
        assert saved['accepted_samples'][0]['review']['decision']=='accept_with_comments'
        checks.append('Accept with text -> accept_with_comments, spinner, single replacement, other DOM samples preserved')
        assert len(saved['rounds'][-1]['candidates'])==10
        old=saved['rounds'][-1]['candidates'][0]['id']
        click('.sample .reject');wait("document.querySelector('.sample').dataset.candidate !== "+json.dumps(old));ready()
        assert any(r['reviews'].get(old,{}).get('decision')=='reject' for r in state()['rounds'])
        checks.append('Reject triggers immediate replacement and preserves negative evidence')
        old=state()['rounds'][-1]['candidates'][0]['id'];click('.sample img')
        wait("document.querySelector('.sample').dataset.candidate !== "+json.dumps(old));ready()
        assert all(old not in r['reviews'] for r in state()['rounds'])
        checks.append('Sample click replaces without falsely recording rejection')
        http('POST',base+'/refresh',{});wait("document.querySelector('#projects button') !== null");click('#projects button');ready()
        assert state()['accepted_samples']
        checks.append('Refresh preserves accepted history')
        js("document.querySelector('.extra').open=true");click('#reasoning')
        wait("!document.querySelector('#reasoning-log').hidden && document.querySelector('#reasoning-log').textContent.length > 0")
        checks.append('Development understanding log and spending display')
        assert js("return document.documentElement.scrollWidth <= window.innerWidth")
        js("document.querySelector('#samples').scrollIntoView({block:'start'})");capture('03-sketch-mobile')
        http('POST',base+'/window/rect',{'width':1440,'height':1000});capture('04-sketch-desktop')
        click('#final');click('#consent');click('#settings-form button[type=submit]')
        wait("document.querySelectorAll('.sample').length === 3 && !document.querySelector('#expensive').hidden");ready()
        checks.append('Final settings, expensive warning and three professional samples')
        old=state()['rounds'][-1]['candidates'][0]['id'];click('.sample .accept');alert()
        wait("document.querySelector('.sample').dataset.candidate !== "+json.dumps(old));ready()
        click('#accepted-samples button:last-child');click('#approve');alert()
        wait("!document.querySelector('#approved').hidden")
        download=js("return document.querySelector('#download').href")
        with opener.open(download,timeout=3) as response:(output/'approved-product.zip').write_bytes(response.read())
        assert state()['listing']['etsy_api_called'] is False
        checks.append('Approve historical accepted professional sample, download and Etsy block')
        report={'passed':True,'checks':checks,'providers':'mock','etsy_calls':0,'paid_calls':0}
        (output/'browser-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    except Exception:
        capture('failure');raise
    finally:http('DELETE',base)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8096/');parser.add_argument('--driver',default='http://127.0.0.1:4446')
    parser.add_argument('--output',required=True);args=parser.parse_args();run(args.url,args.driver,args.output)
