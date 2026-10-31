"""Editorial preferences are soft; duplicate stories and unverified facts are not."""
import copy,json,os,re,shutil,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import Mock,patch
from scripts import selection43 as sel,catalog43 as cat,editorial43 as e,publication43 as pub,daily43 as daily,light43 as light,policy41 as p,site_checks,news,generation_runtime as rt,rights41
from scripts.test_daily43 import ready,state,root,web,NOW,RESERVE_FIXTURE,verdict
from scripts.test_policy41 import source


def named(title,i=0,status='ready',publisher='Fixture'):
    row=ready(i);row['article']['title']=title;row['source']['title']=title;row['source']['publisher']=publisher;row['title']=title;row['status']=status
    e.normalize(row['article']);row['checks']['final43']['input_hash']=e.fingerprint(row);return row


def light_ready(i):
    row=named('Необычная история '+str(i),100+i);row['article']['blocks']=[{'kind':'paragraph','id':'one','text':'Синтетический проверенный факт номер '+str(i)+'.'}]
    row['checks']['final43']['input_hash']=e.fingerprint(row);return row

class TopicTests(unittest.TestCase):
    def test_museums_are_soft_place_preferences_and_distinct_stories_remain_available(self):
        selected=named('История реставрации Царицына');near=named('Архитектура Царицына',1,'discovered');other=named('История Дарвиновского музея',2,'discovered')
        self.assertFalse(sel.duplicate(selected,near));s=state();s['candidates']=[selected,near,other]
        self.assertIs(sel.order(s)[0],other);s['candidates'].remove(other);self.assertEqual(sel.order(s),[near])

    def test_sleep_weight_and_appetite_are_one_story_and_best_is_preserved(self):
        a=named('Недостаток сна и лишний вес');b=named('Почему недосыпание усиливает аппетит',1)
        b['checks']['final43']['claims']=[{'fact':'A useful verified distinction'}]
        self.assertTrue(sel.duplicate(a,b));s=state();s['candidates']=[a,b];before=copy.deepcopy(s['candidates'])
        self.assertEqual(sel.ready(s),[b]);self.assertEqual(s['candidates'],before)

    def test_history_of_sleep_discovery_is_a_different_story(self):
        self.assertFalse(sel.duplicate(named('Исследование сна'),named('История открытия фазы быстрого сна',1)))
        self.assertFalse(sel.duplicate(named('Недосып с последствиями: почему нам хочется есть больше'),named('История исследования сна в XIX веке',1)))

    def test_doi_of_one_primary_study_not_all_references_identifies_a_duplicate(self):
        a=named('Поведение птиц');b=named('Новый результат наблюдений за воронами',1)
        a['source']['doi']=b['source']['doi']='10.1234/one-study'
        self.assertTrue(sel.duplicate(a,b));a['source']['doi']='';b['source']['doi']=''
        a['url']='https://one.example/paper?id=123';b['url']='https://two.example/paper?id=123'
        self.assertFalse(sel.duplicate(a,b))

    def test_space_is_one_preference_not_a_category_ban(self):
        rows=[named('Космический сюжет '+str(i),i,'discovered') for i in range(10)]
        rows += [named('Биология животных '+str(i),20+i,'discovered') for i in range(15)]
        s=state();s['candidates']=rows;chosen=sel.order(s)[:12]
        self.assertLessEqual(sum(sel.profile(r)['space'] for r in chosen),1)
        s['candidates']=rows[:10];self.assertEqual(len(sel.order(s)),10)

    def test_twelve_valid_distinct_stories_publish_despite_one_publisher_or_place(self):
        s=state(12)
        for row in s['candidates']:row['place_hint']='Same museum';row['publisher_id']='same-publisher'
        self.assertEqual(len(sel.ready(s)),12)
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);pub.build(s,target);self.assertEqual(pub.validate(target,s['date'])['article_count'],12)

    def test_broad_words_do_not_make_unrelated_museums_or_health_stories_duplicates(self):
        self.assertFalse(sel.duplicate(named('Музей истории костюма'),named('Музей техники и механизмов',1)))
        self.assertFalse(sel.duplicate(named('Математика орбит планет'),named('История советской космонавтики',1)))

    def test_duplicate_is_skipped_before_any_writer_or_model_call(self):
        a=named('Недостаток сна и лишний вес');b=named('Влияние недосыпания на аппетит',1,'discovered');b.pop('article')
        s=state();s['candidates']=[a,b];model=Mock(side_effect=AssertionError('Duplicate must be skipped'))
        with tempfile.TemporaryDirectory() as temp,patch.object(daily,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True)):
            daily.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW.replace(hour=5),editor=e.Editor(call=model))
        model.assert_not_called();self.assertEqual(b['status'],'topic_duplicate');self.assertTrue(e.eligible(a))

    def test_existing_good_titles_are_not_rewritten_to_meet_a_formal_how_limit(self):
        rows=[named('Как устроен пример '+str(i),i) for i in range(6)];s=state();s['candidates']=rows
        self.assertEqual(sel.title_report(rows)['how_openings'],6);self.assertTrue(sel.title_report(rows)['advisory_only'])
        for row in rows:
            before=copy.deepcopy(row['article']);e.Editor(call=lambda *a,**k:self.fail('No style-only call')).finish(s,row);self.assertEqual(row['article'],before)

