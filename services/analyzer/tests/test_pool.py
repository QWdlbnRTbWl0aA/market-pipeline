"""Incremental discovery must extend saved candidates without fabricating history."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from analyzer.history import HistoryIntake
from analyzer.io import write_json
from analyzer.lifecycle import semantic
from analyzer.normalize import normalize
from analyzer.opportunities import analyze
from test_opportunities import data, AllSelections
from test_production import POLICY


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'runs';self.root.mkdir()
    def save(self,name,day,rows,shops=None,**extra):
        settings={'niches':[{'keywords':'printable'}],'exclude_fetched_listings':True,'exclude_fetched_shops':True}
        value={'run_id':name,'status':'success','finished_at':f'2026-10-{day:02d}T00:00:00Z','dqa':{},'settings':settings,
               'queries':[{'listings':rows}],'shops':[{'shop':s} for s in (shops or [])],**extra}
        write_json(self.root/name/'snapshot.json',value);write_json(self.root/name/'dqa.json',{})
    def row(self,identity,day,title='Printable amber geometry',seller='1'):
        return {'listing_id':str(identity),'shop_id':seller,'title':title,'digital':True,'description':'Wall art','tags':['amber geometry'],
                'price':12,'currency':'USD','taxonomy_id':1,'observed_at':f'2026-10-{day:02d}T00:00:00Z','listing_views':day,'listing_favorites':day}
    def read(self,name):return HistoryIntake(self.root,name,saved_pool=True).read()
    def test_thirteen_new_rows_merge_old_pool_latest_identity_and_real_dates(self):
        self.save('old',1,[self.row(i,1) for i in range(100)])
        self.save('middle',8,[self.row(0,8)])
        self.save('new',15,[self.row(i,15) for i in range(100,113)])
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.glob('*/*.json')}
        with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):batch=self.read('new')
        self.assertEqual(len(batch.records),113);scope=batch.metadata['saved_pool']
        self.assertEqual((scope['current_run_listing_count'],scope['historical_listing_count']),(13,100))
        older=next(r for r in batch.records if r['id']=='etsy:listing:0')
        self.assertEqual(older['observed_at'],'2026-10-08T00:00:00Z');self.assertEqual(older['provenance']['artifact_run_id'],'middle')
        series=batch.metadata['history']['listing_series']['etsy:listing:0']
        self.assertEqual(series['observations'],2);self.assertEqual(series['span_days'],7)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.glob('*/*.json')})
        self.assertEqual(batch.metadata['semantic_context'],self.read('new').metadata['semantic_context'])
        self.assertNotEqual(semantic({'semantic_context':batch.metadata['semantic_context']}),semantic({}))
    def test_empty_new_run_retains_pool_future_failed_probe_and_wrong_niche_excluded(self):
        self.save('old',1,[self.row(1,1),{**self.row(2,1,title='Printable ocean boats'),'tags':['ocean boats']}])
        self.save('future',20,[self.row(3,20)])
        self.save('failed',2,[self.row(4,2)],status='failed')
        self.save('probe',2,[self.row(5,2)],trigger='count-probe')
        self.save('new',15,[],settings={'niches':[{'keywords':'printable amber geometry'}]})
        batch=self.read('new')
        self.assertEqual([r['id'] for r in batch.records],['etsy:listing:1'])
        self.assertEqual(batch.metadata['saved_pool']['current_run_listing_count'],0)
        self.assertTrue(batch.metadata['saved_pool']['issues'])
    def test_shop_bounds_taxonomy_multiple_searches_and_named_cycles(self):
        self.save('old',1,[self.row(1,1),self.row(2,1,seller='2'),self.row(3,1,title='Printable ocean boats')])
        self.save('other-cycle',2,[self.row(4,2)],lineage={'cycle_id':'b'*64})
        self.save('new',15,[],settings={'niches':[{'keywords':'amber geometry','taxonomy_id':1},{'keywords':'ocean boats'}],
                                      'shop_ids':['1'],'search_parameters':{'min_price':10,'max_price':20}},lineage={'cycle_id':'a'*64})
        self.assertEqual({r['id'] for r in self.read('new').records},{'etsy:listing:1','etsy:listing:3'})
    def test_saved_tracking_updates_known_identity_without_importing_unrelated_one(self):
        self.save('old',1,[self.row(1,1)])
        rows=[self.row(1,8),self.row(2,8)];rows[0]['images']=[{'local_path':'images/reference.jpg'}]
        self.save('tracking',8,[],artifact_kind='tracking',tracked_listings=[{'status':'success','listing':r} for r in rows])
        self.save('new',15,[])
        batch=self.read('new');self.assertEqual(len(batch.records),1)
        self.assertEqual(batch.records[0]['observed_at'],'2026-10-08T00:00:00Z')
        self.assertEqual(batch.records[0]['images'][0]['artifact_run_id'],'tracking')
    def test_full_pool_can_support_ten_mock_opportunities_from_empty_new_collection(self):
        original=data(10)
        for day,sales in ((1,100),(8,120),(15,140)):
            rows=[]
            for i,r in enumerate(original['records']):
                rows.append({**self.row(i,day,r['title'],r['seller_id']),'tags':r['tags']})
            shops=[{**s,'observed_at':f'2026-10-{day:02d}T00:00:00Z','transaction_sold_count':sales} for s in original['metadata']['shops']]
            self.save('day-'+str(day),day,rows,shops)
        self.save('new',16,[])
        dataset=normalize(self.read('new'));out=Path(self.temp.name)/'analysis';out.mkdir()
        models=[AllSelections() for _ in range(3)]
        with patch('socket.socket.connect',side_effect=AssertionError('No paid, Etsy or Ollama calls')):
            report=analyze(dataset,out,{'research':POLICY,'output_root':str(out)},*models)
        self.assertEqual(len(report['recommendations']),10)
        self.assertEqual(report['data_scope']['current_run_listing_count'],0)
        self.assertEqual(report['data_scope']['pooled_listing_count'],90)
        self.assertTrue(all(r['listing_sales'] is None for r in report['recommendations']))
    def test_service_uses_pool_only_for_market_and_repeated_trigger_skips_inference(self):
        from analyzer.mock_receiver import server
        from analyzer.services import run_cycle
        from test_services import FakeModel
        self.save('old',1,[self.row(i,1) for i in range(20)])
        self.save('new',15,[self.row(i,15) for i in range(20,33)])
        receiver=server(Path(self.temp.name)/'receiver',0)
        threading.Thread(target=receiver.serve_forever,daemon=True).start()
        try:
            url='http://127.0.0.1:'+str(receiver.server_port)
            config={'saved_runs_root':str(self.root),'output_root':str(Path(self.temp.name)/'output'),'model':'synthetic','sample_size':8,
                    'endpoints':{'search_refinement':url+'/search-refinement','market_insights':url+'/market-insights'}}
            models={s:FakeModel() for s in config['endpoints']}
            results=run_cycle(config,'new',models=models)
            for result in results:
                self.assertEqual(result['analysis_status'],'completed')
                saved=json.loads((Path(result['directory'])/'normalized.json').read_text())
                self.assertEqual(len(saved['records']),33 if result['service']=='market_insights' else 13)
            run_cycle(config,'new',models=models)
            self.assertEqual([m.calls for m in models.values()],[1,1])
        finally:receiver.shutdown();receiver.server_close()
