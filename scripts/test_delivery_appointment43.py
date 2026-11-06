"""Night approval survives missed morning schedules; delivery never invokes a model."""
import copy,os,tempfile,unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from scripts import daily43 as d,publication43 as pub,release_queue as q,news,generation_runtime as rt,delivery_watchdog as w
from scripts.test_daily43 import state,root,NOW,RESERVE_FIXTURE
from scripts import test_delivery_watchdog as fixtures

class AppointmentTests(unittest.TestCase):
    def test_0137_watcher_dispatches_at_0554_without_another_cron_and_verifies_after_six(self):
        clock=fixtures.Clock(fixtures.at('01:37'));api=fixtures.API(clock)
        result=w.run('/unused',clock=clock,sleep=clock.sleep,request=api,check=api.check)
        self.assertTrue(result['verified']);self.assertEqual(len(api.posts),1)
        self.assertEqual(api.posts[0][0],fixtures.at('05:54'));self.assertGreaterEqual(clock(),fixtures.at('06:00'))
        self.assertEqual(api.posts[0][1]['inputs']['phase'],'publish');self.assertEqual(result['gemini_requests'],0)

    def test_observed_0251_not_due_run_now_arms_the_same_morning(self):
        clock=fixtures.Clock(fixtures.at('02:51'));api=fixtures.API(clock)
        self.assertTrue(w.run('/unused',clock=clock,sleep=clock.sleep,request=api,check=api.check)['verified'])
        self.assertEqual(api.posts[0][0],fixtures.at('05:54'))

    def test_appointment_job_fits_the_hosted_limit_and_keeps_other_producers_unlocked(self):
        self.assertLessEqual(w.ARM_SECONDS+w.POLL_SECONDS,330*60)
        self.assertLess(330,360)
        from pathlib import Path
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/delivery-watchdog.yml').read_text()
        self.assertIn('timeout-minutes: 330',workflow);self.assertNotIn('387-news-stage-v31',workflow);self.assertNotIn('secrets.',workflow)

    def test_delivery_of_nightly_eleven_preserves_articles_and_exhausted_model_ledger(self):
        s=state(11);before=copy.deepcopy(s['candidates']);ledger={'day':s['date'],'requests':220,'models':{},'cooldowns':{'fixture':9999999999}}
        budget=rt.RequestBudget(ledger,day_limit=220);snapshot=copy.deepcopy(ledger)
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'),patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(news,'gemini',side_effect=AssertionError('Delivery cannot infer')),patch.object(d,'discover',side_effect=AssertionError('Delivery cannot search')):
            target=root(temp);ops=SimpleNamespace(ROOT=target)
            self.assertFalse(d.deliver(s,s['date'],False,ops,now=NOW.replace(hour=1,minute=37)))
            self.assertEqual(s['pipeline_status'],'APPROVED');self.assertFalse((target/'issues'/s['date']).exists())
            self.assertTrue(d.deliver(s,s['date'],False,ops,now=NOW.replace(hour=6,minute=0)))
            self.assertEqual(pub.validate(target,s['date'])['article_count'],11)
        self.assertEqual(s['candidates'],before);self.assertEqual(ledger,snapshot);self.assertEqual(budget.used,0)

    def test_prewarm_does_not_call_writer_and_commit_gate_still_waits_until_six(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'),patch.object(d,'discover',side_effect=AssertionError('No discovery')):
            s=state(11);target=root(temp)
            self.assertTrue(d.deliver(s,s['date'],False,SimpleNamespace(ROOT=target),now=NOW.replace(hour=5,minute=54)))
            clock=fixtures.Clock(NOW.replace(hour=5,minute=54));q.wait_until_release(s['date'],clock=clock,sleep=clock.sleep)
            self.assertEqual(clock().hour,6);self.assertEqual(clock().minute,0)

    def test_repeated_delivery_and_pages_failure_do_not_rewrite_or_regenerate(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'),patch.object(news,'gemini',side_effect=AssertionError('No model')):
            s=state(11);target=root(temp);pub.build(s,target)
            before={str(f):f.read_bytes() for f in (target/'issues').rglob('*') if f.is_file()}
            def missing(**kwargs):raise RuntimeError('Synthetic Pages failure')
            self.assertTrue(d.deliver(s,s['date'],False,SimpleNamespace(ROOT=target),now=NOW,check_public=missing))
            self.assertFalse(d.deliver(s,s['date'],False,SimpleNamespace(ROOT=target),now=NOW+timedelta(minutes=11),check_public=lambda **kw:{}))
            self.assertEqual(before,{str(f):f.read_bytes() for f in (target/'issues').rglob('*') if f.is_file()})

    def test_delivery_three_or_zero_is_not_a_full_issue_without_stock(self):
        for count in (0,3):
            with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'),patch.object(d,'reserve_rows',return_value=[RESERVE_FIXTURE]),patch.object(news,'gemini',side_effect=AssertionError('No model')):
                s=state(count);target=root(temp)
                self.assertFalse(d.deliver(s,s['date'],False,SimpleNamespace(ROOT=target),now=NOW))
                self.assertEqual(s['block_code'],'MINIMUM_ARTICLES_NOT_MET');self.assertFalse((target/'issues'/s['date']).exists())

    def test_lead_wait_is_bounded_and_normal_commit_wait_remains_early_publication_gate(self):
        clock=fixtures.Clock(fixtures.at('01:37'))
        q.wait_until_release(fixtures.DAY,clock=clock,sleep=clock.sleep,maximum_wait=w.ARM_SECONDS,lead_seconds=w.DELIVERY_LEAD_SECONDS)
        self.assertEqual(clock(),fixtures.at('05:54'))
        with self.assertRaises(ValueError):q.wait_until_release(fixtures.DAY,clock=clock,maximum_wait=18001)
        with self.assertRaises(ValueError):q.wait_until_release(fixtures.DAY,clock=clock,lead_seconds=601)

if __name__=='__main__':unittest.main()
