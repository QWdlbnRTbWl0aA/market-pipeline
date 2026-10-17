"""Editable, evidence-linked preferences. No inference is promoted silently."""
import uuid
from .storage import Invalid, guard, read, write, now


class Preferences:
    def __init__(self, root): self.root=root/'preferences'
    def list(self):
        with guard(self.root):
            return read(self.root/'memory.json') if (self.root/'memory.json').exists() else {'revision':0,'items':[],'history':[]}
    def change(self, payload, project, evidence):
        with guard(self.root):
            state=read(self.root/'memory.json') if (self.root/'memory.json').exists() else {'revision':0,'items':[],'history':[]}
            if payload.get('memory_revision')!=state['revision']:raise Invalid('Preference memory changed; refresh first')
            scope=payload.get('scope','product');family=payload.get('family','')
            if scope not in ('brand','family','product') or not isinstance(family,str) or len(family)>120:raise Invalid('Invalid preference scope')
            if scope=='family' and not family.strip():raise Invalid('Name the product family')
            operation=payload.get('operation','save');identifier=payload.get('preference_id')
            existing=next((x for x in state['items'] if x['id']==identifier),None)
            if operation=='delete':
                if not existing:raise Invalid('Unknown preference')
                state['items'].remove(existing)
            elif operation=='save':
                text=payload.get('text')
                if not isinstance(text,str) or not text.strip() or len(text)>1000:raise Invalid('Bounded preference text required')
                if identifier and not existing:raise Invalid('Unknown preference')
                item={'id':identifier or uuid.uuid4().hex,'scope':scope,'family':family.strip(),'project_id':project,
                      'text':text.strip(),'evidence':evidence[-12:],'source':'explicit_human_confirmation','updated_at':now()}
                if existing:state['items'].remove(existing)
                if len(state['items'])>=200:raise Invalid('Preference memory limit reached; remove unused entries')
                state['items'].append(item)
            else:raise Invalid('Unknown preference operation')
            state['revision']+=1;state['history'].append({'revision':state['revision'],'at':now(),'operation':operation,'prior':existing,'project_id':project})
            write(self.root/'memory.json',state);return state
    def context(self, project, family):
        return [x for x in self.list()['items'] if x['scope']=='brand' or x['scope']=='product' and x['project_id']==project or x['scope']=='family' and x['family']==family][:32]
