"""Offline full-image edit flow and original-output visibility under failure."""
import base64,copy,io,json,unittest
from studio_service import generated_images
from studio_service.providers import OpenAIStudio
from studio_service.dev_budget import Budget
from studio_service.storage import Invalid,read
import test_mockup_board as bf
import test_real_providers as pf
COMMENT='קצה הלהבים של המספריים צריך להיות מעוגל ולא חד. הדף צריך להיות בין להבי המספריים.'
class Provider(unittest.TestCase):
    setUp=pf.Providers.setUp;image=pf.Providers.image;transport=pf.Providers.transport
    def model(self,transport=None):return OpenAIStudio(self.root,transport or self.transport,lambda:'synthetic',limit_usd=25,image_model='gpt-image-2.5-sunburst')
    def test_exact_image_hebrew_prompt_raw_output_cache_and_project_isolation(self):
        model=self.model();pixels=self.image(1536,1024);result=model.mockup_direct_image(pixels,COMMENT,'','exact',self.project)
        self.assertEqual(len(self.calls),1);url,wire,_=self.calls[0];self.assertTrue(url.endswith('/images/edits'))
        self.assertEqual(wire['prompt'],COMMENT);self.assertEqual(base64.b64decode(wire['images'][0]['image_url'].split(',')[1]),pixels)
        self.assertEqual(wire['size'],'1152x768');self.assertEqual(wire['quality'],'medium')
        catalog=generated_images.items(self.root,self.project);self.assertEqual(len(catalog['images']),1)
        entry,original=generated_images.items(self.root,self.project,catalog['images'][0]['id']);self.assertEqual(result.content,original);self.assertTrue(entry['previewable'])
        model.mockup_direct_image(pixels,COMMENT,'','exact',self.project);self.assertEqual(len(self.calls),1)
        before=(self.root/'development-openai/budget.json').read_bytes();generated_images.items(self.root,self.project)
        self.assertEqual((self.root/'development-openai/budget.json').read_bytes(),before)
        self.assertEqual(generated_images.items(self.root,'b'*32)['images'],[])
        with self.assertRaises(FileNotFoundError):generated_images.items(self.root,'b'*32,entry['id'])
    def test_images_remain_visible_after_dimension_count_or_accounting_failure(self):
        for mode in ('size','multiple','usage'):
            with self.subTest(mode=mode):
                def transport(req,timeout):
                    value={'data':[{'b64_json':base64.b64encode(self.image(512,512)).decode()} for _ in range(2 if mode=='multiple' else 1)]}
                    if mode!='usage':value['usage']={'input_tokens_details':{'text_tokens':10,'image_tokens':10},'output_tokens':10}
                    return io.BytesIO(json.dumps(value).encode())
                before=len(generated_images.items(self.root,self.project)['images'])
                with self.assertRaises((Invalid,ValueError,KeyError)):self.model(transport).mockup_direct_image(self.image(),COMMENT,'',mode,self.project)
                images=generated_images.items(self.root,self.project)['images'];self.assertEqual(len(images)-before,2 if mode=='multiple' else 1)
                for item in images:self.assertTrue(generated_images.items(self.root,self.project,item['id'])[0]['previewable'])
                if mode=='usage':self.assertGreater(self.model().budget.summary(self.project)['unknown_outcomes'],0)
