"""Provider-scoped literal files. Never source shell files or collector keys."""
import os
import shlex
import stat
from .storage import Invalid


def read_key(path,assignment):
    if not path:raise Invalid('Provider credential file is not configured')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode&(stat.S_IWGRP|stat.S_IRWXO) or info.st_size>8192:raise Invalid('Protected bounded credential file required')
        body=os.read(fd,8193).decode()
    finally:os.close(fd)
    lines=[s.strip().removeprefix('export ') for s in body.splitlines() if s.strip() and not s.lstrip().startswith('#')]
    if len(lines)!=1 or not lines[0].startswith(assignment+'='):raise Invalid('Only the selected provider key assignment is allowed')
    values=shlex.split(lines[0].split('=',1)[1],comments=False)
    if len(values)!=1 or not values[0] or any(c.isspace() or c in '$`' for c in values[0]):raise Invalid('Invalid literal key')
    return values[0]


def gemini_key():return read_key(os.environ.get('STUDIO_GEMINI_CREDENTIAL_FILE'),'GEMINI_API_KEY')
