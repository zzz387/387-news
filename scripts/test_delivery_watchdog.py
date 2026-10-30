"""Recovery scheduling tests without Secrets, real delays or Gemini calls."""
import copy,json,os,subprocess,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from scripts import delivery_watchdog as w,release_monitor as m,release_queue as q,pipeline,news

DAY='2026-10-30'
def at(clock):return datetime.fromisoformat(DAY+'T'+clock).replace(tzinfo=news.TZ)

class Clock:
    def __init__(self,now):self.now=now;self.sleeps=[]
    def __call__(self):return self.now
    def sleep(self,seconds):self.sleeps.append(seconds);self.now+=timedelta(seconds=seconds)

class API:
    def __init__(self,clock):
        self.clock=clock;self.posts=[];self.issues=[];self.rows=[];self.healthy_at=None;self.dispatch_succeeds=True;self.active_until=None;self.bad_list=False
    def check(self,**kwargs):
        assert kwargs['expected_date']==self.clock().date().isoformat()
        if self.healthy_at and self.clock()>=self.healthy_at:return {'https':'verified','articles':12}
        raise RuntimeError('Synthetic missing/stale HTTPS release')
    def __call__(self,method,path,payload=None):
        if path.startswith('actions/workflows/daily-v31.yml/runs'):
            if self.bad_list:return {'workflow_runs':None}
            rows=copy.deepcopy(self.rows)
            if self.active_until and self.clock()<self.active_until:rows.append({'id':1,'head_branch':'main','event':'schedule','status':'in_progress'})
            return {'workflow_runs':rows}
        if path=='actions/workflows/daily-v31.yml':return {'state':'active'}
        if path.endswith('/dispatches'):
            self.posts.append((self.clock(),copy.deepcopy(payload)))
            self.rows.append({'id':100+len(self.posts),'head_branch':'main','event':'workflow_dispatch','display_title':'Delivery '+DAY,'status':'completed','created_at':self.clock().isoformat()})
            if self.dispatch_succeeds:self.healthy_at=self.clock()+timedelta(seconds=60)
            return None  # Actual dispatch REST response is204, not JSON.
        if method=='GET' and path.startswith('issues?'):return copy.deepcopy(self.issues)
        if method=='POST' and path=='issues':
            row=dict(number=len(self.issues)+1,state='open',user={'login':'github-actions[bot]'},**payload);self.issues.append(row);return row
        if method=='PATCH' and path.startswith('issues/'):
            row=next(r for r in self.issues if r['number']==int(path.split('/')[-1]));row.update(payload);return row
        raise AssertionError('Unexpected endpoint '+path)

