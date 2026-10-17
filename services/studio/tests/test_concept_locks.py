"""Concept approval is independent of final page-placement validation."""
import hashlib
import unittest
from studio_service.storage import Invalid
import test_mockup_board as fixture


class Locks(unittest.TestCase):
    setUp=fixture.Board.setUp;state=fixture.Board.state;command=fixture.Board.command;produce=fixture.Board.produce;ready=fixture.Board.ready;board=fixture.Board.board
    def setup_bad(self):
        self.ready();self.port.bad=True;self.command('suggest_mockups',additional_count=1);self.studio.tick();return self.board()['cards'][0]
    def test_concept_can_lock_unchanged_pixels_with_pending_notes_and_explicit_placement_ack(self):
        card=self.setup_bad();file=self.studio.directory(self.project)/card['candidate']['file'];body=file.read_bytes();calls=len(self.port.images)
        self.command('save_mockup_board',cards=[{'id':card['id'],'comments':'Correct fingers during final refinement'}])
        with self.assertRaises(Invalid):self.command('toggle_mockup_lock',card_id=card['id'])
        self.command('toggle_mockup_lock',card_id=card['id'],concept_review_confirmed=True)
        saved=self.board()['cards'][0];self.assertTrue(saved['locked']);self.assertTrue(saved['needs_render']);self.assertEqual(saved['comments'],'Correct fingers during final refinement');self.assertTrue(saved['concept_approval']['placement_review_required'])
        self.assertEqual(saved['concept_approval']['sha256'],hashlib.sha256(body).hexdigest());self.assertEqual(file.read_bytes(),body);self.assertEqual(len(self.port.images),calls)
        self.command('toggle_mockup_lock',card_id=card['id']);self.assertFalse(self.board()['cards'][0]['locked']);self.assertEqual(len(self.port.images),calls)
    def test_concept_ack_cannot_bypass_bad_final_placement(self):
        card=self.setup_bad();self.command('toggle_mockup_lock',card_id=card['id'],concept_review_confirmed=True)
        with self.assertRaises(Invalid):self.command('approve_mockups')
        self.command('enter_mockup_final');self.command('render_mockup_board',consent_expensive=True);self.studio.tick();before=len(self.port.images)
        self.assertEqual(self.board()['cards'][0]['candidate']['quality'],'final')
        with self.assertRaises(Invalid):self.command('toggle_mockup_lock',card_id=card['id'],concept_review_confirmed=True)
        with self.assertRaises(Invalid):self.command('approve_mockups')
        self.assertEqual(len(self.port.images),before)
    def test_corrupt_saved_pixels_are_not_approved(self):
        card=self.setup_bad();file=self.studio.directory(self.project)/card['candidate']['file'];file.write_bytes(b'synthetic corruption')
        with self.assertRaises(Invalid):self.command('toggle_mockup_lock',card_id=card['id'],concept_review_confirmed=True)
