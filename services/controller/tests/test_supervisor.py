import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from pipeline_control.storage import digest
from pipeline_control.supervisor import Supervisor,process_matches

class SupervisorTests(unittest.TestCase):
 def test_shadow_never_starts_and_activation_requires_exact_review(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);script=root/'worker.py';script.write_text('import time\ntime.sleep(300)\n')
   m={'schema_version':1,'services':[{'name':'fixture','cwd':str(root),'argv':['/usr/bin/python3',str(script)],'markers':[str(script)]}]}
   s=Supervisor(m,root/'state');self.assertEqual(s.tick()['services'][0]['status'],'stopped')
   with self.assertRaises(ValueError):Supervisor(m,root/'state',True)
 def test_worker_crash_restart_and_reboot_do_not_duplicate_processes(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);script=root/'worker.py';script.write_text('import time\ntime.sleep(300)\n')
   m={'schema_version':1,'services':[{'name':name,'cwd':str(root),'argv':['/usr/bin/python3',str(script),name],'markers':[str(script),name]} for name in ['collector','refiner','market','product','receiver','controller']]}
   m['activation_review']={'manifest_sha256':digest(m),'reviewer':'synthetic drill'};s=Supervisor(m,root/'state',True)
   children=[]
   try:
    first=s.tick(clock=100);time.sleep(.1);children=list(s.children.values());second=s.tick(clock=101)
    self.assertEqual([r['pid'] for r in first['services']],[r['pid'] for r in second['services']])
    for name,child in list(s.children.items()):
     child.terminate();child.wait(timeout=3);r=s.tick(clock=102)
    self.assertTrue(all(r['status']=='restart_backoff' for r in r['services']))
    r=s.tick(clock=110);children+=list(s.children.values());time.sleep(.1)
    restarted=Supervisor(m,root/'state',True);reboot=restarted.tick(clock=111)
    self.assertEqual([r['pid'] for r in r['services']],[r['pid'] for r in reboot['services']])
    self.assertTrue(all(x['restart_count']==1 for x in reboot['services']))
   finally:
    for p in set(children+list(s.children.values())):
     if p.poll() is None:p.terminate();p.wait(timeout=3)
 def test_environment_allowlist_refuses_provider_keys(self):
  with tempfile.TemporaryDirectory() as temp:
   m={'schema_version':1,'services':[{'name':'bad','cwd':temp,'argv':['/usr/bin/python3','-c','pass'],'markers':['fixture'],'env':{'ETSY_API_KEY':'fixture'}}]}
   with self.assertRaises(ValueError):Supervisor(m,Path(temp)/'out')
