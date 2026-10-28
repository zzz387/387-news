"""Owner priority, bounded lifecycle and section repair: synthetic/no API calls."""
import copy,json,os,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from scripts import special_priority41 as q,special003r as runner,policy41 as p,content41 as c,editorial41 as e,staged_news as stage
from scripts.test_policy41 import record


class PriorityTests(unittest.TestCase):
    def test_priority_admits_at_night_without_daily_and_preserves_inputs(self):
        now=datetime(2026,10,27,5,tzinfo=p.TZ);ledger={'day':'2026-10-27','requests':24,'models':{'lite':24},'cooldowns':{}}
        before=copy.deepcopy(ledger)
        self.assertEqual(runner.admit(p.ROOT,None,ledger,now,priority=True),(True,'SPECIAL_FIRST_OWNER_AUTHORIZED'))
        self.assertEqual(ledger,before)
        with patch.object(runner,'datetime',wraps=datetime) as clock:
            clock.now.return_value=now
            self.assertEqual(runner.remaining_run_limit(0,dict(ledger,requests=219),priority=True),1)
            self.assertEqual(runner.remaining_run_limit(24,ledger,priority=True),0)

    def test_priority_never_overrides_quota_or_cooldown(self):
        now=datetime(2026,10,27,5,tzinfo=p.TZ)
        self.assertEqual(runner.admit(p.ROOT,None,{'day':'2026-10-27','requests':220},now,priority=True)[1],'DAILY_QUOTA')
        self.assertEqual(runner.admit(p.ROOT,None,{'day':'2026-10-26','requests':220,'cooldowns':{'lite':now.timestamp()+60}},now,priority=True)[1],'GEMINI_COOLDOWN')
        self.assertTrue(runner.admit(p.ROOT,None,{'day':'2026-10-26','requests':220},now,priority=True)[0])
        self.assertEqual(runner.admit(p.ROOT,None,{'day':'2026-10-28','requests':0},now,priority=True)[1],'FUTURE_SHARED_LEDGER')

    def test_priority_survives_checkpoint_and_releases_only_after_https_verification(self):
        state=runner.new_state();self.assertTrue(q.reconcile(state)[0]);key=bytes(range(32))
        restored=stage.decipher(stage.cipher(state,key),key)
        self.assertEqual(state['production_priority'],restored['production_priority'])
        restored['audit_passed']=True;self.assertTrue(q.reconcile(restored)[0])
        restored['publication_verified']=True;self.assertFalse(q.reconcile(restored)[0])
        self.assertEqual(restored['production_priority']['status'],'COMPLETED')
        restored.pop('publication_verified');self.assertFalse(q.reconcile(restored)[0])

    def test_terminal_block_and_stalls_are_bounded_and_not_reactivated(self):
        state=runner.new_state();q.reconcile(state)
        for _ in range(4):q.finish_run(state,q.fingerprint(state),1)
        self.assertEqual(q.reconcile(state)[1],'SPECIAL_PRIORITY_STALLED')
        state['production_priority']['stalled_runs']=0
        self.assertFalse(q.reconcile(state)[0])
        other=runner.new_state();q.reconcile(other)
        for r in other['candidates']:r['status']='ready'
        other['candidates'][0]['status']='needs_review'
        self.assertEqual(q.reconcile(other)[1],'SPECIAL_TOPIC_NEEDS_REVIEW')

    def test_budget_wait_does_not_count_as_stall_and_time_limit_survives_restore(self):
        state=runner.new_state();now=datetime(2026,10,27,5,tzinfo=p.TZ);q.reconcile(state,now)
        q.finish_run(state,q.fingerprint(state),0)
        self.assertEqual(state['production_priority']['stalled_runs'],0)
        self.assertEqual(q.reconcile(copy.deepcopy(state),now+timedelta(hours=72))[1],'SPECIAL_PRIORITY_TIME_LIMIT')

    def test_policy43_daily_has_no_disabled_special_ancestor_and_keeps_mutex_and_cron(self):
        daily=(p.ROOT/'.github/workflows/daily-v31.yml').read_text()
        prepare=daily.split('  prepare:\n',1)[1].split('  deploy:\n',1)[0]
        self.assertNotIn('needs.special-003-r',prepare)
        self.assertNotIn('needs: special-003-r',prepare)
        self.assertIn("always() && needs.prepare.result == 'success'",daily)
        self.assertIn('if: ${{ false }}',daily)
        self.assertIn("|| '387-news-stage-v31'",daily)
        self.assertEqual(daily.count('- cron:'),6)
        self.assertIn("cron: '54 2 * * *'",daily)
        special=(p.ROOT/'.github/workflows/special-003-r.yml').read_text()
        self.assertNotIn('schedule:',special)
        self.assertNotIn('path: ${{ runner.temp }}/read-only-daily\n          retention',special)


