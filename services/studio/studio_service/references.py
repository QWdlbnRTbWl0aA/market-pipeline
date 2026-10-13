"""Bounded raster references: strip metadata and resize before storage/provider use."""
import base64
import hashlib
import io
import re
import warnings
from .storage import Invalid, write_bytes


def thumbnail(body):
    if not isinstance(body,bytes) or len(body)>2_000_000:raise Invalid('Reference image exceeds byte limit')
    try:
        from PIL import Image,ImageOps
    except ImportError:raise Invalid('Reference images require the optional Pillow runtime') from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as image:
                if image.format not in ('PNG','JPEG','WEBP') or image.width*image.height>20_000_000 or getattr(image,'n_frames',1)!=1:raise Invalid('Use a bounded still PNG, JPEG or WebP image')
                image=ImageOps.exif_transpose(image);image.thumbnail((512,512));image=image.convert('RGB');image.info.clear()
                for quality in (75,60,45):
                    result=io.BytesIO();image.save(result,format='JPEG',quality=quality,optimize=True)
                    if len(result.getvalue())<=80_000:return result.getvalue(),image.size
                raise Invalid('Compressed reference exceeds byte bound')
    except Invalid:raise
    except Exception:raise Invalid('Invalid or oversized reference image') from None


def save(directory,values):
    if not isinstance(values,list) or len(values)>3:raise Invalid('At most three brief reference images')
    output=[]
    for index,value in enumerate(values):
        if not isinstance(value,str) or not re.fullmatch(r'data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+',value):raise Invalid('Uploaded raster data URLs only; no remote URLs')
        try:body=base64.b64decode(value.split(',',1)[1],validate=True)
        except ValueError:raise Invalid('Invalid reference encoding') from None
        body,size=thumbnail(body);file=f'references/reference-{index+1}.jpg';write_bytes(directory/file,body)
        output.append({'file':file,'sha256':hashlib.sha256(body).hexdigest(),'width':size[0],'height':size[1],'bytes':len(body),'media_type':'image/jpeg'})
    return output
