"""Bounded Responses API adapter. No SDK retries, tools, redirects or Etsy access."""
import os
from pathlib import Path
import shlex
import stat
from ..security import assert_clean_environment


def api_key():
    assert_clean_environment()
    value=os.environ.get('OPENAI_API_KEY')
    if not value:
        path=Path(os.environ.get('PIPELINE_OPENAI_KEY_FILE','/etc/market-pipeline/credentials/openai.env'))
        if path.name!='openai.env':raise ValueError('Dedicated OpenAI credential file required')
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_mode&(stat.S_IWGRP|stat.S_IRWXO):
                raise ValueError('OpenAI credentials require a protected readable regular file')
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

from pipeline_openai import OpenAIModel as SharedOpenAIModel

class OpenAIModel(SharedOpenAIModel):
    def __init__(self,model,policy,transport=None,key_provider=api_key,experiment_id=None):
        super().__init__(model,policy,transport,key_provider,experiment_id)
