"""4.4 regressions: actual subjects, uncapped issues, cheap resumable briefs."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import policy44 as v,editorial43 as e,selection43 as sel,publication43 as pub,light44 as brief,light43,stock43,news,site_checks,staged_news
from scripts.test_daily43 import state,root,ready,web,NOW
from scripts.test_editorial_visual43 import named,light_ready

TOPICS=['Родители и дети: семейные игры','Супружеские отношения и общение','Здоровое питание и долголетие','Режим сна и профилактика заболеваний','Велосипедные тренировки и выносливость','Йога и подвижность']
def main_row(i):
    title=TOPICS[i] if i<len(TOPICS) else ['Открытие археологов','Инженерный мост','Биография архитектора','Московский маршрут','Музыкальная коллекция','Природа растений'][i%6]+' '+str(i)
    row=named(title,i);row['topic_policy_version']='4.4'
    row['article']['blocks']=[{'kind':'paragraph','text':title+'. Подтверждённый учебный пример '+str(i)+'.'}]
    row['checks']['final43']['input_hash']=e.fingerprint(row)
    return row

def issue(n=8,lights=8):
    s=state();s['policy_version']='4.4';s['candidates']=[main_row(i) for i in range(n)]
    s['light43']={'records':[light_ready(i) for i in range(lights)]}
    return s

def response_item():
    source=ready(45)['source'];source['blocks']=[{'id':'proof','kind':'paragraph','text':'The museum restored 21 paintings in its collection.'}]
    item={'id':'note','source_id':source['id'],'title':'Реставрация коллекции','text':'Музей восстановил 21 картину из своего собрания.','time_kind':'unusual_fact','event_date':'','evidence':[{'block_id':'proof','quote':source['blocks'][0]['text']}]}
    return source,item

class Policy44Tests(unittest.TestCase):
    def test_uncapped_8_12_16_20_25_30_and_lights_8_12_16(self):
        for n,light in [(8,8),(12,8),(16,8),(20,8),(25,12),(30,16)]:
            with self.subTest(main=n,notes=light),tempfile.TemporaryDirectory() as temp:
                s=issue(n,light);target=root(temp)
                self.assertEqual(len(sel.composition(s)),n);self.assertTrue(v.standard(s)['compliant'])
                pub.build(s,target);data=pub.validate(target,s['date'])
                self.assertEqual((data['article_count'],data['light_count']),(n,light))
                with patch.object(site_checks,'fetch',side_effect=web(target)):self.assertEqual(site_checks.check_site(expected_date=s['date'])['articles'],n)
    def test_seven_main_and_five_light_have_exact_deficits(self):
        s=issue(7,5);report=v.standard(s)
        self.assertEqual((report['main_deficit'],report['light_deficit']),(1,3));self.assertFalse(report['compliant'])
        with tempfile.TemporaryDirectory() as temp,self.assertRaisesRegex(ValueError,'EDITORIAL_STANDARD_NOT_MET'):pub.build(s,root(temp))
    def test_six_different_articles_cover_2_2_2(self):
        self.assertEqual(v.counts(issue()['candidates']),dict(family=2,health=2,sport=2))
    def test_ambiguous_old_labels_cannot_fill_a_minimum(self):
        r=named('Дом в центре города');r['article']['category']='Семья';r['category_hint']='Семья'
        self.assertIsNone(v.subject(r))
    def test_published_018_art_and_power_are_not_family_or_health(self):
        files=list((Path(__file__).resolve().parents[1]/'issues/2026-11-11/articles').glob('*/index.html'))
        selected=[v.from_html(f.read_text()) for f in files if any(t in f.read_text() for t in ['Утерянный пейзаж Джорджии','Автономность на кухне'])]
        self.assertEqual(len(selected),2)
        for row in selected:self.assertIsNone(v.subject(row))
    def test_incidental_keywords_and_model_training_do_not_count(self):
        for title,body in [('Картина художницы','Семья обнаружила картину в доме. Полотно изображает горы.'),('Резервное электропитание кухни','Продукты питания сохраняются благодаря батарее.'),('Обучение модели нейросети','Тренировка модели улучшает результат.')]:
            self.assertIsNone(v.subject({'article':{'title':title,'blocks':[{'text':body}]}}))
    def test_cycling_health_overlap_counts_once(self):
        row=main_row(4);row['article']['blocks'][0]['text']+=' Велосипедные тренировки поддерживают здоровье.'
        self.assertEqual(sum(v.counts([row]).values()),1);self.assertEqual(v.subject(row),'sport')
    def test_family_and_sport_sources_do_not_require_second_publication(self):
        for i in (0,1,4,5):self.assertFalse(e.high_risk(main_row(i)))
    def test_risky_treatment_and_dangerous_exercise_remain_protected(self):
        for title in ['Дайте ребёнку лекарство','Лечение заболевания: следует принимать препарат','Как выполнять стойку на голове']:
            self.assertTrue(e.high_risk(named(title)))
    def test_missing_sport_is_prepared_despite_twenty_ready(self):
        s=issue(20);s['candidates']=[r for r in s['candidates'] if v.subject(r)!='sport']
        sports=main_row(4);sports.update(id='new-sport',status='discovered');science=named('Квантовое открытие',99,'discovered');s['candidates'] += [science,sports]
        self.assertIs(sel.order(s,limit=1)[0],sports)
    def test_topic_directed_discovery_includes_three_distinct_streams(self):
        rows=[{'id':g,'priority_ids':[n],'availability':{},'editorial_priority':50} for g,n in [('family',1),('health',12),('sport',13),('science',22)]]
        result=v.publisher_order(rows,issue(0,0));self.assertEqual({r.get('search_group') for r in result[:3]},set(v.GROUPS))
    def test_migration_preserves_text_facts_quota_and_is_idempotent(self):
        s=issue();s['policy_version']='4.3';s['_quota_snapshot']={'requests':219,'cooldowns':{'m':1234}}
        s['candidates'][0]['article']['category']='Наука';s['candidates'][0]['checks']['final43']['input_hash']=e.fingerprint(s['candidates'][0])
        before=copy.deepcopy(s);v.migrate(s);after=copy.deepcopy(s);v.migrate(s)
        self.assertEqual(s,after);self.assertEqual(s['_quota_snapshot'],before['_quota_snapshot'])
        self.assertEqual(s['candidates'][0]['article']['blocks'],before['candidates'][0]['article']['blocks']);self.assertTrue(e.eligible(s['candidates'][0]))
    def test_published_files_are_never_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);s=issue();pub.build(s,target);before={str(f):f.read_bytes() for f in target.rglob('*') if f.is_file()}
            pub.build(issue(20,16),target);self.assertEqual(before,{str(f):f.read_bytes() for f in target.rglob('*') if f.is_file()})
    def test_any_brief_subject_is_allowed_without_animal_whitelist(self):
        for title in ['Люди открыли музей','Культура города','Спортивное событие','Технология печати','Поведение воронов','История открытия','Экономическая жизнь']:
            self.assertTrue(light43.story_suitable({'title':title}))
    def test_simple_brief_has_one_fact_gate_and_no_article_audit(self):
        src,item=response_item();row=brief.accept(item,src)
        self.assertTrue(brief.eligible(row));self.assertNotIn('final43',row['checks'])
        row['article']['blocks'][0]['text']='Подменённый непроверенный текст';self.assertFalse(brief.eligible(row))
    def test_invented_quote_number_copy_or_instruction_is_rejected(self):
        src,item=response_item()
        for field,value in [('text','Музей восстановил 99 картин.'),('text',src['blocks'][0]['text']),('text','Принимайте препарат ежедневно.')]:
            test=copy.deepcopy(item);test[field]=value
            with self.subTest(value=value),self.assertRaises(ValueError):brief.accept(test,src)
        item['evidence'][0]['quote']='A fabricated fact'
        with self.assertRaisesRegex(ValueError,'BRIEF_FACT_NOT_BOUND'):brief.accept(item,src)
    def test_completed_batch_resumes_without_api_or_budget(self):
        src,item=response_item();s=issue(8,0);s['light43']['v44']={'sources':[src],'response':{'items':[item]},'window':'old-run','attempts':1,'http_requests':1,'refusals':[],'completed':[]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',None),patch.object(news,'gemini',side_effect=AssertionError('Already paid')):
            brief.prepare(s);restored=json.loads(json.dumps(s));brief.prepare(restored)
        self.assertEqual(len(brief.ready(restored)),1);self.assertEqual(restored['light43']['v44']['http_requests'],1)
    def test_eight_reserve_notes_form_column_without_gemini(self):
        s=issue(8,0);stock43.ensure(s)['light']=[light_ready(i) for i in range(8)]
        with tempfile.TemporaryDirectory() as temp,patch.object(news,'gemini',side_effect=AssertionError('No inference')):stock43.draw_light(s,root(temp))
        self.assertEqual(len(light43.ready(s)),8);self.assertTrue(v.standard(s)['compliant'])
    def test_independent_encrypted_restore_preserves_completed_stages_and_ledger(self):
        s=issue(20,12);s['_quota_snapshot']={'requests':219};key=bytes(range(32))
        restored=staged_news.decipher(staged_news.cipher(s,key),key)
        self.assertEqual(v.standard(s),v.standard(restored));self.assertEqual(s['_quota_snapshot'],restored['_quota_snapshot']);self.assertEqual(len(sel.composition(restored)),20)


    def test_ready_stock_does_not_hide_the_thirteenth_article_or_note(self):
        s=issue(12,0);stock=stock43.ensure(s)
        stock['records']=[main_row(i) for i in range(12,25)]
        stock['light']=[light_ready(i) for i in range(16)]
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);stock43.draw(s,target,NOW);stock43.draw_light(s,target)
        self.assertEqual((len(sel.composition(s)),len(light43.ready(s))),(25,16))
    def test_short_topics_do_not_use_main_article_family_aliases(self):
        a=named('Живые строительные материалы',30);b=named('Самовосстанавливающийся бетон',31)
        self.assertTrue(sel.duplicate(a,b));self.assertFalse(brief.duplicate(a,b))
    def test_unverified_dates_and_false_recency_are_rejected(self):
        src,item=response_item();item.update(time_kind='news',event_date='2026-11-11')
        with self.assertRaisesRegex(ValueError,'BRIEF_EVENT_DATE_UNSUPPORTED'):brief.accept(item,src)
        item.update(time_kind='unusual_fact',text='Сегодня музей восстановил 21 картину.')
        with self.assertRaisesRegex(ValueError,'BRIEF_FALSE_RECENCY'):brief.accept(item,src)
    def test_one_batched_request_is_charged_and_not_repeated_in_same_window(self):
        from scripts import generation_runtime as rt
        src,item=response_item();s=issue(8,0)
        s['candidates'].append({'id':'brief-source','url':src['url'],'source':src,'status':'discovered','progress':{},'history':[],'for_light_only':True})
        s['light43_queue']=['brief-source']  # Production queue stores IDs, not dictionaries.
        budget=rt.RequestBudget({});budget.deadline=__import__('time').monotonic()+1000
        alias=copy.deepcopy(item);alias.update(source_id='s1');alias['evidence'][0]['block_id']='q1'
        def model(*a,**kw):budget.reserve('fixture-model');return {'items':[alias]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(news,'gemini',side_effect=model) as call:
            brief.prepare(s);brief.prepare(s)
        self.assertEqual(call.call_count,1);self.assertEqual(budget.used,1);self.assertEqual(s['light43']['v44']['http_requests'],1)
        self.assertEqual(len(brief.ready(s)),1)


    def test_due_deficit_creates_existing_safe_incident(self):
        from scripts import release_monitor as monitor
        calls=[]
        def github(method,path,payload=None):
            calls.append((method,path,payload));return [] if method=='GET' else {}
        status=monitor.evaluate(Path('/nonexistent'),{'date':NOW.date().isoformat(),'block_code':'EDITORIAL_STANDARD_NOT_MET'},NOW,check_public=lambda **kw:(_ for _ in ()).throw(ValueError('No issue')))
        self.assertEqual(status['code'],'EDITORIAL_DEFICIT');self.assertTrue(status['alert'])
        self.assertEqual(monitor.incident(status['date'],status['code'],False,request=github),'created')
        self.assertNotIn('source',str(calls[-1][2]).lower())


    def test_watchdog_resumes_policy44_deficits_in_the_same_controller(self):
        from scripts import delivery_watchdog as watch
        from scripts.test_delivery_watchdog import Clock,API,at
        clock=Clock(at('07:00'));api=API(clock)
        with patch.dict(os.environ,NEWS_POLICY_VERSION='4.4'):
            result=watch.run(Path('/unused'),clock=clock,sleep=clock.sleep,request=api,check=api.check)
        self.assertTrue(result['verified']);self.assertEqual(api.posts[0][1]['inputs']['phase'],'run')
        self.assertEqual(len(api.posts),1)


    def test_restored_legacy_news_keep_date_checks_and_titles_are_own(self):
        s=issue(8,1);row=s['light43']['records'][0];row['checks']['final43'].update(is_news=True,event_date='2099-01-01')
        self.assertEqual(light43.ready(s),[])
        src,item=response_item();src['title']=item['title']='Долгая история необычного открытия в музее'
        with self.assertRaisesRegex(ValueError,'BRIEF_COPIED_TITLE'):brief.accept(item,src)


    def test_current_sixteen_briefs_are_not_capped_to_build_stock(self):
        s=issue(8,16);stock43.bank_light(s,NOW)
        self.assertEqual(len(light43.ready(s)),16);self.assertEqual(stock43.report(s)['ready_light'],0)
    def test_independent_stock_batch_survives_current_and_next_issue(self):
        src,item=response_item();s=issue(8,16)
        s['light43']['v44']={'sources':[src],'response':{'items':[item]},'window':'stock-run','attempts':1,'http_requests':1,'refusals':[],'completed':[],'destination':'stock'}
        accept=brief.accept
        def checked(*a):
            row=accept(*a);row['ready_checked_at']=NOW.isoformat();return row
        with patch.object(brief,'accept',side_effect=checked),tempfile.TemporaryDirectory() as temp:
            target=root(temp);brief.apply_response(s);stock43.draw_light(s,target)
            self.assertEqual(len(light43.ready(s)),16);self.assertEqual(stock43.report(s)['ready_light'],1)
            restored=json.loads(json.dumps(s));stock43.draw_light(restored,target)
            self.assertEqual(len(light43.ready(restored)),16)
            tomorrow=issue(8,0);tomorrow['date']='2026-10-28';stock43.merge(tomorrow,restored['stock43']);stock43.draw_light(tomorrow,target)
            self.assertEqual(len(light43.ready(tomorrow)),1)

if __name__=='__main__':unittest.main()
