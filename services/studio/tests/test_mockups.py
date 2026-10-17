"""Deterministic scene composition, edit persistence and source integrity."""
import hashlib
from PIL import Image,ImageChops
from studio_service import production
from studio_service.core import Studio
from studio_service.storage import Invalid,read
import test_production_workflow as fixture


import unittest


class Mockups(unittest.TestCase):
    setUp=fixture.Manufacturing.setUp
    state=fixture.Manufacturing.state
    command=fixture.Manufacturing.command
    produce=fixture.Manufacturing.produce
    # Reuse the independent temporary workflow fixture, not its test cases.
    def test_scene_rendering_is_deterministic_and_does_not_modify_source_pages(self):
        page=Image.new('RGB',(600,900),'#346f8a');pages=[page,Image.new('RGB',(600,900),'#d3aa63')];before=[p.tobytes() for p in pages]
        settings={'kind':'bundle','scale':.82,'x':0,'y':0,'perspective':'right','background':'#eee8df','crop':[0,0,1,1]}
        first,metadata=production.compose_mockup(production.contact_sheet(pages),settings,pages)
        second,again=production.compose_mockup(production.contact_sheet(pages),settings,pages)
        self.assertEqual(first.tobytes(),second.tobytes());self.assertEqual(metadata,again);self.assertEqual([p.tobytes() for p in pages],before)
        self.assertEqual(metadata['displayed_pages'],2);self.assertEqual(metadata['renderer_version'],'studio-scenes-v2')
        self.assertEqual(metadata['source_page_hashes'],[hashlib.sha256(production.png(p)).hexdigest() for p in pages])

    def test_perspective_keeps_the_stack_instead_of_erasing_backing_pages(self):
        page=Image.new('RGB',(600,900),'#346f8a');settings={'perspective':'left','scale':.7,'x':0,'y':0}
        flat,_=production.compose_mockup(page,{**settings,'kind':'flat'})
        stack,metadata=production.compose_mockup(page,{**settings,'kind':'stack'},[page])
        self.assertIsNotNone(ImageChops.difference(flat,stack).getbbox());self.assertEqual(metadata['displayed_pages'],3)

    def test_zero_positions_crop_background_and_scale_persist_without_generation(self):
        record=self.produce();self.command('approve_product',visual_review_confirmed=True);count=len(self.images.requests)
        values=[{'kind':kind,'scale':.62,'x':0,'y':0,'background':'#dfe7e2','perspective':'left','crop':[.02,.02,.98,.98]} for kind in ('flat','stack','bundle')]
        self.command('make_mockups',templates=values)
        self.assertEqual([m['template'] for m in self.state()['workflow']['mockups']],values);self.assertEqual(len(self.images.requests),count)
        restored=Studio(self.root);self.assertEqual([m['template'] for m in restored.get(self.project)['workflow']['mockups']],values)
        self.assertEqual(restored.get(self.project)['workflow']['products'][-1],record)
        self.assertNotIn('mockups',self.state()['workflow']['approvals'])

    def test_non_finite_offsets_and_scale_cannot_generate_broken_scenes(self):
        page=Image.new('RGB',(600,900),'white')
        for setting in ({'scale':float('nan')},{'x':float('inf')},{'crop':[0,0,float('nan'),1]}):
            with self.assertRaises(Invalid):production.compose_mockup(page,{'kind':'flat',**setting})
