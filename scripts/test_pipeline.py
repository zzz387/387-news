import copy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
try:
    from scripts import pipeline as p, release_queue as q, generation_runtime as runtime, publication, release_monitor as monitor, staged_news as stage
    from scripts.test_audit_policy import fixture
except ImportError:
    import pipeline as p
    import release_queue as q
    import generation_runtime as runtime
    import publication
    import release_monitor as monitor
    import staged_news as stage
    from test_audit_policy import fixture

DATE='2026-10-27'

def at(clock, date=DATE):
    return datetime.fromisoformat(date+'T'+clock).replace(tzinfo=p.news.TZ)


def edition(date=DATE):
    state=fixture(); state['date']=date
    for i,plan in enumerate(state['plan']):
        count=8 if plan['long'] else 5
        claims=[{'source_id':f'S{i+1:03d}','quote':f'Invented test evidence {i} fact {j}'} for j in range(count)]
        state['dossiers'][str(i)]={'claims':claims}
        state['sources'][i]['evidence']='\n'.join(c['quote'] for c in claims)
    return state


def public_files(root,state):
    value=publication.public_issue(state,4)
    date=state['date']; base=root/'issues'/date; base.mkdir(parents=True,exist_ok=True)
    (base/'issue.json').write_text(json.dumps(value))
    overview=''.join(f'<a href="/issues/{date}/articles/{a["slug"]}/">Article</a>' for a in value['articles'])
    for article in value['articles']:
        path=base/'articles'/article['slug']/'index.html'; path.parent.mkdir(parents=True,exist_ok=True)
        body=''.join('<p>'+v['text']+'</p>' for v in article['paragraphs'])
        path.write_text('<meta name="viewport"><div class="article-body">'+body+'</div>')
    (base/'index.html').write_text(overview); (root/'index.html').write_text(overview)
    (root/'archive').mkdir(exist_ok=True)
    (root/'archive/index.html').write_text(f'<a href="/issues/{date}/">Issue</a>')


