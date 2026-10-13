"""Named collection schedules use saved fixtures and a fake collector only."""
import datetime as dt
import hashlib
import json
import unittest
from unittest.mock import patch
import test_controller
from pipeline_control.cycles import create, decide, observe, tick
from pipeline_control.storage import digest, read, write


class CycleTests(unittest.TestCase):
    setUp=test_controller.ControllerTests.setUp
    start=dt.datetime(2026,9,1,tzinfo=dt.timezone.utc)
    def profile(self,name='Holiday Judaica',keywords=None):
        return create(self.c,{'name':name,'keywords':keywords or ['printable hanukkah'],'shop_ids':[],'limit':None},self.start)
    def report(self,row,day,complete=True,suggest='printable hanukkah kids',listing='123'):
        run='cycle-'+str(day);value={**self.snapshot,'run_id':run,'finished_at':(self.start+dt.timedelta(days=day)).isoformat(),
                                  'settings':row['manifest']['parameters'],'manifest_sha256':row['manifest_sha256'],
                                  'lineage':{'cycle_id':row['cycle_id']},'queries':[{'niche':row['manifest']['parameters']['niches'][0],
                                  'collection_complete':complete,'listings':[{'listing_id':listing,'shop_id':'8','digital':True,'title':'Printable Hanukkah art'}]}]}
        path=self.c.source/run/'snapshot.json';write(path,value);write(path.parent/'dqa.json',value['dqa'])
        return {**self.payload,'source_run_id':run,'source':{'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest()},'report':{'recommendations':[{'keywords':suggest}]}}
    def saved(self,row):return read(self.c.root/'cycles'/(row['cycle_id']+'.json'))
    def test_new_cycle_preserves_finalized_named_profile(self):
        old=self.profile();decide(self.c,old['cycle_id'],{'action':'finalize','manifest_sha256':old['manifest_sha256']},self.start)
        new=self.profile('Parashat Shavua',['printable parashat shavua'])
        self.assertNotEqual(new['cycle_id'],old['cycle_id']);saved=self.saved(old)
        self.assertEqual(saved['status'],'finalized');self.assertEqual(saved['cadence'],'weekly');self.assertEqual(saved['manifest'],old['manifest'])
        self.c=test_controller.Controller(self.settings)
        self.assertEqual(self.saved(old)['manifest'],old['manifest'])
        self.assertEqual(self.profile()['cycle_id'],old['cycle_id'])
    def test_three_complete_low_novelty_stable_runs_over_seven_days_settle(self):
        row=self.profile()
        for day in (0,1,5,9):observe(self.c,self.report(row,day))
        saved=self.saved(row);self.assertTrue(saved['exhaustion']['detected']);self.assertEqual(saved['cadence'],'weekly')
        self.assertNotIn('listing_ids',saved['observations'][0]);self.assertEqual(len(list((self.c.root/'cycle-observations'/row['cycle_id']).glob('*.json'))),4)
        observe(self.c,self.report(row,9));self.assertEqual(len(self.saved(row)['observations']),4)
    def test_partial_short_unstable_and_new_results_do_not_settle(self):
        for failure in ('partial','short','unstable','novel','empty_suggestions'):
            row=self.profile(failure)
            for day in (0,1,5,9) if failure!='short' else (0,1,2,3):
                observe(self.c,self.report(row,day,complete=not (failure=='partial' and day==5),
                    suggest='printable different' if failure=='unstable' and day==5 else '' if failure=='empty_suggestions' else 'printable hanukkah kids',
                    listing=str(day) if failure=='novel' else '123'))
            with self.subTest(failure=failure):self.assertEqual(self.saved(row)['cadence'],'daily')
    def test_manual_override_wins_and_novelty_reopens_automatic_daily(self):
        row=self.profile();decide(self.c,row['cycle_id'],{'action':'daily','manifest_sha256':row['manifest_sha256']},self.start)
        for day in (0,1,5,9):observe(self.c,self.report(row,day))
        self.assertTrue(self.saved(row)['exhaustion']['detected']);self.assertEqual(self.saved(row)['cadence'],'daily')
        decide(self.c,row['cycle_id'],{'action':'auto','manifest_sha256':row['manifest_sha256']},self.start)
        self.assertEqual(self.saved(row)['cadence'],'weekly');observe(self.c,self.report(row,10,listing='new'))
        self.assertEqual(self.saved(row)['cadence'],'daily')
    def test_daily_observations_can_cover_full_stabilization_week(self):
        row=self.profile()
        for day in range(8):observe(self.c,self.report(row,day))
        self.assertEqual(self.saved(row)['cadence'],'daily')
        observe(self.c,self.report(row,8));self.assertEqual(self.saved(row)['cadence'],'weekly')
    def test_weekly_due_unknown_submission_never_resends(self):
        row=self.profile();row=decide(self.c,row['cycle_id'],{'action':'weekly','manifest_sha256':row['manifest_sha256']},self.start)
        self.c.settings['execution_enabled']=True;calls=[]
        def fail(request):calls.append(request);raise OSError('Lost ACK')
        tick(self.c,fail,self.start+dt.timedelta(days=6));self.assertEqual(calls,[])
        tick(self.c,fail,self.start+dt.timedelta(days=7));tick(self.c,fail,self.start+dt.timedelta(days=30))
        self.assertEqual(len(calls),1);self.assertEqual(self.saved(row)['status'],'submission_unknown')
        self.assertFalse(calls[0]['parameters']['exclude_fetched_shops']);self.assertFalse(calls[0]['parameters']['exclude_fetched_listings'])
    def test_inflight_blocks_future_slots_and_saved_challenge_pauses(self):
        row=self.profile();self.c.settings['execution_enabled']=True;calls=[]
        def submit(request):calls.append(request);return {'run_id':'new-run'}
        tick(self.c,submit,self.start+dt.timedelta(days=1));tick(self.c,submit,self.start+dt.timedelta(days=2));self.assertEqual(len(calls),1)
        write(self.c.source/'new-run'/'snapshot.json',{'status':'failed','finished_at':self.start.isoformat(),'queries':[{'http_status':429}]})
        tick(self.c,submit,self.start+dt.timedelta(days=3));self.assertEqual(self.saved(row)['status'],'paused_access_challenge');self.assertEqual(len(calls),1)
    def test_explicit_reconcile_only_gets_saved_ack(self):
        row=self.profile();self.c.settings['execution_enabled']=True
        tick(self.c,lambda r:(_ for _ in ()).throw(OSError()),self.start+dt.timedelta(days=1))
        saved=self.saved(row);receipt=read(self.c.root/'cycle-jobs'/(saved['pending_job']+'.json'))
        with patch.object(self.c,'send_job',return_value={'run_id':'new-run','request_sha256':digest(receipt['request'])}) as call:
            result=decide(self.c,row['cycle_id'],{'action':'reconcile','manifest_sha256':row['manifest_sha256']})
        call.assert_called_once_with(receipt['request'],lookup=True);self.assertEqual(result['status'],'active')
    def test_bad_source_hash_and_changed_parameters_cannot_reduce_cadence(self):
        row=self.profile();report=self.report(row,1);report['source']['input_sha256']='0'*64
        with self.assertRaises(ValueError):observe(self.c,report)
        for value in ({'name':'x','keywords':['printable'],'shop_ids':[],'limit':None},
                      {'name':'Safe name','keywords':['$(curl evil)'],'shop_ids':[],'limit':None},
                      {'name':'Safe name','keywords':['printable'],'shop_ids':['../etc'],'limit':None}):
            with self.assertRaises(ValueError):create(self.c,value)
    def test_disabled_execution_and_pause_never_submit(self):
        row=self.profile();calls=[];tick(self.c,calls.append,self.start+dt.timedelta(days=30));self.assertEqual(calls,[])
        self.c.settings['execution_enabled']=True;decide(self.c,row['cycle_id'],{'action':'pause','manifest_sha256':row['manifest_sha256']})
        tick(self.c,calls.append,self.start+dt.timedelta(days=30));self.assertEqual(calls,[])


if __name__=='__main__':unittest.main()
