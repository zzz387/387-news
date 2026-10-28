"""Release 0/1/3/7/8/12/13; no provider, private corpus or production key needed."""
import base64,copy,json,os,re,shutil,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch,Mock
from scripts import editorial43 as e,daily43 as d,publication43 as pub,policy41 as p,news,site_checks,rights41,pipeline,staged_news as stage,generation_runtime as rt,release_queue
from scripts.test_policy41 import record,source

NOW=datetime(2026,10,27,8,tzinfo=p.TZ)


def ready(i=0):
    r=record(i);r['article']['category']='Наука';r['category_hint']='Наука';r['article']['title']='Учебная заметка '+str(i)
    r['mode']=r['article']['mode']='INDEPENDENT_ARTICLE';r['rights']=rights41.decision(r['source'],r['mode'])
    r['article']['blocks']=[{'kind':'paragraph','id':'own','text':'Собственное учебное объяснение номер '+str(i)+'.'}]
    r['checks']['final43']={'approved':True,'input_hash':e.fingerprint(r),**{key:True for key in e.CHECKS}}
    return r


def state(n=0):
    s=e.migrate(None,'2026-10-27');s['candidates']=[ready(i) for i in range(n)];return s


def root(temp):
    root=Path(temp);shutil.copytree(p.ROOT/'assets',root/'assets');(root/'archive').mkdir()
    (root/'archive/index.html').write_text('<html></html>');return root


def web(root):
    def fetch(url):
        path=url.split('https://387.su',1)[1].lstrip('/')
        file=root/path
        if not path or path.endswith('/'):file=file/'index.html'
        return file.read_text()
    return fetch


def verdict(prompt,r,approve=True):
    fp=prompt.split('В input_hash верни точно ')[1].split('\n')[0]
    b=r['source']['blocks'][-1]
    return {'input_hash':fp,'approve':approve,**{key:approve for key in e.CHECKS},'is_news':False,
        'event_date':'','event_source_id':'','event_evidence_id':'','event_quote':'',
        'issues':[] if approve else ['Unsafe unsupported advice'],'unresolved':[],
        'claims':[{'fact':b['text'],'source_id':r['source']['id'],'evidence_id':b['id'],'quote':b['text']}]}