class Ops:
    def __init__(self,root,basis,charge=False):
        self.ROOT=root; self.basis=copy.deepcopy(basis); self.calls=[]; self.charge=charge
    def paid_step(self,kind):
        self.calls.append(kind)
        if self.charge: runtime.ACTIVE_BUDGET.reserve('lite')
    def build_plan(self,state,date):
        self.paid_step('plan'); state['plan']=copy.deepcopy(self.basis['plan']); state['sources']=copy.deepcopy(self.basis['sources'])
    def research_batch(self,state,size):
        self.paid_step('research')
        for i in range(8):
            slot=str(i)
            if slot not in state['dossiers']:
                state['dossiers'][slot]=copy.deepcopy(self.basis['dossiers'][slot]); size-=1
                if not size: break
    def write_batch(self,state,size):
        self.paid_step('write')
        for slot in list(state.get('audit_repairs',{})):
            state['articles'][slot]['paragraphs'][0]['text']+=' Обоснованная правка.'
            state['articles'][slot]['word_count']+=2
            state['audit_repairs'].pop(slot)
        for i in range(8):
            slot=str(i)
            if slot not in state['articles']:
                state['articles'][slot]=copy.deepcopy(self.basis['articles'][slot]); size-=1
                if not size: break
    def audit(self,state):
        self.paid_step('audit'); state.update(audit_passed=True,stage='audited')
    def render(self,state,preview):
        self.calls.append('private_build' if preview else 'publish')
        if not preview: public_files(self.ROOT,state)
        return not preview


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name); self.state=edition(); self.ops=Ops(self.root,self.state)
        self.env=patch.dict(os.environ,{'NEWS_RELEASE_APPROVED':'true','GITHUB_REF_NAME':'main'}); self.env.start(); self.addCleanup(self.env.stop)
        self.budget=patch.object(runtime,'ACTIVE_BUDGET',None); self.budget.start(); self.addCleanup(self.budget.stop)
    def advance(self,now,**kwargs):
        return p.advance(self.state,DATE,False,self.ops,now=now,check_public=lambda **k: {},**kwargs)

    def test_01_ready_at_0530_waits_then_releases_after_0600(self):
        self.assertFalse(self.advance(at('05:30:00')))
        self.assertEqual(self.state['pipeline_status'],'WAITING_FOR_RELEASE_TIME')
        self.assertNotIn('publish',self.ops.calls)
        self.assertTrue(self.advance(at('06:05:00')))
        self.assertEqual(self.ops.calls.count('audit'),1)
        self.assertEqual(self.ops.calls.count('private_build'),1)
        self.assertEqual(self.ops.calls.count('publish'),1)

    def test_02_missed_final_cron_releases_at_0715_with_no_new_api_calls(self):
        self.state.update(audit_passed=True,stage='audited')
        self.assertTrue(self.advance(at('07:15:00')))
        self.assertNotIn('audit',self.ops.calls); self.assertNotIn('write',self.ops.calls)

    def test_03_any_preparation_wakeup_audits_eight_complete_articles(self):
        self.assertFalse(self.advance(at('04:17:00')))
        self.assertEqual(self.ops.calls.count('audit'),1)
        self.assertTrue(self.state['audit_passed'])

    def test_04_only_eighth_article_written_then_audited_and_published(self):
        before=copy.deepcopy(self.state['articles']); self.state['articles'].pop('4')
        self.assertTrue(self.advance(at('07:15:00')))
        self.assertEqual(self.ops.calls[:2],['write','audit'])
        for slot in before:
            if slot!='4': self.assertTrue(before[slot]==self.state['articles'][slot])

    def test_completion_crossing_0600_publishes_in_the_same_run(self):
        self.state['articles'].pop('4')
        current=[at('05:20:00')]
        original=self.ops.write_batch
        def late_write(state,size):
            original(state,size)
            current[0]=at('06:05:00')
        self.ops.write_batch=late_write
        with patch.object(p,'now_moscow',side_effect=lambda:current[0]):
            self.assertTrue(p.advance(self.state,DATE,False,self.ops,check_public=lambda **kw:{}))
        self.assertIn('publish',self.ops.calls)

    def test_05_daily_quota_preserves_ready_state_and_rollover_resumes_normally(self):
        today=datetime.now(timezone.utc).date()
        ledger={'day':today.isoformat(),'requests':220,'models':{'lite':220}}
        budget=runtime.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0,seconds=720)
        with patch.object(runtime,'ACTIVE_BUDGET',budget):
            self.assertFalse(self.advance(at('04:17:00')))
        self.assertEqual(self.state['pipeline_status'],'READY_FOR_AUDIT')
        self.assertEqual(ledger['requests'],220); self.assertFalse(self.ops.calls)
        tomorrow=datetime.combine(today+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)
        self.ops.charge=True
        with patch.object(runtime,'datetime') as clock:
            clock.now.return_value=tomorrow
            with patch.object(runtime,'ACTIVE_BUDGET',runtime.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0,seconds=720)):
                self.advance(at('04:17:00'))
        self.assertEqual(ledger['day'],tomorrow.date().isoformat())
        self.assertEqual(ledger['requests'],1)
        self.assertTrue(self.state['audit_passed'])

    def test_06_published_edition_is_not_regenerated_or_renumbered(self):
        public_files(self.root,self.state)
        before={str(f.relative_to(self.root)):f.read_bytes() for f in self.root.rglob('*') if f.is_file()}
        self.assertFalse(self.advance(at('07:15:00')))
        self.assertEqual(self.state['pipeline_status'],'PUBLISHED'); self.assertFalse(self.ops.calls)
        after={str(f.relative_to(self.root)):f.read_bytes() for f in self.root.rglob('*') if f.is_file()}
        self.assertEqual(before,after)

    def test_07_stale_pages_only_redeploys_and_retries_are_bounded(self):
        public_files(self.root,self.state)
        before=(self.root/'issues'/DATE/'issue.json').read_bytes()
        def stale(**kw): raise RuntimeError('Public website still shows the previous issue')
        for clock,expected in [('07:15:00',True),('07:16:00',False),('07:30:00',True),('07:45:00',True),('08:15:00',False)]:
            result=p.advance(self.state,DATE,False,self.ops,now=at(clock),check_public=stale)
            self.assertEqual(result,expected)
        self.assertEqual(self.state['block_code'],'DELIVERY_RETRY_LIMIT')
        self.assertFalse(self.ops.calls)
        self.assertEqual(before,(self.root/'issues'/DATE/'issue.json').read_bytes())

    def test_08_midnight_keeps_next_morning_edition_date(self):
        # Today's published edition permits tomorrow's private preparation.
        public_files(self.root,edition('2026-10-26'))
        healthy=lambda **kw: {}
        self.assertEqual(q.context('write',False,'','schedule',self.root,at('22:00:00','2026-10-26'),healthy),('run',False,DATE))
        self.assertEqual(q.context('write',False,'','schedule',self.root,at('03:00:00'),healthy),('run',False,DATE))

    def test_09_legacy_checkpoint_date_is_never_selected_for_new_morning(self):
        public_files(self.root,edition('2026-10-25'))
        self.assertEqual(q.pending_date(self.root,at('07:00:00')),DATE)
        self.assertEqual(q.target_date(self.root,at('07:00:00')),DATE)
        self.assertNotIn('prior_artifact_id',q.__dict__)
        self.assertNotIn('CONFIG',q.__dict__)

    def test_10_all_night_crons_missed_pipeline_resumes_every_stage(self):
        self.state={'version':31,'date':DATE,'articles':{},'dossiers':{},'audit_passed':False}
        self.assertTrue(self.advance(at('07:15:00')))
        self.assertFalse(self.advance(at('07:30:00')))
        self.assertEqual(self.ops.calls.count('plan'),1)
        self.assertEqual(self.ops.calls.count('audit'),1)

    def test_11_serialized_independent_runs_publish_once(self):
        other=copy.deepcopy(self.state)
        self.assertTrue(self.advance(at('07:15:00')))
        ops2=Ops(self.root,other)
        self.assertFalse(p.advance(other,DATE,False,ops2,now=at('07:16:00'),check_public=lambda **kw:{}))
        self.assertFalse(ops2.calls)
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/daily-v31.yml').read_text()
        self.assertIn("'387-news-stage-v31'",workflow)
        self.assertIn('cancel-in-progress: false',workflow)
        self.assertNotIn('cancel-in-progress: true',workflow)

    def test_12_editorial_hold_never_publishes_or_discards_articles(self):
        original=copy.deepcopy(self.state['articles'])
        def veto(state): state['audit_blocked']='Private diagnosis retained'
        self.ops.audit=veto
        self.assertFalse(self.advance(at('07:15:00')))
        self.assertEqual(self.state['pipeline_status'],'BLOCKED')
        self.assertTrue(original==self.state['articles']); self.assertNotIn('publish',self.ops.calls)

    def test_12b_attributed_veto_is_repaired_before_any_publication(self):
        try:
            from scripts import audit_repair, audit_policy
        except ImportError:
            import audit_repair
            import audit_policy
        original=copy.deepcopy(self.state['articles'])
        count=0
        def audit(state):
            nonlocal count
            count+=1
            self.ops.calls.append('audit')
            if count==1:
                audit_repair.record_veto(state,[audit_policy.issue('article_quality',scope='article',
                    article_ids=[5],repair_ids=[5],action='revise_article',
                    reason='Synthetic opening weakness',instruction='Correct opening from saved evidence')])
                self.assertNotIn('publish',self.ops.calls)
            else:
                state.update(audit_passed=True,stage='audited')
        self.ops.audit=audit
        self.assertTrue(self.advance(at('07:15:00')))
        self.assertEqual(self.ops.calls[:3],['audit','write','audit'])
        for slot in original:
            if slot!='4': self.assertTrue(original[slot]==self.state['articles'][slot])

    def test_13_after_success_next_day_is_selected_at_noon(self):
        public_files(self.root,self.state)
        result=q.context('plan',False,'','schedule',self.root,at('12:00:00'),lambda **kw:{})
        self.assertEqual(result,('run',False,'2026-10-28'))

    def test_14_after_commit_but_stale_site_router_prioritizes_delivery_over_new_day(self):
        public_files(self.root,self.state)
        def stale(**kw): raise RuntimeError('Previous issue still served')
        self.assertEqual(q.context('plan',False,'','schedule',self.root,at('12:00:00'),stale),('run',False,DATE))
        self.assertTrue(p.advance(self.state,DATE,False,self.ops,now=at('12:00:00'),check_public=stale))
        self.assertFalse(self.ops.calls)

    def test_readiness_requires_saved_literal_evidence(self):
        self.state['dossiers']['4']['claims'][0]['quote']='Not in saved source'
        self.assertFalse(self.advance(at('07:15:00')))
        self.assertEqual(self.state['block_code'],'EVIDENCE_INTEGRITY')
        self.assertNotIn('audit',self.ops.calls)

    def test_preview_never_commits_even_after_release_time(self):
        self.assertFalse(p.advance(self.state,DATE,True,self.ops,now=at('07:15:00')))
        self.assertTrue(self.state['audit_passed']); self.assertNotIn('publish',self.ops.calls)

    def test_release_variable_is_required(self):
        with patch.dict(os.environ,{'NEWS_RELEASE_APPROVED':'false'}):
            self.assertFalse(self.advance(at('07:15:00')))
        self.assertNotIn('publish',self.ops.calls)
        self.assertEqual(self.state['block_code'],'RELEASE_DISABLED')

    def test_wrong_dated_checkpoint_is_rejected_before_controller_or_api(self):
        import sys
        old=edition('2026-10-25'); before=copy.deepcopy(old)
        with patch.dict(os.environ,{'GITHUB_REF_NAME':'main','DRAFT_ENCRYPTION_KEY':'synthetic-only'}), \
             patch.object(stage,'validate_key',return_value=bytes(range(32))), \
             patch.object(stage,'fetch_latest_checkpoint',return_value=old), \
             patch.object(sys,'argv',['staged_news','--phase','run','--target-date',DATE]), \
             patch.object(stage.pipeline,'advance') as controller:
            with self.assertRaisesRegex(RuntimeError,'Bad checkpoint metadata'): stage.main()
            controller.assert_not_called()
        self.assertTrue(old==before)

    def test_quota_day_rollover_preserves_external_retry_after(self):
        import time
        today=datetime.now(timezone.utc).date()
        deadline=time.time()+900
        ledger={'day':(today-timedelta(days=1)).isoformat(),'requests':220,
                'models':{'lite':220},'cooldowns':{'lite':deadline}}
        budget=runtime.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0,seconds=720)
        with self.assertRaisesRegex(runtime.GenerationPaused,'cooldown'): budget.reserve('lite')
        self.assertEqual(budget.used,0)
        self.assertEqual(ledger['cooldowns']['lite'],deadline)
        self.assertEqual(ledger['requests'],0)

    def test_budget_inspection_does_not_reset_old_counters(self):
        old={'day':'2000-01-01','requests':220,'models':{'lite':220}}
        before=copy.deepcopy(old)
        budget=runtime.RequestBudget(old,run_limit=24,day_limit=220,gap=0,seconds=720)
        self.assertEqual(budget.remaining_requests(),24)
        self.assertTrue(budget.can_request())
        self.assertEqual(old,before)

    def test_summary_is_technical_and_does_not_claim_publishing_is_delivered(self):
        self.state.update(pipeline_status='PUBLISHING',next_action='commit_and_deploy',audit_note='PRIVATE-DOSSIER')
        value=p.report(self.state,{'day':'2026-10-26','requests':220},at('07:15:00'))
        self.assertFalse(value['publication_verified'])
        self.assertNotIn('PRIVATE',json.dumps(value))
        self.assertEqual(value['articles'],8)


