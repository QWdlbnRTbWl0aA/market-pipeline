"""Offline regression for real refinement orchestration, provenance and recovery."""
import copy
import hashlib
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw,ImageChops
from studio_service import production,refinement
from studio_service.ports import Asset
from studio_service.storage import Invalid,read,write
import test_mockup_board as fixture
from test_lifestyle import Scenes


class Refiner(Scenes):
    def __init__(self):super().__init__();self.corrections=[];self.edits=[];self.pass_review=True;self.compare_calls=0;self.interrupt=False
    def mockup_correction(self,context,images,key,project):
        self.corrections.append((copy.deepcopy(context),images))
        return {'instruction':'Correct the grip; preserve actual printing and everything outside the hand.','change':['Realistic scissors grip'],'preserve':['Existing actual product print'],'checks':['Grip is realistic','Print matches actual product'],
                'edit_box':[.05,.05,.25,.2],'protected_regions':[]}
    def mockup_refinement_image(self,image,plan,key,project,export=False,output_size=None):
        self.edits.append({'image':image,'plan':copy.deepcopy(plan),'export':export,'size':output_size})
        im=Image.new('RGB',output_size,'#aa1111')
        if export:im=production.raster(image).resize(output_size)
        return Asset(production.png(im),'image/png','Synthetic targeted edit',{})
    def mockup_page_layers(self,image,scene,ids,key,project):
        # Fixture's actual page is a white rectangle. Real port maps occlusions.
        if self.bad:return {'surfaces':[]}
        return {'surfaces':[{'page_id':scene['page_id'],'usable':True,'reason':'Clear fixture','quad':[[.18,.28],[.82,.28],[.82,.92],[.18,.92]],'foreground_regions':[]}]}
    def mockup_compare(self,plan,images,key,project):
        self.compare_calls+=1
        if self.interrupt:self.interrupt=False;raise Invalid('Synthetic comparison interruption after image success')
        return {'checks':[{'requirement':c,'passed':self.pass_review,'evidence':'Synthetic fixture evidence'} for c in plan['checks']], 'product_matches_sources':self.pass_review,'preserved_content':True,'summary':'Synthetic correction passed' if self.pass_review else 'Scissors still rest on paper'}