class SectionTests(unittest.TestCase):
    def fixture(self):
        r=record();r['mode']='INDEPENDENT_ARTICLE';r.pop('article');r['progress']={}
        section={'id':'s1','requirement_ids':['r1'],'activity_count':0}
        result={'id':'s1','finished':True,'blocks':[{'kind':'paragraph','text':'Другое самостоятельное объяснение.'}],
                'activities':[],'covered_requirements':[],'covered_requirement_ids':['r1']}
        return r,section,result

    def test_requirement_ids_bind_exact_text_but_unknown_reference_is_rejected(self):
        r,section,result=self.fixture();c.validate_section(result,section,r,{'r1':'Полный точный вопрос'})
        self.assertEqual(result['covered_requirements'],['Полный точный вопрос'])
        result['covered_requirement_ids']=['r100']
        with self.assertRaisesRegex(p.Blocked,'SECTION_REQUIREMENT_REFERENCE_INVALID'):c.validate_section(result,section,r,{'r1':'Вопрос'})

    def test_bad_block_is_rejected_before_accepted_cache(self):
        r,section,result=self.fixture();result['blocks'][0]['kind']='list'
        with self.assertRaisesRegex(p.Blocked,'ARTICLE_BLOCK_INVALID'):c.validate_section(result,section,r,{'r1':'Вопрос'})
        self.assertNotIn('s1',r['progress'].get('sections',{}))

    def test_activity_counts_and_real_content_duplicates_are_checked(self):
        r,section,result=self.fixture();section['activity_count']=1
        with self.assertRaisesRegex(p.Blocked,'SECTION_ACTIVITY_COUNT_MISMATCH'):c.validate_section(result,section,r,{'r1':'Вопрос'})
        a={'id':'1','title':'Уникальное занятие','age':'После года','materials':['Кубик'],'steps':['Покажите кубик и передайте его ребёнку.'],'benefit':'Совместное внимание','safety':'Под наблюдением взрослого'}
        result['activities']=[a];r['progress']['sections']={'old':{'activities':[dict(a,id='other')]}}
        with self.assertRaisesRegex(p.Blocked,'REPEATED_ACTIVITY_CONTENT'):c.validate_section(result,section,r,{'r1':'Вопрос'})

    def test_event_reference_must_witness_the_actual_calendar_date(self):
        self.assertTrue(c.witnessed_event_date('2026-10-26','26 октября 2026 года прошло открытие.'))
        self.assertTrue(c.witnessed_event_date('2026-10-26','October 26, 2026 marked the event.'))
        self.assertFalse(c.witnessed_event_date('2026-10-27','The study was conducted in 2026.'))
        self.assertFalse(c.witnessed_event_date('2026-10-27','26 октября 2026 года.'))

    def test_addressed_migration_keeps_accepted_sections_and_counters_once(self):
        state=e.new_state('2026-10-27');r=record();r['status']='rejected'
        r['history']=[{'code':'TOPIC_REQUIREMENTS_NOT_COVERED'}]
        r['progress']={'sections':{'kept':{'text':'Accepted'}},'section_attempts':{'kept':2}}
        other=record(1);state['candidates']=[r,other];state['_quota_snapshot']={'requests':48}
        before=copy.deepcopy(other);e.restore_preparation_repairs(state)
        self.assertEqual(r['status'],'preparing');self.assertEqual(r['progress']['section_attempts'],{'kept':2})
        self.assertEqual(other,before);self.assertEqual(state['_quota_snapshot']['requests'],48)
        r['status']='rejected';e.restore_preparation_repairs(state);self.assertEqual(r['status'],'rejected')

    def test_section_writer_receives_facts_without_protected_literal_quotes(self):
        r=record();r.pop('article');r['mode']='INDEPENDENT_ARTICLE';r['requirements']=[]
        r['rights']=e.rights41.decision(r['source'],r['mode'])
        r['claims']=[{'id':'f','fact':'Учебный проверенный факт','quote':'PRIVATE_LITERAL_SYNTHETIC','source_id':r['source']['id']}]
        r['progress']['outline']={'title':'Собственная статья','teaser':'','category':'Наука','kind':'статья',
            'sections':[{'id':'s','heading':'Раздел','purpose':'Объяснение','fact_ids':['f']}]}
        def call(prompt,**kwargs):
            self.assertNotIn('PRIVATE_LITERAL_SYNTHETIC',prompt)
            return {'id':'s','finished':True,'blocks':[{'kind':'paragraph','text':'Самостоятельное учебное объяснение.'}],
                    'activities':[],'covered_requirements':[]}
        e.Editor(call=call).prepare(e.new_state('2026-10-27'),r)


