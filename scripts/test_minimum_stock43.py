"""Production minimum-eight policy, protected inventory, independent light column."""
import copy,json,os,tempfile,unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch,Mock
from pathlib import Path
from scripts import daily43 as d,editorial43 as e,publication43 as pub,stock43 as stock,news,staged_news as stage,light43 as light,catalog43 as cat,policy41 as p,site_checks
from scripts import test_daily43 as fixture,test_editorial_visual43 as visual

class MinimumStockTests(unittest.TestCase):
    def make(self,mains=0,bank=0):
        s=fixture.state(mains);inventory=stock.ensure(s)
        inventory['records']=[fixture.ready(i+100) for i in range(bank)]
        return s

    def release(self,s,target):
        with patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'),patch.object(news,'gemini',side_effect=AssertionError('No new inference for delivery')):
            return d.deliver(s,s['date'],False,SimpleNamespace(ROOT=target),now=fixture.NOW)

    def test_real_policy_requires_eight_but_keeps_target_twelve(self):
        actual=json.loads((p.ROOT/'config/daily43.json').read_text())
        self.assertEqual((actual['minimum_articles'],actual['article_target']),(8,12));self.assertEqual(e.CONFIG['minimum_articles'],8)

    def test_one_plus_seven_and_six_plus_ten_and_twelve_are_complete(self):
        for mains,reserve,expected in [(1,7,8),(6,10,12),(12,0,12),(0,8,8)]:
            with self.subTest(mains=mains,reserve=reserve),tempfile.TemporaryDirectory() as temp:
                target=fixture.root(temp);s=self.make(mains,reserve);before=copy.deepcopy(s['candidates'])
                self.assertTrue(self.release(s,target));self.assertEqual(pub.validate(target,s['date'])['article_count'],expected)
                self.assertEqual(s['candidates'][:mains],before);self.assertTrue(pub.metadata(target,s['date'])['standard_issue'])

    def test_three_without_stock_stays_preparing_and_builder_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            target=fixture.root(temp);s=self.make(3);before=copy.deepcopy(s['candidates'])
            self.assertFalse(self.release(s,target));self.assertFalse(s['audit_passed']);self.assertEqual(s['pipeline_status'],'PREPARING')
            self.assertEqual(s['candidates'],before);self.assertEqual(s['block_code'],'MINIMUM_ARTICLES_NOT_MET')
            self.assertFalse((target/'issues'/s['date']).exists())
            with self.assertRaisesRegex(p.Blocked,'MINIMUM_ARTICLES_NOT_MET'):pub.build(s,target)

    def test_zero_reference_links_cannot_bypass_the_normal_minimum(self):
        with tempfile.TemporaryDirectory() as temp:
            target=fixture.root(temp)
            with self.assertRaisesRegex(p.Blocked,'MINIMUM_ARTICLES_NOT_MET'):pub.build(self.make(),target,[fixture.RESERVE_FIXTURE])
            self.assertFalse((target/'issues').exists())

    def test_public_metadata_cannot_disguise_a_partial_issue_or_private_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            target=fixture.root(temp);s=self.make(8);self.assertTrue(self.release(s,target))
            file=target/'issues'/s['date']/'release.json';data=json.loads(file.read_text());data.update(article_count=3,standard_issue=False);file.write_text(json.dumps(data))
            with patch.object(site_checks,'fetch',side_effect=fixture.web(target)):
                with self.assertRaisesRegex(RuntimeError,'PUBLIC_MINIMUM_ARTICLES_NOT_MET'):site_checks.check_site(expected_date=s['date'])
            data['preview']=True;file.write_text(json.dumps(data))
            with patch.object(site_checks,'fetch',side_effect=fixture.web(target)):
                with self.assertRaisesRegex(RuntimeError,'PUBLIC_PREVIEW_FORBIDDEN'):site_checks.check_site(expected_date=s['date'])

    def test_light_stories_do_not_count_towards_eight_and_five_render_separately(self):
        for mains,shorts,allowed in [(6,3,False),(8,5,True),(8,0,True)]:
            with tempfile.TemporaryDirectory() as temp:
                target=fixture.root(temp);s=self.make(mains);s['light43']={'records':[visual.light_ready(i) for i in range(shorts)]}
                self.assertEqual(self.release(s,target),allowed)
                if allowed:
                    data=pub.validate(target,s['date']);self.assertEqual(data['article_count'],mains);self.assertEqual(data['light_count'],shorts)

    def test_duplicate_ready_stories_are_replaced_from_stock_without_deleting_them(self):
        s=self.make(12,3);a,b=s['candidates'][:2];b['article']['title']=a['article']['title'];b['checks']['final43']['input_hash']=e.fingerprint(b)
        with tempfile.TemporaryDirectory() as temp:
            target=fixture.root(temp);self.assertTrue(self.release(s,target))
            self.assertEqual(pub.validate(target,s['date'])['article_count'],12);self.assertIn(a,s['candidates']);self.assertIn(b,s['candidates'])
            self.assertEqual(len(s['selection43']['excluded_duplicate_ids']),1)

    def test_stock_is_reserved_for_one_date_and_publication_prevents_reuse(self):
        s=self.make(0,8)
        with tempfile.TemporaryDirectory() as temp:
            target=fixture.root(temp);stock.draw(s,target,fixture.NOW)
            tomorrow=self.make();tomorrow['date']='2026-10-28';stock.merge(tomorrow,copy.deepcopy(s['stock43']))
            self.assertEqual(stock.draw(tomorrow,target,fixture.NOW),0)
            self.assertTrue(self.release(s,target));stock.merge(tomorrow,s['stock43']);stock.reconcile(tomorrow,target)
            self.assertEqual(stock.draw(tomorrow,target,fixture.NOW),0)
            self.assertEqual(len(tomorrow['stock43']['published_urls']),8)

    def test_published_canonical_source_consumes_an_original_url_alias(self):
        s=self.make(0,8);s['stock43']['records'][0]['url']='https://example.org/redirect-alias'
        with tempfile.TemporaryDirectory() as temp:
            target=fixture.root(temp);self.assertTrue(self.release(s,target));stock.reconcile(s,target)
        self.assertTrue(s['stock43']['records'][0]['stock_published']);self.assertIn('https://example.org/redirect-alias',s['stock43']['published_urls'])
        self.assertEqual(stock.available(s,s['date']),[])

    def test_expired_news_sensitive_and_corrupted_records_are_not_stock(self):
        s=self.make();rows=[]
        for i in range(4):rows.append(fixture.ready(100+i))
        rows[0]['ready_checked_at']=(fixture.NOW-timedelta(days=30)).isoformat()
        rows[1]['checks']['final43']['is_news']=True
        rows[2]['category_hint']='Здоровье и движение';rows[2]['article']['title']='Принимайте препарат при сердечных заболеваниях';rows[2]['checks']['final43']['input_hash']=e.fingerprint(rows[2])
        rows[3]['article']['blocks'][0]['text']='Tampered'
        stock.ensure(s)['records']=rows
        self.assertEqual(stock.available(s,s['date']),[])

    def test_encrypted_inventory_survives_independent_restore_without_quota_reset(self):
        s=self.make(1,9);ledger={'day':'2026-10-27','requests':219,'models':{'fixture':219},'cooldowns':{'fixture':9999999999}}
        s['_quota_snapshot']=copy.deepcopy(ledger);key=bytes(range(32));snapshot=stage.cipher(stock.ensure(s),key)
        self.assertNotIn('Учебная'.encode(),snapshot)
        restored=fixture.state(1);stock.merge(restored,stage.decipher(snapshot,key));stock.merge(restored,stage.decipher(snapshot,key))
        self.assertEqual(len(restored['stock43']['records']),9);self.assertEqual(ledger,s['_quota_snapshot'])
        with tempfile.TemporaryDirectory() as temp:
            target=fixture.root(temp);self.assertTrue(self.release(restored,target));self.assertEqual(pub.validate(target,restored['date'])['article_count'],10)

    def test_historical_issue_one_remains_immutable_after_minimum_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            target=fixture.root(temp);s=self.make(1)
            with patch.dict(e.CONFIG,minimum_articles=1):pub.build(s,target)
            before={str(f):f.read_bytes() for f in target.rglob('*') if f.is_file()}
            self.assertFalse(d.deliver(s,s['date'],False,SimpleNamespace(ROOT=target),now=fixture.NOW,check_public=lambda **kw:{}));self.assertEqual(before,{str(f):f.read_bytes() for f in target.rglob('*') if f.is_file()})

    def test_non_news_needs_no_event_date_but_news_still_requires_it(self):
        row=fixture.ready();self.assertEqual(e.news_errors({'is_news':False},row,fixture.state()),[])
        self.assertIn('NEWS_EVENT_FIELDS_INVALID',e.news_errors({'is_news':True},row,fixture.state()))

    def test_semantic_light_selection_does_not_trust_publisher_flag(self):
        self.assertFalse(light.story_suitable({'title':'Трагедия на войне','light_suitable':True}))
        self.assertTrue(light.story_suitable({'title':'Необычное поведение воронов в зоопарке','light_suitable':False}))
        self.assertFalse(light.story_suitable({'title':'Выборы и политическая борьба','light_suitable':True}))

    def test_light_budget_is_attempted_before_main_target_when_headroom_exists(self):
        s=self.make(1);s['candidates'].append(dict(fixture.ready(50),status='discovered'))
        budget=SimpleNamespace(deadline=float('inf'),can_request=lambda:True,remaining_requests=lambda:24)
        calls=[];editor=Mock();editor.finish.side_effect=lambda state,row:(calls.append('main'),row.update(status='deferred'))
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_LIGHT_NEWS_ENABLED='true'),patch.object(d,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(light,'prepare',side_effect=lambda *a,**k:calls.append('light')):
            d.advance(s,s['date'],False,SimpleNamespace(ROOT=fixture.root(temp)),now=fixture.NOW.replace(hour=5),editor=editor)
        self.assertEqual(calls[0],'light');self.assertIn('main',calls)

    def test_stock_preparation_has_its_own_personal_topic_balance(self):
        titles=['Архитектура библиотеки','Музей старой коллекции','История Москвы','Московские усадьбы','Археологическая находка','Биография художника','Христианская история','Экономика повседневности','Инженерия производства','Квантовая фаза','Нейтрино в эксперименте','Гравитационные волны']
        s=fixture.state();s['candidates']=[visual.named(title,i) for i,title in enumerate(titles)]
        science=visual.named('Физика нового сверхпроводника',90,'discovered');history=visual.named('Биография инженера',91,'discovered');s['candidates'] += [science,history];seen=[]
        class Editor:
            def finish(self,state,row):seen.append(row['id']);raise news.runtime.GenerationPaused('Synthetic time boundary')
        with tempfile.TemporaryDirectory() as temp,patch.object(d,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True)):
            d.advance(s,s['date'],False,SimpleNamespace(ROOT=fixture.root(temp)),now=fixture.NOW.replace(hour=5),editor=Editor())
        self.assertEqual(seen,['91'])

    def test_exhausted_queue_replenishes_target_and_stock_after_minimum(self):
        for count in (11,12):
            with self.subTest(accepted=count):
                s=self.make(count);calls=[]
                def refresh(*args,**kwargs):
                    calls.append(kwargs.get('shortage'))
                    if len(calls)==2:s['candidates'].append(dict(fixture.ready(50),status='discovered'))
                class Editor:
                    def finish(self,state,row):row['status']='ready'
                with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_CATALOG_REFRESH='true'),patch.object(d,'discover'),patch.object(cat,'refresh',side_effect=refresh),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True)):
                    d.advance(s,s['date'],False,SimpleNamespace(ROOT=fixture.root(temp)),now=fixture.NOW.replace(hour=5),editor=Editor())
                self.assertEqual(len(calls),3)  # one initial, at most two additional searches
                self.assertTrue(calls[1]);self.assertEqual(len(d.preparation_order(s)),0)
                self.assertEqual(s['public_article_count'],12)
                self.assertEqual(stock.report(s)['ready_articles'],int(count==12))

    def test_inventory_goals_are_not_fictional_ready_counts(self):
        s=self.make();report=stock.report(s)
        self.assertEqual(report['ready_articles'],0);self.assertEqual(report['ready_light'],0)
        self.assertEqual((report['article_goal'],report['light_goal']),(20,15))

if __name__=='__main__':unittest.main()
