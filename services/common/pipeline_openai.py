"""Priced text-only Responses transport shared by independent services.

No source clients, credential-file discovery or environment loading. The caller
injects its dedicated key reader; admission always precedes invoking that reader.
"""
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error
from dataclasses import dataclass
from pipeline_budget import Budget
from pipeline_mail import write as write_json

RATES={'gpt-6-luna':(.10,.50),'gpt-6.1-sol':(2.,10.),'gpt-6-astra':(10.,50.)}
CACHED_INPUT={'gpt-6-luna':.01,'gpt-6.1-sol':.10,'gpt-6-astra':1.}


def usage_cost(model,usage):
    details=usage.get('input_tokens_details') or {}
    if not isinstance(details,dict):raise ValueError('Invalid provider input accounting')
    cached=details.get('cached_tokens',0);written=details.get('cache_write_tokens',0)
    if any(type(v) is not int or v<0 for v in (cached,written)) or cached+written>usage['input_tokens']:raise ValueError('Invalid provider cache accounting')
    regular=usage['input_tokens']-cached-written;rates=RATES[model]
    return (regular*rates[0]+written*rates[0]*1.25+cached*CACHED_INPUT[model]+usage['output_tokens']*rates[1])/1e6

@dataclass
class ModelRequest:
    system: str
    prompt: str
    schema: dict
    images: tuple = ()

@dataclass
class ModelResponse:
    text: str
    metadata: dict
    raw: dict

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):raise ValueError('Redirects forbidden')

class OpenAIModel:
    def __init__(self, model, policy, transport=None, key_provider=None, experiment_id=None):
        if model not in RATES:raise ValueError('Paid model not in priced allowlist')
        self.model,self.policy,self.transport,self.key_provider=model,policy,transport,key_provider
        self.experiment_id=experiment_id
        if key_provider is None:raise ValueError('Explicit credential reader required')
        effort=policy.get('reasoning_effort','medium' if model!='gpt-6-luna' else 'low')
        if effort not in ('low','medium','high'):raise ValueError('Invalid reasoning effort')
        self.effort=effort
    def generate(self, request):
        if not self.policy['enabled']:raise ValueError('Paid API disabled; no credentials loaded or request sent')
        if request.images:raise ValueError('Paid images disabled until image token budgets implemented; use saved images locally')
        cap=self.policy['max_output_tokens'];rates=RATES[self.model]
        payload={'model':self.model,'instructions':request.system,'input':request.prompt,'store':False,'service_tier':'default',
                 'max_output_tokens':cap,'reasoning':{'effort':self.effort},
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
                budget=Budget(root,self.policy['daily_usd'],self.policy['total_usd'],self.policy['daily_calls'],self.policy.get('development'),self.policy.get('allow_held_unknown',False))
                # Cache writes can cost 1.25x regular input. Reserve the worst
                # case before sending, even when cached reads will cost less.
                budget.reserve(identity,(bound*rates[0]*1.25+cap*rates[1])/1e6, self.experiment_id)
                write_json(cache/'request.json',payload) # No headers/key stored.
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
                try:
                    key=self.key_provider() # Admission, including development cap, precedes credential loading.
                    call=urllib.request.Request('https://api.openai.com/v1/responses',data=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
                    with (self.transport or opener.open)(call,timeout=self.policy.get('timeout_seconds',240)) as response:
                        raw=response.read(2_000_001)
                    if len(raw)>2_000_000:raise ValueError('Paid response exceeds bound')
                    value=json.loads(raw);usage=value.get('usage')
                    if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('input_tokens','output_tokens')):
                        raise ValueError('Provider usage missing; reservation retained')
                    actual=usage_cost(self.model,usage)
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
