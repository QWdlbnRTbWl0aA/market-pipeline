"""Full staged mockup flow with offline, replaceable model ports."""
import copy
import hashlib
from PIL import Image,ImageDraw
import unittest
from studio_service import production
from studio_service.ports import Asset
from studio_service.storage import Invalid,read
import test_production_workflow as fixture


class Scenes:
    def __init__(self):self.plans=[];self.planner_image_counts=[];self.images=[];self.surfaces=[];self.bad=False;self.fail_once=False
    def mockup_plan(self,context,number,key,project,images=()):
        self.plans.append(copy.deepcopy(context));self.planner_image_counts.append(len(images));ids=[u['id'] for u in context['inventory']]
        return {'product_understanding':'A saved product for shared family activity.','direction':'Warm supervised use, based on the brief and comments.',
            'scenes':[{'title':f'Family scene {i+1}','description':f'Adult and child using page {i+1} at a table.','image_prompt':'Warm natural photographic setting; large clear blank sheet.','page_id':ids[i%len(ids)]} for i in range(number)]}
    def mockup_scene(self,scene,comments,key,project,final=False,reference=None):
        self.images.append({'key':key,'final':final,'comments':comments,'reference':reference});size=(1536,1024) if final else (1024,1024)
        im=Image.new('RGB',size,'#bcb4a6');draw=ImageDraw.Draw(im);draw.rectangle((size[0]*.18,size[1]*.28,size[0]*.82,size[1]*.92),fill='white')
        return Asset(production.png(im),'image/png',scene['title'],{'synthetic':True})
    def mockup_surface(self,image,key,project):
        self.surfaces.append(key)
        if self.fail_once and len(self.surfaces)==2:self.fail_once=False;raise Invalid('Synthetic local surface-parser interruption')
        return {'usable':not self.bad,'reason':'Clear blank sheet' if not self.bad else 'Hand covers the sheet','quad':[[.18,.28],[.82,.28],[.82,.92],[.18,.92]]}


