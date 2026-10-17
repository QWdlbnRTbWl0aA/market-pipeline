"""Combined user actions, role admission and failure recovery without paid calls."""
import copy
import unittest
from unittest.mock import patch
from pathlib import Path
from studio_service.storage import Invalid,Conflict,read
from studio_service.providers import PlanningFailure
from studio_service.model_roles import ModelRoles,credential_present
import test_lifestyle as fixture


class Actions(unittest.TestCase):
    setUp=fixture.Lifestyle.setUp
    state=fixture.Lifestyle.state
    command=fixture.Lifestyle.command
    produce=fixture.Lifestyle.produce
    ready=fixture.Lifestyle.ready
    def board(self):return self.state()['workflow']['mockup_design']['board']
    def setup_actions(self):
        self.ready();self.command('suggest_mockups',additional_count=3);self.studio.tick();self.assertEqual(self.state()['phase'],'mockup_review')
    def test_suggest_generates_only_additional_cards_and_apply_handles_empty_cards(self):
        self.setup_actions();old=copy.deepcopy(self.board()['cards']);before=len(self.port.images)
        self.command('suggest_mockups',additional_count=2);self.studio.tick();self.assertEqual(len(self.port.images),before+2)
        self.assertEqual(self.board()['cards'][:3],old);self.assertEqual(len(self.port.plans[-1]['cards_to_plan']),2)
        self.command('toggle_mockup_lock',card_id=old[0]['id']);self.command('add_mockup_card')
        self.command('apply_mockup_comments',comments='More varied gallery');self.studio.tick();self.assertEqual(len(self.port.images),before+7)
        self.assertEqual(self.board()['cards'][0]['candidate'],old[0]['candidate']);self.assertTrue(all(c['scene'] and c['candidate'] for c in self.board()['cards']))
    def test_known_incomplete_plan_can_be_replaced_and_diagnostic_is_preserved(self):
        self.ready();original=self.port.mockup_plan
        def failure(*a,**k):raise PlanningFailure({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[{'type':'message','content':[{'type':'output_text','text':'Partial fixture JSON'}]}]},'mockup_planning','synthetic text')
        self.port.mockup_plan=failure;self.command('suggest_mockups',additional_count=1);self.studio.tick();failed=self.state();old=failed['workflow']['pending']
        self.assertTrue(failed['mockup_recovery']['can_replace']);self.assertEqual(failed['generation_diagnostic']['response']['incomplete_details']['reason'],'max_output_tokens')
        self.port.mockup_plan=original;self.command('apply_mockup_comments');self.studio.tick()
        self.assertEqual(self.state()['phase'],'mockup_review');folder=self.studio.directory(self.project)/'workflow-jobs'/old
        self.assertTrue((folder/'replaced.json').exists());self.assertTrue((folder/'diagnostic.json').exists());self.assertEqual(read(folder/'operation.json')['status'],'failed');self.assertEqual(len(self.port.images),1)
    def test_unknown_billing_cannot_be_replaced(self):
        self.ready()
        def failure(*a,**k):raise Invalid('Unknown synthetic billing outcome')
        self.port.mockup_plan=failure;self.command('suggest_mockups',additional_count=1);self.studio.tick();self.studio.budget.reserve('unknown-fixture',self.project,10,'mockup_planning')
        self.assertFalse(self.state()['mockup_recovery']['can_replace'])
        with self.assertRaises(Conflict):self.command('apply_mockup_comments')
    def test_finalization_is_one_consented_action_and_model_choice_cannot_change_cheap_roles(self):
        self.setup_actions();other=fixture.Scenes();roles=ModelRoles({'openai':['mockup_final_images'],'google':['mockup_final_images']},available=lambda p:True)
        roles.register_final('first','First','openai',self.port,tier='top_tier',capability='image_edit');roles.register_final('second','Second','google',other,tier='top_tier',capability='image_edit');self.studio.model_roles=roles
        for c in self.board()['cards']:self.command('toggle_mockup_lock',card_id=c['id'])
        with self.assertRaises(Invalid):self.command('finalize_mockup_board',model_id='second')
        with self.assertRaises(Invalid):self.command('finalize_mockup_board',model_id='ollama',consent_expensive=True)
        before=len(self.port.images);self.command('finalize_mockup_board',model_id='second',consent_expensive=True);self.studio.tick()
        self.assertEqual(len(other.images),3);self.assertTrue(all(c['final'] for c in other.images));self.assertEqual(len(self.port.images),before)
        self.assertEqual(self.board()['cards'][0]['candidate']['model_id'],'second');self.assertEqual(self.board()['final_model_id'],'second');first=self.board()['cards'][0];self.command('toggle_mockup_lock',card_id=first['id'])
        self.command('apply_mockup_comments',model_id='first',consent_expensive=True);self.studio.tick();self.assertEqual(len(self.port.images),before+2);self.assertEqual(self.board()['cards'][0]['candidate'],first['candidate'])
    def test_combined_job_recovery_reuses_its_completed_plan_and_images(self):
        self.ready();self.port.fail_once=True;self.command('suggest_mockups',additional_count=3);self.studio.tick();self.assertEqual(self.state()['phase'],'generation_failed')
        self.command('retry_workflow',consent_expensive=True);self.studio.tick();self.assertEqual(self.state()['phase'],'mockup_review');self.assertEqual(len(self.port.plans),1);self.assertEqual(len(self.port.images),3)
    def test_registry_requires_key_metadata_and_explicit_top_tier_capability(self):
        present={'openai':True};roles=ModelRoles(available=lambda p:present.get(p,False))
        roles.register_final('professional','Professional','openai',object(),tier='top_tier',capability='image_edit');self.assertEqual(roles.final_options(),[])
        roles.roles['openai'].append('mockup_final_images');self.assertEqual(len(roles.final_options()),1);present['openai']=False;self.assertEqual(roles.final_options(),[])
        self.assertNotIn('mockup_final_images',ModelRoles().roles['openai'])
        with self.assertRaises(Invalid):roles.select_final('professional')
        with self.assertRaises(Invalid):roles.register_final('cheap','Cheap','openai',object(),tier='cheap',capability='image_edit')
        with self.assertRaises(Invalid):roles.register_final('text','Text','openai',object(),tier='top_tier',capability='reasoning')
        path=self.root/'protected.env';path.write_text('OPENAI_API_KEY=synthetic\n');path.chmod(0o600)
        with patch.dict('os.environ',{'STUDIO_OPENAI_CREDENTIAL_FILE':str(path)}),patch.object(Path,'read_text',side_effect=AssertionError('Discovery must not read key values')):
            self.assertTrue(credential_present('openai'))
