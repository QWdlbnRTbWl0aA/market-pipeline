"""Independent reviewed email outbox; model analysis never sends mail directly."""
import argparse
import html
from email.utils import formatdate
from email.message import EmailMessage
from email import policy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import stat
import shlex
from .io import write_json,now
from .security import assert_clean_environment,reject_secrets

TEMPLATE_VERSION='product-email-v3.2-concise'

def address(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',value) or '\r' in value or '\n' in value:raise ValueError('Invalid email address')
    return value

def protected_file(path):
    path=Path(path)
    if path.name not in ('gmail_smtp.env','analyzer-smtp.json'):raise ValueError('Dedicated SMTP credential filename required')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>8192:raise ValueError('SMTP credentials require runtime ownership and mode 600')
        return os.read(descriptor,8193)
    finally:os.close(descriptor)

def smtp_exports(path):
    required={'SMTP_HOST','SMTP_PORT','SMTP_TLS','SMTP_USER','SMTP_FROM','SMTP_PASSWORD'};values={}
    aliases={'SMTP_USERNAME':'SMTP_USER','MAIL_FROM':'SMTP_FROM'}
    for line in protected_file(path).decode().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        if line.startswith('export '):line=line[7:]
        name,separator,value=line.partition('=')
        name=aliases.get(name,name)
        if name=='SMTP_STARTTLS':name='SMTP_TLS'
        if not separator or name not in required|{'SMTP_TO'} or name in values:raise ValueError('Only unique SMTP export assignments allowed')
        parsed=shlex.split(value,comments=False)
        if len(parsed)!=1:raise ValueError('Invalid SMTP assignment')
        result=parsed[0]
        if line.partition('=')[0]=='SMTP_STARTTLS':
            if result.lower() not in {'true','false','1','0'}:raise ValueError('Invalid SMTP_STARTTLS boolean')
            result='starttls' if result.lower() in {'true','1'} else 'ssl'
        values[name]=result
    if not required<=set(values):raise ValueError('Complete SMTP configuration required')
    return values

def configuration(path):
    if Path(path).suffix=='.env':
        exported=smtp_exports(path)
        if 'SMTP_TO' not in exported:raise ValueError('SMTP_TO required; use separate JSON configuration for an explicit recipient')
        if exported['SMTP_HOST']!='smtp.gmail.com' or (exported['SMTP_TLS'],exported['SMTP_PORT']) not in {('ssl','465'),('starttls','587')}:
            raise ValueError('Gmail configuration requires smtp.gmail.com and TLS on 465 or 587')
        if exported['SMTP_USER']!=exported['SMTP_FROM']:raise ValueError('Gmail test sender must match authenticated account')
        value={'host':exported['SMTP_HOST'],'port':int(exported['SMTP_PORT']),'tls':exported['SMTP_TLS'],
            'sender':exported['SMTP_FROM'],'recipient':exported['SMTP_TO'],'username':exported['SMTP_USER'],
            'secret_file':str(Path(path).resolve()),'outbox_root':str(Path(__file__).resolve().parent.parent/'test-output/email-outbox'),
            'saved_artifacts_root':os.environ.get('PIPELINE_SAVED_RUNS_ROOT','/var/lib/market-pipeline/collector/runs')}
    else:value=json.loads(Path(path).read_text())
    reject_secrets(value)
    fields={'host','port','tls','sender','recipient','username','secret_file','outbox_root','saved_artifacts_root'}
    if set(value)!=fields or value['tls'] not in ('ssl','starttls') or type(value['port']) is not int or not 1<=value['port']<=65535:raise ValueError('Explicit SMTP TLS configuration required')
    address(value['sender']);address(value['recipient'])
    artifacts=Path(value['saved_artifacts_root']).resolve();outbox=Path(value['outbox_root']).resolve()
    if artifacts==outbox or artifacts.is_relative_to(outbox) or outbox.is_relative_to(artifacts):raise ValueError('Email outbox must be separate from saved source artifacts')
    if not value['host'] or any(x in value['host'] for x in '/@\r\n'):raise ValueError('Invalid SMTP host')
    return value

def summaries(payload):
    if payload.get('service')!='market_insights' or payload.get('status')!='completed':
        raise ValueError('Successful market report required')
    recommendations=payload['report'].get('recommendations',[])
    if not recommendations or any(not r.get('product_brief') for r in recommendations):
        raise ValueError('Model-generated product briefs required; agent-authored substitution forbidden')
    output=[]
    for r in recommendations:
        brief=r['product_brief']
        # Select existing model prose; never generate a replacement recommendation.
        concept=brief['product_concept'].removeprefix('Design hypothesis: ').strip()
        concept=concept[:1].upper()+concept[1:]
        why=' '.join(re.split(r'(?<=[.!?])\s+',r['rationale'].strip())[:2])
        samples=[]
        for e in r['evidence_excerpts'][:3]:
            identity=e['listing_id'].split(':')[-1]
            if not identity.isdigit():raise ValueError('Invalid sample listing identity')
            image=next((i for i in payload['report'].get('image_audit',[]) if i.get('status')=='attached' and i.get('record_id')==e['listing_id']),None)
            sample_title=e['title'].split('|')[0].strip()
            if len(sample_title)>110:sample_title=sample_title[:107].rsplit(' ',1)[0]+'…'
            samples.append({'title':sample_title,'url':'https://www.etsy.com/listing/'+identity,
                            'image_cid':image['sha256']+'@research' if image else None})
        output.append({'what':concept,'who':brief['intended_customer']['text'],'why':why,
                       'deliverables':[x['text'] for x in brief['deliverables'][:2]],'samples':samples})
    return output


def render(payload):
    lines=['Product ideas for your team','']
    for index,item in enumerate(summaries(payload),1):
        lines += [str(index)+'. '+item['what'],'Who: '+item['who'],'Why this idea: '+item['why'],
                  'Suggested product: '+' '.join(item['deliverables']),'Samples:']
        lines += ['- '+s['title']+' — '+s['url'] for s in item['samples']]
        lines.append('')
    lines+=['These are concepts to validate; demand is not yet verified. Full evidence and implementation checks are in the attached JSON.']
    return '\n'.join(lines)+'\n'


def render_html(payload):
    def escaped(value):return html.escape(str(value),quote=True)
    cards=[]
    for index,item in enumerate(summaries(payload),1):
        samples=[]
        for s in item['samples']:
            picture=('<br><img src="cid:'+escaped(s['image_cid'])+'" alt="Reference sample" style="width:100%;max-width:300px;height:auto;border-radius:8px;margin-top:8px">') if s['image_cid'] else ''
            samples.append('<li style="margin-bottom:14px"><a href="'+escaped(s['url'])+'" style="color:#17634b">'+escaped(s['title'])+'</a>'+picture+'</li>')
        cards.append('<section style="background:#fff;padding:22px;margin:18px 0;border:1px solid #dce4df;border-radius:12px">'
            +'<h2 style="font-size:20px;margin:0 0 16px">'+str(index)+'. '+escaped(item['what'])+'</h2>'
            +'<p><strong>Who it is for</strong><br>'+escaped(item['who'])+'</p>'
            +'<p><strong>Why it was chosen</strong><br>'+escaped(item['why'])+'</p>'
            +'<p><strong>What to make</strong><br>'+escaped(' '.join(item['deliverables']))+'</p>'
            +'<p><strong>Samples</strong></p><ul style="padding-left:18px">'+''.join(samples)+'</ul></section>')
    return '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#f4f7f5;color:#172c24;font:16px/1.55 Arial,sans-serif"><main style="max-width:640px;margin:auto;padding:20px"><h1 style="font-size:26px">Product ideas for your team</h1>'+''.join(cards)+'<p style="font-size:13px;color:#52675b">These are concepts to validate; demand is not yet verified. Full evidence and implementation checks are in the attached JSON.</p></main></body></html>'


def prepare(report_path,config):
    assert_clean_environment();body=Path(report_path).read_bytes();payload=json.loads(body);reject_secrets(payload)
    text=render(payload);identity=hashlib.sha256(body+TEMPLATE_VERSION.encode()+json.dumps({k:config[k] for k in ('sender','recipient')},sort_keys=True).encode()).hexdigest()
    root=Path(config['outbox_root'])/identity;root.mkdir(parents=True,exist_ok=True)
    with (root/'prepare.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if (root/'message.eml').exists():
            manifest=json.loads((root/'manifest.json').read_text())
            if hashlib.sha256((root/'message.eml').read_bytes()).hexdigest()!=manifest['message_sha256']:raise ValueError('Saved email changed; review required')
            return root
        msg=EmailMessage();msg['From']=address(config['sender']);msg['To']=address(config['recipient'])
        msg['Subject']='Product ideas for your team';msg['Date']=formatdate(localtime=False,usegmt=True);msg['Message-ID']='<'+identity+'@market-analyzer.invalid>';msg.set_content(text)
        html_body=render_html(payload);msg.add_alternative(html_body,subtype='html')
        attachments=[]
        artifact=Path(payload['source']['artifact_directory']).resolve()
        if artifact.parent!=Path(config['saved_artifacts_root']).resolve() or artifact.name!=payload['source_run_id']:
            raise ValueError('Email attachments limited to configured saved-artifact root')
        for item in payload['report'].get('image_audit',[]):
            if item.get('status')!='attached':continue
            run=item.get('artifact_run_id') or artifact.name
            if not re.fullmatch(r'[0-9TZ-]+-[a-f0-9]{12}',run):raise ValueError('Unsafe attachment run')
            directory=artifact.parent/run;relative=Path(item['local_path']);path=directory/relative
            if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='images' or directory.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):raise ValueError('Unsafe attachment')
            image=path.read_bytes()
            if len(image)>2_000_000 or hashlib.sha256(image).hexdigest()!=item['sha256']:raise ValueError('Attachment checksum/size failed')
            kind='png' if image.startswith(b'\x89PNG\r\n\x1a\n') else 'jpeg' if image.startswith(b'\xff\xd8\xff') else None
            if kind is None:raise ValueError('Attachment signature failed')
            msg.get_payload()[1].add_related(image,maintype='image',subtype=kind,filename=path.name,disposition='inline',cid='<'+item['sha256']+'@research>')
            attachments.append({'filename':path.name,'sha256':item['sha256']})
        msg.add_attachment(json.dumps(payload,ensure_ascii=False,indent=2).encode(),maintype='application',subtype='json',filename='product-brief-evidence.json')
        eml=msg.as_bytes(policy=policy.SMTP);(root/'message.eml').write_bytes(eml);(root/'preview.txt').write_text(text);(root/'preview.html').write_text(html_body)
        write_json(root/'manifest.json',{'at':now(),'source_report':str(Path(report_path).resolve()),'source_sha256':hashlib.sha256(body).hexdigest(),
            'message_sha256':hashlib.sha256(eml).hexdigest(),'recipient':config['recipient'],'sender':config['sender'],'attachments':attachments,'status':'awaiting_review','template_version':TEMPLATE_VERSION})
        return root

def review(directory,expected_hash,reviewer,notes):
    directory=Path(directory);body=(directory/'message.eml').read_bytes();manifest=json.loads((directory/'manifest.json').read_text())
    if expected_hash!=hashlib.sha256(body).hexdigest() or expected_hash!=manifest['message_sha256']:raise ValueError('Review hash mismatch')
    if not reviewer.strip() or not notes.strip():raise ValueError('Reviewer and actual review notes required')
    write_json(directory/'review.json',{'at':now(),'reviewer':reviewer,'notes':notes,'message_sha256':expected_hash,'approved':True})

def password(path):
    if Path(path).suffix=='.env':
        values=smtp_exports(path)
        # Google displays app passwords in spaced groups; spaces are not part of it.
        value=values['SMTP_PASSWORD'].replace(' ','') if values['SMTP_HOST']=='smtp.gmail.com' else values['SMTP_PASSWORD']
    else:
        secret=json.loads(protected_file(path))
        if set(secret)!={'SMTP_PASSWORD'}:raise ValueError('Expected SMTP_PASSWORD only')
        value=secret['SMTP_PASSWORD']
    if not isinstance(value,str) or not value:raise ValueError('Missing SMTP password')
    return value

def send(directory,config,smtp_factory=None):
    assert_clean_environment();directory=Path(directory)
    with (directory/'delivery.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        receipt=directory/'delivery.json'
        if receipt.exists():return json.loads(receipt.read_text()) # Unknown outcomes never automatically resend.
        manifest=json.loads((directory/'manifest.json').read_text());review_=json.loads((directory/'review.json').read_text());body=(directory/'message.eml').read_bytes()
        digest=hashlib.sha256(body).hexdigest()
        if not review_.get('approved') or digest!=review_['message_sha256'] or digest!=manifest['message_sha256']:raise ValueError('Exact final email must be reviewed before sending')
        if config['sender']!=manifest['sender'] or config['recipient']!=manifest['recipient']:raise ValueError('Recipient/sender changed after review')
        secret=password(config['secret_file'])
        write_json(receipt,{'at':now(),'status':'unknown','message_sha256':digest,'automatic_retry':False})
        try:
            factory=smtp_factory or (smtplib.SMTP_SSL if config['tls']=='ssl' else smtplib.SMTP)
            arguments={'timeout':20}
            if config['tls']=='ssl':arguments['context']=ssl.create_default_context()
            with factory(config['host'],config['port'],**arguments) as smtp:
                if config['tls']=='starttls':smtp.ehlo();smtp.starttls(context=ssl.create_default_context());smtp.ehlo()
                smtp.login(config['username'],secret)
                refused=smtp.sendmail(config['sender'],[config['recipient']],body)
                if refused:raise RuntimeError('SMTP recipient refused')
            result={'at':now(),'status':'accepted_by_smtp','recipient':config['recipient'],'message_sha256':digest,'automatic_retry':False}
        except Exception as error:
            # Responses may contain credentials or provider details; store type only.
            result={'at':now(),'status':'unknown_or_failed','error_type':type(error).__name__,'automatic_retry':False}
        write_json(receipt,result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',default='email-config.json')
    sub=parser.add_subparsers(dest='command',required=True);p=sub.add_parser('prepare');p.add_argument('report')
    p=sub.add_parser('approve');p.add_argument('directory');p.add_argument('--sha256',required=True);p.add_argument('--reviewer',required=True);p.add_argument('--notes',required=True)
    p=sub.add_parser('send');p.add_argument('directory');args=parser.parse_args()
    if args.command=='approve':review(args.directory,args.sha256,args.reviewer,args.notes);print('Exact email approved')
    elif args.command=='prepare':print(prepare(args.report,configuration(args.config)))
    else:print(json.dumps(send(args.directory,configuration(args.config))))

if __name__=='__main__':main()