class Daily43Tests(unittest.TestCase):
    def test_dynamic_counts_and_zero_digest_are_valid_and_honest_over_https(self):
        for count in (0,1,3,7,8,12,13):
            with self.subTest(count=count),tempfile.TemporaryDirectory() as temp:
                r=root(temp);s=state(count);reserve=d.reserve_rows(s,NOW)
                self.assertTrue(pub.build(s,r,reserve));meta=pub.validate(r,s['date'])
                self.assertEqual(meta['article_count'],count)
                with patch.object(site_checks,'fetch',side_effect=web(r)):
                    result=site_checks.check_site(expected_date=s['date'])
                self.assertEqual(result['articles'],count)
                page=(r/'index.html').read_text()
                self.assertNotIn('Двенадцать законченных',page)
                self.assertEqual(len(list((r/'issues'/s['date']/'articles').glob('*/index.html'))),count)
                if count==0:
                    self.assertIn('Обзор источников',page);self.assertIn('не новые полноценные статьи',page)
                    self.assertIn('без генерации',page);self.assertEqual(meta['kind'],'source_digest')
                else:self.assertEqual(meta['kind'],'articles')

    def test_release_does_not_touch_gemini_at_zero_budget_or_without_key(self):
        ledger={'day':'2026-10-27','requests':220,'models':{'fixture':220},'cooldowns':{'fixture':9999999999}}
        snapshot=copy.deepcopy(ledger)
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'),patch.object(news,'gemini',side_effect=AssertionError('No inference allowed')):
            r=root(temp);s=state();s['_quota_snapshot']=copy.deepcopy(ledger)
            with patch.object(news.runtime,'ACTIVE_BUDGET',rt.RequestBudget(ledger,day_limit=220)):
                self.assertTrue(d.advance(s,s['date'],False,SimpleNamespace(ROOT=r),now=NOW))
            self.assertEqual(ledger,snapshot);self.assertEqual(s['_quota_snapshot'],snapshot);self.assertEqual(pub.validate(r,s['date'])['article_count'],0)

    def test_due_one_article_never_waits_for_others_or_calls_model(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'):
            r=root(temp);s=state(1);s['candidates'].append(dict(id='waiting',url='https://example.org/waiting',status='preparing'))
            editor=Mock();editor.finish.side_effect=AssertionError('Must publish ready work first')
            self.assertTrue(d.advance(s,s['date'],False,SimpleNamespace(ROOT=r),now=NOW,editor=editor));editor.finish.assert_not_called()
            self.assertEqual(pub.validate(r,s['date'])['article_count'],1)

    def test_before_six_does_not_write_public_files(self):
        with tempfile.TemporaryDirectory() as temp:
            r=root(temp);s=state(1)
            self.assertFalse(d.advance(s,s['date'],False,SimpleNamespace(ROOT=r),now=NOW.replace(hour=5)))
            self.assertFalse((r/'issues'/s['date']).exists());self.assertEqual(s['next_action'],'publish_when_due')

    def test_repeat_delivery_is_immutable_and_does_not_recreate_articles(self):
        with tempfile.TemporaryDirectory() as temp:
            r=root(temp);s=state(3);pub.build(s,r)
            before={str(f.relative_to(r)):f.read_bytes() for f in (r/'issues').rglob('*') if f.is_file()}
            self.assertTrue(pub.build(state(1),r))
            self.assertEqual(before,{str(f.relative_to(r)):f.read_bytes() for f in (r/'issues').rglob('*') if f.is_file()})
            self.assertFalse(d.advance(s,s['date'],False,SimpleNamespace(ROOT=r),now=NOW,check_public=lambda **k:{'status':'ok'}))
            self.assertEqual(s['pipeline_status'],'PUBLISHED')

    def test_historical_archive_003_and_special_ciphertext_are_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            r=root(temp);old=r/'issues/2026-10-26';shutil.copytree(p.ROOT/'issues/2026-10-26',old)
            cipher=r/'special-003-r.enc';cipher.write_bytes(b'opaque-test-ciphertext')
            before={str(f.relative_to(old)):f.read_bytes() for f in old.rglob('*') if f.is_file()}
            pub.build(state(1),r)
            self.assertEqual(before,{str(f.relative_to(old)):f.read_bytes() for f in old.rglob('*') if f.is_file()})
            self.assertEqual(cipher.read_bytes(),b'opaque-test-ciphertext')

    def test_no_safe_reserve_records_incident_and_does_not_publish_placeholder(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(d,'reserve_rows',return_value=[]):
            r=root(temp);s=state()
            self.assertFalse(d.advance(s,s['date'],False,SimpleNamespace(ROOT=r),now=NOW))
            self.assertEqual(s['block_code'],'NO_SAFE_RESERVE');self.assertFalse((r/'issues'/s['date']).exists())

    def test_unapproved_or_changed_article_never_enters_issue(self):
        s=state(3);s['candidates'][1]['checks']['final43']['safety']=False
        s['candidates'][2]['article']['blocks'][-1]['text']='An unreviewed medical advice'
        self.assertEqual([r['id'] for r in e.select_ready(s)],['0'])

    def test_old_daily_and_quota_migrate_without_loss_or_counter_reset(self):
        old=record();old_state={'version':41,'date':'2026-10-27','candidates':[old],'_quota_snapshot':{'day':'2026-10-27','requests':220},'dossiers':{'saved':{'segments':['saved fixture']}}}
        before=copy.deepcopy(old_state);s=e.migrate(old_state,old_state['date'])
        self.assertEqual(old_state,before);self.assertEqual(s['previous_policy_checkpoint'],before)
        self.assertEqual(s['_quota_snapshot']['requests'],220);self.assertFalse(e.eligible(s['candidates'][0]));self.assertIs(e.migrate(s,s['date']),s)

    def test_resume_uses_one_final_review_and_preserves_complete_draft(self):
        r=record();r['category_hint']='Наука';r['status']='preparing';calls=[]
        def model(prompt,**kwargs):calls.append(kwargs['schema']);return verdict(prompt,r)
        e.Editor(call=model).finish(state(),r)
        self.assertEqual(calls,['v43_final']);self.assertTrue(e.eligible(r));before=copy.deepcopy(r['article'])
        e.Editor(call=lambda *a,**k:self.fail('Approved content repeated')).finish(state(),r)
        self.assertEqual(r['article'],before)

    def test_substantive_safety_refusal_does_not_remove_other_ready_article(self):
        r=record();r['category_hint']='Наука';s=state(1);before=copy.deepcopy(s['candidates'][0])
        with self.assertRaisesRegex(p.Blocked,'FINAL_REJECTED'):e.Editor(call=lambda prompt,**kw:verdict(prompt,r,False)).finish(s,r)
        self.assertFalse(e.eligible(r));self.assertEqual(s['candidates'][0],before)

    def test_incomplete_response_retries_are_finite_and_survive_independent_restore(self):
        r=record();r.pop('article');r['source'].pop('declared_license');r['category_hint']='Наука';r['status']='preparing';calls=[]
        def model(*a,**kw):calls.append(1);return {'finished':False}
        with self.assertRaisesRegex(p.Blocked,'CANDIDATE_ATTEMPTS_EXHAUSTED'):e.Editor(call=model).finish(state(),r)
        self.assertEqual(len(calls),3)
        # Synthetic encryption only; no private production checkpoint or key is downloaded.
        restored=stage.decipher(stage.cipher(r,b'x'*32),b'x'*32)
        with self.assertRaisesRegex(p.Blocked,'CANDIDATE_ATTEMPTS_EXHAUSTED'):e.Editor(call=model).finish(state(),restored)
        self.assertEqual(len(calls),3)

    def test_missing_evidence_or_false_news_event_date_cannot_approve(self):
        for code in ('quote','date'):
            with self.subTest(code=code):
                r=record();r['category_hint']='Наука'
                def model(prompt,**kwargs):
                    result=verdict(prompt,r)
                    if code=='quote':result['claims'][0]['quote']='Invented unsupported quotation'
                    else:result.update(is_news=True,event_date='2026-10-26',event_source_id=r['source']['id'],event_evidence_id=r['source']['blocks'][-1]['id'],event_quote=r['source']['blocks'][-1]['text'])
                    return result
                with self.assertRaises(p.Blocked):e.Editor(call=model).finish(state(),r)
                self.assertFalse(e.eligible(r))

    def test_risky_material_needs_independent_competent_evidence_before_any_model_call(self):
        r=record();r['category_hint']='Здоровье и движение'
        with self.assertRaisesRegex(p.Blocked,'INDEPENDENT_SAFETY_EVIDENCE_REQUIRED'):e.Editor(call=lambda *a,**k:self.fail('Missing safety evidence')).finish(state(),r)

    def test_literal_duplicates_normalize_without_rewriting_distinct_content(self):
        a={'title':'Тема','teaser':'','blocks':[{'kind':'p','text':'Первый факт.'},{'kind':'p','text':'Первый факт.'},{'kind':'paragraph','text':'Другой факт.'}]}
        self.assertEqual([b['text'] for b in e.normalize(a)['blocks']],['Первый факт.','Другой факт.'])

    def test_empty_or_expired_unreachable_reserve_is_not_used(self):
        with patch.dict(e.CONFIG,reserve_max_age_days=0):
            rows=d.reserve_rows(state(),NOW,fetch=lambda url:(_ for _ in ()).throw(OSError('offline')))
        self.assertEqual(rows,[])

    def test_policy43_pauses_all_special_entrypoints_before_loading_private_state(self):
        from scripts import special003r,special_continue41
        with patch.dict(os.environ,NEWS_POLICY_VERSION='4.3'),patch.object(stage,'decipher',side_effect=AssertionError('Special must remain untouched')):
            special003r.run();special_continue41.main()
        workflow=(p.ROOT/'.github/workflows/daily-v31.yml').read_text()
        self.assertIn('special-003-r:\n    # Policy 4.3',workflow);self.assertIn('if: ${{ false }}',workflow)
        self.assertIn("cron: '54 2 * * *'",workflow);self.assertIn('NEWS_MAX_REQUESTS_PER_DAY: "220"',workflow)

    def test_preflight43_allows_gemini_absence_for_fallback_but_requires_safe_recovery(self):
        from scripts import production_preflight41 as pre
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'zzz387/387-news','GITHUB_REF_NAME':'main','NEWS_POLICY_VERSION':'4.3',
            'DRAFT_ENCRYPTION_KEY':base64.b64encode(b'x'*32).decode(),'NEWS_AUTOMATION_V31_ENABLED':'true','NEWS_RELEASE_APPROVED':'true'}
        value=pre.check(env);self.assertFalse(value['gemini_secret_present']);self.assertTrue(value['reserve_without_gemini'])

    def test_past_unfinished_issue_is_retained_without_backdating_today(self):
        with tempfile.TemporaryDirectory() as temp:
            r=root(temp);s=state();s['date']='2026-10-26';before=copy.deepcopy(s['candidates'])
            self.assertFalse(d.advance(s,s['date'],False,SimpleNamespace(ROOT=r),now=NOW))
            self.assertEqual(s['candidates'],before);self.assertEqual(s['block_code'],'SUPERSEDED_UNFINISHED_DATE')

    def test_delivery_failure_retries_existing_files_without_generation(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'):
            r=root(temp);s=state(1);pub.build(s,r)
            self.assertTrue(d.advance(s,s['date'],False,SimpleNamespace(ROOT=r),now=NOW,check_public=lambda **k:(_ for _ in ()).throw(OSError('Pages offline'))))
            self.assertEqual(s['pipeline_status'],'PUBLISHING');self.assertEqual(s['delivery_attempts'],1)
            self.assertFalse(d.advance(s,s['date'],False,SimpleNamespace(ROOT=r),now=NOW,check_public=lambda **k:(_ for _ in ()).throw(OSError('Pages offline'))))
            self.assertEqual(s['block_code'],'DELIVERY_COOLDOWN')


class Preparation43Tests(unittest.TestCase):
    def test_c_uses_two_operations_without_source_requirements_or_foreign_activity_count(self):
        r=record();r.pop('article');r['source'].pop('declared_license');r['category_hint']='Наука'
        r['source']['title']='21 learning activities';calls=[]
        def model(prompt,**kwargs):
            calls.append(kwargs['schema'])
            if kwargs['schema']=='v43_article':return {'finished':True,'title':'Как наблюдать за игрой','teaser':'','blocks':[{'kind':'paragraph','text':'Законченный собственный узкий аспект, не пересказ списка.'}]}
            return verdict(prompt,r)
        e.Editor(call=model).finish(state(),r)
        self.assertEqual(calls,['v43_article','v43_final']);self.assertTrue(e.eligible(r));self.assertEqual(r['article']['activities'],[])

    def test_independent_run_resumes_after_writing_without_writing_again(self):
        r=record();r.pop('article');r['source'].pop('declared_license');r['category_hint']='Наука';calls=[]
        def first(prompt,**kwargs):
            calls.append(kwargs['schema'])
            if kwargs['schema']=='v43_article':return {'finished':True,'title':'Собственный аспект','teaser':'','blocks':[{'kind':'paragraph','text':'Законченное независимое объяснение.'}]}
            raise rt.GenerationPaused('Synthetic natural run boundary')
        with self.assertRaises(rt.GenerationPaused):e.Editor(call=first).finish(state(),r)
        restored=stage.decipher(stage.cipher(r,b'x'*32),b'x'*32);later=[]
        e.Editor(call=lambda prompt,**kw:(later.append(kw['schema']) or verdict(prompt,restored))).finish(state(),restored)
        self.assertEqual(later,['v43_final']);self.assertTrue(e.eligible(restored))

    def test_legally_republished_original_must_retain_every_block_even_with_positive_model(self):
        r=record();r['category_hint']='Наука';r['article']['blocks'].pop()
        with self.assertRaisesRegex(p.Blocked,'SOURCE_COVERAGE_INCOMPLETE'):e.Editor(call=lambda *a,**k:self.fail('Missing original block')).finish(state(),r)

    def test_source_expression_cannot_be_published_as_independent_work(self):
        r=record();r['source'].pop('declared_license');r['mode']=r['article']['mode']='INDEPENDENT_ARTICLE';r['category_hint']='Наука'
        r['rights']=rights41.decision(r['source'],r['mode'])
        with self.assertRaises(p.Blocked):e.Editor(call=lambda *a,**k:self.fail('Copied layout')).finish(state(),r)
