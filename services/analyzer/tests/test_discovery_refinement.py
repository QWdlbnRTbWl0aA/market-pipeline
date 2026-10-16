"""Fresh saved observations, native currency and inert query experiments."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from analyzer.assessments import policy, qualify
from analyzer.opportunities import analyze
from analyzer.refinement import identity, prepare
from analyzer.research import build_evidence, listing_url, analyze as research
from analyzer.io import write_json
from analyzer.product_briefs import local_design_selection, validate as validate_brief, request as brief_request
from analyzer.research import model_request
from test_opportunities import data, AllSelections
from test_production import POLICY, Selection


def fresh():
    d=data();d['metadata']['history']={}
    for i,row in enumerate(d['records']):
        row['metrics']=[{'scope':'listing','name':'views','value':40+i}, {'scope':'listing','name':'favorites','value':2}]
        row['provenance']={'url':f'https://www.etsy.com/listing/{100000+i}/example', 'source_id':str(100000+i)}
    return d


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config={'research':POLICY,'output_root':str(self.root)}

    def assessment(self,d):return qualify(build_evidence(d,POLICY)['candidates'][0],d,[],policy())

    def test_fresh_cross_section_is_discovery_never_trend_or_listing_sales(self):
        result=self.assessment(fresh())
        self.assertFalse(result['qualified']);self.assertTrue(result['discovery']['qualified'])
        self.assertEqual(result['evidence_tier'],'discovery_hypothesis')
        self.assertEqual(result['strong_sales_context_shops'],0)
        self.assertIsNone(result['listing_sales']);self.assertFalse(result['verified_listing_purchase_demand'])
        self.assertIn('insufficient_multi_shop_listing_engagement_history',result['hold_reasons'])

    def test_missing_history_does_not_exclude_native_currency_prices(self):
        d=fresh()
        for r in d['records']:r.update(currency='EUR',price=12)
        c=build_evidence(d,{**POLICY,'cheap_price_reference':{'USD':5}})['candidates'][0]
        a=qualify(c,d,[],policy())
        self.assertEqual(a['known_price_share'],1);self.assertEqual(a['benchmark_price_share'],0)
        self.assertIsNone(a['cheap_share']);self.assertTrue(a['discovery']['qualified'])
        self.assertIsNone(c['prices']['EUR']['reference_price'])
        self.assertIn('Cheap-price benchmarks', ' '.join(a['discovery']['risks']))

    def test_weak_unknown_or_concentrated_evidence_does_not_become_discovery(self):
        for fault in ('engagement','age','prices','query','single_shop','reset','conflict'):
            d=fresh()
            if fault=='engagement':
                for r in d['records']:r['metrics']=[]
            if fault=='age':
                for s in d['metadata']['shops']:s['created_at']=None
            if fault=='prices':
                for r in d['records']:r['price']=None
            if fault=='query':d['metadata']['query_context']['niches']=[{'keywords':'printable amber unrelated'}]
            if fault=='single_shop':
                for r in d['records']:r['seller_id']='1'
            if fault=='reset':
                d['metadata']['history']=data()['metadata']['history']
                for s in d['metadata']['shops']:s['transaction_sold_count']=1
            if fault=='conflict':d['metadata']['shops'] += [{**s,'transaction_sold_count':1} for s in d['metadata']['shops']]
            with self.subTest(fault=fault):self.assertFalse(self.assessment(d)['discovery']['qualified'])

    def test_trend_supported_behavior_and_discovery_opt_out(self):
        self.assertEqual(self.assessment(data())['evidence_tier'],'trend_supported')
        d=fresh();c=build_evidence(d,POLICY)['candidates'][0]
        a=qualify(c,d,[],policy({'discovery_enabled':False}))
        self.assertFalse(a['discovery']['qualified']);self.assertFalse(a['qualified'])

    def test_local_preview_authors_brief_preserves_links_and_does_not_claim_offer(self):
        d=fresh();original=copy.deepcopy(d);folder=self.root/'preview';folder.mkdir();local=AllSelections()
        with patch('socket.socket.connect',side_effect=AssertionError('No network')):
            report=analyze(d,folder,self.config,local,None,None)
        self.assertEqual(report['status'],'local_preview');self.assertFalse(report['final_model_completed'])
        self.assertEqual(len(report['recommendations']),1);rec=report['recommendations'][0]
        self.assertEqual(rec['assessment'],'discovery_hypothesis');self.assertIsInstance(rec['product_brief'],dict)
        self.assertTrue(all(e['url'].startswith('https://www.etsy.com/listing/') for e in rec['evidence_excerpts']))
        self.assertEqual(json.loads((self.root/'market-assessments'/'offers.json').read_text())['offers'],{})
        self.assertEqual(original,d)
        # A later paid-quality assessment must still be allowed to use this idea.
        write_json(self.root/'market_insights'/'preview'/'outbound.json',{'service':'market_insights','status':'completed',
            'source_run_id':'current','finished_at':'2026-10-15T01:00:00Z','report':report})
        d['metadata'].update(source_run_id='later',finished_at='2026-10-16T00:00:00Z')
        final=self.root/'final';final.mkdir();paid=AllSelections()
        result=analyze(d,final,self.config,AllSelections(),AllSelections(),paid)
        self.assertEqual(len(result['recommendations']),1);self.assertEqual(paid.calls,1)

    def test_original_saved_url_only_and_never_external_request(self):
        for url in ('javascript:alert(1)','https://example.invalid/listing/123','https://www.etsy.com@evil.invalid/listing/123','https://www.etsy.com/listing/not-a-number'):
            self.assertIsNone(listing_url({'provenance':{'url':url}}))
        self.assertIsNone(listing_url({'id':'123','provenance':{}}))
        d=fresh()
        for r in d['records']:r['provenance']={}
        a=self.assessment(d)
        self.assertFalse(a['discovery']['qualified'])
        self.assertIn('insufficient_saved_etsy_examples',a['discovery']['hold_reasons'])

    def test_local_proposals_cannot_certify_observations_or_invent_commercial_evidence(self):
        e=build_evidence(fresh(),POLICY);c=e['candidates'];req=brief_request(model_request('market_insights',e,c))
        raw=json.loads(AllSelections().generate(req).text)
        raw['items'][0]['reason']='999 purchases prove high demand.'
        raw['items'][0]['product_brief']['deliverables'][0].update(text='Create 12 original printable activity pages.',basis='observed')
        before=copy.deepcopy(raw);value=local_design_selection(raw,c);_,briefs=validate_brief(value,c)
        self.assertEqual(raw,before);self.assertNotIn('999',value['items'][0]['reason'])
        self.assertEqual(briefs[c[0]['candidate_id']]['deliverables'][0]['basis'],'design_hypothesis')
        value['items'][0]['product_brief']['product_concept']='Guaranteed profit from this product'
        with self.assertRaises(ValueError):validate_brief(value,c)
        raw['items'][0]['evidence_ids']=['foreign']
        with self.assertRaises(ValueError):validate_brief(local_design_selection(raw,c),c)


class RefinementTests(unittest.TestCase):
    def test_cultural_niche_terms_are_not_treated_as_printable_boilerplate(self):
        d=fresh();d['metadata']['query_context']={'niches':[{'keywords':'jewish printable'}]}
        self.assertEqual(build_evidence(d,POLICY)['candidates'],[])
        for r in d['records']:r['title']='Jewish '+r['title']
        self.assertTrue(build_evidence(d,POLICY)['candidates'])

    def test_printable_boilerplate_does_not_make_unrelated_listing_relevant(self):
        d=fresh();d['metadata']['query_context']={'niches':[{'keywords':'printable amber geometry'}]}
        bad={**d['records'][0],'id':'unrelated','title':'Printable engine repair guide','tags':['instant digital download'],
             'description':'Printable PDF engine instructions'}
        d['records'].append(bad)
        e=build_evidence(d,POLICY)
        self.assertTrue(any(f['listing_id']=='unrelated' and 'no_query_terms_in_saved_content' in f['reasons'] for f in e['flags']))
        self.assertTrue(all('unrelated' not in c['listing_ids'] for c in e['candidates']))

    def test_multiple_queries_do_not_require_unrelated_query_terms_to_cooccur(self):
        d=fresh();d['metadata']['query_context']={'niches':[{'keywords':'printable amber geometry'},{'keywords':'printable coral ocean'}]}
        e=build_evidence(d,POLICY)
        self.assertFalse(any('partial_query_term_match_review_required' in f['reasons'] for f in e['flags']))

    def test_refinement_uses_the_query_supported_by_its_listings(self):
        d=fresh();d['metadata']['query_context']={'niches':[{'keywords':'printable coral ocean'},{'keywords':'printable amber'}]}
        result=prepare(build_evidence(d,POLICY),d,12)
        self.assertTrue(result['candidates'])
        self.assertTrue(all(c['search_plan']['baseline_keywords']=='printable amber' for c in result['candidates']))
        self.assertEqual(identity('Printable toddler activities'),identity('toddler activity printable'))

    def test_no_unchanged_duplicate_or_broader_query_and_specific_evidence(self):
        d=fresh();d['metadata']['query_context']={'niches':[{'keywords':'printable amber'}]}
        e=build_evidence(d,{**POLICY,'max_candidates':80})
        # Duplicate word ordering and an unchanged control are intentionally present.
        c=copy.deepcopy(e['candidates'][0]);c.update(candidate_id='duplicate',phrase='geometry amber')
        e['candidates'] += [c,{**c,'candidate_id':'unchanged','phrase':'printable amber'}]
        result=prepare(e,d,12);queries=[c['suggested_keywords'] for c in result['candidates']]
        self.assertTrue(queries);self.assertEqual(len(queries),len({identity(q) for q in queries}))
        self.assertNotIn(identity('printable amber'),{identity(q) for q in queries})
        for candidate in result['candidates']:
            self.assertTrue({'printable','amber'}<=set(candidate['suggested_keywords'].split()))
            p=candidate['search_plan'];self.assertTrue(p['added_terms']);self.assertIn(candidate['phrase'],p['observed_support'])
            self.assertTrue(p['requires_collector_comparison'])

    def test_local_report_has_specific_rationale_and_query_plan(self):
        d=fresh();d['metadata']['query_context']={'niches':[{'keywords':'printable amber'}]}
        with tempfile.TemporaryDirectory() as t,patch('socket.socket.connect',side_effect=AssertionError('No network')):
            report=research('search_refinement',d,Path(t),{'research':POLICY},Selection())
        rec=report['recommendations'][0]
        self.assertIn('amber geometry',rec['rationale']);self.assertIn('search_plan',rec)
        self.assertIn('amber',rec['alternative_keywords'])
        self.assertIn('refinement_plan',report['deterministic_summary'])


if __name__=='__main__':unittest.main()