class CatalogTests(unittest.TestCase):
    def registry_row(self):return dict(cat.registry()['publishers'][0],id='fixture',homepage='https://example.org/',domain='example.org')
    def session(self,forbidden=False,blocked=False):
        src=source(9);src['title']='Full original title'
        feed='<rss><channel><item><title>Real discovered publication metadata</title><link>https://example.org/story/9</link><description>SNIPPET_MUST_NOT_BE_AN_ORIGINAL</description></item></channel></rss>'
        class Session:
            def __init__(self):self.urls=[];self.full=[]
            def transport(self,url):
                self.urls.append(url)
                if url.endswith('/robots.txt'):return 'User-agent: *\nDisallow: /' if forbidden else 'User-agent: *\nAllow: /'
                if 'feed' in url:return feed
                return '<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>'
            def fetch(self,url):
                self.full.append(url);s=copy.deepcopy(src)
                if blocked:s['legal_dispute']=True
                return s
        return Session()

    def test_all_requested_fifty_science_publishers_are_registered_with_access_and_rights_rules(self):
        config=cat.registry();rows=config['publishers'];self.assertEqual(len(rows),55)
        self.assertEqual(len({r['id'] for r in rows}),55)
        for row in rows:
            self.assertEqual(row['rights']['status'],'per_article_required');self.assertTrue(row['access']['respect_robots']);self.assertTrue(row['access']['no_paywall_bypass'])
            self.assertTrue(row['homepage'].startswith('https://'));self.assertIn(row['type'],('research_journal','science_journalism','popular_science','research_news','press_release','official'))

    def test_feed_discovers_url_but_only_complete_eligible_original_is_admitted(self):
        session=self.session();report,rows=cat.inspect_publisher(self.registry_row(),session)
        self.assertEqual(report['status'],'full_sources_verified');self.assertEqual(len(rows),1)
        self.assertNotIn('SNIPPET',json.dumps(rows));self.assertTrue(rows[0][1]['full_text_verified']);self.assertEqual(len(session.full),1)

    def test_robots_disallow_and_uncertain_rights_do_not_enter_active_pool(self):
        for session in (self.session(forbidden=True),self.session(blocked=True)):
            report,rows=cat.inspect_publisher(self.registry_row(),session);self.assertEqual(rows,[]);self.assertNotEqual(report['status'],'full_sources_verified')

    def test_external_entity_feed_is_rejected_and_no_search_snippet_is_used(self):
        with self.assertRaises(p.Blocked):cat.feed_items('<!DOCTYPE rss><rss/>','https://example.org/')
        self.assertEqual(cat.feed_items('<rss><channel/></rss>','https://example.org/'),[])

    def test_cached_refresh_is_bounded_and_survives_state_restore_without_model_calls(self):
        config=cat.registry();config['publishers']=[self.registry_row()];config['publishers_per_run']=1
        s=state();session=self.session()
        with patch.object(cat,'registry',return_value=config),patch.object(news,'gemini',side_effect=AssertionError('No inference')):
            cat.refresh(s,NOW,session);count=len(session.urls);saved=copy.deepcopy(s)
            cat.refresh(saved,NOW+timedelta(minutes=1),session)
        self.assertEqual(len(session.urls),count);self.assertEqual(len(saved['candidates']),1)

    def test_stopped_publisher_with_only_old_materials_does_not_enter_active_pool(self):
        session=self.session();original=session.fetch
        session.fetch=lambda url:dict(original(url),published='2000-01-01')
        report,items=cat.inspect_publisher(self.registry_row(),session,now=NOW)
        self.assertEqual(items,[]);self.assertEqual(report['last_article_code'],'PUBLISHER_ACTIVITY_NOT_CURRENT')

    def test_press_release_type_is_not_promoted_to_peer_reviewed_research(self):
        row=dict(self.registry_row(),type='press_release');_,items=cat.inspect_publisher(row,self.session())
        self.assertEqual(items[0][1]['publisher_type'],'press_release');self.assertEqual(items[0][1]['publication_type'],'unclassified')

