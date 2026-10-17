"""Saved Product structure, grouped content and bounded offline image context."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from studio_service.core import Studio
from studio_service.production import plan
from studio_service.storage import read
from test_production_workflow import Pixels


def handoff():
    components=[]
    for label,height,subjects in [('Short',12,['Car','Van','Bus']),('Longer',20,['Pickup','Dump truck','Tow truck']),('Longest',28,['Ambulance','Fire engine','Delivery truck'])]:
        components.append({'name':label+' Cuts strips: one printable sheet','quantity':3,
            'format':f'Portrait sheet with three 160 by {height} mm strips',
            'content':[f'{subject} strip: four original side-view vehicles; 40 by {height} mm cells, solid border, three dashed dividers.' for subject in subjects]})
    components.extend([{'name':'Adult preparation and supervision guide','quantity':1,'format':'One portrait instruction page','content':['Use child-safe scissors under adult supervision. Print at 100%.']},
                       {'name':'Vehicle parking mat','quantity':1,'format':'One portrait paste surface','content':['Twelve spaces arranged in three rows of four.']}])
    instructions={'scope':'Five pages per A4 and US Letter edition; nine strips and 36 vehicles.',
        'first_sketch':{'component':components[0]['name'],'composition':'Three strips at x=25 mm, y=60,105,150 mm; 160 by 12 mm each.',
                        'exact_visible_text':['Short Cuts','Car','Van','Bus'],'avoid':['Vehicle logos','Background roads']},
        'acceptance_checks':['Exactly five pages, three cutting sheets; keep millimeter activity scale.']}
    return {'vision':'Vehicle cut-and-park activity','definition':{'components':components,**instructions},
        'source_requirements':{'product_concept':'Vehicle cut-and-park activity','deliverables':[c['name']+': '+'; '.join(c['content']) for c in components],
            'visual_direction':'Flat geometric vehicles, sparse black outlines, no backgrounds.','requirements':json.dumps(instructions)},
        'evidence':{'raw_market_rows':'RAW_MARKET_EVIDENCE_'*4500},'reference_images':[]}


class ProductPrompt(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.images=Pixels();self.studio=Studio(Path(self.tmp.name),sketches=self.images)

    def test_large_actual_product_structure_reaches_generator_as_bounded_five_page_design(self):
        doc=handoff();project=self.studio.create(doc,'actual-shape')['project'];directory=self.studio.directory(project['id']);original=(directory/'original-brief.json').read_bytes()
        units=project['workflow']['plan']['units'];self.assertEqual(len(units),5)
        for subject in ('Car strip','Van strip','Bus strip'):self.assertIn(subject,units[0]['description'])
        self.assertEqual(units[3]['kind'],'text')
        self.studio.command(project['id'],'start_sketches',{'revision':project['revision']},'start');self.studio.tick()
        state=self.studio.get(project['id']);self.assertEqual(state['phase'],'sketch_review');self.assertEqual(len(state['rounds'][0]['candidates']),3)
        request=self.images.requests[0];prompt=request['optimized_prompt'];self.assertLessEqual(len(prompt.encode()),20000)
        self.assertNotIn('RAW_MARKET_EVIDENCE_',prompt);self.assertIn('RAW_MARKET_EVIDENCE_',json.dumps(request['source_context']))
        self.assertIn('160 by 12 mm',prompt);self.assertIn('Short Cuts',prompt);self.assertEqual((directory/'original-brief.json').read_bytes(),original)

    def test_separate_pages_and_quantity_validation_stay_unchanged(self):
        from studio_service.briefs import normalize
        from studio_service.storage import Invalid
        doc=handoff();doc['definition']['components']=[{'name':'Three original pictures','quantity':3,'format':'Three separate pages','content':['Picture A','Picture B','Picture C']}]
        self.assertEqual(len(plan(doc,normalize(doc))['units']),3)
        doc['definition']['components'][0]['quantity']=2
        with self.assertRaises(Invalid):plan(doc,normalize(doc))

    def test_real_design_overflow_is_actionable_and_never_reaches_image_provider(self):
        project=self.studio.create(handoff(),'overflow')['project'];value=copy.deepcopy(project['workflow']['plan'])
        value['style']='s'*8000;value['constraints']='c'*8000
        for unit in value['units']:unit['description']='d'*4000
        result=self.studio.command(project['id'],'save_plan',{'revision':project['revision'],'plan':value},'edit')['project']
        self.studio.command(project['id'],'start_sketches',{'revision':result['revision']},'start');self.studio.tick()
        state=self.studio.get(project['id']);self.assertEqual(state['phase'],'generation_failed');self.assertIn('20KB',state['generation_error']);self.assertEqual(self.images.requests,[])
