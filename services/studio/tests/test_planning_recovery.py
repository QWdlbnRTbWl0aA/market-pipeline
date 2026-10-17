"""Whitespace-tail recovery must never infer truncated scene contents."""
import copy
import json
import unittest
from unittest.mock import patch
from studio_service.planning_recovery import recover
from studio_service.storage import Invalid,read,digest
import test_lifestyle as fixture
from studio_service.providers import OpenAIStudio
import io


def plan():return {'product_understanding':'A printable activity','direction':'Natural varied scenes','scenes':[{'title':'Activity','description':'Supervised activity on the floor','image_prompt':'A realistic supervised activity beside an unobstructed page.','page_id':'unit-01','scene_type':'usage'}]}


class Recovery(unittest.TestCase):
    def test_only_missing_containers_after_complete_scene_are_restored(self):
        raw=json.dumps(plan())[:-2]+' \r'*2542;value,suffix=recover(raw,1,['unit-01']);self.assertEqual(value,plan());self.assertEqual(suffix,']}')
        value,suffix=recover(json.dumps(plan())+' \r'*300,1,['unit-01']);self.assertEqual(value,plan());self.assertEqual(suffix,'')
    def test_unfinished_fields_wrong_counts_unknown_pages_or_duplicate_fields_fail(self):
        for raw,n,ids in [(json.dumps(plan())[:100]+' \r'*300,1,['unit-01']),
                          (json.dumps(plan())[:-2]+' \r'*300,2,['unit-01']),
                          (json.dumps(plan())[:-2]+' \r'*300,1,['unit-02']),
                          ('{"direction":"first",'+json.dumps(plan())[1:-2]+' \r'*300,1,['unit-01']),
                          (json.dumps(plan())[:-2]+' ',1,['unit-01'])]:
            with self.assertRaises(Invalid):recover(raw,n,ids)
    def test_completed_paid_response_is_recovered_from_cache_without_new_request(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);calls=[];model=OpenAIStudio(root,lambda req,timeout:calls.append(req) or io.BytesIO(json.dumps({'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'usage':{'input_tokens':10,'output_tokens':100},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(plan())[:-2]+' \r'*300}]}]}).encode()),lambda:'synthetic')
            context={'inventory':[{'id':'unit-01'}]}
            self.assertEqual(model.mockup_plan(context,1,'paid-once','a'*32),plan());self.assertEqual(model.mockup_plan(context,1,'paid-once','a'*32),plan());self.assertEqual(len(calls),1)
            receipts=list((root/'development-openai/steps').glob('*/validation-recovery.json'));self.assertEqual(len(receipts),1);self.assertEqual(read(receipts[0])['appended_closings'],']}');self.assertEqual(model.budget.summary('a'*32)['unknown_outcomes'],0)


class Actions(unittest.TestCase):
    setUp=fixture.Lifestyle.setUp;state=fixture.Lifestyle.state;command=fixture.Lifestyle.command;produce=fixture.Lifestyle.produce;ready=fixture.Lifestyle.ready
    def test_unchanged_explicit_apply_reuses_the_same_failed_operation(self):
        self.ready();original=self.port.mockup_plan
        def failure(*a,**k):raise Invalid('Synthetic deterministic failure')
        self.port.mockup_plan=failure;self.command('suggest_mockups',additional_count=1);self.studio.tick();first=self.state()['workflow']['pending']
        self.port.mockup_plan=original;self.command('apply_mockup_comments');self.assertEqual(self.state()['workflow']['pending'],first);self.studio.tick();self.assertEqual(self.state()['phase'],'mockup_review')
    def test_progress_does_not_serialize_source_rounds_or_invoke_full_get(self):
        with patch.object(self.studio,'get',side_effect=AssertionError('No full get during polling')):
            status=self.studio.progress(self.project)
        self.assertEqual(status['id'],self.project);self.assertNotIn('source_brief',status);self.assertNotIn('rounds',status);self.assertNotIn('brief',status)
