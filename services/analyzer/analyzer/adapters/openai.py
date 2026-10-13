"""Bounded Responses API adapter. No SDK retries, tools, redirects or Etsy access."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import urllib.request
import urllib.error
from ..budget import Budget
from ..io import write_json
from ..ports import ModelResponse
from ..security import NoRedirect, assert_clean_environment

RATES={'gpt-6-luna':(0.10,0.50),'gpt-6.1-sol':(2.00,10.00)}

def api_key():
    assert_clean_environment()
    value=os.environ.get('OPENAI_API_KEY')
    if not value:
        path=Path(os.environ.get('PIPELINE_OPENAI_KEY_FILE','/etc/market-pipeline/credentials/openai.env'))
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
                raise ValueError('OpenAI credential file must be owned by this user, regular and mode 600')
            if info.st_size>8192:raise ValueError('OpenAI credential file too large')
            content=os.read(descriptor,8193).decode('utf-8')
            if len(content.encode())>8192:raise ValueError('OpenAI credential file too large')
        finally:os.close(descriptor)
        lines=[line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if len(lines)!=1:raise ValueError('OpenAI credential file must contain only export OPENAI_API_KEY assignment')
        line=lines[0]
        if line.startswith('export '):line=line[7:]
        if not line.startswith('OPENAI_API_KEY='):raise ValueError('Only OPENAI_API_KEY allowed')
        values=shlex.split(line.split('=',1)[1],comments=False)
        if len(values)!=1:raise ValueError('Invalid OpenAI key assignment')
        value=values[0]
    if not value or any(c.isspace() for c in value) or any(c in value for c in '$`'):
        raise ValueError('Invalid OpenAI key value')
    return value

class OpenAIModel:
    def __init__(self, model, policy, transport=None, key_provider=api_key, experiment_id=None):
        if model not in RATES:raise ValueError('Paid model not in priced allowlist')
        self.model,self.policy,self.transport,self.key_provider=model,policy,transport,key_provider
        self.experiment_id=experiment_id
    def generate(self, request):
        if not self.policy['enabled']:raise ValueError('Paid API disabled; no credentials loaded or request sent')
        if request.images:raise ValueError('Paid images disabled until image token budgets implemented; use saved images locally')
        cap=self.policy['max_output_tokens'];rates=RATES[self.model]
        payload={'model':self.model,'instructions':request.system,'input':request.prompt,'store':False,'service_tier':'default',
                 'max_output_tokens':cap,'reasoning':{'effort':'low'},
                 'text':{'format':{'type':'json_schema','name':'analysis','strict':True,'schema':request.schema}}}
        body=json.dumps(payload,ensure_ascii=False).encode()
        # UTF-8 bytes bound token count for text; reserve additional framing overhead.
        bound=len(body)+2048
        if bound>self.policy['max_input_token_bound']:raise ValueError('Paid input bound exceeded; no request sent')
        identity=hashlib.sha256(body).hexdigest();root=Path(self.policy['ledger_root']);cache=root/'responses'/identity
        cache.mkdir(parents=True,exist_ok=True)
        import fcntl
        with (cache/'lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            result_path=cache/'response.json'
            if result_path.exists():
                value=json.loads(result_path.read_text());return ModelResponse(value['text'],{**value['metadata'],'cache_hit':True},value['raw'])
            with (root/'network.lock').open('a') as network_lock:
                fcntl.flock(network_lock,fcntl.LOCK_EX)
                budget=Budget(root,self.policy['daily_usd'],self.policy['total_usd'],self.policy['daily_calls'],self.policy.get('development'))
                budget.reserve(identity,(bound*rates[0]+cap*rates[1])/1e6, self.experiment_id)
                write_json(cache/'request.json',payload) # No headers/key stored.
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
                try:
                    key=self.key_provider() # Admission, including development cap, precedes credential loading.
                    call=urllib.request.Request('https://api.openai.com/v1/responses',data=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
                    with (self.transport or opener.open)(call,timeout=90) as response:
                        raw=response.read(2_000_001)
                    if len(raw)>2_000_000:raise ValueError('Paid response exceeds bound')
                    value=json.loads(raw);usage=value.get('usage')
                    if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('input_tokens','output_tokens')):
                        raise ValueError('Provider usage missing; reservation retained')
                    actual=(usage['input_tokens']*rates[0]+usage['output_tokens']*rates[1])/1e6
                    budget.settle(identity,actual,usage)
                    write_json(cache/'provider-response.json',value)
                    if value.get('status')!='completed':raise ValueError('Paid response incomplete; no automatic retry')
                    chunks=[part['text'] for item in value.get('output',[]) if item.get('type')=='message' for part in item.get('content',[]) if part.get('type')=='output_text']
                    if not chunks:raise ValueError('Paid response empty/refused; no automatic retry')
                    text=''.join(chunks)
                    metadata={'provider':'openai','model':self.model,'response_id':value.get('id'),'usage':usage,'cost_usd':actual,'cache_hit':False}
                    result={'text':text,'metadata':metadata,'raw':value};write_json(result_path,result)
                    return ModelResponse(text,metadata,value)
                except Exception as error:
                    if isinstance(error,urllib.error.HTTPError) and error.code in (401,403,429):
                        try:retry=float(error.headers.get('Retry-After','60'))
                        except (ValueError,TypeError):
                            import datetime as dt
                            from email.utils import parsedate_to_datetime
                            try:retry=(parsedate_to_datetime(error.headers['Retry-After'])-dt.datetime.now(dt.timezone.utc)).total_seconds()
                            except (ValueError,TypeError,KeyError):retry=60
                        import math
                        if not math.isfinite(retry) or retry<0:retry=60
                        budget.provider_block(error.code,retry)
                    # Do not persist provider errors (may echo request headers/content).
                    write_json(cache/'failure.json',{'type':type(error).__name__,'automatic_retry':False})
                    raise RuntimeError('Paid call failed; no automatic retry. See sanitized call ledger.') from None
