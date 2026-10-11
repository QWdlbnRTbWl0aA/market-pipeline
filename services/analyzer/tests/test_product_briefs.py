"""Synthetic model and SMTP tests; no paid calls or external email."""
import copy
import hashlib
import json
import tempfile
from pathlib import Path
import unittest
from email.parser import BytesParser
from email import policy
from unittest.mock import patch
from analyzer.product_briefs import cross_checks,request,validate
from analyzer.research import build_evidence,model_request,analyze
from analyzer.email_delivery import prepare,review,send,configuration,password,smtp_exports,render_html
from test_production import dataset,POLICY,Selection

class ProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def payload(self):
        data=dataset();data['metadata']['source_run_id']='20261009T205115Z-f9f24ac4f5c3'
        data['provenance']['artifact_directory']=str(self.root/'artifacts'/data['metadata']['source_run_id'])
        report=analyze('market_insights',data,self.root,{'research':POLICY},Selection(),Selection(),Selection())
        return {'service':'market_insights','status':'completed','source_run_id':data['metadata']['source_run_id'],'source':data['provenance'],'report':report}
    def config(self):return {'sender':'research@example.com','recipient':'test@example.com','host':'smtp.example.com','port':465,'tls':'ssl','username':'fixture','secret_file':str(self.root/'secret'),'outbox_root':str(self.root/'outbox'),'saved_artifacts_root':str(self.root/'artifacts')}
    def prepared(self):
        p=self.root/'report.json';p.write_text(json.dumps(self.payload()));return prepare(p,self.config())
    def test_shop_sales_changes_never_become_listing_sales(self):
        d=dataset();d['metadata']['source_run_id']='current';r=d['records'][0];r['observed_at']='2026-10-11T00:00:00+00:00'
        r['metrics']=[{'scope':'listing','name':'views','value':40}]
        d['metadata']['shops']=[{'shop_id':r['seller_id'],'transaction_sold_count':120,'observed_at':r['observed_at']}]
        d['metadata']['history']={'related_observations':[{'run_id':'prior','shops':[{'shop_id':r['seller_id'],'transaction_sold_count':100,'observed_at':'2026-10-09T00:00:00+00:00'}],
            'listings':[{'id':r['id'],'observed_at':'2026-10-09T00:00:00+00:00','metrics':[{'scope':'listing','name':'views','value':20}]}]}]}
        c=cross_checks(d,{'listing_ids':[r['id']]});e=c['examples'][0]
        self.assertEqual(e['shop_sales_intervals'][0]['change'],20)
        self.assertEqual(e['listing_engagement_intervals']['views'][0]['per_day'],10)
        self.assertIsNone(e['listing_sales']);self.assertEqual(c['demand_status'],'unverified')
    def test_negative_counters_and_short_windows_have_no_daily_rate(self):
        d=dataset();r=d['records'][0];r['observed_at']='2026-10-11T01:00:00+00:00';r['metrics']=[{'scope':'listing','name':'views','value':10}]
        d['metadata']['history']={'related_observations':[{'run_id':'prior','shops':[],'listings':[{'id':r['id'],'observed_at':'2026-10-11T00:00:00+00:00','metrics':[{'scope':'listing','name':'views','value':20}]}]}]}
        delta=cross_checks(d,{'listing_ids':[r['id']]})['examples'][0]['listing_engagement_intervals']['views'][0]
        self.assertTrue(delta['reset_or_correction']);self.assertIsNone(delta['per_day'])
    def test_foreign_citations_and_fake_demand_in_product_briefs_rejected(self):
        d=dataset();c=build_evidence(d,POLICY)['candidates'];response=Selection().generate(request(model_request('market_insights',build_evidence(d,POLICY),c)))
        v=json.loads(response.text);validate(v,c)
        v['items'][0]['product_brief']['deliverables'][0]['evidence_ids']=['foreign']
        with self.assertRaises(ValueError):validate(v,c)
        v=json.loads(response.text);v['items'][0]['product_brief']['customer_job']['text']='Guaranteed high demand'
        with self.assertRaises(ValueError):validate(v,c)
    def test_generation_only_prepares_and_does_not_read_smtp_secret(self):
        with patch('analyzer.email_delivery.password',side_effect=AssertionError('Secret read')),patch('smtplib.SMTP_SSL',side_effect=AssertionError('Network')):
            directory=self.prepared();self.assertTrue((directory/'message.eml').exists());self.assertFalse((directory/'review.json').exists())

    def test_concise_email_has_html_plain_text_and_evidence_attachment(self):
        directory=self.prepared()
        message=BytesParser(policy=policy.default).parsebytes((directory/'message.eml').read_bytes())
        plain=message.get_body(preferencelist=('plain',)).get_content()
        markup=message.get_body(preferencelist=('html',)).get_content()
        self.assertIn('Who:',plain);self.assertIn('Why this idea:',plain);self.assertIn('Samples:',plain)
        self.assertEqual(plain.count('demand is not yet verified'),1)
        self.assertNotIn('Cumulative listing engagement medians',plain)
        self.assertIn('Who it is for',markup);self.assertIsNotNone(message['Date'])
        evidence=next(x for x in message.iter_attachments() if x.get_filename()=='product-brief-evidence.json')
        self.assertEqual(json.loads(evidence.get_payload(decode=True))['service'],'market_insights')

    def test_untrusted_email_text_cannot_inject_html_or_sample_links(self):
        payload=self.payload()
        row=payload['report']['recommendations'][0]
        row['product_brief']['product_concept']='<script>fixture</script>'
        row['evidence_excerpts'][0]['title']='<img src=x onerror="fixture">'
        markup=render_html(payload)
        self.assertNotIn('<script>',markup);self.assertNotIn('<img src=x',markup)
        self.assertIn('&lt;script&gt;',markup)
        row['evidence_excerpts'][0]['listing_id']='javascript:alert(1)'
        with self.assertRaises(ValueError):render_html(payload)
    def test_unreviewed_or_modified_email_cannot_send(self):
        directory=self.prepared()
        with patch('analyzer.email_delivery.password',side_effect=AssertionError('Secret read')):
            with self.assertRaises(FileNotFoundError):send(directory,self.config())
            digest=hashlib.sha256((directory/'message.eml').read_bytes()).hexdigest();review(directory,digest,'fixture','Synthetic review')
            (directory/'message.eml').write_bytes(b'mutated')
            with self.assertRaises(ValueError):send(directory,self.config())
    def test_reviewed_delivery_once_and_unknown_outcome_not_retried(self):
        directory=self.prepared();digest=hashlib.sha256((directory/'message.eml').read_bytes()).hexdigest();review(directory,digest,'fixture','Synthetic review')
        calls=[]
        class SMTP:
            def __init__(self,*a,**k):calls.append('connect')
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def login(self,*a):pass
            def sendmail(self,*a):calls.append('send');return {}
        with patch('analyzer.email_delivery.password',return_value='fixture'):
            self.assertEqual(send(directory,self.config(),SMTP)['status'],'accepted_by_smtp')
            send(directory,self.config(),SMTP)
        self.assertEqual(calls,['connect','send'])
        (directory/'delivery.json').write_text(json.dumps({'status':'unknown'}))
        with patch('analyzer.email_delivery.password',side_effect=AssertionError('Secret read')):
            self.assertEqual(send(directory,self.config(),SMTP)['status'],'unknown')
    def test_changed_recipient_is_rejected_before_credentials(self):
        directory=self.prepared();digest=hashlib.sha256((directory/'message.eml').read_bytes()).hexdigest();review(directory,digest,'fixture','Synthetic review')
        with patch('analyzer.email_delivery.password',side_effect=AssertionError('Secret read')):
            with self.assertRaises(ValueError):send(directory,{**self.config(),'recipient':'other@example.com'})

    def test_gmail_exports_are_parsed_without_execution_and_secrets_not_projected(self):
        file=self.root/'gmail_smtp.env'
        content="export SMTP_HOST=smtp.gmail.com\nexport SMTP_PORT=465\nexport SMTP_TLS=ssl\nexport SMTP_USER=test@example.com\nexport SMTP_FROM=test@example.com\nexport SMTP_TO=test@example.com\nexport SMTP_PASSWORD='fixture password'\n"
        file.write_text(content);file.chmod(0o600)
        public=configuration(file);self.assertNotIn('SMTP_PASSWORD',public);self.assertEqual(password(file),'fixturepassword')
        file.chmod(0o644)
        with self.assertRaises(ValueError):configuration(file)
        file.chmod(0o600);file.write_text(content+'export ETSY_API_KEY=fixture\n')
        with self.assertRaises(ValueError):configuration(file)
        with patch('analyzer.email_delivery.os.open',side_effect=AssertionError('Collector credential opened')):
            with self.assertRaises(ValueError):configuration(self.root/'etsy.env')

    def test_smtp_aliases_require_explicit_recipient_and_reject_duplicates(self):
        file=self.root/'gmail_smtp.env'
        content="export SMTP_HOST=smtp.gmail.com\nexport SMTP_PORT=587\nexport SMTP_STARTTLS=true\nexport SMTP_USERNAME=test@example.com\nexport MAIL_FROM=test@example.com\nexport SMTP_PASSWORD=fixture\n"
        file.write_text(content);file.chmod(0o600)
        self.assertEqual(smtp_exports(file)['SMTP_TLS'],'starttls')
        with self.assertRaises(ValueError):configuration(file)
        file.write_text(content+'export SMTP_TO=test@example.com\n')
        self.assertEqual(configuration(file)['recipient'],'test@example.com')
        file.write_text(content+'export SMTP_USER=other@example.com\n')
        with self.assertRaises(ValueError):smtp_exports(file)
