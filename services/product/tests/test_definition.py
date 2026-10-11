import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from product_service.definition import checked,enhanced,qualify,wireframe
from test_flow import fixture as payload

class LocalFixture:
 def __init__(self):self.calls=0
 def generate(self,context,schema):
  self.calls+=1;ref=context['samples'][0]['evidence_id']
  d={'audience':'Family hosts with children','job':'Lead a short table activity','content_units':[{'title':t,'purpose':'Support the host activity','tasks':['Provide one illustrated practice prompt'],'evidence_ids':[ref]} for t in ('Prompt cards','Host guide','Response page')],**{k:['Proposed first requirement','Proposed second requirement'] for k in ('user_flow','package','accessibility','localization','acceptance_tests','assumptions')},'design_directions':[{'name':name,'palette':['#ffffff','#123456'],'typography':'Sans serif for proposed print layout','content_unit_indices':[i],'intent':'Original facilitator-led design'} for i,name in enumerate(('Table cards','Drawing activity'))]}
  return {'definition':d,'raw':{'synthetic':True},'provider':'synthetic'}

class DefinitionTests(unittest.TestCase):
 def test_zero_or_short_shop_counters_cannot_qualify_product(self):
  v=self.input();row=v['report']['recommendations'][0]
  row['facts']={'shop_count':3,'performance_cross_check':{'history_qualification':{'1':{'trend_status':'engagement_proxy_ready','intervals':[{'metrics':{'views':{'change':5}}}]}},'shop_history_qualification':{'4':{'trend_status':'shop_counter_trend_ready','intervals':[{'metrics':{'transaction_sold_count':{'change':0}}}]}},'positive_shop_sales_intervals':0}}
  self.assertEqual(qualify(row,v)['status'],'review_pending')
  row['facts']['performance_cross_check']['positive_shop_sales_intervals']=1
  row['facts']['performance_cross_check']['shop_history_qualification']['4']['trend_status']='insufficient_evidence'
  self.assertEqual(qualify(row,v)['status'],'review_pending')
 def input(self):
  v=payload();v['report']['recommendations'][0]['evidence_excerpts']=[{'evidence_id':'e1','listing_id':'1','title':'Synthetic card'}];return v
 def test_missing_history_stays_review_pending_without_model_call(self):
  with tempfile.TemporaryDirectory() as temp:
   m=LocalFixture();result=enhanced(json.dumps(self.input()).encode(),temp,m)
   self.assertEqual(result['status'],'review_pending');self.assertEqual(m.calls,0)
 def test_local_draft_is_specific_safe_and_idempotent(self):
  with tempfile.TemporaryDirectory() as temp:
   m=LocalFixture();v=self.input();body=json.dumps(v).encode();a=enhanced(body,temp,m,True);b=enhanced(body,temp,m,True)
   self.assertEqual(m.calls,1);self.assertTrue(b['duplicate']);product=a['products'][0];folder=Path(product['directory'])
   self.assertEqual(len(product['drafts']),2);self.assertNotEqual((folder/product['drafts'][0]).read_text(),(folder/product['drafts'][1]).read_text())
   for name in product['drafts']:
    doc=ET.fromstring((folder/name).read_text());self.assertEqual(doc.tag,'{http://www.w3.org/2000/svg}svg');self.assertNotIn('<script',(folder/name).read_text())
   self.assertTrue((folder/'brief.md').exists());self.assertFalse(json.loads((folder/'product.json').read_text())['launch_approved'])
 def test_unknown_citations_indices_and_svg_injection_are_rejected_or_escaped(self):
  row=self.input()['report']['recommendations'][0];d=LocalFixture().generate({'samples':row['evidence_excerpts']},{})['definition'];d['content_units'][0]['evidence_ids']=['missing']
  with self.assertRaises(ValueError):checked(d,row)
  d=LocalFixture().generate({'samples':row['evidence_excerpts']},{})['definition'];d['design_directions'][0]['palette']=['javascript:evil','#123456']
  with self.assertRaises(ValueError):checked(d,row)
  d=LocalFixture().generate({'samples':row['evidence_excerpts']},{})['definition'];d=checked(d,row);svg=wireframe(d,d['design_directions'][0],'<script>alert(1)</script>')
  self.assertNotIn('<script>',svg);ET.fromstring(svg)
  d=LocalFixture().generate({'samples':row['evidence_excerpts']},{})['definition'];d['user_flow']=['Design team creates the files','Studio tests the package']
  with self.assertRaisesRegex(ValueError,'Customer use flow'):checked(d,row)
 def test_shared_concept_dedup_preserves_delivery_revisions(self):
  with tempfile.TemporaryDirectory() as temp:
   m=LocalFixture();v=self.input();a=enhanced(json.dumps(v).encode(),temp,m,True);v['delivery_id']='b'*64;b=enhanced(json.dumps(v).encode(),temp,m,True)
   self.assertEqual(m.calls,1);self.assertNotEqual(a['products'][0]['directory'],b['products'][0]['directory'])
   self.assertTrue((Path(a['products'][0]['directory'])/'product.json').exists())
 def test_unknown_contract_version_and_fabricated_assertions_fail(self):
  v=self.input();v['envelope']={'schema_version':2,'event_type':'analysis_completed'}
  with tempfile.TemporaryDirectory() as temp,self.assertRaises(ValueError):enhanced(json.dumps(v).encode(),temp,LocalFixture(),True)

class PromotionTests(unittest.TestCase):
 def test_enhanced_disabled_and_changed_review_configuration_are_safe(self):
  from product_service.configuration import load,RUBRIC
  from product_service.definition import digest,VERSION
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'config.json';value={'enhanced_enabled':False,'model':'gemma3:4b','ollama_url':'http://127.0.0.1:11434','qualification_root':temp,'promotion_review':None};path.write_text(json.dumps(value));self.assertFalse(load(path)['enhanced_enabled'])
   value['enhanced_enabled']=True;path.write_text(json.dumps(value))
   with self.assertRaises(ValueError):load(path)
   preview=Path(temp)/'preview.json';sample={'recipe':VERSION};preview.write_text(json.dumps(sample))
   value['promotion_review']={'approved':True,'configuration_sha256':digest({k:v for k,v in value.items() if k!='promotion_review'}),'rubric_sha256':digest(RUBRIC),'recipe':VERSION,'reviewer':'synthetic product person','preview_manifest_sha256':digest(sample),'preview_manifest_path':str(preview)};path.write_text(json.dumps(value));self.assertTrue(load(path)['enhanced_enabled'])
   value['model']='other';path.write_text(json.dumps(value))
   with self.assertRaises(ValueError):load(path)
 def test_local_service_never_accepts_remote_or_paid_provider(self):
  from product_service.definition import OllamaDefinition
  for url in ('https://api.openai.com','https://openapi.etsy.com','http://192.0.2.10:8090'):
   with self.assertRaises(ValueError):OllamaDefinition(endpoint=url)