class Lifestyle(unittest.TestCase):
    setUp=fixture.Manufacturing.setUp
    state=fixture.Manufacturing.state
    command=fixture.Manufacturing.command
    produce=fixture.Manufacturing.produce
    def ready(self):
        self.port=Scenes();self.studio.mockup_planner=self.port;self.studio.mockup_drafts=self.port;self.studio.mockup_finals=self.port
        self.produce();self.command('approve_product',visual_review_confirmed=True)
    def plan(self,n=3):self.command('plan_mockups',count=n,comments='Warm family atmosphere, supervised play');self.studio.tick()
    def concepts(self):self.command('generate_mockup_concepts');self.studio.tick()
    def reviews(self):return {c['id']:'accept' if i<2 else 'reject' for i,c in enumerate(self.state()['workflow']['mockup_design']['rounds'][-1]['candidates'])}

    def test_five_cheap_concepts_then_two_selected_finals_with_comments_and_source_provenance(self):
        self.ready();manifest=self.state()['workflow']['products'][-1];self.plan(5)
        self.assertEqual(len(self.port.plans),1);self.assertEqual(self.port.images,[])
        self.assertEqual(self.state()['workflow']['mockup_design']['status'],'plan_review');self.concepts()
        self.assertEqual(len(self.port.images),5);self.assertTrue(all(not c['final'] for c in self.port.images))
        with self.assertRaises(Invalid):self.command('approve_mockups')
        with self.assertRaises(Invalid):self.command('finalize_mockups',mockup_reviews=self.reviews())
        self.command('finalize_mockups',mockup_reviews=self.reviews(),comments='Keep warm light; clearer adult supervision',consent_expensive=True);self.studio.tick()
        state=self.state();self.assertEqual(len(state['workflow']['mockups']),2);self.assertEqual(state['workflow']['products'][-1],manifest)
        final=[c for c in self.port.images if c['final']];self.assertEqual(len(final),2);self.assertTrue(all(c['reference'] and 'supervision' in c['comments'] for c in final))
        for m in state['workflow']['mockups']:
            self.assertEqual(m['origin'],'generative_lifestyle');self.assertEqual(m['quality'],'final');self.assertEqual(m['product_id'],manifest['id'])
            self.assertEqual(hashlib.sha256((self.studio.directory(self.project)/m['file']).read_bytes()).hexdigest(),m['sha256'])
        self.command('approve_mockups');self.assertEqual(self.state()['phase'],'listing_review')
        self.assertEqual(len(list((self.root/'scene-memory').glob('*.json'))),1)  # Identical synthetic backgrounds deduplicate.
        self.command('save_mockup_feedback',comments='Change the final setting to a family kitchen')
        before=len(self.port.images)
        with self.assertRaises(Invalid):self.command('generate_listing')
        self.studio.tick();self.assertEqual(len(self.port.images),before)

    def test_refinement_planner_receives_combined_history_and_explicit_feedback(self):
        self.ready();self.plan();self.concepts();reviews=self.reviews()
        self.command('plan_mockups',count=4,mockup_reviews=reviews,comments='No classroom; cozy family dining table');self.studio.tick()
        self.assertEqual(self.port.plans[-1]['comments'],'No classroom; cozy family dining table')
        self.assertEqual(self.port.plans[-1]['prior_assessments'][-1]['reviews'],reviews)
        self.assertEqual(self.port.planner_image_counts[-1],6);self.assertEqual(len(self.port.images),3);self.concepts();self.assertEqual(len(self.state()['workflow']['mockup_design']['rounds']),2)

    def test_local_interruption_reuses_completed_images_and_idle_does_not_retry(self):
        self.ready();self.plan();self.port.fail_once=True;self.concepts();self.assertEqual(self.state()['phase'],'generation_failed');before=len(self.port.images)
        self.studio.tick();self.assertEqual(len(self.port.images),before)
        self.command('retry_workflow',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.state()['phase'],'mockup_review');self.assertEqual(len(self.port.images),3)
        self.assertEqual(len({c['key'] for c in self.port.images}),3)

    def test_unusable_planes_are_visible_but_cannot_be_promoted_or_approved(self):
        self.ready();self.plan();self.port.bad=True;self.concepts();state=self.state();self.assertEqual(state['phase'],'mockup_review')
        candidates=state['workflow']['mockup_design']['rounds'][-1]['candidates'];self.assertEqual(len(candidates),3)
        self.assertTrue(all(c['placement_status']=='needs_revision' and not c['source_composited'] for c in candidates))
        with self.assertRaises(Invalid):self.command('finalize_mockups',mockup_reviews=self.reviews(),consent_expensive=True)
        self.studio.tick();self.assertEqual(len(self.port.images),3)

    def test_count_bounds_and_persisted_notes_make_no_provider_call(self):
        self.ready()
        for value in (0,11,True,'3'):
            with self.assertRaises(Invalid):self.command('plan_mockups',count=value)
        self.command('save_mockup_feedback',count=7,comments='Warm family scene');self.studio.tick()
        design=self.state()['workflow']['mockup_design'];self.assertEqual(design['count'],7);self.assertEqual(design['comments'],'Warm family scene');self.assertEqual(self.port.plans,[]);self.assertEqual(self.port.images,[])

    def test_bad_geometry_is_rejected_before_pasting_artwork(self):
        from studio_service.lifestyle import checked_surface
        for quad in ([[.1,.1],[.9,.9],[.9,.1],[.1,.9]],[[0,0],[1,0],[1,1],[0,1]],[[.1,.1],[.2,.1],[.2,.2],[.1,.2]]):
            with self.assertRaises(Invalid):checked_surface({'usable':True,'quad':quad})

    def test_paper_edge_fit_corrects_an_inscribed_model_box_without_network(self):
        from studio_service.lifestyle import fit_paper
        image=Image.new('RGB',(1200,1000),'#775231');draw=ImageDraw.Draw(image);expected=[(350,220),(800,200),(1000,900),(180,900)];draw.polygon(expected,fill='#f5f5f4')
        fitted=fit_paper(image,[[.35,.3],[.65,.3],[.65,.65],[.35,.65]])
        for actual,target in zip(fitted,expected):
            self.assertAlmostEqual(actual[0],target[0]/1200,delta=.015);self.assertAlmostEqual(actual[1],target[1]/1000,delta=.015)

    def test_local_geometry_refresh_uses_saved_backgrounds_without_provider_calls(self):
        self.ready();self.plan();self.concepts();before=len(self.port.images);backgrounds=[c['background_sha256'] for c in self.state()['workflow']['mockup_design']['rounds'][-1]['candidates']]
        self.command('refresh_mockup_geometry');self.assertEqual(len(self.port.images),before)
        rounds=self.state()['workflow']['mockup_design']['rounds'];self.assertEqual(len(rounds),2);self.assertTrue(all(c['geometry_version']==2 for c in rounds[-1]['candidates']))
        self.assertEqual([c['background_sha256'] for c in rounds[-1]['candidates']],backgrounds)
