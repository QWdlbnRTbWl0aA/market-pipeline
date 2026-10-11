"""Fast dashboard indexes and persistent scheduling tests; no real API calls."""
import datetime as dt
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from etsy_app.core import Store, atomic_json, config
from etsy_app.server import App, handler
from test_app import SETTINGS, good_fetch


class FastIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root)
        self.run=self.store.collect(SETTINGS,fetcher=good_fetch)

    def test_warm_critical_panels_do_not_parse_source_snapshots_or_unchanged_events(self):
        atomic_json(self.root/'requests'/'a.json',{'source':'api','request_id':'a','started_at':dt.datetime.now(dt.timezone.utc).isoformat()})
        self.store.list_runs();self.store.request_usage()
        original=Path.read_text
        def guard(path,*args,**kwargs):
            self.assertNotEqual(path.name,'snapshot.json')
            self.assertNotEqual(path.parent.name,'requests')
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',guard):
            self.assertEqual(self.store.list_runs()[0]['run_id'],self.run['run_id'])
            self.assertEqual(self.store.request_usage()['last_24_hours'],1)
            self.assertEqual(self.store.known_shops(),[])

    def test_request_append_replace_delete_and_time_expiry_are_fresh(self):
        now=dt.datetime.now(dt.timezone.utc);path=self.root/'requests'/'a.json'
        event={'source':'api','request_id':'a','started_at':now.isoformat()}
        atomic_json(path,event);self.assertEqual(self.store.request_usage(now)['last_24_hours'],1)
        atomic_json(path,{**event,'rate_limits':{'x-remaining-today':'10'}})
        self.assertEqual(self.store.request_usage(now)['last_known_rate_limits']['x-remaining-today'],'10')
        atomic_json(self.root/'requests'/'b.json',{**event,'request_id':'b'})
        self.assertEqual(self.store.request_usage(now)['last_24_hours'],2)
        self.assertEqual(self.store.request_usage(now+dt.timedelta(days=1))['last_24_hours'],0)
        path.unlink();self.assertEqual(self.store.request_usage(now)['last_24_hours'],1)

    def test_index_survives_restart_and_external_snapshot_changes(self):
        path=self.root/'runs'/self.run['run_id']/'snapshot.json'
        original=path.read_bytes()
        self.assertTrue((self.root/'dashboard-index'/(self.run['run_id']+'.json')).exists())
        self.assertEqual(Store(self.root).list_runs()[0]['listing_count'],2)
        # External writes that don't use the app writer are detected and indexed.
        changed={**self.run,'listing_count':7};path.write_text(json.dumps(changed))
        self.assertEqual(self.store.list_runs()[0]['listing_count'],7)
        path.write_bytes(original);self.assertEqual(self.store.list_runs()[0]['listing_count'],2)

    def test_corrupt_metadata_rebuilds_without_changing_snapshot(self):
        path=self.root/'runs'/self.run['run_id']/'snapshot.json';original=path.read_bytes()
        (self.root/'dashboard-index'/(self.run['run_id']+'.json')).write_text('invalid')
        self.assertEqual(Store(self.root).list_runs()[0]['run_id'],self.run['run_id'])
        self.assertEqual(path.read_bytes(),original)


class DailyControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=App(SETTINGS,self.tmp.name)

    def toggle(self,enabled,instant=None):
        return self.app.set_daily_enabled({'enabled':enabled,'revision':self.app.configuration()['revision']},instant)

    def test_disabled_schedule_survives_restart_manual_search_is_available(self):
        self.toggle(False)
        restarted=App(config(self.app.config_path),self.tmp.name,self.app.config_path)
        with patch.object(restarted,'start') as start:
            self.assertFalse(restarted.schedule_tick(dt.datetime(2026,10,11,12,tzinfo=dt.timezone.utc)))
            start.assert_not_called()
        self.assertFalse(restarted.configuration()['daily_enabled'])
        self.assertEqual(restarted.trial_settings({'keywords':'planner','limit':None})['niches'][0]['keywords'],'planner')

    def test_enable_arms_next_due_time_without_immediate_query(self):
        instant=dt.datetime(2026,10,10,12,tzinfo=dt.timezone.utc)
        self.toggle(False);value=self.toggle(True,instant)
        restarted=App(config(self.app.config_path),self.tmp.name,self.app.config_path)
        due=dt.datetime.fromisoformat(value['daily_resume_at'])
        self.assertGreater(due,instant)
        with patch.object(restarted,'start') as start:
            self.assertFalse(restarted.schedule_tick(instant));start.assert_not_called()
            self.assertTrue(restarted.schedule_tick(due));start.assert_called_once()
            self.assertFalse(restarted.schedule_tick(due));start.assert_called_once()

    def test_stale_or_invalid_toggle_rejected_and_running_run_not_cancelled(self):
        revision=self.app.configuration()['revision'];self.toggle(False)
        with self.assertRaises(RuntimeError):self.app.set_daily_enabled({'enabled':True,'revision':revision})
        for enabled in ('false',1,None):
            with self.assertRaises(ValueError):self.app.set_daily_enabled({'enabled':enabled,'revision':self.app.configuration()['revision']})
        self.app.job={'status':'running'};self.toggle(True)
        self.assertEqual(self.app.job['status'],'running')

    def test_saving_daily_trial_replaces_search_and_preserves_disabled_flag(self):
        # Simulates the saved-search endpoint; no collection or settings mutation from trial alone.
        self.app.settings={**SETTINGS,'source':'api'}
        atomic_json(self.app.config_path,self.app.settings)
        self.toggle(False);original=self.app.config_path.read_bytes()
        value=self.app.trial_settings({'keywords':'printable invitations','limit':12,'shop_ids':['42']})
        self.assertEqual(self.app.config_path.read_bytes(),original)
        self.app.save_configuration({'settings':value,'revision':self.app.configuration()['revision']})
        saved=self.app.configuration();self.assertFalse(saved['daily_enabled'])
        self.assertEqual(saved['niches'],[{'category':'Trial search','keywords':'printable invitations'}])
        self.assertEqual(saved['limit'],12);self.assertEqual(saved['shop_ids'],['42'])

    def test_http_toggle_v1_and_removed_versions_same_origin(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.app));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        for route in ('/','/v1','/v1/'):
            body=urllib.request.urlopen(base+route).read().decode()
            self.assertIn('Current daily configuration',body);self.assertNotIn('/v2',body)
        for route in ('/v2','/v3','/v2/','/v3/'):
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+route)
            self.assertEqual(error.exception.code,404)
        payload={'enabled':False,'revision':self.app.configuration()['revision']}
        req=urllib.request.Request(base+'/api/daily-enabled',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':base})
        self.assertFalse(json.load(urllib.request.urlopen(req))['daily_enabled'])
        req.add_header('Origin','http://evil.example')
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
        self.assertEqual(error.exception.code,403)


if __name__=='__main__':unittest.main()
