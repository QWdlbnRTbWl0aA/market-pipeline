import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy'))
from migrate_state import migrate


class MigrationTests(unittest.TestCase):
    def test_paid_history_and_raw_files_survive_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'old'
            for name in ('collector/runs/run-fixture','collector/requests','analyzer','paid','product/intake'):
                (source/name).mkdir(parents=True)
            raw=source/'collector'/'runs'/'run-fixture'/'raw-0.json';raw.write_text('{"synthetic":true}')
            event=source/'collector'/'requests'/'event.json';event.write_text('{"synthetic":true}')
            ledger=source/'paid'/'budget.json';ledger.write_text('{"calls":{"previous":{"charged_usd":0.1570365,"status":"completed"}}}')
            config=source/'collector.json';config.write_text((ROOT/'config'/'collector.example.json').read_text())
            originals={str(p):p.read_bytes() for p in source.rglob('*') if p.is_file()}
            state=root/'new-state';configs=root/'new-config'
            result=migrate(state,configs,source/'collector',config,source/'analyzer',source/'paid',source/'product')
            self.assertEqual((state/'paid-ledger'/'budget.json').read_bytes(),ledger.read_bytes())
            self.assertEqual((state/'collector'/'runs'/'run-fixture'/'raw-0.json').read_bytes(),raw.read_bytes())
            self.assertEqual((state/'collector'/'requests'/'event.json').read_bytes(),event.read_bytes())
            self.assertEqual(originals,{str(p):p.read_bytes() for p in source.rglob('*') if p.is_file()})
            self.assertEqual(result['external_requests'],0)
            self.assertAlmostEqual(result['charged_or_reserved_usd'],.1570365)
            with self.assertRaises(ValueError):migrate(state,configs,source/'collector',config,source/'analyzer',source/'paid',source/'product')

    def test_missing_ledger_cannot_reset_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('collector','analyzer','paid','product'):(root/name).mkdir()
            config=root/'collector.json';config.write_text('{}')
            with self.assertRaises(ValueError):migrate(root/'new',root/'configs',root/'collector',config,root/'analyzer',root/'paid',root/'product')
            self.assertFalse((root/'new').exists())
