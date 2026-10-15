#!/usr/bin/env python3
"""Inspect saved candidate coverage and deterministic holds; no inference or delivery."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services'/'analyzer'))
from analyzer.history import HistoryIntake
from analyzer.normalize import normalize
from analyzer.research import build_evidence
from analyzer.assessments import policy,qualify
from analyzer.io import write_json


def audit(root,run,as_of=None):
    batch=HistoryIntake(root,run,saved_pool=True,as_of=as_of).read();dataset=normalize(batch)
    evidence=build_evidence(dataset,{'min_group_listings':3,'max_candidates':80,'cheap_price_reference':{'USD':3}})
    assessments=[qualify(candidate,dataset,[],policy()) for candidate in evidence['candidates']]
    return {'source_run_id':run,'saved_pool':batch.metadata['saved_pool'],'normalization_dqa':dataset['dqa'],
            'candidate_count':len(assessments),'qualified_count':sum(a['qualified'] for a in assessments),
            'hold_reasons':dict(Counter(reason for a in assessments for reason in a['hold_reasons'])),
            'policy_scope':'Default deterministic policy and USD price reference; not deployed custom settings or prior-offer suppression.',
            'models_called':False,'delivery_attempted':False,'source_modified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',required=True);parser.add_argument('--run',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--as-of');args=parser.parse_args()
    output=Path(args.output).resolve();source=Path(args.runs).resolve()
    if output.is_relative_to(ROOT) or output.is_relative_to(source.parent):raise ValueError('Audit output must be outside source and collector storage')
    result=audit(source,args.run,args.as_of);write_json(output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('saved_pool','normalization_dqa')} | {
        'current_run_listing_count':result['saved_pool']['current_run_listing_count'],'pooled_listing_count':result['saved_pool']['pooled_listing_count'],
        'shop_count':result['saved_pool']['shop_count']}))
