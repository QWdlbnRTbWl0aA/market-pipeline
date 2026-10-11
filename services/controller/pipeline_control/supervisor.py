"""Project-owned process supervision. No host integration or business retries.

Process death permits a bounded restart; unhealthy/busy external work is reported,
never killed automatically. Work identity/quota/paid/email ledgers are not restored.
"""
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request
from .storage import clean_environment, digest, event, Guard, LocalHTTP, local_url, now, read, write


def process_matches(pid, markers, cwd=None):
    try:
        path=Path('/proc')/str(pid);args=path.joinpath('cmdline').read_bytes().split(b'\0')
        if not args or any(m.encode() not in args for m in markers):return False
        return cwd is None or path.joinpath('cwd').resolve()==Path(cwd).resolve()
    except (OSError,ValueError):return False


class Supervisor:
    def __init__(self,manifest,root,activate=False):
        clean_environment();self.manifest=manifest;self.root=Path(root);self.activate=activate;self.children={};self.operations={}
        if manifest.get('schema_version')!=1 or not isinstance(manifest.get('services'),list) or not manifest['services']:raise ValueError('Explicit supervisor manifest required')
        if activate and manifest.get('activation_review',{}).get('manifest_sha256')!=digest({k:v for k,v in manifest.items() if k!='activation_review'}):raise ValueError('Exact recovery-reviewed supervisor manifest required')
        names=set()
        for service in manifest['services']:
            name=service['name']
            if name in names or not name.replace('_','').isalnum():raise ValueError('Unique service names required')
            names.add(name)
            if service['argv'][0] not in ('/usr/bin/python3','/usr/bin/bash') or not Path(service['cwd']).is_dir():raise ValueError('Known existing runtime and project directory required')
            allowed_env={'PATH','PIPELINE_CONTROL_AUTH_FILE','PIPELINE_CONTROLLER_URL','PIPELINE_OPERATIONS_ROOT','ETSY_BIND_HOST'}
            if set(service.get('env',{}))-allowed_env:raise ValueError('Service environment must be an allowlist; no inherited secrets')
            if service.get('health_url'):local_url(service['health_url'])
        self.root.mkdir(parents=True,exist_ok=True)
        path=self.root/'status.json';old=read(path) if path.exists() else {}
        self.state={r['name']:r for r in old.get('services',[])}

    def discover(self,service):
        for path in Path('/proc').glob('[0-9]*/cmdline'):
            if process_matches(int(path.parent.name),service['markers'],service['cwd']):return int(path.parent.name)

    def tick(self,clock=None):
        current=clock if clock is not None else time.time();rows=[]
        operations=self.root.parent/'operations'
        for p in operations.glob('*-paused.json'):
            value=read(p);name=p.name.removesuffix('-paused.json')
            if name in {s['name'] for s in self.manifest['services']}:self.state.setdefault(name,{'name':name})['paused']=value['paused']
        for service in self.manifest['services']:
            name=service['name'];old=self.state.get(name,{})
            child=self.children.get(name)
            if child is not None:child.poll() # Reap exited children before /proc discovery.
            pid=self.discover(service)
            row={'name':name,'pid':pid,'at':now(),'status':'running' if pid else 'stopped',
                 'restart_count':old.get('restart_count',0),'next_restart_at':old.get('next_restart_at',0),'paused':old.get('paused',False)}
            if not pid and self.activate and not row['paused']:
                if old.get('pid'):
                    row['restart_count']+=1;row['next_restart_at']=current+min(60,2**min(row['restart_count'],6))
                    event(self.root,'worker_exited',digest(name),{'service':name,'old_pid':old['pid'],'restart_count':row['restart_count']})
                if row['restart_count']>=5:
                    row['status']='requires_attention_restart_ceiling'
                elif current<row['next_restart_at']:row['status']='restart_backoff'
                else:
                    log=self.root/(name+'.log')
                    if log.exists() and log.stat().st_size>5_000_000:
                        rotated=self.root/(name+'-'+str(int(current))+'.log');log.rename(rotated)
                    with log.open('ab') as out:
                        process=subprocess.Popen(service['argv'],cwd=service['cwd'],env={'PATH':'/usr/bin:/bin',**service.get('env',{})},stdout=out,stderr=out,start_new_session=True)
                    self.children[name]=process;row.update(pid=process.pid,status='starting')
                    event(self.root,'worker_started',digest(name),{'service':name,'pid':process.pid,'clean_environment':True})
            if row['pid'] and service.get('health_url'):
                try:
                    with LocalHTTP()(service['health_url'],timeout=2) as response:health=json.loads(response.read(16385))
                    ready=health.get('worker_alive',True) and health.get('status','running')=='running'
                    row['readiness']='ready' if ready else 'degraded_requires_attention'
                except Exception:row['readiness']='unhealthy_requires_attention'
            if row['pid'] and service.get('heartbeat'):
                try:
                    beat=read(service['heartbeat']);stamp=dt.datetime.fromisoformat(beat['at'].replace('Z','+00:00'))
                    age=current-stamp.timestamp();busy=beat.get('status')=='analyzing'
                    row.update(heartbeat_age_seconds=max(0,age),activity=beat.get('status'),readiness='busy' if busy and age<600 else 'ready' if age<120 else 'stale_requires_attention')
                except (OSError,ValueError,KeyError):row['readiness']='heartbeat_unavailable'
            # Quota waits in collector job progress are healthy states, never crash triggers.
            rows.append(row);self.state[name]=row
        status={'schema_version':1,'at':now(),'status':'active' if self.activate else 'shadow','services':rows,
                'business_retries':False,'boot_integrated':False,'dynamic_ledgers_rolled_back':False}
        write(self.root/'status.json',status)
        if self.activate:self.run_operations()
        return status

    def run_operations(self):
        operations=self.root.parent/'operations'
        for path in operations.glob('*.json'):
            row=read(path)
            if row.get('status')=='running':
                child=self.operations.get(row.get('operation_id'))
                if child is None:
                    row.update(status='interrupted_requires_reconciliation',automatic_retry=False);write(path,row)
                elif child.poll() is not None:
                    row.update(status='completed' if child.returncode==0 else 'failed',exit_code=child.returncode,finished_at=now());write(path,row)
                continue
            if row.get('status')!='queued':continue
            service=next((s for s in self.manifest['services'] if s['name']==row['stage']),None)
            if not service or not service.get('analyzer_config'):continue
            if row['stage'] not in ('search_refinement','market_insights') or row['action'] not in ('retry','reconcile'):raise ValueError('Unsupported stage operation')
            key=row['record_id']
            if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Invalid recovery identity')
            argv=['/usr/bin/python3','-m','analyzer.operations','--config',service['analyzer_config'],'--service',row['stage'],'--job',key,'--action',row['action']]
            row.update(status='running',started_at=now());write(path,row)
            with (self.root/('operation-'+row['operation_id']+'.log')).open('ab') as log:
                child=subprocess.Popen(argv,cwd=service['cwd'],env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log,start_new_session=True)
            self.operations[row['operation_id']]=child

    def pause(self,name,paused=True):
        if name not in {s['name'] for s in self.manifest['services']}:raise ValueError('Unknown stage')
        self.state.setdefault(name,{'name':name})['paused']=paused
        # Pausing admission/restart does not kill an active collector/model request.
        write(self.root/'operator-pause.json',{'stage':name,'paused':paused,'at':now()})


def supervise(path,root,activate=False):
    manifest=read(path);manager=Supervisor(manifest,root,activate);stop=False
    def end(*args):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,end);signal.signal(signal.SIGINT,end)
    with Guard(root):
        while not stop:
            manager.tick();time.sleep(2)
    # Leave independent services running on supervisor shutdown; no blind replay.
