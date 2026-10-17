"""Manual dashboard → saved collection → both analyzers → Product → two mock emails."""
import copy
import datetime as dt
from email.parser import BytesParser
from email import policy as email_policy
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
for service in ('collector','analyzer','product','controller','common'):sys.path.insert(0,str(ROOT/'services'/service))
sys.path.insert(0,str(ROOT/'services'/'analyzer'/'tests'))
sys.path.insert(0,str(ROOT/'services'/'product'/'tests'))
from test_flow import FixtureBrief
from test_opportunities import AllSelections
from etsy_app.server import App,handler
from etsy_app.core import config,FetchResult,atomic_json
from analyzer.services import run_cycle
from analyzer.automatic_mail import deliver as send_analysis
from product_service.server import server as product_server
from pipeline_control.server import server as control_server
from pipeline_mail import read
from test_mail_outboxes import SMTP,SECRET,POLICY


class CompletePipeline(unittest.TestCase):
    def test_dashboard_query_to_exact_analysis_and_studio_brief_emails_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);SMTP.sent=[]
            app=App({**config(),'source':'api','limit':None,'capture_images':False},root/'collector')
            collection=app.store.collect;calls=[]
            def source(url,timeout,headers):
                calls.append(url);route=urlparse(url)
                if route.path.endswith('/listings/active'):
                    value={'count':9,'results':[{'listing_id':i,'url':'https://www.etsy.com/listing/'+str(i)+'/synthetic-fixture','shop_id':(i-1)//3+1,'title':'Printable amber geometry','description':'Original printable wall art','tags':['amber geometry'],'listing_type':'download','views':150,'num_favorers':30,'taxonomy_id':1,
                        'original_creation_timestamp':1600000000,'creation_timestamp':1600000000,'state':'active','price':{'amount':1200,'divisor':100,'currency_code':'USD'}} for i in range(1,10)]}
                else:value={'shop_id':int(route.path.rsplit('/',1)[-1]),'shop_name':'Fixture shop','listing_active_count':3,'transaction_sold_count':140,'created_timestamp':1600000000}
                return FetchResult(200,json.dumps(value).encode(),'application/json',{'x-limit-per-second':'2','x-limit-per-day':'5000','x-remaining-today':'4990'})
            app.store.collect=lambda settings,niches,trigger:collection(settings,niches,trigger,fetcher=source)
            http=ThreadingHTTPServer(('127.0.0.1',0),handler(app));threading.Thread(target=http.serve_forever,daemon=True).start()
            self.addCleanup(http.server_close);self.addCleanup(http.shutdown)
            with patch.dict(os.environ,{'ETSY_API_KEY':'fixture-key','ETSY_API_SECRET':'fixture-secret'}):
                request=urllib.request.Request('http://127.0.0.1:'+str(http.server_port)+'/api/collect',data=json.dumps({'parameters':{'keywords':'printable','limit':None,'shop_ids':[],'exclude_fetched_listings':False,'exclude_fetched_shops':False}}).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=3) as response:self.assertEqual(response.status,202)
                app.active_thread.join(timeout=20)
            self.assertEqual(app.job['status'],'success');self.assertEqual(len(calls),4)
            run_id=app.job['run_id'];snapshot=json.loads((app.store.runs/run_id/'snapshot.json').read_text());finished=dt.datetime.fromisoformat(snapshot['finished_at'])
            for index,days in enumerate((14,7)):
                old=copy.deepcopy(snapshot);old['run_id']='history-'+str(days);stamp=(finished-dt.timedelta(days=days)).isoformat();old['finished_at']=stamp
                for query in old['queries']:
                    for row in query['listings']:row.update(observed_at=stamp,listing_views=100+index*20,listing_favorites=10+index*10)
                for shop in old['shops']:shop['shop'].update(observed_at=stamp,transaction_sold_count=100+index*20)
                atomic_json(app.store.runs/old['run_id']/'snapshot.json',old);atomic_json(app.store.runs/old['run_id']/'dqa.json',old['dqa'])
            product_config=json.loads((ROOT/'config'/'product.example.json').read_text());product_config['mail']=POLICY
            path=root/'product.json';path.write_text(json.dumps(product_config))
            product=product_server(root/'product',0,path,brief_model=FixtureBrief());threading.Thread(target=product.serve_forever,daemon=True).start()
            self.addCleanup(product.server_close);self.addCleanup(product.shutdown);self.addCleanup(product.stop_worker)
            control=control_server({'data_root':str(root/'control'),'saved_runs_root':str(app.store.runs),'analyzer_output_root':str(root/'analyzer'),'product_data_root':str(root/'product'),'collector_url':'http://127.0.0.1:'+str(http.server_port),
                                   'control_auth_file':str(root/'unused-auth'),'execution_enabled':False,'poll_seconds':1},0)
            threading.Thread(target=control.serve_forever,daemon=True).start();self.addCleanup(control.server_close);self.addCleanup(control.shutdown);self.addCleanup(control.stop_worker)
            settings={'saved_runs_root':str(app.store.runs),'output_root':str(root/'analyzer'),'model':'fixture','sample_size':3,'research':{'min_group_listings':3,'max_candidates':12,'cheap_price_reference':{'USD':5}},'opportunities':{'enabled':True},
                      'paid':{'enabled':True,'cheap_model':'fixture','final_model':'fixture'},'mail':POLICY,'endpoints':{'market_insights':'http://127.0.0.1:'+str(product.server_port)+'/market-insights','search_refinement':'http://127.0.0.1:'+str(control.server_port)+'/search-refinement'}}
            with patch('analyzer.adapters.openai.OpenAIModel',return_value=AllSelections()),patch('product_service.automatic_mail.tick',side_effect=lambda r,p:__import__('pipeline_mail').tick(r,p,smtp_factory=SMTP,key_provider=lambda:SECRET)):
                results=run_cycle(settings,run_id,{s:AllSelections() for s in settings['endpoints']});self.assertTrue(all(r['analysis_status']=='completed' and r['delivery_status']=='delivered' for r in results))
                send_analysis(settings,smtp_factory=SMTP,key_provider=lambda:SECRET)
                deadline=time.monotonic()+10
                while len(SMTP.sent)<2 and time.monotonic()<deadline:time.sleep(.1)
                self.assertEqual(len(SMTP.sent),2)
                run_cycle(settings,run_id,{s:AllSelections() for s in settings['endpoints']});send_analysis(settings,smtp_factory=SMTP,key_provider=lambda:SECRET);time.sleep(1)
                self.assertEqual(len(SMTP.sent),2)
            messages=[BytesParser(policy=email_policy.default).parsebytes(row[2]) for row in SMTP.sent]
            analysis=next(m for m in messages if str(m['Subject']).startswith('Market analysis'))
            attachment=next(analysis.iter_attachments()).get_payload(decode=True)
            directory=Path(next(r for r in results if r['service']=='market_insights')['directory'])
            self.assertEqual(attachment,(directory/'outbound-wire.json').read_bytes());self.assertTrue(json.loads(attachment)['report']['recommendations'])
            message=next(m for m in messages if str(m['Subject']).startswith('Studio briefs'))
            brief=next(a for a in message.iter_attachments() if a.get_filename()=='studio-brief-01.json').get_payload(decode=True)
            actual=next((root/'product'/'studio-outbox').glob('*/product-01/product.json')).read_bytes();self.assertEqual(brief,actual)
            self.assertIn(json.loads(actual)['vision'],message.get_body(preferencelist=('plain',)).get_content())
            self.assertFalse((root/'studio').exists())
            evidence=os.environ.get('PIPELINE_TEST_ARTIFACTS')
            if evidence:
                destination=Path(evidence).resolve()
                if destination.is_relative_to(ROOT):raise ValueError('Test artifacts must stay outside source')
                destination.mkdir(parents=True,exist_ok=True)
                (destination/'analyzer-message.eml').write_bytes(analysis.as_bytes(policy=email_policy.SMTP))
                (destination/'product-message.eml').write_bytes(message.as_bytes(policy=email_policy.SMTP))
                (destination/'analysis-product-wire.json').write_bytes(attachment);(destination/'studio-brief.json').write_bytes(actual)
                for name,email in (('analyzer',analysis),('product',message)):
                    (destination/(name+'-preview.txt')).write_text(email.get_body(preferencelist=('plain',)).get_content())
                    (destination/(name+'-preview.html')).write_text(email.get_body(preferencelist=('html',)).get_content())
                (destination/'result.json').write_text(json.dumps({'fixture':True,'manual_trigger':True,'mock_smtp_deliveries':2,'live_etsy_calls':0,'paid_calls':0,'external_smtp_calls':0,
                    'analyzer_attachment_exact':True,'studio_brief_attachment_exact':True,'repeated_trigger_deliveries':0,'studio_invoked':False},indent=2))


if __name__=='__main__':unittest.main()
