"""Real policy regressions: content risk, balanced accepted works and bounded batches."""
import copy,os,tempfile,unittest
from datetime import datetime,timezone
from unittest.mock import patch
from scripts import editorial43 as e,selection43 as sel,stock43 as stock,light43 as light,news,generation_runtime as rt,priorities43 as pri
from scripts.test_daily43 import state,root,NOW
from scripts.test_editorial_visual43 import named,light_ready

class FamilyRiskTests(unittest.TestCase):
    def test_ordinary_family_sport_and_health_history_are_not_medical(self):
        for title in ['Семейные настольные игры','Воспитание детей: поддержка и общение','Семейные традиции за общим столом','История велоспорта','Велосипедное путешествие по Подмосковью','История йоги','История медицины и культурные традиции']:
            with self.subTest(title=title):
                row=named(title);row['category_hint']='Семья';row['category']='Здоровье и движение'
                self.assertFalse(e.high_risk(row));self.assertTrue(e.eligible(row))
    def test_risky_recommendations_need_independent_evidence_in_any_category(self):
        for title in ['Как лечить младенца при температуре','Рекомендации по нагрузкам при сердечных заболеваниях','Принимайте лекарство в двойной дозе','Как выполнять стойку на голове','Клиническое исследование нового лечения','Примите препарат ежедневно','Советы по инвестициям','Как выполнять задержку дыхания','Как кормить младенца']:
            with self.subTest(title=title):
                row=named(title);row['category_hint']='История и культура'
                self.assertTrue(e.high_risk(row));self.assertFalse(e.eligible(row))
    def test_history_of_cycling_and_family_games_can_be_banked(self):
        s=state()
        for i,title in enumerate(['История велоспорта','Семейные настольные игры']):
            row=named(title,i);row['category_hint']='Семья' if i else 'Здоровье и движение'
            self.assertTrue(stock.bank(s,row,NOW))
        self.assertEqual(stock.report(s)['ready_articles'],2)
    def test_balanced_twelve_keep_family_and_sport_preserve_accepted_surplus(self):
        s=state();s['candidates']=[named('Квантовая физика '+str(i),i) for i in range(12)]
        s['candidates'] += [named('Семейные игры и воспитание детей',30),named('История велосипеда',31)]
        before=[copy.deepcopy(r['article']) for r in s['candidates']]
        with tempfile.TemporaryDirectory() as temp:chosen=stock.balance(s,root(temp),NOW)
        self.assertEqual(len(chosen),14);self.assertTrue({'A','C'}<={pri.classify(r)['group'] for r in chosen})
        self.assertEqual([r['article'] for r in s['candidates']],before);self.assertEqual(stock.report(s)['ready_articles'],0)
    def test_missing_family_sport_never_blocks_other_verified_articles(self):
        self.assertEqual(len(sel.composition(state(8))),8)
    def test_three_stock_light_items_need_no_model_and_do_not_count_as_main(self):
        s=state(12);stock.ensure(s)['light']=[light_ready(i) for i in range(3)]
        with tempfile.TemporaryDirectory() as temp,patch.object(news,'gemini',side_effect=AssertionError('No model for inventory')):stock.draw_light(s,root(temp))
        self.assertEqual(len(light.ready(s)),3);self.assertEqual(len(sel.composition(s)),12)

    def test_coverage_preparation_precedes_unrelated_unfinished_stock(self):
        from scripts import daily43 as d
        from types import SimpleNamespace
        s=state(12);other=named('Архитектура старого дворца',90,'preparing');family=named('Семейные игры и воспитание детей',91,'discovered');s['candidates'] += [other,family];seen=[]
        class Editor:
            def finish(self,state,row):seen.append(row['id']);raise rt.GenerationPaused('Natural synthetic boundary')
        with tempfile.TemporaryDirectory() as temp,patch.object(d,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True)):
            d.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW.replace(hour=5),editor=Editor())
        self.assertEqual(seen,['91']);self.assertEqual(other['status'],'preparing')
    def test_witnessed_expired_news_is_rejected_after_one_review(self):
        from scripts.test_daily43 import verdict
        s=state();r=named('Новость о музее');r['status']='preparing';r['checks'].pop('final43');r['source']['blocks'][-1]['text']='The event occurred on January 1, 2020.';calls=[]
        def model(prompt,**kwargs):
            calls.append(kwargs['schema']);result=verdict(prompt,r)
            result.update(is_news=True,event_date='2020-01-01',event_source_id=r['source']['id'],event_evidence_id=r['source']['blocks'][-1]['id'],event_quote=r['source']['blocks'][-1]['text'])
            return result
        with self.assertRaisesRegex(e.p.Blocked,'NEWS_EVENT_TOO_OLD'):e.Editor(call=model).finish(s,r)
        self.assertEqual(calls,['v43_final']);self.assertFalse(e.eligible(r));self.assertIn('article',r)


    def test_unfinished_checkpoint_save_does_not_require_another_editorial_count(self):
        from scripts import staged_news as stage
        from pathlib import Path
        checkpoint={'version':43,'date':'2026-11-08','candidates':[{'status':'preparing','article':{'blocks':[]}}]}
        with tempfile.TemporaryDirectory() as temp,patch.object(stage,'ARTIFACT_FILE',Path(temp)/'synthetic.enc'),patch.object(stage,'vetted_count',side_effect=AssertionError('Saving is not another editorial audit')):
            stage.save(checkpoint,b'x'*32)
            self.assertEqual(stage.decipher(stage.ARTIFACT_FILE.read_bytes(),b'x'*32),checkpoint)


