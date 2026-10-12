"""Portable credential-loader regressions; synthetic secrets, no API requests."""
import contextlib
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy'))
from launch import command, read_collector_credentials


class CollectorCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'etsy.env'
        self.body = 'export ETSY_API_KEY=synthetic-key\nexport ETSY_API_SECRET=synthetic-secret\n'
        self.path.write_text(self.body)
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_service_manager_ownership_is_not_assumed_to_match_process_uid(self):
        metadata = self.path.stat()
        # Simulate readable, manager-owned deliveries without chown, root or
        # assumptions about any host's service IDs or group allocation.
        delivered = SimpleNamespace(st_mode=stat.S_IFREG | stat.S_IRUSR | stat.S_IRGRP,
                                    st_size=metadata.st_size, st_uid=os.geteuid() + 1,
                                    st_gid=os.getegid() + 1)
        with patch('launch.os.fstat', return_value=delivered), \
                patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            values = read_collector_credentials(self.path)
        self.assertEqual(values, {'ETSY_API_KEY': 'synthetic-key', 'ETSY_API_SECRET': 'synthetic-secret'})

    def test_read_only_service_group_delivery_is_accepted(self):
        self.path.chmod(stat.S_IRUSR | stat.S_IRGRP)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            cwd, argv, env = command('collector', self.root / 'config.json', self.root,
                                     credential_directory=self.root)
        self.assertEqual(env['ETSY_API_KEY'], 'synthetic-key')
        self.assertEqual(env['ETSY_API_SECRET'], 'synthetic-secret')
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('synthetic-key', ' '.join(argv) + stdout.getvalue() + stderr.getvalue())
        self.assertNotIn('synthetic-secret', ' '.join(argv) + stdout.getvalue() + stderr.getvalue())

    def test_owner_private_read_only_and_writable_files_remain_supported(self):
        for permission in (stat.S_IRUSR, stat.S_IRUSR | stat.S_IWUSR):
            with self.subTest(permission=permission):
                self.path.chmod(permission)
                self.assertEqual(read_collector_credentials(self.path)['ETSY_API_KEY'], 'synthetic-key')

    def test_group_writable_and_other_access_are_rejected(self):
        for bit in (stat.S_IWGRP, stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH):
            with self.subTest(bit=bit):
                self.path.chmod(stat.S_IRUSR | stat.S_IWUSR | bit)
                with self.assertRaises(ValueError):
                    read_collector_credentials(self.path)

    def test_symlinks_and_directories_are_rejected(self):
        link = self.root / 'alias'
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            read_collector_credentials(link)
        with self.assertRaises(ValueError):
            read_collector_credentials(self.root)

    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo, stat.S_IRUSR | stat.S_IWUSR)
        script = ('import sys; sys.path.insert(0, sys.argv[1]); '
                  'from launch import read_collector_credentials\n'
                  'try: read_collector_credentials(sys.argv[2])\n'
                  'except ValueError: sys.exit(0)\n'
                  'sys.exit(1)\n')
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT / 'deploy'), str(fifo)],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unreadable_file_fails_at_open_without_permission_bypass(self):
        with patch('launch.os.open', side_effect=PermissionError('Synthetic access denied')), \
                patch('launch.os.fstat') as metadata:
            with self.assertRaises(PermissionError):
                read_collector_credentials(self.path)
        metadata.assert_not_called()

    def test_bounds_and_literal_parser_fail_closed_without_exposing_values(self):
        for body in ('x' * 8193,
                     'export ETSY_API_KEY=$(touch forbidden)\nexport ETSY_API_SECRET=synthetic-secret\n',
                     'export ETSY_API_KEY=synthetic-key\n',
                     'export OTHER_KEY=synthetic-key\nexport ETSY_API_SECRET=synthetic-secret\n'):
            with self.subTest(body_length=len(body)):
                self.path.write_text(body)
                with self.assertRaises(ValueError) as caught:
                    read_collector_credentials(self.path)
                self.assertNotIn('synthetic-key', str(caught.exception))
                self.assertNotIn('synthetic-secret', str(caught.exception))
                self.assertFalse((self.root / 'forbidden').exists())

    def test_only_collector_opens_delivered_etsy_credentials(self):
        with patch('launch.read_collector_credentials', side_effect=AssertionError('Collector key read')):
            for service in ('search-refiner', 'market-analyst', 'controller', 'product'):
                cwd, argv, env = command(service, self.root / 'config.json', self.root,
                                         credential_directory=self.root)
                self.assertNotIn('ETSY_API_KEY', env)
                self.assertNotIn('ETSY_API_SECRET', env)
