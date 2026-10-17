"""Locally configured, capability-checked model roles. Discovery never reads keys."""
import os
import stat
from .storage import Invalid

ROLES=('mockup_planning','mockup_sketches','mockup_final_images')
DEFAULT_ROLES={'openai':['mockup_planning','mockup_sketches']}


def checked_roles(value):
    if not isinstance(value,dict) or set(value)-{'openai','google'}:raise Invalid('Unknown credential provider roles')
    for roles in value.values():
        if not isinstance(roles,list) or any(not isinstance(r,str) or r not in ROLES for r in roles) or len(set(roles))!=len(roles):raise Invalid('Unknown provider usage role')
    return value


def credential_present(provider):
    """Metadata check only; paid adapters validate/load contents after admission."""
    variable={'openai':'STUDIO_OPENAI_CREDENTIAL_FILE','google':'STUDIO_GEMINI_CREDENTIAL_FILE'}.get(provider)
    path=os.environ.get(variable or '')
    if not path:return False
    try:
        info=os.lstat(path)
        return stat.S_ISREG(info.st_mode) and not info.st_mode&(stat.S_IWGRP|stat.S_IRWXO) and 0<info.st_size<=8192 and os.access(path,os.R_OK)
    except OSError:return False


class ModelRoles:
    def __init__(self,roles=None,available=credential_present):
        self.roles={provider:list(values) for provider,values in checked_roles(roles if roles is not None else DEFAULT_ROLES).items()};self.available=available;self.entries={}
    def register_final(self,identifier,label,provider,adapter,*,tier,capability):
        if tier!='top_tier' or capability!='image_edit':raise Invalid('Finals require an explicitly vetted top-tier image-edit adapter')
        if provider not in ('openai','google') or not identifier or identifier in self.entries:raise Invalid('Unknown or duplicate final model')
        self.entries[identifier]={'id':identifier,'label':label,'provider':provider,'tier':tier,'capability':capability,'adapter':adapter}
    def permitted(self,provider,role):return role in self.roles.get(provider,[]) and self.available(provider)
    def final_options(self):
        return [{k:v for k,v in entry.items() if k!='adapter'} for entry in self.entries.values() if self.permitted(entry['provider'],'mockup_final_images')]
    def select_final(self,identifier=None):
        options=self.final_options()
        if identifier is None and len(options)==1:identifier=options[0]['id']
        selected=next((e for e in options if e['id']==identifier),None)
        if selected is None:raise Invalid('Select a configured top-tier image model with an available credential and explicit final-image permission')
        return self.entries[identifier]['adapter']
    def require_cheap(self):
        if not self.permitted('openai','mockup_planning') or not self.permitted('openai','mockup_sketches'):raise Invalid('Planning/sketch credential roles are unavailable')
    def public(self,planner,sketch):
        from .openai_dev import TEXT_MODEL
        return {'planning':{'provider':getattr(planner,'name','configured'),'model':TEXT_MODEL,'role':'mockup_planning','available':self.permitted('openai','mockup_planning'),'purpose':'תכנון והבנת הערות · טקסט וראייה זולים'},
                'sketches':{'provider':getattr(sketch,'name','configured'),'model':getattr(sketch,'image_model','synthetic'),'role':'mockup_sketches','available':self.permitted('openai','mockup_sketches'),'purpose':'סקיצות · יצירת תמונות זולה'},
                'finals':self.final_options(),'finals_local_check_only':True}
