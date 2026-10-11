import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from secret_audit import audit,findings
from publish_check import check


class PublicationTests(unittest.TestCase):
    def test_scan_unreachable_git_secret_without_emitting_value(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            subprocess.run(['git','init','-q',str(root)],check=True)
            secret=('sk-'+'proj-'+'X'*40).encode()
            process=subprocess.run(['git','hash-object','-w','--stdin'],input=secret,cwd=root,capture_output=True,check=True)
            result=audit(root)
            self.assertFalse(result['clean']);self.assertEqual(result['all_git_objects_scanned'],1)
            self.assertNotIn(secret.decode(),json.dumps(result))
            self.assertEqual(result['findings'][0]['rule'],'openai_key')

    def test_exact_unknown_format_and_ignored_runtime_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'.gitignore').write_text('runtime/\n');(root/'runtime').mkdir()
            secret=('unique-'+'fixture'*4).encode();(root/'runtime'/'hidden.env').write_bytes(secret)
            result=audit(root,[secret])
            self.assertFalse(result['clean']);self.assertNotIn(secret.decode(),json.dumps(result))

    def test_tracked_generated_artifact_blocks_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'data').mkdir();(root/'data'/'raw-0.json').write_text('{}')
            subprocess.run(['git','add','.'],cwd=root,check=True)
            result=check(root)
            self.assertFalse(result['clean'])
            self.assertIn('runtime_or_secret_artifact',[r['rule'] for r in result['publication_issues']])

    def test_publication_hook_requires_explicit_grant(self):
        import os
        env={k:v for k,v in os.environ.items() if k!='MARKET_PIPELINE_ALLOW_PUSH'}
        result=subprocess.run(['sh',str(ROOT/'.githooks'/'pre-push'),'origin','git@example.invalid:repo.git'],env=env,cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('Push disabled',result.stderr)
