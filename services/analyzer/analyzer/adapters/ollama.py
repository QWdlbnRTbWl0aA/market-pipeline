"""Only this adapter knows Ollama's wire format."""
import json
import urllib.error
import urllib.request
from ..ports import ModelResponse


class OllamaModel:
    def __init__(self, model='gemma3:4b', base_url='http://127.0.0.1:11434', timeout=120, transport=None):
        self.model,self.base_url,self.timeout=model,base_url.rstrip('/'),timeout
        self.transport = transport

    def available_models(self):
        with (self.transport or urllib.request.urlopen)(self.base_url+'/api/tags',timeout=5) as response:
            return [m['name'] for m in json.load(response).get('models',[])]

    def generate(self, request):
        payload={'model':self.model,'system':request.system,'prompt':request.prompt,'format':request.schema,'stream':False,
                 'options':{'temperature':0,'num_predict':1400,'num_ctx':8192}}
        if request.images:payload['images']=list(request.images)
        call=urllib.request.Request(self.base_url+'/api/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        try:
            with (self.transport or urllib.request.urlopen)(call,timeout=self.timeout) as response:
                body=response.read(2_000_001)
        except (OSError,urllib.error.URLError) as error:
            raise RuntimeError('Ollama generation unavailable: '+str(error)) from error
        if len(body)>2_000_000:raise ValueError('Ollama response exceeds 2 MB bound')
        result=json.loads(body)
        if not result.get('done') or result.get('done_reason')=='length':raise ValueError('Ollama did not complete generation')
        if not isinstance(result.get('response'),str):raise ValueError('Ollama response text missing')
        return ModelResponse(result['response'],{'provider':'ollama','model':result.get('model',self.model),'endpoint':self.base_url,
                            'prompt_eval_count':result.get('prompt_eval_count'),'eval_count':result.get('eval_count'),
                            'total_duration_ns':result.get('total_duration'),'done_reason':result.get('done_reason')},result)

class VerifiedOllamaModel(OllamaModel):
    """Check availability only when uncached inference is actually needed."""
    def __init__(self,*args,digest=None,**kwargs):super().__init__(*args,**kwargs);self.digest=digest
    def generate(self,request):
        with (self.transport or urllib.request.urlopen)(self.base_url+'/api/tags',timeout=5) as response:
            selected=next((m for m in json.load(response).get('models',[]) if m.get('name')==self.model),None)
        if selected is None or self.digest and selected.get('digest')!=self.digest:
            raise RuntimeError('Installed local model missing or digest changed; no download/fallback')
        response=super().generate(request);response.metadata['model_digest']=selected.get('digest');return response
