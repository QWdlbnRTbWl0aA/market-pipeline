"""Malformed legacy geometry cannot hide completed work or repeat paid steps."""
import copy
import unittest
from studio_service import refinement
from studio_service.storage import Invalid,read,write
from studio_service.dev_budget import BudgetBlocked
import test_targeted_refinement as fixture

ZERO_PLAN={'instruction':'Round only the scissors tips and put paper between blades.','change':['Rounded scissors tips','Paper between blades'],'preserve':['Actual product print'],'checks':['Rounded tips','Paper between blades'],'edit_box':[0,0,0,0],'protected_regions':[]}


class Partial(unittest.TestCase):
    setUp=fixture.Targeted.setUp;state=fixture.Targeted.state;command=fixture.Targeted.command;produce=fixture.Targeted.produce;ready=fixture.Targeted.ready;board=fixture.Targeted.board;setup_board=fixture.Targeted.setup_board;lock=fixture.Targeted.lock;final_ready=fixture.Targeted.final_ready
    def test_zero_rectangle_on_middle_card_preserves_completed_siblings_and_manual_area_reuses_plan(self):
        cards=self.final_ready(3);before=copy.deepcopy(cards);original=self.port.mockup_correction
        def malformed(context,*args):
            if context['card_comments']=='Second correction':return copy.deepcopy(ZERO_PLAN)
            return original(context,*args)
        self.port.mockup_correction=malformed
        self.command('apply_mockup_comments',cards=[{'id':c['id'],'comments':('Second correction' if i==1 else 'Grip only')} for i,c in enumerate(cards)],consent_expensive=True)
        self.studio.tick();saved=self.board()['cards'];self.assertEqual(self.state()['phase'],'mockup_review');self.assertIsNone(self.state()['workflow']['pending'])
        self.assertNotEqual(saved[0]['candidate']['id'],before[0]['candidate']['id']);self.assertNotEqual(saved[2]['candidate']['id'],before[2]['candidate']['id']);self.assertEqual(saved[1]['candidate'],before[1]['candidate'])
        self.assertEqual(saved[1]['refinement_failure']['correction_plan'],ZERO_PLAN);self.assertEqual(saved[1]['refinement_failure']['stage'],'correction_planning')
        calls=len(self.port.edits)
        with self.assertRaises(Invalid):self.command('apply_mockup_comments',consent_expensive=True)
        self.assertEqual(len(self.port.edits),calls)
        # A blocked card must not prevent a different edited card from running.
        self.command('save_mockup_board',cards=[{'id':cards[0]['id'],'comments':'Another first-card correction'}])
        self.command('apply_mockup_comments',consent_expensive=True);self.studio.tick()
        self.assertEqual(len(self.port.edits),calls+1);self.assertEqual(self.board()['cards'][1]['candidate'],before[1]['candidate'])
        saved=self.board()['cards'];calls=len(self.port.edits)
        self.command('save_mockup_board',cards=[{'id':cards[1]['id'],'edit_box':[.2,.2,.5,.6]}]);self.assertEqual(len(self.port.edits),calls)
        def forbidden(*a,**k):raise AssertionError('Manual bounds must reuse the saved interpretation')
        self.port.mockup_correction=forbidden
        self.command('apply_mockup_comments',consent_expensive=True);self.studio.tick()
        self.assertEqual(len(self.port.edits),calls+1);self.assertEqual(self.port.edits[-1]['plan']['edit_box'],[.2,.2,.5,.6]);self.assertIsNone(self.board()['cards'][1].get('refinement_failure'));self.assertIsNone(self.board()['cards'][1].get('edit_box'))
        self.assertEqual(self.board()['cards'][0]['candidate'],saved[0]['candidate']);self.assertEqual(self.board()['cards'][2]['candidate'],saved[2]['candidate'])
    def test_first_card_is_published_before_second_starts(self):
        cards=self.final_ready(2);old=cards[0]['candidate']['id'];original=self.port.mockup_correction;seen=[]
        def inspect(context,*args):
            if context['card_comments']=='Second':
                state=self.state();seen.append(state['workflow']['mockup_design']['board']['cards'][0]['candidate']['id'])
                self.assertEqual(state['phase'],'generating_mockups');self.assertEqual(state['workflow']['mockup_progress']['completed'],1)
            return original(context,*args)
        self.port.mockup_correction=inspect
        self.command('apply_mockup_comments',cards=[{'id':c['id'],'comments':('Second' if i else 'First')} for i,c in enumerate(cards)],consent_expensive=True);self.studio.tick()
        self.assertEqual(len(seen),1);self.assertNotEqual(seen[0],old)
    def test_no_cost_recovery_installs_saved_candidate_and_reports_missing_card(self):
        cards=self.final_ready(2);original=self.port.mockup_correction
        def stop(context,*args):
            if context['card_comments']=='Second':raise RuntimeError('Synthetic daemon interruption')
            return original(context,*args)
        self.port.mockup_correction=stop
        self.command('apply_mockup_comments',cards=[{'id':c['id'],'comments':('Second' if i else 'First')} for i,c in enumerate(cards)],consent_expensive=True);self.studio.tick();self.assertEqual(self.state()['phase'],'generation_failed')
        pending=self.state()['workflow']['pending'];directory=self.studio.directory(self.project);saved=read(directory/'state.json');completed=copy.deepcopy(saved['workflow']['mockup_design']['board']['cards'][0]['candidate'])
        # Reproduce the previous release's all-or-nothing board publication.
        saved['workflow']['mockup_design']['board']['cards'][0]['candidate']=cards[0]['candidate'];saved['workflow']['mockup_design']['board']['cards'][0]['refinement_attempts']=[];write(directory/'state.json',saved)
        calls=len(self.port.edits);ledger=self.studio.budget.summary(self.project)
        def forbidden(*a,**k):raise AssertionError('No provider call is allowed during saved-result recovery')
        self.port.mockup_correction=forbidden;self.port.mockup_refinement_image=forbidden;self.port.mockup_compare=forbidden
        self.command('recover_mockup_results');self.studio.tick()
        self.assertEqual(self.board()['cards'][0]['candidate'],completed);self.assertEqual(len(self.port.edits),calls);self.assertEqual(self.studio.budget.summary(self.project),ledger);self.assertIsNone(self.state()['workflow']['pending']);self.assertEqual(self.state()['phase'],'mockup_review')
        self.assertTrue((directory/'workflow-jobs'/pending/'saved-results-recovery.json').exists());self.assertIsNotNone(self.board()['cards'][1].get('refinement_failure'))
    def test_budget_block_stops_subsequent_cards_and_positive_region_schema_is_backward_compatible(self):
        cards=self.final_ready(2);calls=[]
        def blocked(*a,**k):calls.append(True);raise BudgetBlocked('Unknown accounting outcome')
        self.port.mockup_correction=blocked;self.command('apply_mockup_comments',consent_expensive=True);self.studio.tick();self.assertEqual(calls,[True]);self.assertEqual(self.state()['phase'],'generation_failed')
        positive={k:v for k,v in ZERO_PLAN.items() if k!='edit_box'};positive['edit_region']={'left':.2,'top':.3,'width':.2,'height':.4}
        self.assertEqual(refinement.checked_plan(positive)['edit_box'],[.2,.3,.4,.7])
        positive['edit_region']['width']=0
        with self.assertRaises(Invalid):refinement.checked_plan(positive)
