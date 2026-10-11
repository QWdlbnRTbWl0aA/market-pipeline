"""Synthetic privacy fixtures assembled at runtime; no real network information."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from environment_audit import context,findings,load,safe_address
from secret_audit import audit


class EnvironmentAuditTests(unittest.TestCase):
    def test_real_style_ipv4_ipv6_are_blocked_and_reserved_examples_allowed(self):
        examples=['127.0.0.1','0.0.0.0','::1','::','192.0.2.10','198.51.100.20','203.0.113.8','2001:db8::8']
        for address in examples:
            self.assertTrue(safe_address(address));self.assertEqual(findings(address.encode()),[])
        # Construct non-example addresses so the tests themselves pass publication audit.
        addresses=['.'.join(map(str,parts)) for parts in [(10,23,45,67),(100,88,77,66),(192,168,44,22),(8,8,4,4)]]
        addresses+=[':'.join(parts) for parts in [('fd12','3456','','8'),('fe80','','9'),('2001','4860','','8')]]
        addresses+=['::'+'ffff:'+addresses[0]]
        for address in addresses:
            self.assertFalse(safe_address(address))
            self.assertIn('non_example_ip_address',findings(('http://['+address+']:8090').encode()))

    def test_private_hostnames_observed_short_names_and_unknown_domains(self):
        host='fixture-'+'host'
        names=['device.tailfixture.'+'ts'+'.net','device.'+'local','server.'+'lan','device.private-customer.'+'com']
        for name in names:self.assertTrue(findings(name.encode()))
        self.assertIn('observed_machine_hostname',findings(host.encode(),{'hostnames':[host]}))
        self.assertEqual(findings((host+'-unrelated').encode(),{'hostnames':[host]}),[])
        for name in ('dashboard.example','device.example.com','api.openai.com','openapi.etsy.com','github.com'):
            self.assertEqual(findings(name.encode()),[])

    def test_personal_paths_and_escaped_paths_are_blocked_portable_layout_allowed(self):
        personal=['/'+prefix+'/fixture/projects/source' for prefix in ('home','Users','mnt','srv','workspace')]
        personal+=['C:'+chr(92)+'Users'+chr(92)+'fixture'+chr(92)+'project']
        for value in personal:self.assertIn('personal_absolute_path',findings(value.encode()))
        self.assertIn('personal_absolute_path',findings(personal[0].replace('/','\\/').encode()))
        custom='/custom-'+'volume/project'
        self.assertIn('observed_machine_path',findings((custom+'/app.py').encode(),{'paths':[custom]}))
        for value in ('/etc/market-pipeline/analyzer.json','/var/lib/market-pipeline/collector/runs','/opt/market-pipeline/current','/etc/systemd/system'):
            self.assertEqual(findings(value.encode()),[])

    def test_unreachable_history_and_filename_are_scanned_without_printing_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);subprocess.run(['git','init','-q',str(root)],check=True)
            host='fixture-'+'private-host'
            content=('/'+'home/fixture/project').encode()
            subprocess.run(['git','hash-object','-w','--stdin'],input=content,cwd=root,capture_output=True,check=True)
            (root/(host+'.txt')).write_text('Synthetic')
            result=audit(root,inventory={'hostnames':[host]})
            self.assertFalse(result['clean'])
            self.assertTrue(any(r.get('kind')=='blob' and r['rule']=='personal_absolute_path' for r in result['findings']))
            self.assertTrue(any(r['rule']=='observed_machine_hostname' for r in result['findings']))
            self.assertNotIn(content.decode(),json.dumps(result))

    def test_saved_inventory_permissions_and_no_values_in_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'environment.json'
            values={'schema_version':1,'hostnames':['fixture-'+'machine'],'addresses':['192.0.2.10'],'paths':['/'+ 'home/fixture']}
            file.write_text(json.dumps(values));file.chmod(0o600)
            self.assertEqual(load(file),values)
            merged=context(ROOT,file);self.assertIn(values['hostnames'][0],merged['hostnames'])
            file.chmod(0o644)
            with self.assertRaises(ValueError):load(file)
            file.chmod(0o600);link=Path(temp)/'link.json';link.symlink_to(file)
            with self.assertRaises(OSError):load(link)
