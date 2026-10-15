"""Three-sample review and bounded reference processing, with mock providers only."""
import base64
import importlib.util
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from studio_service.core import Studio
from studio_service.storage import Invalid,read
from studio_service.references import thumbnail
from test_studio import BRIEF,RecordingGenerator
from test_development import png


class Batches(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.generator=RecordingGenerator();self.studio=Studio(self.tmp.name,sketches=self.generator,development=True)
    def project(self,**extra):
        project=self.studio.create({**BRIEF,**extra},'intake',library=False)['project']['id'];self.studio.tick();return project,self.studio.get(project)
    def test_all_three_reviews_and_shared_comment_are_required_and_aggregated(self):
        project,state=self.project();samples=state['rounds'][-1]['candidates'];self.assertEqual(len(samples),3)
        reviews={c['id']:{'decision':'reject' if i==1 else 'accept','comment':''} for i,c in enumerate(samples)}
        with self.assertRaises(Invalid):self.studio.command(project,'regenerate_batch',{'revision':state['revision'],'reviews':{samples[0]['id']:reviews[samples[0]['id']]}},'partial')
        self.studio.command(project,'regenerate_batch',{'revision':state['revision'],'reviews':reviews,'comments':'Keep blue; use a boy'},'batch');self.studio.tick()
        request=self.generator.requests[-1];self.assertEqual(request['count'],3);self.assertEqual(len(request['accepted']),2);self.assertEqual(len(request['rejected']),1)
        self.assertIn('Keep blue',request['optimized_prompt']);self.assertEqual(len(request['feedback_context']['evidence']),3)
        self.assertTrue(list((self.studio.directory(project)/'reasoning-log').glob('*.json')))
    @unittest.skipUnless(importlib.util.find_spec('PIL'),'Optional Pillow runtime unavailable')
    def test_references_are_compressed_fixed_and_never_fetched(self):
        with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            project,state=self.project(reference_images=['data:image/png;base64,'+base64.b64encode(png()).decode()])
        reference=state['reference_images'][0];body=(self.studio.directory(project)/reference['file']).read_bytes()
        self.assertLessEqual(len(body),80000);self.assertLessEqual(reference['width'],512);self.assertTrue(body.startswith(b'\xff\xd8'))
        self.assertEqual(hashlib.sha256(body).hexdigest(),reference['sha256']);self.assertEqual(self.generator.requests[0]['reference_images'],state['reference_images'])
        with self.assertRaises(Invalid):self.studio.command(project,'start_over',{'revision':state['revision'],'reference_images':[]},'changed-references')
    def test_invalid_remote_and_too_many_references_stop_before_generation(self):
        for refs in (['https://example.com/image.png'],['data:image/png;base64,invalid'],['x']*4):
            with self.assertRaises(Invalid):self.studio.create({**BRIEF,'reference_images':refs},str(len(refs)),library=False)
        self.assertEqual(self.generator.requests,[])
    @unittest.skipUnless(importlib.util.find_spec('PIL'),'Optional Pillow runtime unavailable')
    def test_large_input_is_reduced_and_metadata_removed(self):
        from PIL import Image
        image=Image.new('RGB',(1800,1200),'blue');buffer=io.BytesIO();image.save(buffer,format='JPEG',comment=b'private fixture metadata')
        body,size=thumbnail(buffer.getvalue());self.assertEqual(size,(512,341));self.assertNotIn(b'private fixture metadata',body);self.assertLess(len(body),80000)
    def test_legacy_ten_sample_history_is_retained_then_new_batch_has_three(self):
        project,state=self.project();directory=self.studio.directory(project)
        from studio_service.storage import write
        state['rounds'][0]['candidates'] += [{**state['rounds'][0]['candidates'][0],'id':'legacy-'+str(i)} for i in range(7)]
        write(directory/'state.json',state);samples=state['rounds'][-1]['candidates'][:3]
        self.studio.command(project,'regenerate_batch',{'revision':state['revision'],'reviews':{c['id']:{'decision':'accept','comment':''} for c in samples}},'legacy-batch');self.studio.tick()
        current=self.studio.get(project);self.assertEqual(len(current['rounds'][0]['candidates']),10);self.assertEqual(len(current['rounds'][-1]['candidates']),3)


if __name__=='__main__':unittest.main()