class ContinuationTests(unittest.TestCase):
    def test_one_same_workflow_continuation_respects_quota_cooldown_and_existing_run(self):
        from scripts import special_continue41 as continuation
        now=datetime(2026,10,27,6,tzinfo=timezone.utc);ledger={'day':'2026-10-27','requests':72,'models':{'lite':72}}
        runs=[{'id':1,'status':'in_progress'}];before=copy.deepcopy(ledger)
        self.assertTrue(continuation.decision(ledger,runs,1,now)[0]);self.assertEqual(ledger,before)
        self.assertFalse(continuation.decision(dict(ledger,requests=220),runs,1,now)[0])
        self.assertFalse(continuation.decision(dict(ledger,cooldowns={'lite':now.timestamp()+10}),runs,1,now)[0])
        self.assertFalse(continuation.decision(ledger,runs+[{'id':2,'status':'queued'}],1,now)[0])
        self.assertFalse(continuation.decision(dict(ledger,day='2026-10-26'),runs,1,now)[0])


class DeliveryTests(unittest.TestCase):
    def test_https_requires_exact_deployed_article_and_preserves_original(self):
        from scripts import special_publication41 as pub,special_contract41 as sc
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'issues'/sc.SLUG;folder.mkdir(parents=True)
            overview='data-special-edition="003-R" data-article-count="8"'+''.join('<a href="/issues/'+sc.SLUG+'/articles/article-'+str(i)+'/"></a>' for i in range(8))
            (folder/'index.html').write_text(overview)
            original=root/'issues'/sc.ORIGINAL;original.mkdir();(original/'index.html').write_text('immutable original')
            pages={'https://387.su/issues/'+sc.SLUG+'/':overview,'https://387.su/issues/'+sc.ORIGINAL+'/':'immutable original',
                   'https://387.su/archive/':'/issues/'+sc.SLUG+'/','https://387.su/':'daily homepage'}
            for i in range(8):
                path=folder/'articles'/('article-'+str(i));path.mkdir(parents=True);(path/'index.html').write_text('real final '+str(i))
                pages['https://387.su/issues/'+sc.SLUG+'/articles/article-'+str(i)+'/']='real final '+str(i)
            with patch.object(pub.pub,'validate_page',return_value=True):
                self.assertEqual(pub.check_public(root,pages.__getitem__)['status'],'PUBLISHED')
                pages['https://387.su/issues/'+sc.SLUG+'/articles/article-3/']='old cached different article'
                with self.assertRaisesRegex(p.Blocked,'SPECIAL_HTTPS_ARTICLE_VERSION_MISMATCH'):pub.check_public(root,pages.__getitem__)