class WatchdogTests(unittest.TestCase):
    def run_watch(self,clock,api,**kw):
        with patch.object(news,'gemini',side_effect=AssertionError('No model in delivery watchdog')):
            return w.run(Path('/unused'),clock=clock,sleep=clock.sleep,request=api,check=api.check,**kw)

    def test_before_arming_window_is_normal_wait_not_publication_or_error(self):
        clock=Clock(at('04:00'));api=API(clock);result=self.run_watch(clock,api)
        self.assertEqual(result['publication_status'],'WAITING_FOR_RELEASE');self.assertFalse(result['verified']);self.assertEqual(api.posts,[]);self.assertEqual(clock.sleeps,[])

    def test_pre_six_appointment_recovers_at_six_even_without_any_later_cron(self):
        clock=Clock(at('04:55'));api=API(clock);result=self.run_watch(clock,api)
        self.assertTrue(result['verified']);self.assertEqual(api.posts[0][0],at('06:00'))
        self.assertTrue(all(delay<=30 for delay in clock.sleeps));self.assertEqual(len(api.posts),1)

    def test_seven_am_missing_release_dispatches_exact_owner_requested_inputs(self):
        clock=Clock(at('07:00'));api=API(clock);result=self.run_watch(clock,api)
        self.assertEqual(api.posts[0][1],{'ref':'main','inputs':{'phase':'run','preview':'false','target_date':DAY}})
        self.assertTrue(result['verified']);self.assertEqual(result['gemini_requests'],0)

    def test_already_verified_does_not_start_another_producer(self):
        clock=Clock(at('07:00'));api=API(clock);api.healthy_at=clock()
        result=self.run_watch(clock,api);self.assertTrue(result['verified']);self.assertFalse(result['recovery_dispatched']);self.assertEqual(api.posts,[])

    def test_active_production_is_given_time_without_duplicate_dispatch(self):
        clock=Clock(at('07:00'));api=API(clock);api.active_until=clock()+timedelta(seconds=90);api.healthy_at=api.active_until
        result=self.run_watch(clock,api);self.assertTrue(result['verified']);self.assertEqual(api.posts,[])

    def test_active_failure_is_followed_by_one_serial_recovery(self):
        clock=Clock(at('07:00'));api=API(clock);api.active_until=clock()+timedelta(seconds=60)
        result=self.run_watch(clock,api);self.assertTrue(result['verified']);self.assertEqual(api.posts[0][0],at('07:01'))

    def test_stuck_active_job_creates_safe_failure_incident_without_another_generator(self):
        clock=Clock(at('07:00'));api=API(clock);api.active_until=clock()+timedelta(hours=1)
        result=self.run_watch(clock,api,poll_seconds=60)
        self.assertEqual(result['code'],'ACTIVE_PRODUCTION_TIMEOUT');self.assertEqual(api.posts,[]);self.assertEqual(len(api.issues),1)

    def test_failed_recovery_is_bounded_and_its_count_survives_an_independent_watcher(self):
        clock=Clock(at('07:00'));api=API(clock);api.dispatch_succeeds=False
        result=self.run_watch(clock,api,poll_seconds=60)
        self.assertEqual(result['publication_status'],'PUBLICATION_FAILED');self.assertEqual(len(api.posts),1)
        self.assertEqual(m.incident_attempts(api.issues[0]['body']),1)
        # The next independent process sees the same public issue/run metadata.
        clock.now=at('07:13');api.dispatch_succeeds=True
        result=self.run_watch(clock,api,poll_seconds=120)
        self.assertTrue(result['verified']);self.assertEqual(len(api.posts),2);self.assertEqual(api.issues[0]['state'],'closed')

    def test_three_observed_recoveries_prevent_an_unbounded_loop(self):
        clock=Clock(at('07:00'));api=API(clock)
        api.rows=[{'id':i,'head_branch':'main','status':'completed','event':'workflow_dispatch','display_title':'Delivery '+DAY,'created_at':at('06:00').isoformat()} for i in range(3)]
        result=self.run_watch(clock,api);self.assertEqual(result['code'],'WATCHDOG_RECOVERY_LIMIT');self.assertEqual(api.posts,[])

    def test_more_than_three_owner_dispatches_still_create_a_safe_limit_incident(self):
        clock=Clock(at('07:00'));api=API(clock)
        api.rows=[{'id':i,'head_branch':'main','status':'completed','event':'workflow_dispatch','display_title':'Delivery '+DAY,'created_at':at('06:00').isoformat()} for i in range(4)]
        result=self.run_watch(clock,api);self.assertEqual(result['code'],'WATCHDOG_RECOVERY_LIMIT')
        self.assertNotIn('notification_error',result);self.assertEqual(m.incident_attempts(api.issues[0]['body']),3)

    def test_durable_failed_dispatch_count_applies_even_when_github_run_never_appeared(self):
        clock=Clock(at('07:00'));api=API(clock)
        m.incident(DAY,'RECOVERY_NOT_VERIFIED',False,api,recovery_attempts=3)
        result=self.run_watch(clock,api);self.assertEqual(result['code'],'WATCHDOG_RECOVERY_LIMIT');self.assertEqual(api.posts,[])

    def test_delivery_backoff_is_not_bypassed_by_immediate_workflow_run_events(self):
        clock=Clock(at('07:00'));api=API(clock)
        api.rows=[{'id':1,'head_branch':'main','status':'completed','event':'workflow_dispatch','display_title':'Delivery '+DAY,'created_at':at('06:58').isoformat()}]
        result=self.run_watch(clock,api,poll_seconds=30);self.assertFalse(result['verified']);self.assertEqual(api.posts,[])

    def test_untrusted_issue_markers_cannot_disable_or_trigger_production(self):
        clock=Clock(at('07:00'));api=API(clock)
        api.issues=[{'number':99,'state':'open','user':{'login':'untrusted'},'body':f'<!-- 387-news-release:{DAY} -->\n<!-- 387-news-recoveries: 3 -->'}]
        result=self.run_watch(clock,api);self.assertTrue(result['verified']);self.assertEqual(len(api.posts),1);self.assertEqual(api.issues[0]['state'],'open')

    def test_api_uncertainty_fails_closed_without_a_dispatch(self):
        clock=Clock(at('07:00'));api=API(clock);api.bad_list=True
        result=self.run_watch(clock,api);self.assertEqual(result['code'],'WATCHDOG_GITHUB_ERROR');self.assertEqual(api.posts,[])

    def test_pull_request_ci_does_not_masquerade_as_active_production(self):
        clock=Clock(at('07:00'));api=API(clock)
        api.rows=[{'id':1,'head_branch':'main','status':'in_progress','event':'pull_request'}]
        self.assertEqual(w.productions(api),[]);self.assertTrue(self.run_watch(clock,api)['verified'])

    def test_incident_updates_and_closure_preserve_attempt_counts(self):
        clock=Clock(at('07:00'));api=API(clock)
        m.incident(DAY,'RECOVERY_NOT_VERIFIED',False,api,recovery_attempts=2)
        m.incident(DAY,'READY_NOT_PUBLISHED',False,api);m.incident(DAY,'VERIFIED',True,api)
        self.assertEqual(m.incident_attempts(api.issues[0]['body']),2);self.assertEqual(len(api.issues),1)

    def test_dispatch_helper_accepts_empty_204_without_false_failure(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self):return b''
        with patch.dict(os.environ,GITHUB_REPOSITORY='zzz387/387-news',GH_TOKEN='synthetic-only'),patch.object(m,'urlopen',return_value=Response()):
            self.assertIsNone(m.github('POST','actions/workflows/daily-v31.yml/dispatches',{}))

    def test_public_diagnostics_are_fixed_codes_never_raw_error_or_private_prose(self):
        diagnostic={}
        def bad(**kw):raise RuntimeError('PRIVATE_RESEARCH_NARRATIVE_AND_SECRET')
        self.assertFalse(w.current(DAY,bad,diagnostic));self.assertEqual(diagnostic,{'public_check_code':'PUBLIC_CHECK_FAILED'})
        def mismatch(**kw):raise RuntimeError('PUBLIC_CONTENT_CHANGED')
        w.current(DAY,mismatch,diagnostic);self.assertEqual(diagnostic['public_check_code'],'PUBLIC_CONTENT_CHANGED')

    def test_watchdog_import_needs_only_the_standard_library_no_secret_or_crypto_dependency(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,'-S','-c','from scripts import delivery_watchdog; from scripts import publication43; print("WATCHDOG_STDLIB_READY")'],cwd=root,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_publication_states_never_confuse_waiting_or_commit_with_https_verification(self):
        state={'date':DAY,'articles':{'a':{}},'pipeline_status':'APPROVED','audit_passed':True}
        self.assertEqual(pipeline.delivery_state(state,at('05:00')),'WAITING_FOR_RELEASE')
        self.assertEqual(pipeline.delivery_state(state,at('06:00')),'READY_TO_PUBLISH')
        state['pipeline_status']='PUBLISHING'
        self.assertEqual(pipeline.delivery_state(state,at('05:54')),'READY_TO_PUBLISH')
        self.assertEqual(pipeline.delivery_state(state,at('06:00')),'PUBLISHING')
        state['pipeline_status']='PUBLISHED';self.assertNotEqual(pipeline.delivery_state(state,at('07:00')),'PUBLISHED_VERIFIED')
        state['delivery_verified_at']=at('07:00').isoformat();self.assertEqual(pipeline.delivery_state(state,at('07:00')),'PUBLISHED_VERIFIED')
        state['pipeline_status']='BLOCKED';self.assertEqual(pipeline.delivery_state(state,at('07:00')),'PUBLICATION_FAILED')

    def test_independent_https_monitor_is_failed_after_due_and_waiting_before_six(self):
        def absent(**kw):raise RuntimeError('Synthetic missing release')
        self.assertEqual(m.evaluate(Path('/unused'),{},at('05:00'),absent)['publication_status'],'WAITING_FOR_RELEASE')
        self.assertEqual(m.evaluate(Path('/unused'),{},at('06:00'),absent)['publication_status'],'PUBLICATION_FAILED')

