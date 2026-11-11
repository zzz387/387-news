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
        src,item=response_item();item.update(time_kind='news',event_date='2026-11-11',text='Сегодня музей восстановил 21 картину.')
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


    def test_explicit_main_stock_does_not_reenter_the_current_issue(self):
        s=issue(16);row=main_row(40);row['stock_prepared_for']=s['date'];self.assertTrue(stock43.bank(s,row,NOW))
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);stock43.draw(s,target,NOW)
            self.assertEqual(len(sel.composition(s)),16);self.assertEqual(stock43.report(s)['ready_articles'],1)
            tomorrow=issue(8);tomorrow['date']='2026-10-28';stock43.merge(tomorrow,s['stock43']);stock43.draw(tomorrow,target,NOW)
            self.assertEqual(len(sel.composition(tomorrow)),9)
    def test_main_stock_commissioning_preserves_uncapped_current_issue(self):
        from scripts import daily43
        s=issue(20);pending=main_row(40);pending.update(id='future-article',status='discovered');s['candidates'].append(pending)
        class Editor:
            def finish(self,state,row):row['status']='ready'
        with tempfile.TemporaryDirectory() as temp,patch.object(daily43,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True)):
            daily43.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW.replace(hour=5),editor=Editor())
        self.assertEqual(len(sel.composition(s)),20);self.assertEqual(stock43.report(s)['ready_articles'],1)


    def test_full_general_reserve_does_not_prevent_missing_subjects(self):
        s=issue(16);stock43.ensure(s)['records']=[main_row(i) for i in range(30,50)]
        row=main_row(0);self.assertTrue(stock43.bank(s,row,NOW))
        self.assertEqual(stock43.report(s)['required_topics']['family'],1)
        self.assertEqual(stock43.report(s)['ready_articles'],21)


    def test_incidental_source_words_do_not_enter_targeted_writing(self):
        row={'title':'Образование и экономика региона','source':{'title':'Образование и экономика региона','blocks':[{'text':'Исследуется промышленность, университеты и экономика. Спортивные тренировки упомянуты в студенческой жизни. Затем рассматриваются бюджет, экспорт, промышленность и занятость. Обсуждаются отрасли экономики и университеты.'}]}}
        self.assertIsNone(v.subject(row))
    def test_focused_publisher_precedes_mixed_convenient_feed(self):
        rows=[{'id':'mixed','priority_ids':[1,3,18,23],'availability':{'full_originals_verified':20}}, {'id':'family','priority_ids':[1,2,3],'availability':{'full_originals_verified':2}}]
        self.assertEqual(v.publisher_order(rows,issue(0,0))[0]['id'],'family')
    def test_equivalent_number_notation_is_not_a_factual_refusal(self):
        self.assertEqual(brief.numbers('1,000 and 2.5','en'),brief.numbers('1 000 и 2,5','ru'))
        self.assertNotEqual(brief.numbers('1,000','en'),brief.numbers('999','ru'))
    def test_surplus_general_articles_do_not_consume_missing_subject_budget(self):
        from scripts import daily43
        s=issue(20);s['candidates']=[r for r in s['candidates'] if v.subject(r) is None];s['candidates'] += [main_row(i) for i in range(40,50)]
        row=main_row(90);row['status']='discovered';s['candidates'].append(row);editor=__import__('unittest.mock',fromlist=['Mock']).Mock()
        with tempfile.TemporaryDirectory() as temp,patch.object(daily43,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True)):
            daily43.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW.replace(hour=5),editor=editor)
        editor.finish.assert_not_called();self.assertFalse(s['audit_passed'])


    def test_search_targets_two_candidates_per_missing_subject(self):
        self.assertEqual(v.search_deficits(issue(0,0)),dict(family=2,health=2,sport=2))
        s=issue();self.assertEqual(v.search_deficits(s),dict(family=2,health=2,sport=2))  # Replenish empty protected stock.
    def test_ordinary_bedtime_games_are_not_medical_but_infant_safety_is(self):
        self.assertFalse(e.high_risk(named('Игры с малышом перед сном: пение и дыхание')))
        for title in ['Как кормить младенца','Медицинская помощь младенцу при температуре','Как укладывать младенца спать на живот']:
            self.assertTrue(e.high_risk(named(title)))


    def test_decimal_admission_migration_recovers_saved_response_without_api(self):
        src,item=response_item();src['language']='en';src['blocks'][0]['text']='The museum restored 1,000 paintings in its collection.'
        item['text']='Музей восстановил 1 000 картин из своего собрания.';item['evidence'][0]['quote']=src['blocks'][0]['text']
        s=issue(8,0);s['light43']['v44']={'sources':[src],'response':{'items':[item]},'response_applied':True,'admission_revision':1,'window':'paid-run','attempts':1,'http_requests':1,'refusals':[{'url':src['url'],'code':'BRIEF_NUMBER_UNSUPPORTED'}],'completed':[]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',None),patch.object(news,'gemini',side_effect=AssertionError('Response already paid')):
            brief.prepare(s);brief.prepare(s)
        self.assertEqual(len(light43.ready(s)),1);self.assertEqual(s['light43']['v44']['http_requests'],1)


    def test_source_medical_aside_does_not_force_an_ordinary_c_article_to_be_medical(self):
        row=main_row(0);article=row.pop('article');row['title']=row['source']['title']='Семейные игры'
        row['source']['blocks'].append({'id':'aside','text':'A clinical trial described medication effects in patients.','kind':'paragraph'})
        row['checks'].pop('final43');row['mode']='INDEPENDENT_ARTICLE'
        editor=e.Editor();editor.verify_source(row);self.assertTrue(row['source_risk_pending'])
        row['article']=article;editor.verify_source(row);self.assertFalse(e.high_risk(row))
        row['article']['title']='Дайте ребёнку лекарство'
        with self.assertRaisesRegex(ValueError,'INDEPENDENT_SAFETY_EVIDENCE_REQUIRED'):editor.verify_source(row)


    def test_children_inflections_and_child_are_real_family_not_processes(self):
        for title in ['Развитие детей','Общение с детьми','Счастливое детство','A child learns through play','Kids and parents']:
            row={'article':{'title':title,'blocks':[{'text':title+'. '+title+' — основная тема исследования.'}]}}
            self.assertEqual(v.subject(row),'family')
        self.assertIsNone(v.subject({'title':'Parent company funds research','summary':'Parent company manages its subsidiaries.'}))
        self.assertIsNone(v.subject({'title':'Child processes in Linux','summary':'Child processes inherit parent process state.'}))
    def test_sport_inflections_and_walking_are_supported(self):
        for title in ['История спорта','Физиология бега','Плавание для взрослых','Walking and physical activity']:
            self.assertEqual(v.subject({'article':{'title':title,'blocks':[{'text':title+'. '+title+' — тема этого материала.'}]}}),'sport')


    def test_literary_family_title_is_supported_by_lead_and_repeated_actual_content(self):
        body='Parents can support children at home. Adults often have questions. Each child develops at a different pace. Play can be shared. Parents can listen without judging. New experiences take time. The practical examples explain ordinary communication. Support can be quiet.'
        self.assertEqual(v.subject({'article':{'title':'Small steps together','teaser':'','blocks':[{'text':body}]}}),'family')
    def test_peruvian_hotel_does_not_become_health_because_people_sleep_there(self):
        body='Guests sleep in a capsule. The hotel offers places to sleep. Sleeping high above the valley is unusual. Guests sleep after the climb.'
        self.assertIsNone(v.subject({'source':{'title':'The Peruvian hotel with a terrifying check-in','blocks':[{'text':body}]}}))
    def test_ironman_record_is_a_real_sport_subject(self):
        body='The athlete completed the Ironman distance. The report describes swimming, cycling and running. The record was recorded at the finish.'
        self.assertEqual(v.subject({'source':{'title':'Magnus Ditlev sets an Ironman record','blocks':[{'text':body}]}}),'sport')
    def test_official_stable_guidance_can_be_undated_but_breaking_clinical_news_cannot(self):
        from scripts import catalog43
        src={'title':'Clinical guidance','url':'https://www.nhs.uk/conditions/asthma/','blocks':[{'text':'Medical treatment and medication are discussed.'}]}
        self.assertTrue(catalog43.undated_evergreen(src,{'allow_archive':True}))
        src['title']='New study today';src['url']='https://www.nhs.uk/news/clinical-study'
        self.assertFalse(catalog43.undated_evergreen(src,{'allow_archive':True}))


    def test_health_is_human_medical_content_not_a_metaphor(self):
        body='Health concerns can include symptoms. Medical advice explains when parents should seek help. The guidance discusses healthcare and symptoms.'
        self.assertEqual(v.subject({'source':{'title':'Newborn baby health','blocks':[{'text':body}]}}),'health')
        for title in ['Healthy forests','Financial health','Здоровье бизнеса']:
            self.assertIsNone(v.subject({'source':{'title':title,'blocks':[{'text':(title+'. ')*5}]}}))
    def test_missing_groups_keep_searching_in_round_robin_within_existing_budget(self):
        from scripts import catalog43 as catalog
        original=catalog.registry();template=original['publishers'][0];publishers=[]
        for group,direction in [('family',1),('health',12),('sport',13)]:
            for i in range(1,5):
                pub=copy.deepcopy(template);pub.update(id=group+str(i),domain=group+str(i)+'.example.org',homepage='https://'+group+str(i)+'.example.org/',priority_ids=[direction],enabled=True,availability={'status':'verified','full_originals_verified':1})
                publishers.append(pub)
        cfg=dict(original,publishers=publishers,publishers_per_run=5,article_checks_per_run=8)
        calls={g:0 for g in v.GROUPS};limits=[]
        titles={'family':'Воспитание детей','health':'Здоровое питание','sport':'Йога и подвижность'}
        def inspect(pub,session,article_limit=2,exclude=(),now=None,preferred_group=None):
            group=preferred_group or next(g for g in v.GROUPS if pub['id'].startswith(g));calls[group]+=1;limits.append(article_limit);found=[]
            if calls[group]>=3:
                for i in range(min(2,article_limit)):
                    src=copy.deepcopy(ready(90)['source']);src.update(id=pub['id']+str(i),url=pub['homepage']+str(i),title=titles[group]);src['blocks']=[{'id':'proof','kind':'paragraph','text':titles[group]+'. '+titles[group]+'.'}]
                    found.append(({'url':src['url'],'title':src['title']},src))
            return {'publisher':pub['id'],'status':'full_sources_verified' if found else 'discovery_verified','discovered':5,'eligible':len(found),'article_checks':1,'last_article_code':None},found
        s=issue(0,0)
        with patch.object(catalog,'registry',return_value=cfg),patch.object(catalog,'inspect_publisher',side_effect=inspect),patch.dict(os.environ,NEWS_LIGHT_NEWS_ENABLED='false'):
            report=catalog.refresh(s,NOW,shortage=True)['last_run']
        self.assertEqual(limits[:3],[2,2,2]);self.assertTrue(all(calls[g]>=3 for g in v.GROUPS));self.assertTrue(all(report['candidate_groups'][g]>=2 for g in v.GROUPS));self.assertLessEqual(report['article_checks'],24)


    def test_official_nhs_identity_does_not_grant_republication_rights(self):
        from scripts import source41,rights41
        html='<html lang="en"><head><title>Food habits</title></head><body><article><h1>Food habits</h1><p>Nutrition guidance explains ordinary food habits and practical choices for adults.</p><p>The page is an official informational guide for readers.</p></article></body></html>'
        src=source41.extract(html,'https://www.nhs.uk/live-well/eat-well/')
        self.assertEqual(src['metadata_status'],'verified');self.assertTrue(src['full_text_verified'])
        self.assertEqual(rights41.decision(src,'INDEPENDENT_ARTICLE')['status'],'allowed')
        self.assertNotEqual(rights41.decision(src,'ORIGINAL_REPUBLICATION')['status'],'allowed')


    def test_model_date_hint_does_not_block_a_verified_undated_source_report(self):
        src,item=response_item();item.update(time_kind='news',event_date='2026-11-11')
        row=brief.accept(item,src);self.assertEqual(row['light_kind'],'source_report')
        self.assertEqual(row['checks']['brief44']['event_date'],'');self.assertTrue(brief.eligible(row))
        for text in ['Сегодня музей восстановил 21 картину.','Музей откроется завтра.','В 2026 году музей восстановил 21 картину.']:
            case=copy.deepcopy(item);case['text']=text
            with self.assertRaises(ValueError):brief.accept(case,src)


    def test_medlineplus_and_nih_are_not_independent_medical_publishers(self):
        from scripts import editorial41
        self.assertEqual(editorial41.publisher_identity('https://magazine.medlineplus.gov/article'),editorial41.publisher_identity('https://www.nih.gov/article'))
        self.assertNotEqual(editorial41.publisher_identity('https://www.nhs.uk/article'),editorial41.publisher_identity('https://www.nih.gov/article'))


    def test_who_navigation_is_not_a_complete_publication(self):
        from scripts import catalog43
        self.assertFalse(catalog43.article_link({'url':'https://www.who.int/mega-menu/health-topics/resources/questions-and-answers','heading_link':True}))
        self.assertTrue(catalog43.article_link({'url':'https://www.who.int/news-room/feature-stories/detail/an-example','heading_link':True}))
    def test_real_nhs_guidance_subjects_are_health(self):
        for title,text in [('Healthy teeth and gums','Brush your teeth. Dental care matters. Your dentist can help with oral hygiene.'),('Best way to wash your hands','Handwashing is ordinary hygiene. Wash your hands carefully. Handwashing helps reduce spread.')]:
            self.assertEqual(v.subject({'source':{'title':title,'blocks':[{'text':text}]}}),'health')

if __name__=='__main__':unittest.main()
