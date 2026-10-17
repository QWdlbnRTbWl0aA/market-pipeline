"""Read-only, project-scoped access to original image-provider responses.

Independent of accounting settlement, postprocessing, validation and board state.
Never loads credentials, writes files, or requests a remote image URL.
"""
import base64
import hashlib
from pathlib import Path
from .storage import read, Invalid, identity, digest


def responses(root,project):
    identity(project);base=Path(root)/'development-openai';ledger=base/'budget.json'
    if not ledger.exists():return []
    result=[]
    for call_id,row in read(ledger)['calls'].items():
        if row.get('product_id')!=project or len(call_id)!=64 or any(c not in '0123456789abcdef' for c in call_id):continue
        folder=base/'calls'/call_id
        for name in ('provider-response.json','response.json'):
            p=folder/name
            if folder.is_symlink() or p.is_symlink() or not p.is_file():continue
            info=p.stat()
            if info.st_size>90_000_000:continue
            result.append((call_id,row,p,info));break
    return result


def revision(root,project):return digest([(i,row.get('status'),p.name,s.st_mtime_ns,s.st_size) for i,row,p,s in responses(root,project)])


def encoded_images(value):
    for row in value.get('data') or []:
        if isinstance(row,dict) and isinstance(row.get('b64_json'),str):yield row['b64_json']
    for step in value.get('steps') or []:
        if isinstance(step,dict) and step.get('type')=='model_output':
            for item in step.get('content') or []:
                if isinstance(item,dict) and item.get('type')=='image' and isinstance(item.get('data'),str):yield item['data']


def items(root,project,token=None):
    found=[]
    for call_id,row,path,_ in responses(root,project):
        if token and not token.startswith(call_id+'-'):continue
        try:value=read(path)
        except (ValueError,OSError):continue
        for index,encoded in enumerate(encoded_images(value)):
            identifier=call_id+'-'+str(index)
            if token and token!=identifier:continue
            valid=True;size=None;media='application/octet-stream';problem=None
            try:body=base64.b64decode(encoded,validate=True)
            except (ValueError,TypeError):
                body=encoded.encode();valid=False;problem='Provider returned invalid image encoding; received payload remains downloadable'
            try:
                if not valid:raise Invalid(problem)
                import io
                from PIL import Image
                with Image.open(io.BytesIO(body)) as im:
                    if im.width*im.height>20_000_000:raise Invalid('Image exceeds preview pixel bound')
                    im.verify();size=[im.width,im.height];media=Image.MIME.get(im.format,media)
            except Exception:valid=False;problem=problem or 'Received image cannot be previewed; original bytes remain downloadable'
            entry={'id':identifier,'at':row['at'],'stage':row['stage'],'accounting_status':row['status'],'sha256':hashlib.sha256(body).hexdigest(),
                   'size':size,'media_type':media,'previewable':valid,'warning':problem,'original_provider_output':True}
            if token:return entry,body
            found.append(entry)
    if token:raise FileNotFoundError()
    return {'images':sorted(found,key=lambda r:(r['at'],r['id']),reverse=True),'revision':revision(root,project)}
