"""Bounded collector-only download of public Etsy CDN thumbnails, no credentials."""
import hashlib
import time
import urllib.parse
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Image redirects forbidden')

def save_images(row, directory, maximum=1, transport=None):
    audit=[]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for image in (row.get('images') or [])[:maximum]:
        if not isinstance(image, dict): continue
        url=image.get('url_570xN') or image.get('url_75x75')
        parsed=urllib.parse.urlsplit(url or '')
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.etsystatic.com') or parsed.port not in (None,443) or parsed.username or parsed.password:
            audit.append({'status':'unsafe_url_rejected'});continue
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'EtsyResearchTrial/0.1'})
            with (transport or opener.open)(request,timeout=15) as response:
                body=response.read(2_000_001)
            if len(body)>2_000_000:raise ValueError('Image size limit')
            suffix='.png' if body.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg' if body.startswith(b'\xff\xd8\xff') else None
            if not suffix:raise ValueError('Unsupported image signature')
            identity=hashlib.sha256(body).hexdigest()
            path=directory/'images'/(identity+suffix);path.parent.mkdir(exist_ok=True);path.write_bytes(body)
            image.update(local_path='images/'+path.name,sha256=identity,bytes=len(body))
            audit.append({'status':'saved','url':url,'sha256':identity,'bytes':len(body),'local_path':image['local_path']})
        except Exception as error:
            audit.append({'status':'failed','error_type':type(error).__name__})
        time.sleep(1.25)
    return audit