class Targeted(unittest.TestCase):
    setUp=fixture.Board.setUp;state=fixture.Board.state;command=fixture.Board.command;produce=fixture.Board.produce;ready=fixture.Board.ready;board=fixture.Board.board;setup_board=fixture.Board.setup_board;lock=fixture.Board.lock
    def final_ready(self,n=2):
        cards=self.setup_board(n)
        for c in cards:self.lock(c)
        self.port=Refiner();self.studio.mockup_planner=self.port;self.studio.mockup_finals=self.port
        self.command('finalize_mockup_board',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.state()['phase'],'mockup_review')
        return self.board()['cards']

    def test_displayed_pixels_crop_and_resolved_plan_working_render_then_optional_export(self):
        concepts=self.setup_board(1);old=copy.deepcopy(concepts[0]['candidate']);directory=self.studio.directory(self.project)
        # Make background differ from the displayed composited product image.
        self.assertNotEqual(old['sha256'],old['background_sha256'])
        self.lock(concepts[0]);self.port=Refiner();self.studio.mockup_planner=self.port;self.studio.mockup_finals=self.port
        self.command('finalize_mockup_board',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.port.corrections[0][1][0],(directory/old['file']).read_bytes())
        self.assertNotEqual(self.port.corrections[0][1][0],(directory/old['background_file']).read_bytes())
        card=self.board()['cards'][0];candidate=card['candidate'];self.assertEqual(candidate['render_profile'],'working');self.assertTrue(candidate['refinement']['passed'])
        self.assertEqual(self.port.edits[0]['size'],(1152,768));self.assertFalse(self.port.edits[0]['export'])
        before=production.raster((directory/old['file']).read_bytes()).resize(tuple(candidate['native_size']),Image.Resampling.LANCZOS)
        after=production.raster((directory/candidate['file']).read_bytes());self.assertEqual(before.getpixel((after.width-5,5)),after.getpixel((after.width-5,5)))
        self.lock(card);calls=len(self.port.edits)
        with self.assertRaises(Invalid):self.command('export_mockup_board')
        self.assertEqual(len(self.port.edits),calls)
        self.command('export_mockup_board',consent_expensive=True);self.studio.tick()
        exported=self.board()['cards'][0];self.assertEqual(exported['candidate']['render_profile'],'export');self.assertFalse(exported['locked']);self.assertTrue(self.port.edits[-1]['export'])
        self.assertEqual((directory/old['file']).read_bytes(),self.port.corrections[0][1][0])

    def test_failed_correction_keeps_previous_candidate_and_records_attempt_without_retry(self):
        cards=self.final_ready();self.lock(cards[0]);unchanged=copy.deepcopy(self.board()['cards'][0]);old=copy.deepcopy(cards[1]['candidate'])
        self.port.pass_review=False;self.command('apply_mockup_comments',cards=[{'id':cards[1]['id'],'comments':'Paper BETWEEN rounded blades, not on top'}],consent_expensive=True);self.studio.tick()
        saved=self.board()['cards'][1];self.assertEqual(saved['candidate'],old);self.assertTrue(saved['needs_render']);self.assertIn('Scissors',saved['refinement_failure']['summary']);self.assertFalse(saved['refinement_attempts'][-1]['refinement']['passed'])
        self.assertEqual(self.board()['cards'][0],unchanged);before=len(self.port.edits);self.studio.tick();self.assertEqual(len(self.port.edits),before)
        with self.assertRaises(Invalid):self.lock(saved)
        with self.assertRaises(Invalid):self.command('approve_mockups')

    def test_bad_geometry_preserves_prior_image_without_buying_another_comparison(self):
        card=self.final_ready(1)[0];old=copy.deepcopy(card['candidate']);self.port.bad=True;before=self.port.compare_calls
        self.command('apply_mockup_comments',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.board()['cards'][0]['candidate'],old);self.assertEqual(self.port.compare_calls,before)
        self.assertIn('placement failed',self.board()['cards'][0]['refinement_failure']['summary'])

    def test_recovery_reuses_compilation_and_completed_render_after_comparison_interruption(self):
        self.final_ready(1);self.port.interrupt=True
        self.command('apply_mockup_comments',consent_expensive=True);self.studio.tick();self.assertEqual(self.state()['phase'],'generation_failed')
        calls=len(self.port.edits);plans=len(self.port.corrections)
        self.command('retry_workflow',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.state()['phase'],'mockup_review');self.assertEqual(len(self.port.edits),calls);self.assertEqual(len(self.port.corrections),plans)

    def test_restore_earlier_round_retains_history_assets_comments_and_ledger(self):
        cards=self.final_ready(1);s=self.state();first=s['workflow']['mockup_design']['rounds'][-1];directory=self.studio.directory(self.project);ledger=self.studio.budget.summary(self.project)
        self.command('apply_mockup_comments',cards=[{'id':cards[0]['id'],'comments':'A later edit'}],consent_expensive=True);self.studio.tick();later=copy.deepcopy(self.board()['cards']);rounds=copy.deepcopy(self.state()['workflow']['mockup_design']['rounds']);calls=len(self.port.edits)
        self.command('restore_mockup_round',round_id=first['id']);self.studio.tick();restored=self.board()['cards'][0]
        self.assertEqual(restored['candidate'],first['candidates'][0]);self.assertEqual(restored['comments'],'');self.assertFalse(restored['locked']);self.assertEqual(len(self.port.edits),calls)
        self.assertEqual(self.state()['workflow']['mockup_design']['rounds'],rounds);self.assertEqual(self.board()['restorations'][-1]['previous_cards'],later);self.assertEqual(self.studio.budget.summary(self.project),ledger)
        self.assertTrue((directory/later[0]['candidate']['file']).exists())

    def test_region_bounds_protected_pixels_and_foreground_layers(self):
        im=Image.new('RGB',(1536,1024),'#123456');plan={'edit_box':[.1,.1,.9,.9],'protected_regions':[[[.4,.4],[.6,.4],[.6,.6],[.4,.6]]]}
        canvas,rect=refinement.edit_canvas(im,plan);merged,mask=refinement.merge_patch(im,Image.new('RGB',canvas.size,'red'),plan,rect)
        self.assertEqual(merged.size,(1152,768));self.assertEqual(merged.getpixel((550,380)),(18,52,86));self.assertEqual(merged.getpixel((10,10)),(18,52,86));self.assertEqual(merged.getpixel((150,150)),(255,0,0))
        page=Image.new('RGB',(100,150),'blue');bg=Image.new('RGB',(1000,1000),'red');quad=[[.2,.2],[.8,.2],[.8,.9],[.2,.9]]
        surface={'page_id':'p','usable':True,'quad':quad,'foreground_regions':[[[.3,.3],[.4,.3],[.4,.4],[.3,.4]]]}
        result,placements=refinement.layers(bg,{'p':{'body':production.png(page),'record':{'sha256':'synthetic-source-hash'}}},{'surfaces':[surface]})
        self.assertEqual(result.getpixel((350,350)),(255,0,0));self.assertGreater(result.getpixel((500,500))[2],100);self.assertEqual(result.getpixel((500,500))[:2],(0,0));self.assertEqual(placements[0]['sha256'],'synthetic-source-hash')
        surface['foreground_regions']=[quad]
        with self.assertRaises(Invalid):refinement.layers(bg,{'p':{'body':production.png(page),'record':{'sha256':'synthetic'}}},{'surfaces':[surface]})
