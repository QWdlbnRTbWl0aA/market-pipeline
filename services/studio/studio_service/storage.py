"""Atomic file state with cross-process guards; no provider credentials."""
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


class Invalid(ValueError): pass
class Conflict(Invalid): pass


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def digest(value): return hashlib.sha256(canonical(value)).hexdigest()


def clean_environment():
    if any(n.upper().startswith(('ETSY', 'OPENAI', 'ANTHROPIC', 'SMTP')) for n in os.environ):
        raise Invalid('Use the clean Studio launcher; providers are mocked and credentials are forbidden')


def reject_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key).lower()
            if name in {'api_key', 'api_secret', 'credentials', 'authorization', 'password', 'access_token', 'refresh_token'} or name.endswith(('_api_key', '_api_secret', '_password')):
                raise Invalid('Credential fields are forbidden')
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value: reject_secrets(child)


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value): raise Invalid('Invalid project identity')
    return value


def action_key(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}', value): raise Invalid('Idempotency key required')
    return value


def write_bytes(path, body):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def write(path, value): write_bytes(path, canonical(value))
def read(path): return json.loads(Path(path).read_bytes())


@contextmanager
def guard(directory, blocking=True):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
