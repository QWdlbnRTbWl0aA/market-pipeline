"""OpenAI credential copies honor kernel readability without host-specific IDs."""
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services'/'analyzer'))
from analyzer.adapters.openai import api_key


class CredentialDelivery(unittest.TestCase):
    def test_service_manager_owned_read_only_group_delivery_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            file=Path(temporary)/'openai.env';file.write_text('export OPENAI_API_KEY=fixture\n');file.chmod(stat.S_IRUSR|stat.S_IRGRP)
            with patch.dict(os.environ,{'PIPELINE_OPENAI_KEY_FILE':str(file)}):self.assertEqual(api_key(),'fixture')
    def test_collector_filename_rejected_before_open(self):
        with patch.dict(os.environ,{'PIPELINE_OPENAI_KEY_FILE':'/etc/market-pipeline/credentials/etsy.env'}),patch('analyzer.adapters.openai.os.open',side_effect=AssertionError('Collector key opened')),self.assertRaises(ValueError):api_key()
