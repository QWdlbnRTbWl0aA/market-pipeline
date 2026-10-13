"""Comparable saved searches determine novelty without inference or Etsy calls."""
import tempfile
from pathlib import Path
import unittest
from analyzer.saved_intake import SavedCollectionIntake
from analyzer.search_memory import analyze
from analyzer.io import write_json


class SearchMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'runs'
    def save(self,day,complete=True,exclude=False,keyword='printable hanukkah',title='Printable Hanukkah art'):
        name=f'run-{day}';snapshot={'run_id':name,'status':'success','finished_at':f'2026-10-{day:02d}T00:00:00Z','dqa':{},
            'settings':{'niches':[{'keywords':keyword}],'shop_ids':[],'exclude_fetched_listings':exclude,'exclude_fetched_shops':False},
            'queries':[{'niche':{'keywords':keyword},'collection_complete':complete,'listings':[{'listing_id':'1','shop_id':'1','title':title,'digital':True}]}]}
        write_json(self.root/name/'snapshot.json',snapshot);write_json(self.root/name/'dqa.json',{})
        return SavedCollectionIntake(self.root,name).read()
    def test_complete_low_novelty_history_is_report_only(self):
        for day in (1,2,6,10):batch=self.save(day)
        result=analyze(self.root,batch)
        self.assertTrue(result['low_novelty_evidence_ready']);self.assertFalse(result['automatic_settings_changes'])
        self.assertEqual(result['observations'][0]['new_listing_fraction'],1)
        self.assertEqual(result['observations'][-1]['new_listing_fraction'],0)
    def test_truncation_exclusion_query_change_and_irrelevant_results_prevent_exhaustion(self):
        for day in (1,2,6):self.save(day)
        for kwargs in ({'complete':False},{'exclude':True},{'keyword':'printable christmas'},{'title':'Printable birthday art'}):
            with self.subTest(kwargs=kwargs):
                result=analyze(self.root,self.save(10,**kwargs));self.assertFalse(result['low_novelty_evidence_ready'])
        batch=self.save(10);batch.metadata['query_context']['shop_ids']=['1','2']
        batch.metadata['query_coverage'][0]['shop_id']='1'
        self.assertFalse(analyze(self.root,batch)['low_novelty_evidence_ready'])
    def test_daily_samples_stabilize_after_full_week_of_low_novelty(self):
        for day in range(1,9):batch=self.save(day)
        self.assertFalse(analyze(self.root,batch)['low_novelty_evidence_ready'])
        self.assertTrue(analyze(self.root,self.save(9))['low_novelty_evidence_ready'])


if __name__=='__main__':unittest.main()
