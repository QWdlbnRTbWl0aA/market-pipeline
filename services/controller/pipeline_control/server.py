"""Local passive report intake, operator decisions and read-only pipeline timeline."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import urllib.request
from .controller import Controller
from .storage import clean_environment, identity, local_url, now, read, write


def inventory(settings, root):
    """Read small completion receipts only. Full raw snapshots stay lazy."""
    stages = []; errors = []
    locations = [('collection', Path(settings['saved_runs_root']).parent/'dashboard-index', '*.json'),
                 ('search_refinement', Path(settings['analyzer_output_root'])/'search_refinement', '*/state.json'),
                 ('market_insights', Path(settings['analyzer_output_root'])/'market_insights', '*/state.json'),
                 ('product', Path(settings['product_data_root'])/'studio-outbox', '*/state.json')]
    for kind, path, glob in locations:
        for p in sorted(path.glob(glob),key=lambda p:p.stat().st_mtime_ns,reverse=True)[:200]:
            try:
                v = read(p)
                if kind == 'collection': v = v['run']
                row = {'stage': kind, 'root_cycle_id': v.get('root_cycle_id') or v.get('source_run_id') or v.get('run_id'),
                       'job_id': v.get('job_id') or v.get('delivery_id') or v.get('run_id'),
                       'status': v.get('analysis_status', v.get('status')), 'delivery_status': v.get('delivery_status'),
                       'at': v.get('finished_at') or v.get('started_at'), 'source_run_id': v.get('source_run_id') or v.get('run_id')}
                stages.append(row)
            except (ValueError, OSError, KeyError, TypeError) as e: errors.append({'stage':kind,'file':p.name,'error_type':type(e).__name__})
    proposals, cohorts, cycles = [], [], []
    for kind, target in [('proposals',proposals),('cohorts',cohorts),('cycles',cycles)]:
        for p in sorted((root/kind).glob('*.json'))[-100:]:
            try: target.append(read(p))
            except (ValueError, OSError): errors.append({'stage':kind,'file':p.name,'error_type':'InvalidRecord'})
    heartbeats = []
    for p in (Path(settings['analyzer_output_root'])/'lifecycle').glob('heartbeat-*.json'):
        try: heartbeats.append(read(p))
        except (ValueError,OSError): pass
    supervisor = root/'supervisor'/'status.json'
    return {'schema_version':1,'at':now(),'execution_enabled':settings['execution_enabled'], 'timeline':sorted(stages,key=lambda r:r.get('at') or '',reverse=True),
            'proposals':proposals,'cohorts':cohorts,'cycles':[{k:v for k,v in row.items() if k!='observations'} for row in cycles],'heartbeats':heartbeats,'errors':errors,
            'supervisor':read(supervisor) if supervisor.exists() else {'status':'not_activated'},
            'counts':{'pending_proposals':sum(r.get('status')=='awaiting_approval' for r in proposals), 'errors':len(errors)},
            'holds':{'live_experiment':'exact manifest/rubric approval required','tracking':'exact cohort approval required','enhanced_product':'rubric and sample review required','deployment':'prepared independently; host installation is separate'}}


def server(settings, port=8094):
    clean_environment(); controller=Controller(settings); stop=threading.Event()
    def work():
        while not stop.is_set():
            try:
                pause=controller.root/'operations'/'controller-paused.json'
                if pause.exists() and read(pause).get('paused'):
                    write(controller.root/'heartbeat.json',{'at':now(),'status':'paused','execution_enabled':settings['execution_enabled']})
                else:controller.tick()
            except Exception as e:write(controller.root/'worker-error.json',{'at':now(),'error_type':type(e).__name__})
            stop.wait(settings['poll_seconds'])
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,value):
            body=json.dumps(value,ensure_ascii=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path=='/health':self.reply(200,{'service':'pipeline_controller','status':'running','worker_alive':self.server.worker.is_alive(),'execution_enabled':settings['execution_enabled']})
            elif self.path=='/status':self.reply(200,inventory(settings,controller.root))
            else:self.reply(404,{'error':'Unknown route'})
        def do_POST(self):
            if self.headers.get('Origin') or self.headers.get('Sec-Fetch-Site')=='cross-site':self.reply(403,{'error':'Local service interface only'});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=5_000_000:
                    self.close_connection=True
                    self.reply(413,{'error':'Bounded payload required','max_bytes':5_000_000});return
                self.connection.settimeout(10);body=self.rfile.read(length)
                if len(body)!=length:raise ValueError('Incomplete body')
                if self.path=='/search-refinement':
                    payload=json.loads(body)
                    if self.headers.get('Idempotency-Key')!=payload.get('delivery_id'):raise ValueError('Mismatched delivery identity')
                    result=controller.receive(body)
                elif re.fullmatch('/proposals/[a-f0-9]{64}/decision',self.path):
                    value=json.loads(body);result=controller.decide(self.path.split('/')[2],value['action'],value['manifest_sha256'],value['reviewer'],value.get('reference'))
                elif re.fullmatch('/proposals/[a-f0-9]{64}/labels',self.path):
                    result=controller.labels(self.path.split('/')[2],json.loads(body))
                elif re.fullmatch('/cohorts/[a-f0-9]{64}/decision',self.path):
                    from .tracking import decide
                    value=json.loads(body);result=decide(controller,self.path.split('/')[2],value['action'],value['manifest_sha256'],value['reviewer'])
                elif self.path=='/cycles':
                    from .cycles import create
                    result=create(controller,json.loads(body))
                elif re.fullmatch('/cycles/[a-f0-9]{64}/decision',self.path):
                    from .cycles import decide
                    result=decide(controller,self.path.split('/')[2],json.loads(body))
                elif self.path=='/operations':
                    value=json.loads(body)
                    if set(value)!={'stage','action','record_id','reason'} or value['stage'] not in ('search_refinement','market_insights','product','collector','controller') or value['action'] not in ('pause','resume','reconcile','retry') or not isinstance(value['reason'],str) or not value['reason'].strip():raise ValueError('Scoped operator instruction required')
                    from .storage import digest
                    key=identity(value['record_id'])
                    if value['action'] in ('pause','resume'):
                        write(controller.root/'operations'/(value['stage']+'-paused.json'),{'paused':value['action']=='pause','reason':value['reason'][:500],'at':now()})
                        result={'recorded':True,'status':'admission_paused' if value['action']=='pause' else 'admission_resumed','active_work_cancelled':False}
                    elif value['stage']=='controller' and value['action']=='reconcile':
                        result=controller.reconcile_submission(key)
                    else:
                        if value['stage'] not in ('search_refinement','market_insights'):raise ValueError('Source/product outcomes require manual saved-evidence reconciliation; no blind retry')
                        state=read(Path(settings['analyzer_output_root'])/value['stage']/key/'state.json')
                        if state.get('job_id')!=key:raise ValueError('Unknown saved analysis job')
                        operation_id=digest(value)
                        target=controller.root/'operations'/(operation_id+'.json')
                        if not target.exists():write(target,{**value,'at':now(),'status':'queued','operation_id':operation_id,'automatic_retry':False})
                        result={'recorded':True,'status':read(target)['status'],'operation_id':operation_id,'automatic_retry':False}
                else:self.reply(404,{'error':'Unknown route'});return
                if self.path=='/cycles' or self.path.startswith('/cycles/'):
                    result={k:v for k,v in result.items() if k!='observations'}
                self.reply(200,result)
            except (ValueError,KeyError,TypeError,AttributeError):self.reply(400,{'error':'Invalid operation or report'})
            except OSError:self.reply(503,{'error':'Intake storage unavailable'})
        def log_message(self,*args):pass
    http=ThreadingHTTPServer(('127.0.0.1',port),Handler);http.controller=controller
    http.worker=threading.Thread(target=work,daemon=True);http.worker.start();http.stop_worker=stop.set;return http
