import json
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from pipeline_control.controller import Controller
from pipeline_control.storage import write

class PersistenceFailureTests(unittest.TestCase):
 def test_disk_full_before_ack_never_creates_submission(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);settings={'data_root':str(root/'control'),'saved_runs_root':str(root/'runs')};c=Controller(settings)
   payload={'schema_version':1,'service':'search_refinement','delivery_id':'a'*64,'status':'failed','source_run_id':'fixture'}
   with patch('pipeline_control.controller.write',side_effect=OSError('Synthetic disk full')),self.assertRaises(OSError):c.receive(json.dumps(payload).encode())
   self.assertEqual(list((c.root/'inbox').glob('*.json')),[]);self.assertEqual(list((c.root/'proposals').glob('*.json')),[])
 def test_unknown_envelope_version_is_rejected_before_saved_queue(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=Controller({'data_root':tmp,'saved_runs_root':tmp+'/runs'})
   with self.assertRaises(ValueError):c.receive(json.dumps({'schema_version':1,'service':'search_refinement','delivery_id':'a'*64,'envelope':{'schema_version':2,'event_type':'analysis_completed'}}).encode())
