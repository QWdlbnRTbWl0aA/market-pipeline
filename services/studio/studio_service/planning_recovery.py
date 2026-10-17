"""Recover completed values followed by provider whitespace, never missing content."""
import json
from .storage import Invalid
from .lifestyle import checked_plan


def recover(text,number,page_ids):
    # This is specifically the observed terminal whitespace degeneration. Never
    # turn an ordinary truncated response, refusal or unfinished field into data.
    if len(text)-len(text.rstrip())<256 or not page_ids:raise Invalid('Not a recoverable whitespace tail')
    compact=text.rstrip();stack=[];quoted=False;escaped=False
    for char in compact:
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char in '{[':stack.append(char)
        elif char in '}]':
            if not stack or stack.pop()!=('{' if char=='}' else '['):raise Invalid('Malformed JSON containers')
    if quoted or not compact or compact[-1] not in '}]':raise Invalid('A field or value is incomplete')
    if len(stack)>3:raise Invalid('Too many incomplete containers')
    suffix=''.join('}' if c=='{' else ']' for c in reversed(stack))
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise Invalid('Duplicate JSON field')
            value[key]=item
        return value
    try:value=json.loads(compact+suffix,object_pairs_hook=unique)
    except (ValueError,TypeError):raise Invalid('Container completion did not form valid JSON') from None
    checked_plan(value,number,set(page_ids))
    if any(len(value[k])>400 for k in ('product_understanding','direction')):raise Invalid('Explanation exceeds provider schema')
    for scene in value['scenes']:
        if set(scene)!={'title','description','image_prompt','page_id','scene_type'} or len(scene['description'])>500 or len(scene['image_prompt'])>1200:raise Invalid('Scene does not satisfy the complete provider schema')
    return value,suffix
