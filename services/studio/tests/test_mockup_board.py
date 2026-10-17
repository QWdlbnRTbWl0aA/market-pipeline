"""Offline card-level costs, locks, history and final refinement contracts."""
import copy
import unittest
import hashlib
from PIL import Image,ImageDraw
from studio_service import production
from studio_service.ports import Asset
from studio_service.storage import Invalid,read
import test_lifestyle as fixture


class Board(unittest.TestCase):
    setUp=fixture.Lifestyle.setUp
    state=fixture.Lifestyle.state
    command=fixture.Lifestyle.command
    produce=fixture.Lifestyle.produce
    ready=fixture.Lifestyle.ready
    plan=fixture.Lifestyle.plan
    concepts=fixture.Lifestyle.concepts
    def board(self):return self.state()['workflow']['mockup_design']['board']
    def setup_board(self,n=3):
        self.ready();self.command('plan_mockup_board',count=n);self.studio.tick();self.command('render_mockup_board');self.studio.tick()
        self.assertEqual(self.state()['phase'],'mockup_review');return self.board()['cards']
    def lock(self,card):self.command('toggle_mockup_lock',card_id=card['id'])

    def test_locked_pixels_and_prompts_skip_both_planning_and_generation(self):
        cards=self.setup_board();locked=copy.deepcopy(cards[0]);self.lock(cards[0]);before=len(self.port.images)
        self.command('plan_mockup_board',comments='Vary the two open scenes');self.studio.tick()
        self.assertEqual(len(self.port.plans[-1]['cards_to_plan']),2);self.assertEqual(self.port.plans[-1]['locked_scenes'],[locked['scene']])
        self.command('render_mockup_board');self.studio.tick();self.assertEqual(len(self.port.images),before+2)
        current=self.board()['cards'][0];self.assertTrue(current['locked']);self.assertEqual(current['candidate'],locked['candidate']);self.assertEqual(current['scene'],locked['scene'])
        with self.assertRaises(Invalid):self.command('save_mockup_board',cards=[{'id':current['id'],'comments':'Edit locked'}])
        self.lock(current);self.assertFalse(self.board()['cards'][0]['locked']);self.command('render_mockup_board');self.studio.tick();self.assertEqual(len(self.port.images),before+5)

    def test_delete_and_add_preserve_history_and_never_purchase_images(self):
        cards=self.setup_board();deleted=cards[1];path=self.studio.directory(self.project)/deleted['candidate']['file'];before=path.read_bytes();calls=len(self.port.images)
        self.command('delete_mockup_card',card_id=deleted['id']);self.command('add_mockup_card');self.studio.tick()
        self.assertEqual(len(self.port.images),calls);self.assertEqual(path.read_bytes(),before);self.assertEqual(len(self.board()['cards']),3)
        self.assertEqual(self.board()['deleted'][-1]['candidate'],deleted['candidate']);self.assertNotIn(deleted['id'],[c['id'] for c in self.board()['cards']])
        with self.assertRaises(Invalid):self.command('render_mockup_board')
        self.command('plan_mockup_board');self.studio.tick();self.command('render_mockup_board');self.studio.tick();self.assertEqual(len(self.board()['cards']),3)

    def test_final_loop_preserves_selected_reference_and_skips_locked_finals(self):
        cards=self.setup_board(2)
        with self.assertRaises(Invalid):self.command('enter_mockup_final')
        for card in cards:self.lock(card)
        before=len(self.port.images);self.command('enter_mockup_final');self.studio.tick();self.assertEqual(len(self.port.images),before)
        self.assertEqual(self.board()['stage'],'final')
        with self.assertRaises(Invalid):self.command('render_mockup_board')
        with self.assertRaises(Invalid):self.command('toggle_mockup_lock',card_id=cards[0]['id'])
        self.command('render_mockup_board',consent_expensive=True);self.studio.tick();finals=self.board()['cards'];self.assertEqual(len(self.port.images),before+2)
        self.assertEqual(self.port.images[-1]['reference']['background_sha256'],cards[-1]['candidate']['background_sha256'])
        self.lock(finals[0]);first=copy.deepcopy(self.board()['cards'][0]);other=finals[1]
        self.command('save_mockup_board',cards=[{'id':other['id'],'comments':'Fix six fingers and awkward face, preserve framing'}])
        self.command('render_mockup_board',consent_expensive=True);self.studio.tick();self.assertEqual(len(self.port.images),before+3);self.assertEqual(self.board()['cards'][0],first)
        self.assertIn('six fingers',self.port.images[-1]['comments']);self.assertTrue(self.port.images[-1]['final']);self.lock(self.board()['cards'][1])
        self.command('approve_mockups');self.command('generate_listing');self.studio.tick();self.assertEqual(self.copy.calls,1)

    def test_edited_prompt_cannot_lock_old_image_and_final_cannot_redesign(self):
        cards=self.setup_board(1);card=cards[0];scene={**card['scene'],'description':'Overhead view of the existing activity'}
        self.command('save_mockup_board',cards=[{'id':card['id'],'scene':scene}])
        with self.assertRaises(Invalid):self.lock(card)
        self.command('render_mockup_board');self.studio.tick();self.lock(self.board()['cards'][0]);self.command('enter_mockup_final')
        with self.assertRaises(Invalid):self.command('save_mockup_board',cards=[{'id':card['id'],'scene':{**scene,'description':'Change to a classroom'}}])
        self.command('return_mockup_concepts');self.assertEqual(self.board()['stage'],'concept');self.assertTrue(self.board()['cards'][0]['locked'])

    def test_read_only_legacy_projection_does_not_rewrite_state(self):
        self.ready();self.plan();self.concepts();directory=self.studio.directory(self.project);before=(directory/'state.json').read_bytes()
        board=self.board();self.assertEqual(len(board['cards']),3);self.assertEqual((directory/'state.json').read_bytes(),before)
        self.command('save_mockup_board');self.assertIn('board',read(directory/'state.json')['workflow']['mockup_design']);self.assertFalse(any(c['locked'] for c in self.board()['cards']))

    def test_multiple_surfaces_use_different_actual_pages_and_reject_overlap(self):
        self.ready();self.command('plan_mockup_board',count=1);self.studio.tick();card=self.board()['cards'][0]
        scene={**card['scene'],'scene_type':'spread'};self.command('save_mockup_board',cards=[{'id':card['id'],'scene':scene}])
        class Multi:
            overlap=False
            def mockup_scene(me,*args):
                image=Image.new('RGB',(1024,1024),'#67513c');draw=ImageDraw.Draw(image);draw.rectangle((100,200,400,850),fill='white');draw.rectangle((600,200,900,850),fill='white');return Asset(production.png(image),'image/png','Synthetic spread',{})
            def mockup_surfaces(me,image,scene,ids,*args):
                quads=[[[.1,.2],[.39,.2],[.39,.83],[.1,.83]],[[.59,.2],[.88,.2],[.88,.83],[.59,.83]]]
                if me.overlap:quads[1]=quads[0]
                return {'surfaces':[{'page_id':ids[i],'usable':True,'reason':'Clear','quad':quad} for i,quad in enumerate(quads)]}
        multi=Multi();self.studio.mockup_planner=multi;self.studio.mockup_drafts=multi
        self.command('render_mockup_board');self.studio.tick();candidate=self.board()['cards'][0]['candidate'];self.assertEqual(candidate['placement_status'],'ready');self.assertEqual(len(candidate['placements']),2);self.assertNotEqual(candidate['placements'][0]['page_id'],candidate['placements'][1]['page_id'])
        multi.overlap=True;self.command('render_mockup_board');self.studio.tick();candidate=self.board()['cards'][0]['candidate'];self.assertEqual(candidate['placement_status'],'needs_revision')
        with self.assertRaises(Invalid):self.lock(card)

    def test_interrupted_scene_recovery_does_not_repeat_completed_image_calls(self):
        self.ready();self.command('plan_mockup_board',count=3);self.studio.tick();self.port.fail_once=True
        self.command('render_mockup_board');self.studio.tick();self.assertEqual(self.state()['phase'],'generation_failed');before=len(self.port.images)
        self.studio.tick();self.assertEqual(len(self.port.images),before)
        self.command('retry_workflow',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.state()['phase'],'mockup_review');self.assertEqual(len(self.port.images),3);self.assertEqual(len({c['key'] for c in self.port.images}),3)

    def test_new_product_creates_fresh_board_without_discarding_previous_board(self):
        self.setup_board(1);old=copy.deepcopy(self.board());state=read(self.studio.directory(self.project)/'state.json')
        # Projection logic is independent of manufacture; use an alternate identity only here.
        state['workflow']['products'][-1]['id']='different-product-version'
        new=self.studio.workflow.lifestyle.board.state(state)
        self.assertEqual(new['cards'],[]);self.assertEqual(new['product_id'],'different-product-version');self.assertEqual(state['workflow']['mockup_design']['board_history'][-1],old)
