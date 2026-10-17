"""Durable SMTP admission tests. Fake SMTP only; no external mail or keys."""
import base64
from email.parser import BytesParser
from email import policy as email_policy
import json
import os
from pathlib import Path
import smtplib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services'/'common'))
from pipeline_mail import enqueue,tick,read,write,credentials,policy

POLICY={'enabled':True,'recipients':['team@example.com'],'max_attempts':3,'retry_seconds':10}
SECRET={'SMTP_HOST':'smtp.example.com','SMTP_PORT':'465','SMTP_TLS':'ssl','SMTP_USER':'fixture','SMTP_PASSWORD':'fixture','SMTP_FROM':'research@example.com','SMTP_TO':'fallback@example.com'}


class SMTP:
    sent=[]
    def __init__(self,*a,**kwargs):pass
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def login(self,*a):pass
    def sendmail(self,sender,recipients,body):self.sent.append((sender,recipients,body));return {}


class MailTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);SMTP.sent=[]
    def queue(self,cycle='cycle-one',stage='analyzer'):
        return enqueue(self.root,stage,cycle,'Fixture report','Focused report','<p>Focused report</p>',[('exact.json',b'{"exact":true}\n')],POLICY)
    def deliver(self,**kw):return tick(self.root,POLICY,smtp_factory=SMTP,key_provider=lambda:SECRET,timestamp=100,**kw)
    def test_disabled_never_reads_credentials_or_sends(self):
        self.assertIsNone(enqueue(self.root,'analyzer','x','subject','text','html',[],{'enabled':False}))
        self.assertEqual(tick(self.root,{},key_provider=lambda:self.fail('Key read')),[])
    def test_once_per_stage_cycle_restart_and_exact_attachment(self):
        folder=self.queue();self.queue();self.deliver();self.deliver();self.assertEqual(len(SMTP.sent),1)
        self.assertEqual(read(folder/'delivery.json')['status'],'accepted_by_smtp')
        message=BytesParser(policy=email_policy.default).parsebytes(SMTP.sent[0][2])
        self.assertEqual(next(message.iter_attachments()).get_payload(decode=True),b'{"exact":true}\n')
        self.assertIn('Focused report',message.get_body(preferencelist=('plain',)).get_content())
        self.queue(stage='product');self.deliver();self.assertEqual(len(SMTP.sent),2)
    def test_content_collision_cannot_send_second_email(self):
        self.queue()
        with self.assertRaises(ValueError):enqueue(self.root,'analyzer','cycle-one','Other','text','html',[],POLICY)
    def test_transient_connect_failure_retries_to_finite_limit(self):
        folder=self.queue();calls=[]
        def fail(*a,**kw):calls.append(1);raise TimeoutError()
        for instant in (100,105,110,120,150):tick(self.root,POLICY,smtp_factory=fail,key_provider=lambda:SECRET,timestamp=instant)
        state=read(folder/'delivery.json');self.assertEqual(len(calls),3);self.assertEqual(state['status'],'retries_exhausted');self.assertTrue(state['explicit_recovery_required'])
    def test_permanent_auth_failure_does_not_retry(self):
        folder=self.queue()
        class Auth(SMTP):
            def login(self,*a):raise smtplib.SMTPAuthenticationError(535,b'fixture')
        tick(self.root,POLICY,smtp_factory=Auth,key_provider=lambda:SECRET,timestamp=100)
        tick(self.root,POLICY,key_provider=lambda:self.fail('Key loaded again'),timestamp=200)
        self.assertEqual(read(folder/'delivery.json')['status'],'permanent_failure')
    def test_unknown_data_outcome_never_automatically_replays(self):
        folder=self.queue()
        class Unknown(SMTP):
            def sendmail(self,*a):raise TimeoutError()
        tick(self.root,POLICY,smtp_factory=Unknown,key_provider=lambda:SECRET,timestamp=100)
        tick(self.root,POLICY,key_provider=lambda:self.fail('Unknown outcome retried'),timestamp=200)
        self.assertEqual(read(folder/'delivery.json')['status'],'unknown')
        self.assertTrue((folder/'message.eml').exists())
    def test_explicit_route_change_is_held_before_connect(self):
        folder=self.queue()
        tick(self.root,POLICY,smtp_factory=lambda *a,**k:(_ for _ in ()).throw(TimeoutError()),key_provider=lambda:SECRET,timestamp=100)
        tick(self.root,POLICY,smtp_factory=lambda *a,**k:self.fail('New route connected'),key_provider=lambda:{**SECRET,'SMTP_FROM':'changed@example.com'},timestamp=200)
        self.assertEqual(read(folder/'delivery.json')['status'],'permanent_failure')
    def test_credential_exports_are_literal_and_api_files_never_loaded(self):
        file=self.root/'gmail_smtp.env';file.write_text('\n'.join('export '+k+'='+v for k,v in SECRET.items()));file.chmod(0o600)
        with patch.dict(os.environ,{'PIPELINE_SMTP_CREDENTIAL_FILE':str(file)}):self.assertEqual(credentials()['SMTP_FROM'],'research@example.com')
        file.write_text(file.read_text()+'\nexport ETSY_API_KEY=fixture')
        with patch.dict(os.environ,{'PIPELINE_SMTP_CREDENTIAL_FILE':str(file)}),self.assertRaises(ValueError):credentials()
        with patch.dict(os.environ,{'PIPELINE_SMTP_CREDENTIAL_FILE':str(self.root/'etsy.env')}),patch('pipeline_mail.os.open',side_effect=AssertionError('API credential opened')),self.assertRaises(ValueError):credentials()
    def test_rendered_units_only_mail_stages_get_smtp(self):
        sys.path.insert(0,str(ROOT/'deploy'));from unit_templates import SPECS,render
        for service in SPECS:
            self.assertNotIn('gmail_smtp.env',render(service))
            self.assertEqual('LoadCredential=gmail_smtp.env' in render(service,mail=True),service in ('market-analyst','product'))
    def test_additive_upgrade_preserves_paid_ledger_and_user_settings(self):
        sys.path.insert(0,str(ROOT/'deploy'));from upgrade_config import plan
        for name in ('analyzer','product'):
            value=json.loads((ROOT/'config'/(name+'.example.json')).read_text());value.pop('mail');write(self.root/(name+'.json'),value)
        old=json.loads((self.root/'analyzer.json').read_text());changed=plan(self.root,True,['team@example.com'])
        self.assertEqual(changed['analyzer']['after']['paid'],old['paid']);self.assertTrue(changed['product']['after']['mail']['enabled'])
        self.assertEqual(json.loads((self.root/'analyzer.json').read_text()),old)
    def test_product_openai_upgrade_uses_existing_policy_without_calls_or_writes(self):
        sys.path.insert(0,str(ROOT/'deploy'));from upgrade_config import plan
        before={}
        for name in ('analyzer','product'):
            value=json.loads((ROOT/'config'/(name+'.example.json')).read_text());write(self.root/(name+'.json'),value);before[name]=value
        ledger=self.root/'budget.json';ledger.write_text('{"reserved":"preserve exact bytes"}')
        with patch('socket.socket.connect',side_effect=AssertionError('Upgrade made a request')):
            changes=plan(self.root,enable_product_openai=True)
        brief=changes['product']['after']['briefing'];self.assertEqual(brief['provider'],'openai')
        self.assertEqual(brief['paid']['ledger_root'],before['analyzer']['paid']['ledger_root'])
        self.assertEqual(brief['paid']['total_usd'],before['analyzer']['paid']['total_usd'])
        self.assertEqual(changes['analyzer']['after']['paid'],before['analyzer']['paid'])
        self.assertEqual(changes['product']['after']['studio_delivery'],before['product']['studio_delivery'])
        self.assertEqual(json.loads((self.root/'product.json').read_text()),before['product'])
        self.assertEqual(ledger.read_text(),'{"reserved":"preserve exact bytes"}')
    def test_message_tampering_and_quit_failure_do_not_create_duplicate_sends(self):
        folder=self.queue()
        class QuitFailure(SMTP):
            def __exit__(self,*a):raise smtplib.SMTPServerDisconnected('Fixture after accepted DATA')
        tick(self.root,POLICY,smtp_factory=QuitFailure,key_provider=lambda:SECRET,timestamp=100)
        self.assertEqual(read(folder/'delivery.json')['status'],'accepted_by_smtp');self.deliver();self.assertEqual(len(SMTP.sent),1)
        second=self.queue('cycle-two')
        tick(self.root,POLICY,smtp_factory=lambda *a,**k:(_ for _ in ()).throw(TimeoutError()),key_provider=lambda:SECRET,timestamp=100)
        (second/'message.eml').write_bytes(b'Changed message')
        tick(self.root,POLICY,smtp_factory=lambda *a,**k:self.fail('Tampered mail sent'),key_provider=lambda:SECRET,timestamp=200)
        self.assertEqual(read(second/'delivery.json')['status'],'permanent_failure')


if __name__=='__main__':unittest.main()