class SourceAccessTests(unittest.TestCase):
    def test_new_source_metadata_uses_its_own_domain_and_actual_language(self):
        from scripts import catalog43 as c
        rows=[r for r in c.registry()['publishers'] if r['id'] in ('unicef-parenting','healthychildren','raisingchildren','zerotothree')]
        self.assertEqual(len(rows),4)
        for r in rows:
            self.assertEqual(r['language'],'en');self.assertEqual(r['rights']['evidence_url'],r['homepage'])

    def test_official_http_link_is_requested_over_https_without_changing_the_path(self):
        from scripts import catalog43 as c
        row={'domain':'scholastic.com'}
        self.assertEqual(c.secure_discovery_url('http://www.scholastic.com/parents/books/story.html',row),'https://www.scholastic.com/parents/books/story.html')
        self.assertEqual(c.secure_discovery_url('http://elsewhere.example/story',row),'http://elsewhere.example/story')
    def test_undated_educational_original_is_not_rejected_as_undated_news(self):
        from scripts import catalog43 as c
        from scripts.test_editorial_visual43 import CatalogTests
        f=CatalogTests();session=f.session();original=session.fetch
        session.fetch=lambda url:dict(original(url),title='Игры для детей: учимся вместе',published='')
        report,rows=c.inspect_publisher(dict(f.registry_row(),allow_archive=True),session,now=NOW)
        self.assertEqual(len(rows),1);self.assertTrue(report['undated_archival_original']);self.assertEqual(rows[0][1]['published'],'')
        session.fetch=lambda url:dict(original(url),title='Рекомендации по лечению младенца',published='')
        report,rows=c.inspect_publisher(dict(f.registry_row(),allow_archive=True),session,now=NOW)
        self.assertEqual(rows,[]);self.assertEqual(report['last_article_code'],'PUBLISHER_ACTIVITY_UNCONFIRMED')