class Flow(unittest.TestCase):
    setUp=bf.Board.setUp;state=bf.Board.state;command=bf.Board.command;produce=bf.Board.produce;ready=bf.Board.ready;board=bf.Board.board;setup_board=bf.Board.setup_board;lock=bf.Board.lock
    def wire(self,req,timeout):
        value=json.loads(req.data);self.wires.append(value)
        if self.fail_after and len(self.wires)>=self.fail_after:raise ValueError('Synthetic later-card failure')
        from PIL import Image
        from studio_service.production import png
        w,h=map(int,value['size'].split('x'))
        return io.BytesIO(json.dumps({'usage':{'input_tokens_details':{'text_tokens':20,'image_tokens':10},'output_tokens':100},'data':[{'b64_json':base64.b64encode(png(Image.new('RGB',(w,h),'#123456'))).decode()}]}).encode())
    def final_ready(self,n=1):
        cards=self.setup_board(n)
        for card in cards:self.lock(card)
        self.wires=[];self.fail_after=0
        Budget(self.studio.root/'development-openai').authorize(25,'Explicit zero-spend synthetic fixture',initialize_empty=True)
        self.studio.mockup_finals=OpenAIStudio(self.studio.root,self.wire,lambda:'synthetic',limit_usd=25,image_model='gpt-image-2.5-sunburst');self.studio.budget.limit=25_000_000
        self.command('finalize_mockup_board',consent_expensive=True);self.studio.tick();return cards
    def test_exact_pixels_no_transform_manual_approval_then_separate_export(self):
        old=self.final_ready()[0];self.assertEqual(self.state()['phase'],'mockup_review')
        card=self.board()['cards'][0];candidate=card['candidate'];directory=self.studio.directory(self.project)
        self.assertEqual(base64.b64decode(self.wires[0]['images'][0]['image_url'].split(',')[1]),(directory/old['candidate']['file']).read_bytes())
        self.assertFalse(candidate['source_composited']);self.assertEqual(candidate['renderer_version'],'direct-edit-v1')
        entry=generated_images.items(self.studio.root,self.project)['images'][0]
        self.assertEqual((directory/candidate['file']).read_bytes(),generated_images.items(self.studio.root,self.project,entry['id'])[1])
        with self.assertRaises(Invalid):self.lock(card)
        self.command('toggle_mockup_lock',card_id=card['id'],human_review_confirmed=True)
        self.command('approve_mockups');self.assertIn('mockups',self.state()['workflow']['approvals'])
        self.studio.mockup_planner=object();self.command('export_mockup_board',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.state()['phase'],'mockup_review');self.assertEqual(self.wires[-1]['quality'],'high')
    def test_exact_correction_no_legacy_defaults_and_free_previous_version(self):
        self.final_ready();card=self.board()['cards'][0];previous=copy.deepcopy(card['candidate'])
        self.command('apply_mockup_comments',cards=[{'id':card['id'],'comments':COMMENT}],consent_expensive=True);self.studio.tick()
        self.assertEqual(self.wires[-1]['prompt'],COMMENT);current=self.board()['cards'][0]['candidate'];calls=len(self.wires)
        self.command('previous_mockup_image',card_id=card['id']);self.studio.tick();self.assertEqual(len(self.wires),calls)
        self.assertEqual(self.board()['cards'][0]['candidate'],previous);self.assertTrue((self.studio.directory(self.project)/current['file']).exists())
    def test_completed_card_visible_when_later_card_fails_no_automatic_retry(self):
        self.final_ready(2);self.fail_after=len(self.wires)+2
        self.command('apply_mockup_comments',consent_expensive=True);self.studio.tick();self.assertEqual(self.state()['phase'],'generation_failed')
        cards=self.board()['cards'];pending=self.state()['workflow']['pending']
        self.assertTrue(cards[0]['candidate']['id'].startswith(pending));self.assertFalse(cards[1]['candidate']['id'].startswith(pending))
        self.assertEqual(len(generated_images.items(self.studio.root,self.project)['images']),3)
        before=len(self.wires);self.studio.tick();self.assertEqual(len(self.wires),before)

    def test_failed_local_validation_reuses_paid_response_and_skips_completed_sibling(self):
        self.final_ready(2);original=self.studio.mockup_finals.transport;calls=[]
        def wrong(req,timeout):
            value=json.loads(req.data);calls.append(value)
            if len(calls)==2:value['size']='512x512'
            import urllib.request
            return original(urllib.request.Request(req.full_url,data=json.dumps(value).encode()),timeout)
        self.studio.mockup_finals.transport=wrong
        self.command('apply_mockup_comments',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.state()['phase'],'generation_failed');pending=self.state()['workflow']['pending'];count=len(calls)
        self.assertFalse(self.board()['cards'][0]['needs_render']);self.assertTrue(self.board()['cards'][1]['needs_render'])
        self.command('apply_mockup_comments',consent_expensive=True);self.studio.tick()
        self.assertEqual(self.state()['workflow']['pending'],pending);self.assertEqual(len(calls),count)
        self.assertEqual(len(generated_images.items(self.studio.root,self.project)['images']),4)

    def test_invalid_image_encoding_is_reported_instead_of_hidden(self):
        from studio_service.storage import write
        self.final_ready();catalog=generated_images.items(self.studio.root,self.project);call=catalog['images'][0]['id'].rsplit('-',1)[0]
        response=self.studio.root/'development-openai/calls'/call/'provider-response.json'
        value=read(response);value['data'][0]['b64_json']='not base64!';write(response,value)
        metadata,body=generated_images.items(self.studio.root,self.project,call+'-0')
        self.assertFalse(metadata['previewable']);self.assertIn('invalid image encoding',metadata['warning']);self.assertEqual(body,b'not base64!')
