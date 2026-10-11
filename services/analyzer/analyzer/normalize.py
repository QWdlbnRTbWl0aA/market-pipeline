"""Deterministic canonical normalization; independent of intake source and LLM."""
import collections
import datetime as dt
from html.parser import HTMLParser
import html
import math
import re


class TextParser(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.ignored=0
    def handle_starttag(self, tag, attrs):
        if tag in {'script','style'}:self.ignored+=1
    def handle_endtag(self, tag):
        if tag in {'script','style'}:self.ignored=max(0,self.ignored-1)
        elif not self.ignored:self.parts.append(' ')
    def handle_data(self, value):
        if not self.ignored:self.parts.append(value)


def clean(value):
    if value is None:return ''
    if not isinstance(value,str):raise ValueError('Expected text field')
    parser=TextParser();parser.feed(value);parser.close()
    return re.sub(r'\s+', ' ', html.unescape(' '.join(parser.parts))).strip()


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def timestamp(value):
    if value is None:return None
    if not isinstance(value,str):raise ValueError('Timestamp must be ISO text')
    try:dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('Invalid ISO timestamp') from None
    return value  # Keep original timezone/date precision; never invent an age.


def normalize(batch):
    records, errors, warnings, seen=[],[],[],{}
    for index, raw in enumerate(batch.records):
        try:
            if not isinstance(raw,dict):raise ValueError('Record must be an object')
            identity=raw.get('id')
            if not isinstance(identity,str) or not identity.strip():raise ValueError('Record requires stable string id')
            title=clean(raw.get('title'))
            if not title:raise ValueError('Record requires a title')
            tags=raw.get('tags') or []
            if not isinstance(tags,list):raise ValueError('Tags must be a list')
            tags=list(dict.fromkeys(clean(t) for t in tags if clean(t)))
            price=raw.get('price')
            if price is not None and (not finite(price) or price<0):raise ValueError('Price must be a finite nonnegative number')
            metrics=raw.get('metrics') or []
            if not isinstance(metrics,list):raise ValueError('Metrics must be scoped objects')
            for metric in metrics:
                if not isinstance(metric,dict) or not isinstance(metric.get('scope'),str) or not isinstance(metric.get('name'),str):raise ValueError('Metric requires scope and name')
                if metric.get('value') is not None and (not finite(metric['value']) or metric['value']<0):raise ValueError('Metric must be nonnegative or null')
            digital=raw.get('digital')
            if digital is not None and type(digital) is not bool:raise ValueError('Digital must be true/false/null')
            record={'id':identity.strip(),'title':title,'description':clean(raw.get('description')),'tags':tags,
                    'category':raw.get('category'),'seller_id':raw.get('seller_id'),'price':price,'currency':raw.get('currency'),
                    'digital':digital,'images':raw.get('images') or [],'metrics':metrics,'original_created_at':timestamp(raw.get('original_created_at')),
                    'last_modified_at':timestamp(raw.get('last_modified_at')), 'state':raw.get('state'), 'observed_at':timestamp(raw.get('observed_at')),'provenance':raw.get('provenance',{})}
            for key in ('category','seller_id','currency'):
                if record[key] is not None and not isinstance(record[key],str):raise ValueError(key+' must be text or null')
            if identity.strip() in seen:
                previous=seen[identity.strip()]
                warnings.append({'index':index,'id':identity,'issue':'duplicate id; first observation retained',
                                 'conflicting':{k:v for k,v in previous.items() if k!='provenance'}!={k:v for k,v in record.items() if k!='provenance'}})
                continue
            seen[record['id']]=record;records.append(record)
        except (ValueError,TypeError) as error:errors.append({'index':index,'error':str(error)})
    return {'schema_version':1,'metadata':batch.metadata,'provenance':batch.provenance,'records':records,
            'dqa':{'input_records':len(batch.records),'accepted_records':len(records),'rejected_records':errors,'duplicate_records':warnings,
                   'missing_descriptions':sum(not r['description'] for r in records),'missing_categories':sum(r['category'] is None for r in records),
                   'category_counts':dict(collections.Counter(r['category'] or 'unknown' for r in records)),
                   'unique_sellers':len({r['seller_id'] for r in records if r['seller_id'] is not None}),
                   'scope':'Normalization checks only; not independent source verification'}}


def sample_records(records, limit=8, description_chars=600):
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('Sample size must be 1–20')
    count=min(limit,len(records))
    positions=[round(i*(len(records)-1)/(count-1)) for i in range(count)] if count>1 else [0] if count else []
    sample=[{k:records[i][k] for k in ('id','title','description','tags','category','seller_id','digital')} for i in positions]
    for row in sample:row['description']=row['description'][:description_chars]
    return sample, {'method':'Evenly spaced deterministic sample in original normalized order; not statistically representative',
                    'positions':positions,'sample_count':count,'available_count':len(records),'description_char_limit':description_chars}
