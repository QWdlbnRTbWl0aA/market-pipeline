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
        http('POST',base+'/window/rect',{'width':390,'height':844});http('POST',base+'/url',{'url':url})
        wait("document.querySelector('#brief-form') !== null");click('#new-project')
        assert js("return document.documentElement.lang === 'he' && document.documentElement.dir === 'rtl'")
        fill('[name=concept]','בדיקת חנוכה')
        for name,value in {'audience':'משפחות','purpose':'לקשט בית לחנוכה','deliverables':'חנוכייה\nסביבונים\nסופגניות\nכד שמן\nנרות','visual_direction':'אקוורל ידני רך'}.items():fill('[name='+name+']',value)
        js("""const canvas=document.createElement('canvas');canvas.width=900;canvas.height=600;
        const context=canvas.getContext('2d');context.fillStyle='blue';context.fillRect(0,0,900,600);
        const bytes=Uint8Array.from(atob(canvas.toDataURL('image/png').split(',')[1]),c=>c.charCodeAt(0));
        const transfer=new DataTransfer();transfer.items.add(new File([bytes],'reference.png',{type:'image/png'}));
        document.querySelector('#reference-paste').onpaste({clipboardData:transfer,preventDefault:()=>{}});""")
        wait("document.querySelectorAll('#reference-previews img').length === 1")
        data=js("const canvas=document.createElement('canvas');canvas.width=750;canvas.height=500;return canvas.toDataURL('image/png').split(',')[1]")
        reference=output/'upload-fixture.png';reference.write_bytes(base64.b64decode(data))
        element=http('POST',base+'/element',{'using':'css selector','value':'#reference-files'})['element-6066-11e4-a52e-4f735466cecf']
        http('POST',base+'/element/'+element+'/value',{'text':str(reference),'value':list(str(reference))})
        wait("document.querySelectorAll('#reference-previews img').length === 2")
        checks.append('Simulated clipboard input and real file upload are resized before intake')
        click('#brief-form button[type=submit]')
        wait("document.querySelector('#phase').textContent === 'בריף שמור · מוכן לבחירה'")
        assert state()['rounds']==[]
        assert js("return !document.querySelector('#library-brief').hidden")
        assert js("return document.querySelector('#library-source').textContent.includes('concept')")
        js("document.querySelector('#library-brief details').open=true")
        assert js("return document.documentElement.scrollWidth <= window.innerWidth")
        capture('00-passive-library-mobile')
        fill('#batch-comments','stale comment from another project')
        click('#start-sketches');alert();ready()
        assert state()['interaction'][-1]['payload']['comments']==''
        checks.append('Library intake stays idle until explicit Start sketches consent')
        wait("document.querySelectorAll('.sample').length === 3")
        saved=state();assert saved['reference_images'][0]['width']<=512 and saved['reference_images'][0]['bytes']<=80000
        checks.append('Hebrew RTL intake, fixed compressed reference and three sketches')
        assert js("return document.querySelectorAll('.candidate-comment').length === 0")
        assert js("return document.querySelectorAll('#batch-comments').length === 1")
        assert js("return document.querySelector('.controls').getBoundingClientRect().right <= document.querySelector('.visual').getBoundingClientRect().left")
        assert js("return document.querySelector('#budget').getBoundingClientRect().height > 0 && document.querySelector('#budget').textContent.includes('$1')")
        assert js("return document.querySelector('#provider-status').textContent.includes('mock')")
        assert js("return document.querySelector('#round-info').textContent.includes('סבב 1')")
        revision=saved['revision'];click('#samples .sample:nth-child(1) .accept')
        assert js("return document.querySelector('#samples .sample:nth-child(1) .accept').getAttribute('aria-pressed') === 'true'")
        click('#samples .sample:nth-child(1) .reject')
        assert js("return document.querySelector('#samples .sample:nth-child(1) .accept').getAttribute('aria-pressed') === 'false' && document.querySelector('#samples .sample:nth-child(1) .reject').getAttribute('aria-pressed') === 'true'")
        click('#samples .sample:nth-child(1) .reject')
        assert js("return document.querySelector('#samples .sample:nth-child(1) .reject').getAttribute('aria-pressed') === 'false'")
        click('#samples .sample:nth-child(1) .accept')
        checks.append('Visible budget/provider and exclusive toggleable vote selection')
        assert js("return document.querySelector('#regenerate').disabled")
        assert state()['revision']==revision
        click('#samples .sample:nth-child(2) .reject');click('#samples .sample:nth-child(3) .accept')
        fill('#batch-comments','לשמור את הצבע הכחול ולהגדיל את הרווחים')
        checks.append('All three like/dislike decisions plus one shared comment before submission')
        old=state()['rounds'][-1]['id'];click('#regenerate')
        wait("!document.querySelector('#generation').hidden")
        capture('01-batch-spinner-mobile')
        wait("document.querySelector('.sample').dataset.candidate !== "+json.dumps(saved['rounds'][-1]['candidates'][0]['id']));ready()
        assert js("return document.querySelector('#round-info').textContent.includes('סבב 2')")
        assert len(state()['rounds'][-1]['candidates'])==3
        assert len(state()['rounds'][-2]['reviews'])==3
        assert state()['rounds'][-2]['comments']=='לשמור את הצבע הכחול ולהגדיל את הרווחים'
        checks.append('Whole batch regenerates three previews; shared feedback and accepted history persist')
        http('POST',base+'/refresh',{});wait("document.querySelector('#projects button') !== null");click('#projects button');ready()
        assert state()['accepted_samples']
        js("document.querySelector('.extra').open=true");click('#reasoning')
        wait("!document.querySelector('#reasoning-log').hidden && document.querySelector('#reasoning-log').textContent.length > 0")
        assert js("return document.documentElement.scrollWidth <= window.innerWidth")
        capture('02-three-sketch-mobile')
        checks.append('Refresh, development understanding log and mobile width')
        click('#final');click('#consent');click('#settings-form button[type=submit]')
        wait("document.querySelectorAll('.sample').length === 3 && !document.querySelector('#expensive').hidden");ready()
        click('#samples .sample:nth-child(1) .accept');click('#samples .sample:nth-child(2) .reject');click('#samples .sample:nth-child(3) .reject')
        click('#approve');wait("!document.querySelector('#approved').hidden")
        download=js("return document.querySelector('#download').href")
        with opener.open(download,timeout=3) as response:(output/'approved-product.zip').write_bytes(response.read())
        assert state()['listing']['etsy_api_called'] is False
        checks.append('Professional three-sample loop, final approval, download and Etsy block')
        click('#new-project')
        assert js("return !document.querySelector('[name=concept]').required")
        fill('[name=concept]','רעיון ללא סגנון')
        click('#brief-form button[type=submit]')
        wait("document.querySelector('#phase').textContent === 'בריף שמור · מוכן לבחירה'")
        assert state()['brief']['visual_direction']=='' and state()['rounds']==[]
        js("document.querySelector('#api-details').open=true")
        click('#load-payloads')
        wait("document.querySelector('#api-payload').textContent.includes('אין בקשות')")
        checks.append('Optional style remains ready and passive; mock payload panel truthfully reports no API calls')
        report={'passed':True,'checks':checks,'providers':'mock','etsy_calls':0,'paid_calls':0}
        (output/'browser-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    except Exception:
        (output/'ui-error.json').write_text(json.dumps({'message':js("return document.querySelector('#message').textContent"),'reference_previews':js("return document.querySelectorAll('#reference-previews img').length")}))
        capture('failure');raise
    finally:http('DELETE',base)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8096/');parser.add_argument('--driver',default='http://127.0.0.1:4446')
    parser.add_argument('--output',required=True);args=parser.parse_args();run(args.url,args.driver,args.output)
