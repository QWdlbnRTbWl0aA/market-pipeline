"""Independent, optional SMTP outboxes. No model/source clients or shell sourcing."""
import base64
from email.message import EmailMessage
from email import policy as email_policy
from email.utils import formatdate
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import smtplib
import ssl
import stat
import tempfile
import time

DEFAULT={'enabled':False,'recipients':[],'max_attempts':5,'retry_seconds':60}


def policy(value=None):
    value={**DEFAULT,**(value or {})}
    if set(value)!=set(DEFAULT) or type(value['enabled']) is not bool:raise ValueError('Invalid mail policy')
    if type(value['max_attempts']) is not int or not 1<=value['max_attempts']<=100 or type(value['retry_seconds']) is not int or not 1<=value['retry_seconds']<=86400:raise ValueError('Invalid SMTP retry bounds')
    if not isinstance(value['recipients'],list) or len(value['recipients'])>20 or len(set(value['recipients']))!=len(value['recipients']):raise ValueError('Unique bounded email recipients required')
    for recipient in value['recipients']:address(recipient)
    return value


def address(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',value):raise ValueError('Invalid mail address')
    return value


def write(path,value,preserve=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.mail-',dir=path.parent)
    try:
        if preserve:
            info=path.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):raise ValueError('Regular configuration required')
            os.fchmod(fd,stat.S_IMODE(info.st_mode))
            if os.fstat(fd).st_uid!=info.st_uid or os.fstat(fd).st_gid!=info.st_gid:os.fchown(fd,info.st_uid,info.st_gid)
        with os.fdopen(fd,'wb') as stream:stream.write(value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode());stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def read(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>20_000_000:raise ValueError('Bounded regular mail artifact required')
    return json.loads(path.read_bytes())


def credentials():
    if any(k.startswith(('ETSY','SMTP_','OPENAI_API_KEY')) for k in os.environ):raise ValueError('Credential-separated mail environment required')
    path=Path(os.environ.get('PIPELINE_SMTP_CREDENTIAL_FILE','/etc/market-pipeline/credentials/gmail_smtp.env'))
    if path.name!='gmail_smtp.env':raise ValueError('Dedicated SMTP file required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode&(stat.S_IWGRP|stat.S_IRWXO) or info.st_size>8192:raise ValueError('Protected bounded SMTP credential required')
        body=os.read(fd,8193).decode()
    finally:os.close(fd)
    values={};aliases={'SMTP_USERNAME':'SMTP_USER','MAIL_FROM':'SMTP_FROM'}
    for line in body.splitlines():
        line=line.strip().removeprefix('export ')
        if not line or line.startswith('#'):continue
        name,separator,value=line.partition('=');name=aliases.get(name,name)
        if name=='SMTP_STARTTLS':name='SMTP_TLS';value='starttls' if value.lower() in ('true','1') else 'ssl' if value.lower() in ('false','0') else ''
        if not separator or name not in {'SMTP_HOST','SMTP_PORT','SMTP_TLS','SMTP_USER','SMTP_FROM','SMTP_PASSWORD','SMTP_TO'} or name in values:raise ValueError('Only unique literal SMTP assignments')
        parts=shlex.split(value)
        if len(parts)!=1 or any(c in parts[0] for c in '$`\r\n'):raise ValueError('Literal SMTP values required')
        values[name]=parts[0]
    if not {'SMTP_HOST','SMTP_PORT','SMTP_TLS','SMTP_USER','SMTP_FROM','SMTP_PASSWORD'}<=set(values):raise ValueError('Complete SMTP configuration required')
    if values['SMTP_TLS'] not in ('ssl','starttls') or not values['SMTP_PORT'].isdigit() or not 1<=int(values['SMTP_PORT'])<=65535 or not re.fullmatch(r'[A-Za-z0-9.-]+',values['SMTP_HOST']):raise ValueError('SMTP host, port and TLS required')
    address(values['SMTP_FROM'])
    if not values['SMTP_PASSWORD']:raise ValueError('SMTP password required')
    if values['SMTP_HOST']=='smtp.gmail.com':values['SMTP_PASSWORD']=values['SMTP_PASSWORD'].replace(' ','')
    return values


def enqueue(root,stage,cycle,subject,text,html,attachments,settings):
    settings=policy(settings)
    if not settings['enabled']:return None
    if not isinstance(cycle,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,99}',cycle):raise ValueError('Stable source cycle required')
    key=hashlib.sha256((stage+':'+cycle).encode()).hexdigest();folder=Path(root)/key;folder.mkdir(parents=True,exist_ok=True)
    if '\n' in subject or '\r' in subject:raise ValueError('Invalid subject')
    files=[]
    for name,body in attachments:
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',name) or not isinstance(body,bytes):raise ValueError('Safe attachment name required')
        files.append({'name':name,'sha256':hashlib.sha256(body).hexdigest(),'content':base64.b64encode(body).decode()})
    document={'stage':stage,'cycle_id':cycle,'subject':subject,'text':text,'html':html,'attachments':files,'mail_policy':settings}
    encoded=json.dumps(document,ensure_ascii=False,sort_keys=True).encode()
    if len(encoded)>15_000_000:raise ValueError('Email exceeds bounded outbox size')
    with (folder/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=folder/'content.json'
        if path.exists():
            old=read(path)
            if {k:v for k,v in old.items() if k!='mail_policy'}!={k:v for k,v in document.items() if k!='mail_policy'}:raise ValueError('Cycle mail content changed; preserve prior delivery')
        else:write(path,document)
        if not (folder/'delivery.json').exists():write(folder/'delivery.json',{'status':'pending','attempts':0,'next_attempt_at':0})
    return folder


def tick(root,settings,smtp_factory=None,key_provider=credentials,timestamp=None,mail_id=None):
    if not policy(settings)['enabled']:return []
    results=[]
    for folder in sorted(Path(root).glob('*')):
        if mail_id is not None and folder.name!=mail_id:continue
        if not folder.is_dir() or folder.is_symlink():continue
        with (folder/'.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:continue
            state=read(folder/'delivery.json');config=read(folder/'content.json')['mail_policy'];instant=timestamp if timestamp is not None else time.time()
            if state['status'] not in ('pending','retry_wait') or instant<state.get('next_attempt_at',0):continue
            if state['attempts']>=config['max_attempts']:state.update(status='retries_exhausted',explicit_recovery_required=True);write(folder/'delivery.json',state);continue
            state.update(status='unknown',total_attempts=state.get('total_attempts',state['attempts'])+1,attempts=state['attempts']+1,at=instant,explicit_recovery_required=True);write(folder/'delivery.json',state)
            data_started=False
            try:
                secret=key_provider();recipients=config['recipients'] or [address(s) for s in re.split(r'[,\s]+',secret.get('SMTP_TO','')) if s]
                if not recipients or len(recipients)>20 or len(set(recipients))!=len(recipients):raise ValueError('Configured SMTP recipients required')
                route={k:secret[k] for k in ('SMTP_HOST','SMTP_PORT','SMTP_TLS','SMTP_FROM','SMTP_USER')}|{'recipients':recipients}
                manifest=folder/'route.json'
                if manifest.exists() and read(manifest)!=route:raise ValueError('Pending mail route changed')
                if not manifest.exists():write(manifest,route)
                content=read(folder/'content.json');message=folder/'message.eml'
                if not message.exists():
                    msg=EmailMessage();msg['From']=secret['SMTP_FROM'];msg['To']=', '.join(recipients);msg['Subject']=content['subject'];msg['Date']=formatdate(usegmt=True);msg['Message-ID']='<'+folder.name+'@market-pipeline.invalid>'
                    msg.set_content(content['text']);msg.add_alternative(content['html'],subtype='html')
                    for attachment in content['attachments']:
                        body=base64.b64decode(attachment['content'],validate=True)
                        if hashlib.sha256(body).hexdigest()!=attachment['sha256']:raise ValueError('Attachment changed')
                        msg.add_attachment(body,maintype='application',subtype='json',filename=attachment['name'])
                    write(message,msg.as_bytes(policy=email_policy.SMTP))
                body=message.read_bytes()
                if len(body)>20_000_000:raise ValueError('SMTP message exceeds bound')
                checksum=hashlib.sha256(body).hexdigest();saved_hash=folder/'message-sha256.json'
                if saved_hash.exists() and read(saved_hash)['sha256']!=checksum:raise ValueError('Prepared message changed')
                if not saved_hash.exists():write(saved_hash,{'sha256':checksum})
                state['message_sha256']=hashlib.sha256(body).hexdigest();write(folder/'delivery.json',state)
                factory=smtp_factory or (smtplib.SMTP_SSL if secret['SMTP_TLS']=='ssl' else smtplib.SMTP)
                options={'timeout':20}
                if secret['SMTP_TLS']=='ssl':options['context']=ssl.create_default_context()
                with factory(secret['SMTP_HOST'],int(secret['SMTP_PORT']),**options) as smtp:
                    if secret['SMTP_TLS']=='starttls':smtp.ehlo();smtp.starttls(context=ssl.create_default_context());smtp.ehlo()
                    smtp.login(secret['SMTP_USER'],secret['SMTP_PASSWORD']);data_started=True
                    refused=smtp.sendmail(secret['SMTP_FROM'],recipients,body)
                    state.update(status='partially_delivered' if refused else 'accepted_by_smtp',refused_recipients=sorted(refused),explicit_recovery_required=bool(refused))
            except Exception as error:
                status=getattr(error,'smtp_code',None)
                known_rejection=isinstance(error,(smtplib.SMTPRecipientsRefused,smtplib.SMTPDataError))
                permanent=isinstance(error,(ValueError,smtplib.SMTPAuthenticationError)) or status is not None and 500<=status<=599
                if state['status'] in ('accepted_by_smtp','partially_delivered'):state['post_accept_error_type']=type(error).__name__
                elif data_started and not known_rejection:state['status']='unknown'
                elif permanent:state['status']='permanent_failure'
                elif state['attempts']>=config['max_attempts']:state['status']='retries_exhausted'
                else:state.update(status='retry_wait',next_attempt_at=instant+config['retry_seconds'])
                state.update(error_type=type(error).__name__,explicit_recovery_required=state['status'] not in ('retry_wait','accepted_by_smtp'))
            write(folder/f'attempt-{state["total_attempts"]:04d}.json',state);write(folder/'delivery.json',state);results.append({'mail_id':folder.name,**state})
            if state['status'] in ('unknown','permanent_failure','retries_exhausted','partially_delivered'):
                write(folder/'failure-event.json',{'event_type':'smtp_delivery_failed','mail_id':folder.name,'stage':read(folder/'content.json')['stage'],
                                                'status':state['status'],'attempts':state['total_attempts'],'explicit_recovery_required':True})
    return results