class WorkflowContractTests(unittest.TestCase):
    def test_watchdog_is_independent_and_never_gets_model_or_draft_secrets(self):
        root=Path(__file__).resolve().parents[1]
        watcher=(root/'.github/workflows/delivery-watchdog.yml').read_text()
        self.assertIn('workflow_run:',watcher);self.assertIn('schedule:',watcher)
        self.assertIn('head_repository.full_name == github.repository',watcher)
        self.assertIn("event != 'pull_request'",watcher)
        self.assertNotIn('secrets.',watcher);self.assertNotIn('needs:',watcher)
        self.assertNotIn('387-news-stage-v31',watcher)
        producer=(root/'.github/workflows/daily-v31.yml').read_text()
        self.assertIn('387-news-stage-v31',producer);self.assertIn('cancel-in-progress: false',producer)
        self.assertIn('NEWS_MAX_REQUESTS_PER_RUN: "24"',producer);self.assertIn('NEWS_MAX_REQUESTS_PER_DAY: "220"',producer)
        self.assertIn("needs.monitor.outputs.verified == 'true'",producer)

    def test_old_missed_checkpoint_is_not_relabelled_or_overwritten_as_today(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old-2026-10-29.enc';old.write_bytes(b'opaque-synthetic-ciphertext')
            self.assertEqual(q.target_date(root,at('07:00')),DAY)
            self.assertEqual(old.read_bytes(),b'opaque-synthetic-ciphertext')

    def test_current_moscow_date_and_calendar_rollover_never_dispatch_a_wrong_date(self):
        clock=Clock(datetime.fromisoformat('2026-10-29T21:15:00+00:00'));api=API(clock)
        result=w.run(Path('/unused'),clock=clock,sleep=clock.sleep,request=api,check=api.check)
        self.assertEqual(result['date'],DAY);self.assertEqual(api.posts,[])


if __name__=='__main__':unittest.main()
