"""Evidence loss and misleading concentration regressions; saved synthetic data."""
import copy
import json
import unittest
from analyzer.evidence_quality import description_context, profile
from analyzer.research import build_evidence, model_request
from analyzer.assessments import qualify, policy
from test_production import dataset, POLICY


class EvidenceQuality(unittest.TestCase):
    def test_late_product_mechanics_survive_bounded_verbatim_extraction(self):
        text=('Download information and shop policy. '*180+
              'INCLUDED: ten fruit mats; roll dough over the picture and cut with a child-safe knife. '+
              'Final download instructions. '*100)
        excerpt=description_context(text)
        self.assertTrue(excerpt['truncated']);self.assertLessEqual(len(excerpt['text']),3000)
        self.assertIn('child-safe knife',excerpt['text'])
        for start,end in excerpt['selected_spans']:self.assertIn(text[start:end],excerpt['text'])

    def test_missing_ages_and_metrics_remain_unknown_and_leader_removal_is_by_shop(self):
        rows=[{'id':'a','seller_id':'one','original_created_at':'2026-10-01T00:00:00Z','metrics':[{'scope':'listing','name':'favorites','value':80}]},
              {'id':'b','seller_id':'one','metrics':[{'scope':'listing','name':'favorites','value':10}]},
              {'id':'c','seller_id':'two','metrics':[{'scope':'listing','name':'favorites','value':10}]},
              {'id':'d','seller_id':'three','metrics':[]}]
        p=profile(rows,'2026-10-17T00:00:00Z')
        self.assertEqual(p['age_unknown'],3);self.assertEqual(p['original_age_days_median'],16)
        self.assertEqual(p['top_shop_favorite_share'],.9)
        self.assertEqual(p['leave_leading_shop_out']['favorites'],10)
        self.assertEqual(p['leave_leading_shop_out']['favorite_positive_shops'],1)

    def test_model_and_product_handoff_retain_mechanics_and_actual_source(self):
        data=dataset()
        for row in data['records']:row['description']='Digital download. '+'Saved background information. '*10+'Use dough mats and a child-safe knife; not paper scissors.'
        evidence=build_evidence(data,POLICY);candidates=evidence['candidates']
        request=json.loads(model_request('market_insights',evidence,candidates).prompt)
        for c in request['candidates']:
            for ref in c['evidence']:
                self.assertIn('child-safe knife',request['listing_examples'][ref['content_ref']]['description_excerpt'])
        self.assertGreater(len(candidates[0]['evidence'][0]['description_excerpt']),180)

    def test_favourite_replication_beats_equal_views_only_context(self):
        d=dataset()
        d['metadata']['finished_at']='2026-10-17T00:00:00Z'
        for row in d['records']:
            row['metrics']=[{'scope':'listing','name':'views','value':100}, {'scope':'listing','name':'favorites','value':0}]
        c=build_evidence(d,POLICY)['candidates'][0];low=qualify(c,d,[],policy())
        for row in d['records']:row['metrics'][1]['value']=20
        c=build_evidence(d,POLICY)['candidates'][0];high=qualify(c,d,[],policy())
        self.assertGreater(high['discovery']['score'],low['discovery']['score'])
        self.assertFalse(high['verified_listing_purchase_demand'])
