"""Human scene edits must survive lossy planner output and explicit recovery."""
import copy,json,unittest
from studio_service.storage import Invalid,read
import test_mockup_board as fixture
DESCRIPTION='דפי הגזירה מפוזרים זה על גבי זה על נייר עבה ואיכותי, ללא אנשים.'
class Feedback(unittest.TestCase):
    setUp=fixture.Board.setUp;state=fixture.Board.state;command=fixture.Board.command;produce=fixture.Board.produce;ready=fixture.Board.ready;board=fixture.Board.board;setup_board=fixture.Board.setup_board;lock=fixture.Board.lock
    def test_authored_description_and_comments_survive_planner_rewrite_and_reach_image(self):
        card=self.setup_board(1)[0];old=copy.deepcopy(card);images=[];original=self.port.mockup_scene
        def capture(scene,*args,**kwargs):images.append(copy.deepcopy(scene));return original(scene,*args,**kwargs)
        self.port.mockup_scene=capture
        scene={**card['scene'],'description':DESCRIPTION}
        self.command('apply_mockup_comments',cards=[{'id':card['id'],'scene':scene,'comments':'Keep clear thick paper edges'}]);self.studio.tick()
        saved=self.board()['cards'][0];candidate=saved['candidate']
        self.assertEqual(saved['scene'],scene);self.assertEqual(saved['comments'],'Keep clear thick paper edges')
        self.assertEqual(images[-1]['description'],DESCRIPTION);self.assertEqual(images[-1]['image_prompt'],DESCRIPTION)
        self.assertEqual(json.loads(self.port.images[-1]['comments'])['explicit_scene_edits']['description'],DESCRIPTION)
        self.assertEqual(candidate['requested_scene'],scene);self.assertEqual(candidate['scene_overrides']['description'],DESCRIPTION)
        self.assertEqual(self.port.plans[-1]['cards_to_plan'][0]['latest_scene_edits']['description'],DESCRIPTION)
        self.assertNotEqual(candidate['id'],old['candidate']['id']);self.lock(saved)
        self.command('toggle_mockup_lock',card_id=card['id'])
        self.command('apply_mockup_comments');self.studio.tick();self.assertEqual(images[-1]['image_prompt'],DESCRIPTION)
        self.assertEqual(self.board()['cards'][0]['scene'],scene)
    def test_explicit_advanced_prompt_takes_priority(self):
        card=self.setup_board(1)[0];scene={**card['scene'],'description':DESCRIPTION,'image_prompt':'Exact user advanced prompt: photograph thick printed paper edges'}
        self.command('apply_mockup_comments',cards=[{'id':card['id'],'scene':scene}]);self.studio.tick()
        self.assertEqual(self.board()['cards'][0]['candidate']['scene']['image_prompt'],scene['image_prompt'])
        self.assertEqual(self.board()['cards'][0]['scene'],scene)
    def test_return_from_final_keeps_final_history_then_edited_concept_is_preserved(self):
        card=self.setup_board(1)[0];self.lock(card);self.command('finalize_mockup_board',consent_expensive=True);self.studio.tick()
        final=copy.deepcopy(self.board()['cards'][0]['candidate']);self.command('return_mockup_concepts');self.command('toggle_mockup_lock',card_id=card['id'])
        scene={**self.board()['cards'][0]['scene'],'description':DESCRIPTION}
        self.command('apply_mockup_comments',cards=[{'id':card['id'],'scene':scene,'comments':'No hands over the paper'}]);self.studio.tick()
        saved=self.board()['cards'][0];self.assertEqual(saved['scene'],scene);self.assertEqual(saved['comments'],'No hands over the paper')
        self.assertEqual(saved['candidate']['scene']['image_prompt'],DESCRIPTION)
        self.assertTrue((self.studio.directory(self.project)/final['file']).exists())