class MonitorTests(unittest.TestCase):
    def test_notification_is_created_once_updated_and_closed_after_delivery(self):
        issues=[]; posts=[]
        def request(method,path,payload=None):
            if method=='GET': return copy.deepcopy(issues)
            if method=='POST':
                posts.append(payload); issues.append(dict(number=1,state='open',**payload)); return issues[0]
            issues[0].update(payload); return issues[0]
        self.assertEqual(monitor.incident(DATE,'NOT_PREPARED',False,request),'created')
        monitor.incident(DATE,'NOT_PREPARED',False,request)
        monitor.incident(DATE,'QUOTA_EXHAUSTED',False,request)
        self.assertEqual(len(posts),1)
        monitor.incident(DATE,'VERIFIED',True,request)
        self.assertEqual(issues[0]['state'],'closed')

    def test_monitor_distinguishes_quota_editorial_and_ready_unpublished(self):
        def absent(**kw): raise RuntimeError('Site stale')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for status,expected in [({'block_code':'DAILY_QUOTA'},'QUOTA_EXHAUSTED'),
                                    ({'block_code':'API_COOLDOWN'},'EXTERNAL_SERVICE'),
                                    ({'block_code':'AUDIT_EXTERNAL_ERROR'},'EXTERNAL_SERVICE'),
                                    ({'block_code':'RELEASE_DISABLED','stage':'BLOCKED'},'SETTINGS_BLOCKED'),
                                    ({'stage':'BLOCKED'},'EDITORIAL_HOLD'),
                                    ({'audit_passed':True},'READY_NOT_PUBLISHED'),({},'NOT_PREPARED')]:
                status['date']=DATE
                result=monitor.evaluate(root,status,at('07:15:00'),absent)
                self.assertEqual(result['code'],expected)
                self.assertTrue(result['alert'])

    def test_https_success_resolves_today_even_while_tomorrow_is_being_written(self):
        result=monitor.evaluate(Path('/nonexistent'),{'date':'2026-10-28','stage':'WRITING'},at('12:00:00'),lambda **kw:{})
        self.assertTrue(result['verified']); self.assertFalse(result['alert'])

if __name__=='__main__': unittest.main()
