"""Small file protocol: immutable events, atomic records and loopback-only transport."""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request
from urllib.parse import urlsplit


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def read(path, maximum=20_000_000):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum or any(p.startswith('.env') for p in path.parts):
        raise ValueError('Bounded regular saved JSON required')
    value = json.loads(path.read_bytes()); reject_secrets(value)
    return value


def reject_secrets(value):
    if isinstance(value, dict):
        for k, v in value.items():
            name = str(k).lower()
            if name in {'api_key', 'api_secret', 'credentials', 'authorization', 'password', 'access_token', 'refresh_token', 'control_token'} or name.endswith(('_api_key', '_api_secret', '_password')):
                raise ValueError('Credential-shaped intake forbidden')
            reject_secrets(v)
    elif isinstance(value, list):
        for v in value: reject_secrets(v)


def clean_environment():
    if any(k.upper().startswith(('ETSY', 'OPENAI', 'ANTHROPIC', 'SMTP')) for k in os.environ):
        raise ValueError('Launch controller with a clean environment')


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Invalid stable identity')
    return value


def run_identity(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,99}', value):
        raise ValueError('Invalid saved run identity')
    return value


class Guard:
    def __init__(self, root):
        root = Path(root); root.mkdir(parents=True, exist_ok=True)
        self.path = root / '.lock'
    def __enter__(self):
        self.stream = self.path.open('a'); fcntl.flock(self.stream, fcntl.LOCK_EX); return self
    def __exit__(self, *args): self.stream.close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): raise ValueError('Redirects forbidden')


def local_url(url):
    p = urlsplit(url)
    if p.scheme != 'http' or p.hostname != '127.0.0.1' or not p.port or p.username or p.password or p.query or p.fragment:
        raise ValueError('Numeric IPv4 loopback endpoint required')
    return url.rstrip('/')


class LocalHTTP:
    def __init__(self): self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def __call__(self, request, timeout=5):
        local_url(request if isinstance(request, str) else request.full_url)
        return self.opener.open(request, timeout=timeout)


def event(root, kind, key, value):
    row = {'schema_version': 1, 'event_type': kind, 'job_id': key, 'data': value}
    event_id = digest(row); path = Path(root) / 'events' / (event_id + '.json')
    if not path.exists(): write(path, {**row, 'event_id': event_id, 'at': now()})
    return event_id
