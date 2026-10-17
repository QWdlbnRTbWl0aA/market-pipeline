import argparse
import json
import os
from .core import ROOT, Store, atomic_json, config, dqa, validate_config
from .server import serve


def main():
    parser = argparse.ArgumentParser(description='Etsy research collector and local dashboard')
    parser.add_argument('--config', default=str(ROOT / 'config.example.json'))
    parser.add_argument('--data', default=str(ROOT / 'data'))
    commands = parser.add_subparsers(dest='command', required=True)
    server = commands.add_parser('serve')
    server.add_argument('--port', type=int, default=8090)
    server.add_argument('--host', default=os.environ.get('ETSY_BIND_HOST', '127.0.0.1'),
                        help='IPv4 bind address; use 0.0.0.0 for LAN access')
    server.add_argument('--no-schedule', action='store_true')
    server.add_argument('--defer-today', action='store_true', help='enable scheduling starting tomorrow; skip deployment-day catch-up')
    collect = commands.add_parser('collect')
    collect.add_argument('--keywords')
    collect.add_argument('--category', default='Custom')
    collect.add_argument('--source', choices=['public', 'api'])
    collect.add_argument('--trigger', default='manual', choices=['manual', 'daily', 'smoke'])
    probe = commands.add_parser('probe', help='Exactly one search page/result per phrase; no shop follow-ups')
    probe.add_argument('--keywords', action='append', required=True)
    commands.add_parser('track', help='collect selected listing/shop observations only')
    commands.add_parser('reprocess', help='recover saved raw fields offline without requests')
    commands.add_parser('index', help='rebuild the file history index without requests')
    check = commands.add_parser('dqa')
    check.add_argument('run_id')
    args = parser.parse_args()
    settings = config(args.config)
    if args.command == 'serve':
        serve(settings, args.data, args.port, not args.no_schedule, args.host, args.config, args.defer_today)
    elif args.command == 'probe':
        settings = {**settings, 'source':'api', 'limit':1, 'page_size':1, 'max_pages':1, 'max_shops':0,
                    'max_requests_per_run':len(args.keywords), 'daily_mode':'search', 'shop_ids':[],
                    'exclude_fetched_listings':False, 'exclude_fetched_shops':False}
        settings = validate_config(settings)
        niches=[{'category':'Refiner count probe','keywords':value} for value in args.keywords]
        run=Store(args.data).collect(settings,niches,'count-probe')
        print(json.dumps({'run_id':run['run_id'],'status':run['status'],'request_count':run['request_count'],
                          'queries':[{'keywords':q['niche']['keywords'],'available':q['provider_result_count'],'fetched':len(q['listings']),'status':q['status']} for q in run['queries']]},indent=2))
        return 0 if run['status']=='success' else 2
    elif args.command in {'collect', 'track'}:
        if getattr(args, 'source', None):
            settings['source'] = args.source
        niches = [{'keywords': args.keywords, 'category': args.category}] if getattr(args, 'keywords', None) else None
        store = Store(args.data)
        run = store.track(settings) if args.command == 'track' else store.collect(settings, niches, args.trigger)
        print(json.dumps({'run_id': run['run_id'], 'status': run['status'], 'listing_count': run['listing_count'], 'shop_count': sum(bool(i.get('shop')) for i in run.get('shops', [])),
                          'request_count': run.get('request_count'),
                          'errors': [q['error'] for q in run['queries'] + run.get('tracked_listings', []) + run.get('shops', []) if q.get('error')]}, indent=2))
        return 0 if run['status'] == 'success' else 2
    elif args.command in {'reprocess', 'index'}:
        store = Store(args.data)
        print(json.dumps(store.reprocess() if args.command == 'reprocess' else store.rebuild_index(), indent=2))
    else:
        store = Store(args.data)
        run = store.read(args.run_id)
        result = dqa(run, store.runs / args.run_id)
        atomic_json(store.runs / args.run_id / 'dqa.json', result)
        print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
