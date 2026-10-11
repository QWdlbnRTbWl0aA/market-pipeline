"""Real local processes; no collection, paid calls, model generation or email."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy'))
from launch import command,read_collector_credentials
from prepare import prepare
from unit_templates import render,SPECS


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


class DeploymentTests(unittest.TestCase):
    def test_clean_environment_and_service_credential_separation(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);secret=directory/'etsy.env'
            secret.write_text('export ETSY_API_KEY=fixture\nexport ETSY_API_SECRET=fixture\n');secret.chmod(0o600)
            for name in SPECS:
                cwd,argv,env=command(name,directory/'config.json',directory,credential_directory=directory)
                self.assertNotIn('OPENAI_API_KEY',env)
                self.assertEqual('ETSY_API_KEY' in env,name=='collector')
                self.assertEqual('PIPELINE_OPENAI_KEY_FILE' in env,name in ('search-refiner','market-analyst'))
                self.assertNotIn('fixture',' '.join(argv))
            secret.write_text('export ETSY_API_KEY=$(touch forbidden)\nexport ETSY_API_SECRET=fixture\n')
            with self.assertRaises(ValueError):read_collector_credentials(secret)
            self.assertFalse((directory/'forbidden').exists())
            secret.write_text('export ETSY_API_KEY=fixture\nexport ETSY_API_SECRET=fixture\n');secret.chmod(0o644)
            with self.assertRaises(ValueError):read_collector_credentials(secret)

    def test_independent_units_and_filesystem_write_scope(self):
        for name in SPECS:
            unit=render(name)
            self.assertIn('User=market-pipeline',unit);self.assertIn('ProtectSystem=strict',unit)
            self.assertNotIn('Requires=',unit);self.assertNotIn('PartOf=',unit)
            self.assertEqual('LoadCredential=etsy.env' in unit,name=='collector')
            self.assertEqual('LoadCredential=openai.env' in unit,name in ('search-refiner','market-analyst'))
            if name!='collector':self.assertNotIn('ReadWritePaths=/var/lib/market-pipeline/collector',unit)

    def test_preparation_preserves_existing_state_and_disables_new_paid_work(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state';configs=Path(temp)/'configs';prepare(state,configs)
            budget=state/'paid-ledger'/'budget.json';budget.write_text('{"must":"preserve"}')
            token=(state/'control-auth').read_bytes()
            config=state/'collector'/'config.json';config.write_text('{"must":"preserve"}')
            prepare(state,configs)
            self.assertEqual(budget.read_text(),'{"must":"preserve"}')
            self.assertEqual(config.read_text(),'{"must":"preserve"}')
            self.assertEqual((state/'control-auth').read_bytes(),token)
            self.assertFalse(json.loads((configs/'analyzer.json').read_text())['paid']['enabled'])

    def test_all_five_daemons_start_stop_and_restart_without_source_or_paid_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'state';configs=root/'configs';prepare(state,configs)
            processes=[];logs=[];ports={name:free_port() for name in ('collector','controller','product')}
            def start(name):
                config=state/'collector'/'config.json' if name=='collector' else configs/({'search-refiner':'analyzer','market-analyst':'analyzer'}.get(name,name)+'.json')
                log=(root/(name+'.log')).open('ab');logs.append(log)
                args=[sys.executable,str(ROOT/'deploy'/'launch.py'),name,'--config',str(config),'--state',str(state)]
                if name in ports:args+=['--port',str(ports[name])]
                process=subprocess.Popen(args,env={**os.environ,'ETSY_API_KEY':'synthetic-sentinel','OPENAI_API_KEY':'synthetic-sentinel'},stdout=log,stderr=log)
                processes.append(process);return process
            def wait_ready():
                deadline=time.monotonic()+15;opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));last_error=None
                while time.monotonic()<deadline:
                    self.assertTrue(all(p.poll() is None for p in processes),'Daemon exited; inspect bounded local logs')
                    try:
                        for name,port in ports.items():
                            route='/api/health' if name=='collector' else '/health'
                            with opener.open(f'http://127.0.0.1:{port}{route}',timeout=1) as response:
                                self.assertEqual(json.load(response)['status'],'running')
                        for service in ('search_refinement','market_insights'):
                            self.assertTrue((state/'analyzer'/'lifecycle'/('heartbeat-'+service+'.json')).exists())
                        return
                    except (OSError,AssertionError) as error:last_error=repr(error);time.sleep(.1)
                self.fail('Independent daemons did not become ready: '+str(last_error))
            def stop_all():
                for process in processes:
                    if process.poll() is None:process.terminate()
                for process in processes:self.assertEqual(process.wait(timeout=15),0)
                processes.clear()
            try:
                for name in SPECS:start(name)
                wait_ready()
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f'http://127.0.0.1:{ports["collector"]}/v1',timeout=3) as response:
                    self.assertEqual(response.status,200)
                marker=state/'paid-ledger'/'budget.json';marker.write_text('{"calls":{}}')
                stop_all()
                for name in SPECS:start(name)
                wait_ready();stop_all()
                self.assertEqual(marker.read_text(),'{"calls":{}}')
                self.assertEqual(list((state/'collector'/'runs').iterdir()),[])
                self.assertFalse((state/'collector'/'requests').exists())
            finally:
                for process in processes:
                    if process.poll() is None:process.terminate()
                    process.wait(timeout=15)
                for log in logs:log.close()
            for path in root.glob('*.log'):
                self.assertNotIn('synthetic-sentinel',path.read_text())
                self.assertNotIn('Traceback',path.read_text())
