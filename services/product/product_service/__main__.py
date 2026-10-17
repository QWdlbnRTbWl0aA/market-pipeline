import argparse
import json
import signal
import threading
from .core import SavedReportIntake, process
from .server import server

parser = argparse.ArgumentParser(description='Stage-one digital product studio handoff')
sub = parser.add_subparsers(dest='command', required=True)
p = sub.add_parser('run'); p.add_argument('report'); p.add_argument('--output', default='test-output'); p.add_argument('--definition-config')
p = sub.add_parser('define'); p.add_argument('report'); p.add_argument('--output', default='test-output/definitions'); p.add_argument('--allow-provisional', action='store_true'); p.add_argument('--qualification-root'); p.add_argument('--reuse-response')
p = sub.add_parser('serve'); p.add_argument('--data', default='data'); p.add_argument('--port', type=int, default=8093); p.add_argument('--definition-config'); p.add_argument('--operations-root')
p = sub.add_parser('deliver-studio',help='Delivery-only backfill of saved briefs to passive library; no definition, inference or email');p.add_argument('--data',required=True);p.add_argument('--config',required=True);p.add_argument('--recover');p.add_argument('--reason')
p = sub.add_parser('enrich-visuals',help='Attach real visual references to a saved brief in a new directory; no inference or delivery');p.add_argument('--brief',required=True);p.add_argument('--output',required=True);p.add_argument('--definition-config')
args = parser.parse_args()
if args.command == 'run':
    from .briefing import default_model
    from .configuration import load
    config=load(args.definition_config) if args.definition_config else {}
    from .visual_references import policy as visual_policy
    print(json.dumps(process(SavedReportIntake().read(args.report), args.output, default_model(config.get('briefing')),visual_policy(config.get('visual_references')))))
elif args.command == 'enrich-visuals':
    from .visual_references import revise
    from .configuration import load
    config=load(args.definition_config) if args.definition_config else {}
    print(json.dumps(revise(args.brief,args.output,config.get('visual_references'))))
elif args.command == 'define':
    from .definition import enhanced, SavedDefinitionResponse
    print(json.dumps(enhanced(SavedReportIntake().read(args.report), args.output, model=SavedDefinitionResponse(args.reuse_response) if args.reuse_response else None, allow_provisional=args.allow_provisional, qualification_root=args.qualification_root)))
elif args.command=='deliver-studio':
    from .configuration import load
    from .studio_delivery import backfill,tick,recover
    config=load(args.config);settings=config['studio_delivery']
    if not settings['enabled']:parser.error('Enable studio_delivery in Product configuration first')
    if bool(args.recover)!=bool(args.reason):parser.error('Recovery requires both --recover and --reason')
    if args.recover:recover(args.data,args.recover,settings,args.reason)
    queued=backfill(args.data,settings);delivered=tick(args.data,settings)
    print(json.dumps({'queued_brief_ids':queued,'delivery_results':delivered,'inference_calls':0,'mail_calls':0}))
else:
    http = server(args.data, args.port, args.definition_config, args.operations_root)
    def shutdown(*unused):
        http.stop_worker();threading.Thread(target=http.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    try:
        http.serve_forever()
    finally:
        http.stop_worker();http.worker.join(timeout=540);http.server_close()