class LightBatchTests(unittest.TestCase):
    titles=['Вороны решают головоломки','Музей нашёл редкую карту','Животные: панды осваивают новый сад','Волонтёры спасли морских черепах','Необычная музейная мозаика']
    def budget(self):return rt.RequestBudget({'day':datetime.now(timezone.utc).date().isoformat(),'requests':0,'models':{},'cooldowns':{}},day_limit=220,gap=0)
    def sample(self):
        s=state(8)
        s['candidates'] += [named(self.titles[i],80+i,'discovered') for i in range(5)]
        return s
    def writer(self,budget,approve=lambda i:True):
        titles=self.titles
        class Editor:
            def call(self,prompt,**kwargs):
                budget.reserve('fixture')
                if kwargs['schema']=='v43_light_write':return {'items':[{'id':str(i),'source_id':'s'+str(i+1),'title':titles[i],'text':'Подтверждённый факт: '+titles[i]+'.'} for i in range(5)]}
                sources=saved_sources[0];reviews=[]
                for i,src in enumerate(sources):
                    b=src['blocks'][-1];good=approve(i)
                    reviews.append({'id':str(i),'approve':good,**{k:good for k in e.CHECKS},'is_news':False,'event_date':'','event_source_id':'','event_evidence_id':'','event_quote':'','issues':[] if good else ['private reason'],'unresolved':[], 'claims':[{'fact':b['text'],'source_id':'s'+str(i+1),'evidence_id':'q'+str(len(src['blocks'])),'quote':b['text']}]})
                return {'reviews':reviews}
        saved_sources=[[]]
        return Editor(),saved_sources
    def test_two_of_five_survive_three_individual_vetoes_and_are_persisted(self):
        s=self.sample();budget=self.budget();editor,sources=self.writer(budget,lambda i:i<2)
        def persist():sources[0]=s['light43'].get('sources',[])
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):light.prepare(s,persist,editor)
        self.assertEqual(len(light.ready(s)),2);self.assertEqual(budget.used,2)
        self.assertIn('review',s['light43']);self.assertEqual(s['light43']['summary']['rejection_codes']['LIGHT_REVIEW_VETO'],3)
        self.assertEqual(len(sel.composition(s)),8)
    def test_one_retry_in_next_window_uses_new_sources_and_preserves_counters(self):
        s=self.sample();budget=self.budget();editor,sources=self.writer(budget,lambda i:False)
        def persist():sources[0]=s['light43'].get('sources',[])
        with patch.dict(os.environ,GITHUB_RUN_ID='first'),patch.object(news.runtime,'ACTIVE_BUDGET',budget):
            light.prepare(s,persist,editor);light.prepare(s,persist,editor)
        self.assertEqual(budget.used,2);previous={src['url'] for src in s['light43']['sources']}
        s['candidates'] += [named('Спасённые животные зоопарка '+str(i),90+i,'discovered') for i in range(5)]
        later=self.budget();editor,sources=self.writer(later,lambda i:False)
        with patch.dict(os.environ,GITHUB_RUN_ID='second'),patch.object(news.runtime,'ACTIVE_BUDGET',later):light.prepare(s,persist,editor)
        self.assertEqual(later.used,2);self.assertEqual(s['light43']['http_requests'],4);self.assertEqual(s['light43']['write_attempts'],2)
        self.assertFalse(previous&{src['url'] for src in s['light43']['sources']})
        with patch.dict(os.environ,GITHUB_RUN_ID='third'),patch.object(news.runtime,'ACTIVE_BUDGET',self.budget()):light.prepare(s,persist,editor)
        self.assertEqual(s['light43']['http_requests'],4);self.assertEqual(len(s['light43']['batches']),1)
    def saved_review(self):
        s=self.sample();src=s['candidates'][8]['source'];b=src['blocks'][-1]
        item={'id':'x','source_id':'s1','title':'Вороны решают головоломки','text':'Собственная формулировка проверенного факта.'}
        s['light43']={'write_attempts':1,'review_attempts':1,'http_requests':2,'records':[],'sources':[src],'draft':{'items':[item]},'review_inputs':{'x':e.fingerprint(light.safe_record(item,src))},'review':{'reviews':[{'id':'x','approve':True,**{k:True for k in e.CHECKS},'is_news':False,'event_date':'','event_source_id':'','event_evidence_id':'','event_quote':'','issues':[],'unresolved':[],'claims':[{'fact':b['text'],'source_id':'s1','evidence_id':'q'+str(len(src['blocks'])),'quote':b['text']}]}]}}
        return s
    def test_completed_review_is_recovered_after_interruption_without_another_call(self):
        s=self.saved_review();budget=self.budget()
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(news,'gemini',side_effect=AssertionError('Accepted review must be recovered')):light.prepare(s)
        self.assertEqual(len(light.ready(s)),1);self.assertEqual(budget.used,0);self.assertEqual(s['light43']['http_requests'],2)
    def test_retained_review_cannot_approve_a_changed_draft(self):
        s=self.saved_review();s['light43']['draft']['items'][0]['text']='Другой непроверенный текст.'
        self.assertEqual(light.apply_batch_review(s['light43'],s),[])
        self.assertIn('LIGHT_REVIEW_INPUT_CHANGED',s['light43']['diagnostics'][0]['codes'])

    def test_verified_light_source_is_reserved_before_main_writing(self):
        s=self.saved_review();budget=self.budget();source_id=s['candidates'][8]['id']
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):light.prepare(s)
        self.assertEqual(len(light.ready(s)),1);self.assertTrue(s['candidates'][8]['for_light_only'])
        self.assertNotIn(source_id,[r['id'] for r in sel.order(s)])
    def test_accepted_long_reserve_cannot_be_consumed_as_a_short_story(self):
        s=state(8);long=named('Необычная история воронов',88);stock.ensure(s)['records']=[long]
        candidate=copy.deepcopy(long);candidate['status']='discovered';s['candidates'].append(candidate)
        self.assertEqual(light.sources_for_batch(s),[])
    def test_legacy_diagnostic_counts_main_conflicts_separately(self):
        s=state(8);row=copy.deepcopy(s['candidates'][0]);s['light43']={'records':[row],'review_attempts':1,'http_requests':2}
        summary=light.diagnose_saved(s)
        self.assertEqual(summary['reviewed_records'],1);self.assertEqual(summary['main_conflicts'],1);self.assertEqual(summary['accepted'],0)

    def test_pause_before_any_http_resumes_same_write_without_reset_or_new_batch(self):
        s=self.sample();budget=self.budget()
        class Paused:
            def call(self,*a,**kw):raise rt.GenerationPaused('Global cooldown before reservation')
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):light.prepare(s,editor=Paused())
        self.assertEqual(s['light43']['http_requests'],0);self.assertEqual(s['light43']['write_attempts'],1)
        editor,sources=self.writer(budget)
        def persist():sources[0]=s['light43'].get('sources',[])
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):light.prepare(s,persist,editor)
        self.assertEqual(budget.used,2);self.assertEqual(s['light43']['write_attempts'],1);self.assertNotIn('batches',s['light43']);self.assertGreater(len(light.ready(s)),0)
    def test_pause_before_review_http_keeps_draft_and_resumes_only_review(self):
        s=self.sample();budget=self.budget();editor,sources=self.writer(budget)
        class PausedReview:
            def call(self,prompt,**kw):
                if kw['schema']=='v43_light_review':raise rt.GenerationPaused('Time boundary before review request')
                return editor.call(prompt,**kw)
        def persist():sources[0]=s['light43'].get('sources',[])
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):light.prepare(s,persist,PausedReview())
        draft=copy.deepcopy(s['light43']['draft']);self.assertEqual(budget.used,1)
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):light.prepare(s,persist,editor)
        self.assertEqual(s['light43']['draft'],draft);self.assertEqual(budget.used,2);self.assertEqual(s['light43']['review_attempts'],1);self.assertGreater(len(light.ready(s)),0)
    def test_failed_one_http_write_allows_one_different_batch_next_window(self):
        s=self.sample();budget=self.budget()
        class FailedWrite:
            def call(self,*a,**kw):budget.reserve('fixture');raise rt.GenerationPaused('Gemini HTTP 503')
        with patch.dict(os.environ,GITHUB_RUN_ID='first'),patch.object(news.runtime,'ACTIVE_BUDGET',budget):light.prepare(s,editor=FailedWrite())
        self.assertEqual(budget.used,1);old={src['url'] for src in s['light43']['sources']}
        s['candidates'] += [named('Животные в новом зоопарке '+str(i),95+i,'discovered') for i in range(5)]
        later=rt.RequestBudget(budget.ledger,day_limit=220,gap=0);editor,sources=self.writer(later)
        def persist():sources[0]=s['light43'].get('sources',[])
        with patch.dict(os.environ,GITHUB_RUN_ID='second'),patch.object(news.runtime,'ACTIVE_BUDGET',later):light.prepare(s,persist,editor)
        self.assertEqual(s['light43']['http_requests'],3);self.assertEqual(later.ledger['requests'],3);self.assertEqual(len(s['light43']['batches']),1);self.assertFalse(old&{src['url'] for src in s['light43']['sources']})

    def test_same_source_retry_and_main_duplicates_are_not_allowed(self):
        s=self.sample();s['light43']={'complete':True,'http_requests':2,'write_attempts':1,'review_attempts':1,'records':[],'sources':[r['source'] for r in s['candidates'][8:]]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',self.budget()),patch.object(news,'gemini',side_effect=AssertionError('No new source')):light.prepare(s)
        self.assertNotIn('batches',s['light43'])
        row=copy.deepcopy(s['candidates'][0]);row['light_suitable']=True
        self.assertFalse(light.sources_for_batch(dict(s,candidates=[row])))

if __name__=='__main__':unittest.main()
