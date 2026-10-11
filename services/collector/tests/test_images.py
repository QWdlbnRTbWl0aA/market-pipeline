import io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from etsy_app.images import save_images
class ImageTests(unittest.TestCase):
 def test_safe_public_thumbnail_without_credentials_and_host_escape_rejected(self):
  with tempfile.TemporaryDirectory() as tmp,patch('etsy_app.images.time.sleep'):
   calls=[]
   def transport(request,**kwargs):
    calls.append(request);return io.BytesIO(b'\xff\xd8\xfffixture')
   row={'images':[{'url_570xN':'https://i.etsystatic.com/example.jpg'}]}
   audit=save_images(row,Path(tmp),transport=transport)
   self.assertEqual(audit[0]['status'],'saved');self.assertEqual(len(calls),1)
   self.assertNotIn('x-api-key',dict(calls[0].header_items()));self.assertNotIn('Authorization',dict(calls[0].header_items()))
   row={'images':[{'url_570xN':'https://i.etsystatic.com.attacker.example/secret'}]}
   self.assertEqual(save_images(row,Path(tmp),transport=transport)[0]['status'],'unsafe_url_rejected');self.assertEqual(len(calls),1)
 def test_bad_signature_and_size_not_saved(self):
  with tempfile.TemporaryDirectory() as tmp,patch('etsy_app.images.time.sleep'):
   for body in [b'html',b'\xff\xd8\xff'+b'x'*2_000_001]:
    row={'images':[{'url_570xN':'https://i.etsystatic.com/x.jpg'}]}
    self.assertEqual(save_images(row,Path(tmp),transport=lambda *a,**k:io.BytesIO(body))[0]['status'],'failed')
