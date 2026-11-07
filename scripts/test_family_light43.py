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
        self.assertEqual(len(chosen),12);self.assertTrue({'A','C'}<={pri.classify(r)['group'] for r in chosen})
        self.assertEqual([r['article'] for r in s['candidates']],before);self.assertEqual(stock.report(s)['ready_articles'],2)
    def test_missing_family_sport_never_blocks_other_verified_articles(self):
        self.assertEqual(len(sel.composition(state(8))),8)
    def test_three_stock_light_items_need_no_model_and_do_not_count_as_main(self):
        s=state(12);stock.ensure(s)['light']=[light_ready(i) for i in range(3)]
        with tempfile.TemporaryDirectory() as temp,patch.object(news,'gemini',side_effect=AssertionError('No model for inventory')):stock.draw_light(s,root(temp))
        self.assertEqual(len(light.ready(s)),3);self.assertEqual(len(sel.composition(s)),12)

class SourceAccessTests(unittest.TestCase):
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

    def test_same_source_retry_and_main_duplicates_are_not_allowed(self):
        s=self.sample();s['light43']={'complete':True,'http_requests':2,'write_attempts':1,'review_attempts':1,'records':[],'sources':[r['source'] for r in s['candidates'][8:]]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',self.budget()),patch.object(news,'gemini',side_effect=AssertionError('No new source')):light.prepare(s)
        self.assertNotIn('batches',s['light43'])
        row=copy.deepcopy(s['candidates'][0]);row['light_suitable']=True
        self.assertFalse(light.sources_for_batch(dict(s,candidates=[row])))

if __name__=='__main__':unittest.main()
