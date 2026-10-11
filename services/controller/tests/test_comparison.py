import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from pipeline_control.comparison import compare,statistics
from pipeline_control.storage import write

class ComparisonTests(unittest.TestCase):
 def fixture(self,root):
  directory=root/'run';queries=[]
  for key,rows in [('printable broad',[{'listing_id':1,'title':'Physical vase','is_digital':False,'shop_id':1},{'listing_id':2,'title':'Printable card','is_digital':True,'shop_id':2}]),('printable cards',[{'listing_id':2,'title':'Printable card','is_digital':True,'shop_id':2},{'listing_id':3,'title':'Printable card','is_digital':True,'shop_id':3}])]:
   raw=json.dumps({'count':200,'results':rows}).encode();name='raw-'+str(len(queries))+'.json';directory.mkdir(exist_ok=True);(directory/name).write_bytes(raw)
   queries.append({'status':'success','niche':{'keywords':key},'pages':[{'http_status':200,'raw_file':name,'raw_sha256':hashlib.sha256(raw).hexdigest(),'effective_parameters':{'limit':100,'offset':0}}]})
  snapshot={'status':'success','finished_at':'2026-10-11T00:00:00Z','dqa':{},'lineage':{'experiment_id':'a'*64},'settings':{'limit':100,'max_pages':1,'exclude_fetched_listings':False,'exclude_fetched_shops':False},'queries':queries,'request_count':2}
  write(directory/'snapshot.json',snapshot);write(directory/'dqa.json',{})
  manifest={'proposal_id':'a'*64,'searches':['printable broad','printable cards'],'phrases':[{'parent_keywords':'printable broad','keywords':'printable cards'}],'comparison_policy':{'minimum_relevance_gain':.1}}
  return directory,manifest
 def test_comparison_requires_all_human_labels_and_does_not_confuse_novelty(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder,m=self.fixture(root)
   r=compare(root,'run',m,root/'out');self.assertEqual(r['status'],'awaiting_human_labels')
   labels={'snapshot_sha256':r['snapshot_sha256'],'reviewer':'synthetic operator','labels':{'1':'irrelevant','2':'relevant','3':'relevant'}}
   r=compare(root,'run',m,root/'out',labels);self.assertEqual(r['status'],'accepted');self.assertEqual(r['iterations_remaining'],0)
 def test_partial_and_checksum_tampering_cannot_qualify(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder,m=self.fixture(root);(folder/'raw-0.json').write_text('{}')
   with self.assertRaises(ValueError):compare(root,'run',m,root/'out')
 def test_prices_stay_separated_and_unknown_digital_is_not_false(self):
  result=statistics([{'listing_id':1,'title':'card','is_digital':True,'price':{'amount':3,'divisor':1,'currency_code':'USD'}},{'listing_id':2,'title':'card','price':{'amount':5,'divisor':1,'currency_code':'EUR'}}],['card'])
  self.assertEqual(result['unknown_digital_rows'],1);self.assertEqual(set(result['price_statistics_by_currency']),{'USD','EUR'})
