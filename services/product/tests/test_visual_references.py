"""Synthetic image/HTTP fixtures: no network, paid inference or email."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from product_service import visual_references as visual
from product_service.briefing import references, document, html_document
from product_service.core import process
from test_flow import fixture, FixtureBrief

CDN='https://i.etsystatic.com/123/r/il/abc/123/il_570xN.123.jpg'


def raster():
    from PIL import Image
    image=Image.new('RGB',(1200,800),'blue');out=io.BytesIO()
    image.save(out,format='JPEG',exif=b'Exif\x00\x00private-metadata')
    return out.getvalue()


class VisualReferences(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        result=process(json.dumps(fixture()).encode(),self.root/'base',FixtureBrief())
        self.source=Path(result['directory'])/'product-01/product.json'
        self.product=json.loads(self.source.read_text())

    def test_selected_listing_metadata_image_is_bounded_embedded_and_durable(self):
        calls=[];body=raster()
        def fetch(url,limit,timeout):
            calls.append(url)
            return ('<meta content="'+CDN+'" property="og:image">').encode() if url==self.product['samples'][0]['url'] else body
        before=self.source.read_bytes()
        result=visual.revise(self.source,self.root/'visual',fetcher=fetch)
        product=json.loads((self.root/'visual/product.json').read_text());ref=product['visual_references'][0]
        image=base64.b64decode(product['reference_images'][0].split(',')[1])
        self.assertEqual(result['images'],1);self.assertEqual(len(calls),2)
        self.assertLessEqual(max(ref['width'],ref['height']),512);self.assertLessEqual(len(image),80000)
        self.assertNotIn(b'private-metadata',image);self.assertEqual(hashlib.sha256(image).hexdigest(),ref['sha256'])
        self.assertEqual(ref['source_image_sha256'],hashlib.sha256(body).hexdigest())
        self.assertFalse(product['visual_reference_status']['images_visually_inspected_by_product'])
        self.assertIn('data:image/jpeg;base64,',(self.root/'visual/brief.html').read_text())
        self.assertEqual(json.loads((self.root/'visual/studio-handoff.json').read_text())['products'][0]['brief'],product)
        visual.revise(self.source,self.root/'visual',fetcher=lambda *a: self.fail('Repeated network retrieval'))
        self.assertEqual(self.source.read_bytes(),before)

    def test_saved_image_metadata_survives_product_and_skips_page_lookup(self):
        data=fixture();data['report']['recommendations'][0]['evidence_excerpts'][0]['images']=[{'url_570xN':CDN}]
        self.assertEqual(references(data['report']['recommendations'][0])[0]['images'],[{'url_570xN':CDN}])
        calls=[]
        def fetch(url,*a):calls.append(url);return raster()
        model=FixtureBrief()
        result=process(json.dumps(data).encode(),self.root/'new',model,visual.policy(),fetch)
        folder=Path(result['directory'])/'product-01';product=json.loads((folder/'product.json').read_text())
        self.assertEqual(calls,[CDN]);self.assertEqual(model.calls,1)
        self.assertEqual(product['visual_reference_status']['status'],'ready')
        again=process(json.dumps(data).encode(),self.root/'new',model,visual.policy(),lambda *a:self.fail('Network'))
        self.assertTrue(again['duplicate']);self.assertEqual(model.calls,1)

    def test_access_block_stops_remaining_pages_and_failed_receipt_is_reused(self):
        product=copy.deepcopy(self.product)
        for i in (2,3):
            product['samples'].append({**product['samples'][0],'listing_id':str(i),'url':f'https://www.etsy.com/listing/{i}/reference','evidence_id':f'e{i}'})
        calls=[]
        def fetch(url,*a):calls.append(url);raise visual.FetchError('Media HTTP failure',403)
        enriched=visual.enrich(product,self.root/'blocked',fetcher=fetch)
        self.assertEqual(len(calls),1);self.assertEqual(enriched['reference_images'],[])
        self.assertEqual(enriched['visual_reference_status']['status'],'unavailable')
        self.assertEqual(len(enriched['visual_reference_status']['failures']),3)
        self.assertIn('HTTP 403',html_document(document(enriched)))
        visual.enrich(product,self.root/'blocked',fetcher=lambda *a:self.fail('Repeated blocked request'))

    def test_untrusted_urls_metadata_and_private_addresses_are_never_fetched(self):
        for url in ('http://i.etsystatic.com/a.jpg','https://127.0.0.1/a.jpg','https://i.etsystatic.com.evil.invalid/a.jpg',
                    'https://i.etsystatic.com@evil.invalid/a.jpg','https://i.etsystatic.com/a.svg','https://i.etsystatic.com/a.jpg?token=private',
                    'https://i.etsystatic.com/../a.jpg','https://i.etsystatic.com:444/a.jpg'):
            self.assertFalse(visual.allowed(url,'image'))
        with patch('product_service.visual_references.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('product_service.visual_references.http.client.HTTPSConnection') as connection:
            with self.assertRaises(visual.FetchError):visual.fetch(CDN,2000000,1)
            connection.assert_not_called()
        parser=visual.Metadata();parser.feed('<meta property="og:image" content="http://127.0.0.1/secret">')
        self.assertIsNone(parser.image)

    def test_decode_failure_interrupted_receipt_and_disabled_lookup(self):
        enriched=visual.enrich(self.product,self.root/'bad',fetcher=lambda *a:b'not an image')
        self.assertEqual(enriched['reference_images'],[])
        output=self.root/'interrupted';output.mkdir();(output/'visual-reference-started.json').write_text('{}')
        with self.assertRaises(RuntimeError):visual.enrich(self.product,output,fetcher=lambda *a:self.fail('Network'))
        disabled=visual.enrich(self.product,self.root/'off',{'enabled':False},lambda *a:self.fail('Network'))
        self.assertEqual(disabled['visual_reference_status']['status'],'disabled')
        with self.assertRaises(ValueError):visual.revise(self.source,self.source.parent)

    def test_images_reach_passive_studio_without_inference(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'studio'))
        from studio_service.core import Studio
        self.product['samples'][0]['images']=[CDN]
        value=visual.enrich(self.product,self.root/'images',fetcher=lambda *a:raster())
        studio=Studio(self.root/'studio')
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Network forbidden')):
            result=studio.create(value,'visual-intake',library=True)
        state=result['project'];self.assertTrue(state['library_import']);self.assertEqual(state['rounds'],[])
        self.assertEqual(len(state['reference_images']),1);self.assertFalse(state['generation_started'])

    def test_configuration_bounds(self):
        for value in ({'enabled':'true'},{'max_images':4},{'timeout_seconds':60},{'unknown':True}):
            with self.assertRaises(ValueError):visual.policy(value)

    def test_host_access_blocks_survive_new_products_and_processes(self):
        calls=[]
        def denied(*a):calls.append(1);raise visual.FetchError('Media HTTP failure',429)
        first=visual.GuardedFetch(self.root/'access',denied)
        with self.assertRaises(visual.FetchError):first(self.product['samples'][0]['url'],1000,1)
        second=visual.GuardedFetch(self.root/'access',lambda *a:self.fail('Repeated access challenge'))
        with self.assertRaises(visual.FetchError) as caught:second('https://etsy.com/listing/2/example',1000,1)
        self.assertTrue(caught.exception.cached);self.assertEqual(len(calls),1)

    def test_invalid_visual_policy_rejected_before_inference(self):
        with self.assertRaises(ValueError):
            process(json.dumps(fixture()).encode(),self.root/'invalid',None,{'max_images':4})

    def test_no_redirect_following_and_stream_size_bound(self):
        class Response:
            status=302
            def getheader(self,name,default=None):return 'https://example.invalid/' if name=='Location' else default
        class Connection:
            def __init__(self,*a,**k):pass
            def request(self,*a,**k):pass
            def getresponse(self):return Response()
            def close(self):pass
        with patch('product_service.visual_references.socket.getaddrinfo',return_value=[(2,1,6,'',('203.0.113.8',443))]),patch('product_service.visual_references.ipaddress.ip_address',return_value=SimpleNamespace(is_global=True,is_multicast=False)),patch('product_service.visual_references.http.client.HTTPSConnection',Connection):
            with self.assertRaises(visual.FetchError) as caught:visual.fetch(CDN,100,1)
            self.assertEqual(caught.exception.status,302)
            Response.status=200
            Response.getheader=lambda self,name,default=None:'image/jpeg' if name=='Content-Type' else default
            Response.read1=lambda self,size:b'x'*size
            with self.assertRaises(visual.FetchError):visual.fetch(CDN,100,1)
