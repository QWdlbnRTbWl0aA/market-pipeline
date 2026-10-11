import argparse
import json
import signal
import threading
from .controller import config, Controller

parser=argparse.ArgumentParser(description='Independent bounded refinement and pipeline operations')
parser.add_argument('--config',default='config.json')
sub=parser.add_subparsers(dest='command',required=True)
p=sub.add_parser('serve');p.add_argument('--port',type=int,default=8094)
p=sub.add_parser('receive');p.add_argument('report')
p=sub.add_parser('cohort');p.add_argument('report')
p=sub.add_parser('compare');p.add_argument('proposal');p.add_argument('run');p.add_argument('--labels')
p=sub.add_parser('status')
p=sub.add_parser('supervise');p.add_argument('manifest');p.add_argument('--activate',action='store_true')
args=parser.parse_args();settings=config(args.config);control=Controller(settings)
if args.command=='serve':
 from .server import server
 http=server(settings,args.port)
 def shutdown(*unused):
  http.stop_worker();threading.Thread(target=http.shutdown,daemon=True).start()
 signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
 try:http.serve_forever()
 finally:http.stop_worker();http.worker.join(timeout=30);http.server_close()
elif args.command=='receive':
 from pathlib import Path
 receipt=control.receive(Path(args.report).read_bytes());print(json.dumps(control.prepare(receipt['delivery_id']),indent=2))
elif args.command=='cohort':
 from .tracking import prepare
 print(json.dumps(prepare(control,args.report),indent=2))
elif args.command=='compare':
 from .comparison import compare
 from .storage import read
 row=read(control.root/'proposals'/(args.proposal+'.json'))
 print(json.dumps(compare(control.source,args.run,row['manifest'],control.root/'comparisons'/args.proposal,read(args.labels) if args.labels else None),indent=2))
elif args.command=='status':
 from .server import inventory
 print(json.dumps(inventory(settings,control.root),indent=2))
elif args.command=='supervise':
 from .supervisor import supervise
 supervise(args.manifest,control.root/'supervisor',activate=args.activate)
