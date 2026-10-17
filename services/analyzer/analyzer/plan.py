"""Offline plan: normalize and quantify evidence without any model/API request."""
import argparse
import json
from .history import HistoryIntake
from .normalize import normalize
from .research import build_evidence, VERSION
from .saved_intake import discover
from .services import load_config
from .io import write_json

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',default='services-production.json');parser.add_argument('--run');parser.add_argument('--output',default='test-output/offline-plan.json')
    args=parser.parse_args();config=load_config(args.config)
    identities=[args.run] if args.run else discover(config['saved_runs_root'])[-1:]
    if not identities:raise ValueError('No finalized successful saved collection')
    dataset=normalize(HistoryIntake(config['saved_runs_root'],identities[0]).read());evidence=build_evidence(dataset,config['research'])
    plan={'version':VERSION,'source':dataset['provenance'],'normalization_dqa':dataset['dqa'],
          'observed_listings':evidence['observed_listings'],'candidate_count':len(evidence['candidates']),
          'flagged_listing_count':len(evidence['flags']),'network_calls':0,'models':[],
          'paid_enabled':config['paid']['enabled'],'paid_policy':config['paid'],'evidence':evidence}
    write_json(args.output,plan);print(json.dumps({k:v for k,v in plan.items() if k not in ('evidence','normalization_dqa','source')},indent=2))
if __name__=='__main__':main()
