"""Real print files and local workflow; synthetic image/text providers only."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
from studio_service.core import Studio
from studio_service.ports import Asset
from studio_service.storage import read, Invalid, Conflict
from studio_service import production
from studio_service.dev_budget import Budget,BudgetBlocked

ROOT=Path(__file__).resolve().parents[3]


class Pixels:
    name='synthetic-raster'
    def __init__(self):self.requests=[]
    def generate(self,request):
        self.requests.append(copy.deepcopy(request));result=[]
        for index in range(request['count']):
            size=request.get('image_size',[1024,1024]);image=Image.new('RGB',size,('#dfb864','#6e8aa4','#e7c5b5')[index%3])
            result.append(Asset(production.png(image),'image/png','Synthetic test image',{'features':{'subject':'fixture'},'synthetic':True}))
        return result


class Copy:
    def __init__(self):self.calls=0
    def listing(self,context,*args):
        self.calls+=1
        return {'titles':['Printable holiday art collection','Holiday pictures to print at home'],
                'description':'A coordinated collection of original holiday illustrations for printing and displaying at home. Download and choose the appropriate paper format.',
                'tags':[f'fixture tag {i}' for i in range(13)]}


class Manufacturing(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.images=Pixels();self.copy=Copy();self.studio=Studio(self.root,sketches=self.images,professional=self.images,copywriter=self.copy)
        brief=json.loads((ROOT/'examples/studio-hanukkah-brief.example.json').read_text())
        self.project=self.studio.create(brief,'intake')['project']['id'];self.key=0
    def state(self):return self.studio.get(self.project)
    def command(self,action,**payload):
        self.key+=1;return self.studio.command(self.project,action,{'revision':self.state()['revision'],**payload},str(self.key))
    def produce(self):
        self.command('start_sketches');self.studio.tick();state=self.state();candidate=state['rounds'][-1]['candidates'][0]
        self.command('approve_direction',reviews={candidate['id']:{'decision':'accept'}},candidate_id=candidate['id'],consent_expensive=True,
                     print_settings={'formats':['A4','Letter'],'dpi':150,'margin_mm':10,'bleed_mm':0,'color_mode':'color'})
        self.studio.tick();self.assertEqual(self.state()['phase'],'product_review')
        self.assertEqual(self.state()['workflow']['progress']['completed'],5)
        return self.state()['workflow']['products'][-1]

    def test_full_hanukkah_inventory_to_customer_zip_mockups_and_copy(self):
        self.assertEqual(len(self.state()['workflow']['plan']['units']),5);self.assertEqual(self.images.requests,[])
        record=self.produce();folder=self.studio.directory(self.project)/record['directory'];manifest=read(folder/'manifest.json')
        self.assertEqual(len([f for f in manifest['files'] if f['role']=='print_page']),10)
        self.assertEqual(len([f for f in manifest['files'] if f['role']=='print_pdf']),2)
        self.assertTrue(all(c['passed'] for c in manifest['checks']))
        self.assertIn(b'/Count 5', (folder/'A4/bundle.pdf').read_bytes());self.assertIn(b'/TrimBox',(folder/'A4/bundle.pdf').read_bytes())
        with Image.open(folder/'A4/unit-01.png') as image:self.assertEqual(image.size,(1240,1754));self.assertAlmostEqual(image.info['dpi'][0],150,delta=.1)
        calls=len(self.images.requests);self.command('approve_product',visual_review_confirmed=True)
        state=self.state();self.assertEqual(len(state['workflow']['mockups']),3);self.assertEqual(len(self.images.requests),calls)
        self.command('approve_mockups');self.command('generate_listing');self.studio.tick();self.assertEqual(self.copy.calls,1)
        self.assertIn('5 content pages',self.state()['workflow']['listing']['copy']['description'])
        self.command('approve_listing',copy_review_confirmed=True);state=self.state();self.assertEqual(state['phase'],'approved')
        directory=self.studio.directory(self.project)
        with zipfile.ZipFile(directory/'customer.zip') as archive:
            self.assertEqual(len([p for p in archive.namelist() if p.endswith('.png')]),10)
            self.assertEqual(len([p for p in archive.namelist() if p.endswith('.pdf')]),2)
            self.assertFalse(any('listing' in p or 'mockup' in p or p.endswith('.svg') for p in archive.namelist()))
        with zipfile.ZipFile(directory/'product.zip') as archive:self.assertEqual(len([p for p in archive.namelist() if p.startswith('listing-assets/')]),3)
        self.assertFalse(read(directory/'listing-handoff.json')['etsy_api_called'])
        before=len(self.images.requests);self.studio.tick();self.assertEqual(len(self.images.requests),before)

    def test_selected_revision_reuses_other_artwork_and_invalidates_approvals(self):
        first=self.produce();before=len(self.images.requests);self.command('approve_product',visual_review_confirmed=True)
        self.command('produce_selected',unit_ids=['unit-02'],comments='Use softer edges only on this picture',consent_expensive=True)
        self.studio.tick();state=self.state();second=state['workflow']['products'][-1]
        self.assertEqual(len(self.images.requests),before+1);self.assertEqual(state['workflow']['approvals'],{})
        for unit in ('unit-01','unit-03','unit-04','unit-05'):self.assertEqual(first['assets'][unit]['sha256'],second['assets'][unit]['sha256'])
        self.assertEqual(self.images.requests[-1]['accepted'][0]['sha256'],first['assets']['unit-02']['sha256'])
        self.assertEqual(self.images.requests[-1]['last_feedback'],'Use softer edges only on this picture')
        with self.assertRaises(Invalid):self.command('approve_mockups')

    def test_native_resolution_and_text_overflow_fail_before_approval(self):
        plan=production.plan({'deliverables':[]},{'concept':'Image','deliverables':[]})
        small=production.png(Image.new('RGB',(128,128),'white'))
        with self.assertRaises(Invalid):production.assemble(self.root/'bad',plan,{'formats':['A4'],'dpi':300,'margin_mm':10,'bleed_mm':0,'color_mode':'color'},{'unit-01':{'content':small}},'version')
        plan['units'][0].update(kind='text',visible_text='longword'*1000)
        with self.assertRaises(Invalid):production.assemble(self.root/'text',plan,{'formats':['A4'],'dpi':300,'margin_mm':10,'bleed_mm':0,'color_mode':'color'},{},'version')

    def test_file_tamper_blocks_approval_and_listing_requires_current_mockups(self):
        record=self.produce();folder=self.studio.directory(self.project)/record['directory'];(folder/'A4/unit-01.png').write_bytes(b'changed')
        with self.assertRaises(Invalid):self.command('approve_product',visual_review_confirmed=True)
        with self.assertRaises(Invalid):self.command('generate_listing')
        self.assertEqual(self.copy.calls,0)

    def test_budget_migration_retains_prior_usage_and_unknown_holds(self):
        budget=Budget(self.root/'ledger');budget.reserve('old',self.project,100000,'draft_generation');budget.settle('old',80000,{})
        budget.reserve('unknown',self.project,200000,'visual_observation')
        budget.authorize(25,'User approved the workflow proposal')
        ledger=read(self.root/'ledger/budget.json');self.assertEqual(ledger['calls']['old']['charged_micro_usd'],80000)
        self.assertEqual(ledger['calls']['unknown']['charged_micro_usd'],200000)
        with self.assertRaises(BudgetBlocked):Budget(self.root/'ledger',25).reserve('new',self.project,1000,'draft_generation')
        self.assertEqual(Budget(self.root/'ledger',25).summary(self.project)['unknown_outcomes'],1)

    def test_preferences_are_explicit_editable_and_scoped(self):
        self.command('remember_preference',memory_revision=0,text='Keep generous white margins',scope='family',family='Holiday art')
        context=self.studio.preferences.context(self.project,'Holiday art');self.assertEqual(len(context),1)
        self.assertEqual(self.studio.preferences.context('b'*32,'Different family'),[])
        with self.assertRaises(Invalid):self.command('remember_preference',memory_revision=0,text='Stale edit',scope='brand')
        self.command('remember_preference',memory_revision=1,operation='delete',preference_id=context[0]['id'])
        self.assertEqual(self.studio.preferences.context(self.project,'Holiday art'),[])

    def test_partial_production_is_parked_and_explicit_retry_reuses_completed_units(self):
        original=self.images.generate;failed=[]
        def sometimes(request):
            if request['mode']=='production' and request['production_unit']['id']=='unit-02' and not failed:
                failed.append(True);raise Invalid('Known synthetic failure')
            return original(request)
        self.images.generate=sometimes
        self.command('start_sketches');self.studio.tick();candidate=self.state()['rounds'][-1]['candidates'][0]
        self.command('approve_direction',reviews={candidate['id']:{'decision':'accept'}},candidate_id=candidate['id'],consent_expensive=True,
            print_settings={'formats':['A4'],'dpi':150,'margin_mm':10,'bleed_mm':0,'color_mode':'color'})
        self.studio.tick();self.assertEqual(self.state()['phase'],'generation_failed');before=len(self.images.requests)
        self.studio.tick();self.assertEqual(len(self.images.requests),before)
        self.command('retry_workflow',consent_expensive=True);self.studio.tick();self.assertEqual(self.state()['phase'],'product_review')
        self.assertEqual(self.state()['workflow']['progress']['completed'],5)
        self.assertEqual(sum(r.get('production_unit',{}).get('id')=='unit-01' for r in self.images.requests),1)

    def test_final_approval_interruption_requires_and_reuses_original_action(self):
        self.produce();self.command('approve_product',visual_review_confirmed=True);self.command('approve_mockups')
        self.command('generate_listing');self.studio.tick();revision=self.state()['revision'];payload={'revision':revision,'copy_review_confirmed':True}
        from studio_service import workflow
        original=workflow.write_bytes
        def fail(path,body):
            if path.name=='product.zip':raise OSError('Synthetic interruption')
            return original(path,body)
        with patch('studio_service.workflow.write_bytes',side_effect=fail),self.assertRaises(OSError):
            self.studio.command(self.project,'approve_listing',payload,'final-reserved')
        directory=self.studio.directory(self.project);reservation=read(directory/'workflow-final-reservation.json')
        with self.assertRaises(Conflict):self.studio.command(self.project,'approve_listing',payload,'different-action')
        self.studio.command(self.project,'approve_listing',payload,'final-reserved')
        self.assertEqual(self.state()['phase'],'approved');self.assertEqual(self.state()['workflow']['approvals'],reservation['approvals'])

    def test_perspective_and_crop_reuse_pixels_and_template_validation(self):
        image=Image.new('RGB',(800,1200),'#123456')
        mockup,provenance=production.compose_mockup(image,{'kind':'frame','perspective':'left','crop':[0,0,1,1]})
        self.assertEqual(mockup.size,(1200,1400));self.assertEqual(len(provenance['perspective_quad']),4)
        self.assertEqual(provenance['source_image_sha256'],hashlib.sha256(production.png(image)).hexdigest())
        for template in ({'kind':'frame','crop':[0,0,0,1]},{'kind':'frame','background':'url(secret)'},{'kind':'frame','perspective':'unsupported'}):
            with self.assertRaises(Invalid):production.compose_mockup(image,template)

    def test_stage_allocation_and_listing_quantity_gates(self):
        budget=Budget(self.root/'allocated',25);budget.authorize(25,'Synthetic zero prior usage',initialize_empty=True);budget.reserve('old',self.project,3800000,'direction_generation');budget.settle('old',3800000,{})
        with self.assertRaises(BudgetBlocked):budget.reserve('next',self.project,300000,'direction_generation')
        bad=Copy().listing({});bad['titles'][0]='999 printable pages'
        with self.assertRaises(Invalid):production.factual_listing(bad,{'units':[{'kind':'illustration'}]*5,'settings':{'formats':['A4'],'dpi':300}})

    def test_confirmed_prior_total_carries_external_spend_without_erasing_calls(self):
        budget=Budget(self.root/'reconciled',1);budget.reserve('old',self.project,150000,'draft_generation');budget.settle('old',144836,{})
        budget.authorize(25,'User confirmed all previous Studio usage',prior_total_usd=.43)
        newer=Budget(self.root/'reconciled',25);self.assertEqual(newer.summary(self.project)['charged_or_reserved_usd'],.43)
        newer.authorize(25,'Same confirmed total',prior_total_usd=.43)
        self.assertEqual(len(read(self.root/'reconciled/budget.json')['calls']),2)
        with self.assertRaises(BudgetBlocked):newer.authorize(25,'Cannot erase charges',prior_total_usd=.1)
        newer.reserve('unknown',self.project,1000,'trial')
        with self.assertRaises(BudgetBlocked):newer.authorize(25,'Unknown is unresolved',prior_total_usd=.44)

    def test_fresh_trial_config_cannot_silently_omit_prior_usage(self):
        budget=Budget(self.root/'empty-trial',25)
        self.assertTrue(budget.summary(self.project)['authorization_required'])
        with self.assertRaises(BudgetBlocked):budget.reserve('first',self.project,1000,'trial')
        self.assertFalse((self.root/'empty-trial/budget.json').exists())

    def test_edited_inventory_and_style_reach_representative_sketch_prompt(self):
        value=copy.deepcopy(self.state()['workflow']['plan']);value['style']='Monochrome pencil with generous white space';value['constraints']='No golden decoration'
        self.command('save_plan',plan=value);self.command('start_sketches');self.studio.tick()
        prompt=json.loads(self.images.requests[0]['optimized_prompt'])
        self.assertEqual(prompt['production_plan']['style'],value['style'])
        self.assertEqual(prompt['production_plan']['constraints'],value['constraints'])
        self.assertEqual(prompt['representative_unit']['id'],value['representative_id'])
