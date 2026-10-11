"""Shared local preprocessing cache. Failed local requests are not auto-repeated."""
import fcntl
import hashlib
import json
from pathlib import Path
from ..io import write_json
from ..ports import ModelResponse

class CachedLocalModel:
    def __init__(self, model,root,identity):self.model,self.root,self.identity=model,Path(root),identity
    def generate(self,request):
        value={'identity':self.identity,'system':request.system,'prompt':request.prompt,'schema':request.schema,
               'image_hashes':[hashlib.sha256(image.encode()).hexdigest() for image in request.images]}
        identity=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest();root=self.root/identity;root.mkdir(parents=True,exist_ok=True)
        with (root/'lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            path=root/'response.json'
            if path.exists():
                cached=json.loads(path.read_text());return ModelResponse(cached['text'],{**cached['metadata'],'local_cache_hit':True},cached['raw'])
            if (root/'started.json').exists():raise RuntimeError('Previous local inference interrupted/failed; no automatic repeat')
            write_json(root/'started.json',{'fingerprint':identity})
            response=self.model.generate(request);write_json(path,{'text':response.text,'metadata':response.metadata,'raw':response.raw})
            return response