class LightAndLayoutTests(unittest.TestCase):
    def test_optional_section_counts_never_change_main_article_admission(self):
        for mains,shorts in [(12,5),(8,3),(1,1),(12,0),(0,0)]:
            with self.subTest(mains=mains,shorts=shorts),tempfile.TemporaryDirectory() as temp:
                target=root(temp);s=state(mains);s['light43']={'records':[light_ready(i) for i in range(shorts)]}
                pub.build(s,target,[RESERVE_FIXTURE]);data=pub.validate(target,s['date'])
                self.assertEqual(data['article_count'],mains);self.assertEqual(data['light_count'],shorts)
                with patch.object(site_checks,'fetch',side_effect=web(target)):self.assertEqual(site_checks.check_site(expected_date=s['date'])['articles'],mains)
                text=(target/'index.html').read_text();self.assertEqual('id="light-news"' in text,bool(shorts));self.assertNotIn('PRIVATE',json.dumps(data))

    def test_unapproved_light_story_is_omitted_without_blocking_the_main_article(self):
        s=state(1);row=light_ready(0);row['checks']['final43']['facts']=False;s['light43']={'records':[row]}
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);pub.build(s,target);self.assertEqual(pub.validate(target,s['date'])['light_count'],0)

    def test_compact_current_home_is_derived_from_immutable_overview_and_still_hash_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)
            for folder in ('assets','issues','archive'):shutil.copytree(p.ROOT/folder,target/folder)
            shutil.copyfile(p.ROOT/'index.html',target/'index.html')
            before={str(f.relative_to(target)):f.read_bytes() for f in (target/'issues').rglob('*') if f.is_file()}
            changed,date=pub.refresh_home(target);self.assertTrue(changed);text=(target/'index.html').read_text()
            self.assertNotIn('mast-top',text);self.assertNotIn('Каждый день есть что открыть',text);self.assertNotIn('front-intro',text)
            self.assertIn('visually-hidden',text);self.assertIn('Обзор номера</a>',text);self.assertIn('Ежедневная газета · Москва',text)
            self.assertEqual(before,{str(f.relative_to(target)):f.read_bytes() for f in (target/'issues').rglob('*') if f.is_file()})
            with patch.object(site_checks,'fetch',side_effect=web(target)):self.assertEqual(site_checks.check_site(expected_date=date)['https'],'verified')
            self.assertFalse(pub.refresh_home(target)[0]);(target/'index.html').write_text(text.replace('387 <span>NEWS','HACKED <span>NEWS'))
            with patch.object(site_checks,'fetch',side_effect=web(target)),self.assertRaisesRegex(RuntimeError,'PUBLIC_HOME_CHANGED'):site_checks.check_site(expected_date=date)

    def test_light_generation_is_batched_two_calls_and_persisted_not_repeated(self):
        s=state(1);extra=named('Необычный факт о воронах',80,'discovered');extra['light_suitable']=True;s['candidates'].append(extra)
        ledger={'day':datetime.now(timezone.utc).date().isoformat(),'requests':0,'models':{},'cooldowns':{}}
        budget=rt.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0);calls=[]
        class Editor:
            def call(self,prompt,**kw):
                budget.reserve('fixture');calls.append(kw['schema'])
                if kw['schema']=='v43_light_write':return {'items':[{'id':'x','source_id':'s1','title':'Неожиданный поворот','text':'Самостоятельный подтверждённый факт.'}]}
                src=extra['source'];b=src['blocks'][-1]
                return {'reviews':[{'id':'x','approve':True,**{k:True for k in e.CHECKS},'is_news':False,'issues':[],'unresolved':[],
                    'event_date':'','event_source_id':'','event_evidence_id':'','event_quote':'',
                    'claims':[{'fact':b['text'],'source_id':'s1','evidence_id':'q'+str(len(src['blocks'])),'quote':b['text']}]}]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):
            light.prepare(s,editor=Editor());light.prepare(copy.deepcopy(s),editor=Editor())
        self.assertEqual(calls,['v43_light_write','v43_light_review']);self.assertEqual(len(light.ready(s)),1);self.assertEqual(budget.used,2)

    def test_light_transport_retries_cannot_spend_more_than_two_real_reservations(self):
        s=state(1);extra=named('Необычный факт о природе',80,'discovered');extra['light_suitable']=True;s['candidates'].append(extra)
        ledger={'day':datetime.now(timezone.utc).date().isoformat(),'requests':0,'models':{},'cooldowns':{}};budget=rt.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0)
        class RetryEditor:
            def call(self,*args,**kw):
                for attempt in range(3):budget.reserve('fixture')
                raise AssertionError('Third HTTP attempt must not happen')
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):
            light.prepare(s,editor=RetryEditor());light.prepare(copy.deepcopy(s),editor=RetryEditor())
        self.assertEqual(budget.used,2);self.assertEqual(ledger['requests'],2);self.assertEqual(budget.run_limit,24)
        self.assertEqual(s['light43']['http_requests'],2);self.assertEqual(len(sel.ready(s)),1)

    def test_light_api_failure_or_exhausted_quota_never_raises_a_main_publication_veto(self):
        s=state(1);extra=named('Необычный факт о природе',80,'discovered');extra['light_suitable']=True;s['candidates'].append(extra)
        ledger={'day':datetime.now(timezone.utc).date().isoformat(),'requests':220,'models':{},'cooldowns':{}};budget=rt.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0)
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):light.prepare(s,editor=Mock(call=Mock(side_effect=AssertionError('No free budget'))))
        self.assertEqual(len(sel.ready(s)),1);self.assertEqual(light.ready(s),[])

if __name__=='__main__':unittest.main()
