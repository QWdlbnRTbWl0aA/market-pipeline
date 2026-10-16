"""Real adapter contract tests with fake HTTP only; no keys or paid requests."""
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio_service.core import Studio
from studio_service.openai_dev import OpenAIDev
from studio_service.storage import canonical, read, write
from test_development import png


class GenerationFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_local_file_broker_is_durable_and_idempotent(self):
        from studio_service.adapters import FileBroker
        from studio_service.server import configuration,DEFAULT
        from studio_service.storage import Conflict
        path=self.root/'config.json';write(path,{**DEFAULT,'broker_provider':'file'})
        self.assertEqual(configuration(path)['broker_provider'],'file')
        message={'event_id':'notification','message':'נדרשת בחירה'}
        broker=FileBroker(self.root/'inbox');receipt=broker.publish(message)
        self.assertEqual(receipt['provider'],'file')
        self.assertEqual(FileBroker(broker.root).publish(message),receipt)
        self.assertEqual(read(broker.root/'notification.json'),message)
        with self.assertRaises(Conflict):broker.publish({**message,'message':'Different'})

    def test_any_bounded_brief_is_passive_and_can_start(self):
        for index,brief in enumerate(({},'חנוכה בצבעי מים',{'vision':'Five holiday prints'},{'custom_notes':'Paint five candles'})):
            with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
                studio=Studio(self.root/str(index))
                state=studio.create(brief,'intake')['project']
                self.assertEqual(state['phase'],'brief_ready');self.assertEqual(state['missing_information'],[])
                self.assertEqual(state['rounds'],[])
                studio.command(state['id'],'start_sketches',{'revision':state['revision']},'start')
                studio.tick();self.assertEqual(studio.get(state['id'])['round_number'],1)

    def test_exact_image_bodies_use_rich_brief_and_each_round_feedback(self):
        bodies=[]
        def transport(req,timeout):
            body=json.loads(req.data)
            if req.full_url.endswith('/images/generations'):
                bodies.append(body)
                result={'usage':{'input_tokens_details':{'text_tokens':100,'image_tokens':0},'output_tokens':272},
                        'data':[{'b64_json':base64.b64encode(png()).decode()} for _ in range(body['n'])]}
            else:
                samples=[{'index':i,'description':'נרות בצבעי מים','subject':'candles','palette':'blue',
                          'composition':'centered','style':'watercolor','texture':'paper','bundle_cohesion':'consistent'} for i in range(1,4)]
                result={'status':'completed','usage':{'input_tokens':100,'output_tokens':50},
                        'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'samples':samples})}]}]}
            return io.BytesIO(json.dumps(result).encode())
        adapter=OpenAIDev(self.root,transport,lambda:'fixture')
        studio=Studio(self.root,sketches=adapter,professional=adapter,development=True)
        document={'vision':'חמש תמונות חנוכה','content_units':[{'subject':'חנוכייה עם שמונה קנים ושמש'}],
                  'design_directions':[{'name':'אקוורל','texture':'hand painted cotton paper'}]}
        project=studio.create(document,'intake')['project'];identity=project['id']
        studio.command(identity,'start_sketches',{'revision':project['revision']},'start');studio.tick()
        state=studio.get(identity);self.assertEqual(state['phase'],'sketch_review');self.assertEqual(state['round_number'],1)
        self.assertEqual(state['runtime_providers']['sketch'],'openai_dev')
        self.assertIn('חנוכייה',bodies[0]['prompt']);self.assertIn('cotton paper',bodies[0]['prompt'])
        first_operation=state['active_operation'];reviews={c['id']:{'decision':'reject' if i==1 else 'accept',
                    'comment':'Keep handwork texture' if i==0 else ''} for i,c in enumerate(state['rounds'][-1]['candidates'])}
        studio.command(identity,'regenerate_batch',{'revision':state['revision'],'reviews':reviews,'comments':'Only candles; warm gold, remove blue'},'batch')
        studio.tick();state=studio.get(identity)
        self.assertEqual(state['phase'],'sketch_review');self.assertEqual(state['round_number'],2)
        self.assertNotEqual(first_operation,state['active_operation']);self.assertEqual(len(bodies),2)
        self.assertIn('warm gold',bodies[1]['prompt']);self.assertIn('Keep handwork texture',bodies[1]['prompt'])
        self.assertNotEqual(bodies[0]['prompt'],bodies[1]['prompt'])
        calls=studio.payloads(identity)['calls'];image_calls=[c for c in calls if c['endpoint']=='images/generations']
        self.assertEqual(len(image_calls),2)
        saved_bodies=[studio.payloads(identity,c['id'])['body'] for c in image_calls]
        self.assertCountEqual([canonical(b) for b in saved_bodies],[canonical(b) for b in bodies])
        self.assertTrue(all(c['status']=='response_received' for c in calls))
        self.assertNotIn('Bearer fixture',canonical(studio.payloads(identity,image_calls[0]['id'])).decode())
        before=len(bodies);studio.tick();self.assertEqual(len(bodies),before)
        other=studio.create({},'other')['project']['id']
        self.assertEqual(studio.payloads(other)['calls'],[])
        with self.assertRaises(FileNotFoundError):studio.payloads(other,image_calls[0]['id'])

    def test_prepared_request_is_not_misrepresented_as_dispatched(self):
        studio=Studio(self.root);project=studio.create({},'intake')['project']['id']
        def missing_key():raise RuntimeError('Key unavailable')
        adapter=OpenAIDev(self.root,transport=lambda *a,**k:self.fail('Network called'),credentials=missing_key)
        with self.assertRaises(Exception):adapter.text({'test':'brief'}, {},'request',project)
        call=studio.payloads(project)['calls'][0]
        self.assertEqual(call['status'],'prepared_dispatch_unconfirmed')
        self.assertEqual(call['accounting_status'],'reserved_unknown')
        self.assertEqual(studio.budget.summary(project)['unknown_outcomes'],1)
