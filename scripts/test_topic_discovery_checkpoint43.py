"""Real №012 metadata plus bounded core discovery and addressed checkpoint migration."""
import copy,json,tempfile,unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from scripts import selection43 as sel,priorities43 as pr,catalog43 as cat,daily43 as daily,editorial43 as ed,news,publication43 as pub
from scripts import test_daily43 as fixtures,test_editorial_visual43 as visual
from scripts.test_editorial_topic_coverage43 import candidate

class TopicDiscoveryTests(unittest.TestCase):
    def eos(self):
        a=candidate('Живые строительные материалы меняют подход к проектированию городской среды',5,source_title='There Are No Small Parts, Only Small Organisms')
        b=candidate('Самовосстанавливающийся бетон и мицелий меняют облик городской архитектуры',6,source_title='Building the Cities of Tomorrow with Living Materials')
        a['url']='https://eos.org/agu-news/there-are-no-small-parts-only-small-organisms'
        b['url']='https://eos.org/features/building-the-cities-of-tomorrow-with-living-materials'
        return a,b

    def test_real_eos_metadata_is_one_narrow_story_but_modernism_is_another(self):
        a,b=self.eos();self.assertTrue(sel.duplicate(a,b))
        self.assertFalse(sel.duplicate(a,candidate('История московского модерна: особняк Рябушинского',7)))
        self.assertFalse(sel.duplicate(a,candidate('Бактерии в городской экологии рек',8)))
        self.assertFalse(sel.duplicate(a,candidate('Бактерии в старых зданиях и проблемы санитарии',9)))

    def test_cryptic_original_title_uses_verified_full_source_before_writing(self):
        a,b=self.eos();a['title']=a['source']['title'];b['title']=b['source']['title']
        a['source'].update(full_text_verified=True,blocks=[{'text':'Microorganisms enable self-healing concrete building materials.'}])
        self.assertTrue(sel.duplicate(a,b))

    def test_own_prose_reveals_duplicate_when_source_titles_differ(self):
        a=candidate('A surprising new approach',1);b=candidate('A different report from a laboratory',2)
        for row in (a,b):row['article']={'title':row['title'],'blocks':[{'text':'Разработчики исследовали самовосстанавливающийся бетон с бактериями и мицелием. Применение живых строительных материалов меняет методы ремонта зданий.'}]}
        self.assertTrue(sel.duplicate(a,b))

    def test_final_selection_prefers_better_story_and_retains_both_records(self):
        s=fixtures.state(2);a,b=self.eos()
        for row,meta in zip(s['candidates'],(a,b)):
            row['url']=meta['url'];row['title']=meta['title'];row['article']['title']=meta['title'];row['checks']['final43']['input_hash']=ed.fingerprint(row)
        s['candidates'][1]['editorial_priority']=99
        before=copy.deepcopy(s['candidates'])
        self.assertEqual(sel.ready(s),[s['candidates'][1]]);self.assertEqual(s['candidates'],before)

    def test_27_candidates_choose_core_groups_before_more_science(self):
        titles=['Quantum experiment '+str(i) for i in range(10)]
        titles+=['Воспитание ребёнка','Семейный досуг и игры','Супружеские отношения']
        titles+=['История Москвы и улицы','Подмосковные усадьбы','Поездка выходного дня']
        titles+=['Кардиотренировки и выносливость','Йога и подвижность','Велосипедный маршрут 40 км']
        titles+=['Биография художника','Археологические раскопки','Христианская история','Древняя крепость','Историческая загадка']
        titles+=['Банкротство ИП','Экономика повседневности','Инженерия и производство']
        rows=[candidate(t,i) for i,t in enumerate(titles)]
        result=sel.order(dict(date='2026-11-06',candidates=rows))[:12]
        self.assertEqual(len(result),12);self.assertEqual({pr.classify(r)['group'] for r in result[:3]},set('ABC'))
        self.assertGreaterEqual(sum(pr.classify(r)['direction'] is not None for r in result),8)

    def test_categories_follow_content_not_eos_domain_or_stale_science_hint(self):
        cases=[('Парламентский контроль Конгресса США','Общество'),('История искусства и живопись Ренессанса','История и культура'),('Самовосстанавливающийся бетон для строительства','Технологии'),('Квантовая физика и нейтрино','Наука'),('Неопределённая новая публикация','Общество')]
        for title,category in cases:
            with self.subTest(title=title):
                self.assertEqual(pr.classify(dict(title=title,category_hint='Наука',priority_ids=[22],publisher_id='eos'))['category'],category)
        row=candidate('Quantum physics feed',1);row['article']={'title':'Йога и подвижность','teaser':'Восстановление после тренировки','blocks':[]}
        self.assertEqual(pr.classify(row)['group'],'C')

    def test_migration_keeps_approved_work_quota_and_histories_and_is_idempotent(self):
        s=fixtures.state(1);row=candidate('Семейный досуг с детьми',99,status='preparing');row['category_hint']='Наука';row['history']=[{'code':'PREVIOUS_REFUSAL'}];s['candidates'].append(row)
        s['_quota_snapshot']={'requests':219,'cooldowns':{'model':9999999999}};approved=copy.deepcopy(s['candidates'][0]);quota=copy.deepcopy(s['_quota_snapshot'])
        self.assertTrue(pr.apply_rules(s,fixtures.NOW));self.assertEqual(row['category_hint'],'Семья')
        self.assertEqual(s['candidates'][0],approved);self.assertEqual(s['_quota_snapshot'],quota);self.assertEqual(row['history'],[{'code':'PREVIOUS_REFUSAL'}])
        restored=json.loads(json.dumps(s));self.assertFalse(pr.apply_rules(restored,fixtures.NOW+timedelta(minutes=1)))
        self.assertEqual(len(restored['history']),1);self.assertIn('catalog_hash',restored['selection_policy43'])
        self.assertEqual(restored['selection_policy43']['classifier_version'],2)

    def test_full_pool_rotates_without_removing_sources_checks_or_drafts(self):
        s=fixtures.state(1)
        rows=[candidate('Quantum article '+str(i),i+1) for i in range(125)]
        rows[0]['checks']={'source43':{'approved':True}};rows[0]['source']={'title':'Verified complete source','blocks':[{'text':'Retained'}]}
        s['candidates']+=rows;before=copy.deepcopy(rows[0]);accepted=copy.deepcopy(s['candidates'][0])
        self.assertEqual(cat.rotate_candidates(s),5);self.assertEqual(len(s['candidates']),126)
        self.assertEqual(rows[0]['status'],'discovery_retired');self.assertEqual(rows[0]['source'],before['source']);self.assertEqual(rows[0]['checks'],before['checks']);self.assertEqual(s['candidates'][0],accepted)

    def core_registry(self):
        original=visual.CatalogTests().registry_row()
        rows=[dict(original,id=g,priority_ids=[i],name=g) for g,i in [('A',1),('B',9),('C',15),('science',22)]]
        return dict(cat.registry(),publishers=rows,publishers_per_run=4,article_checks_per_run=4)

    def test_distinct_publishers_search_abc_even_if_one_site_covers_all_three(self):
        rows=self.core_registry()['publishers'];rows[0]['priority_ids']=[1,9,15]
        result=pr.publisher_order(rows,{},[],'2026-11-06')
        self.assertEqual({r['search_group'] for r in result[:3]},set('ABC'));self.assertEqual(len({r['id'] for r in result[:3]}),3)

    def test_core_network_allowance_and_real_candidate_counts_are_reported(self):
        s=fixtures.state();seen=[];fixture=visual.CatalogTests();source=fixture.session().fetch('https://example.org/story/9')
        def inspect(row,session,**kw):
            seen.append((row['id'],kw['article_limit']))
            title={'A':'Воспитание ребёнка','B':'История Москвы','C':'Йога и подвижность','science':'Quantum physics'}[row['id']]
            src=dict(source,url='https://example.org/'+row['id'],title=title)
            return {'status':'full_sources_verified','article_checks':kw['article_limit']},[({'title':title},src)]
        config=self.core_registry()
        with patch.object(cat,'registry',return_value=config),patch.object(cat,'inspect_publisher',side_effect=inspect):cat.refresh(s,fixtures.NOW,fixture.session())
        report=s['discovery43']['last_run'];self.assertEqual(set(report['attempted_groups']),set('ABC'))
        self.assertEqual(report['article_checks'],4);self.assertTrue(all(report['candidate_groups'][g]==1 for g in 'ABC'));self.assertEqual([n for _,n in seen[:3]],[1,1,1])

    def test_failed_family_search_does_not_stop_moscow_and_health(self):
        s=fixtures.state();seen=[]
        def inspect(row,session,**kw):
            seen.append(row['id'])
            if row['id']=='A':raise TimeoutError('Synthetic publisher failure')
            return {'status':'unavailable','article_checks':0},[]
        with patch.object(cat,'registry',return_value=self.core_registry()),patch.object(cat,'inspect_publisher',side_effect=inspect):cat.refresh(s,fixtures.NOW,visual.CatalogTests().session())
        self.assertTrue(set('ABC')<=set(seen));self.assertEqual(set(s['discovery43']['last_run']['missing_candidate_groups']),set('ABC'))

    def test_missing_core_candidates_use_remaining_slots_for_fallback_not_science(self):
        config=self.core_registry();config['publishers']=config['publishers'][:3]
        config['publishers'] += [dict(config['publishers'][0],id='A2'),dict(config['publishers'][2],id='C2')]
        config.update(publishers_per_run=5,article_checks_per_run=8)
        source=visual.CatalogTests().session().fetch('https://example.org/story/9');s=fixtures.state();seen=[]
        def inspect(row,session,**kw):
            seen.append(row['id'])
            if row['id'] in ('A','C'):return {'status':'unavailable','article_checks':1},[]
            title={'A2':'Воспитание ребёнка','B':'История Москвы','C2':'Йога и подвижность'}[row['id']]
            src=dict(source,url='https://example.org/'+row['id'],title=title)
            return {'status':'full_sources_verified','article_checks':1},[({},src)]
        with patch.object(cat,'registry',return_value=config),patch.object(cat,'inspect_publisher',side_effect=inspect):cat.refresh(s,fixtures.NOW,visual.CatalogTests().session())
        self.assertEqual(set(seen),{'A','B','C','A2','C2'})
        report=s['discovery43']['last_run'];self.assertEqual(report['missing_candidate_groups'],[]);self.assertLessEqual(report['article_checks'],8)

    def test_common_english_personal_topic_metadata_is_recognized(self):
        for title,group in [('Family rituals and time together','A'),('Helping kids learn','A'),('Fitness and recovery after a workout','C'),('Heart health and disease prevention','C'),('Подготовка к забегу и марафону','C'),('Пять небоскрёбов у площади Гагарина','B')]:
            self.assertEqual(pr.classify({'title':title})['group'],group,title)

    def test_only_publisher_publication_field_can_fill_missing_date_not_updated(self):
        fixture=visual.CatalogTests();src=fixture.session().fetch('https://example.org/story/9');src['published']=None
        class Session:
            def __init__(self,field):self.field=field
            def transport(self,url):
                if url.endswith('robots.txt'):return 'User-agent: *\nAllow: /'
                if url.endswith('feed.xml'):return '<feed><entry><title>Family activities for kids</title><link href="https://example.org/story/9"/><'+self.field+'>2026-10-26T00:00:00Z</'+self.field+'></entry></feed>'
                return '<html><link rel="alternate" type="application/atom+xml" href="/feed.xml"></html>'
            def fetch(self,url):return copy.deepcopy(src)
        report,rows=cat.inspect_publisher(fixture.registry_row(),Session('published'),now=fixtures.NOW)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0][1]['published'],'2026-10-26T00:00:00Z')
        self.assertEqual(rows[0][1]['publication_date_evidence']['kind'],'publisher_feed')
        report,rows=cat.inspect_publisher(fixture.registry_row(),Session('updated'),now=fixtures.NOW)
        self.assertEqual(rows,[]);self.assertEqual(report['last_article_code'],'PUBLISHER_ACTIVITY_UNCONFIRMED')

    def test_verified_original_context_classifies_an_ambiguous_title(self):
        row=candidate('Интересный маршрут недели',1);row['source'].update(full_text_verified=True,blocks=[{'text':'Велосипедный маршрут длиной 40 км проходит через лес.'}])
        self.assertEqual(pr.classify(row)['group'],'C')

    def test_preparation_reranks_after_a_refusal_instead_of_assuming_planned_coverage(self):
        rows=[candidate('Quantum experiment',0),candidate('Семейный досуг и игры',1),candidate('Семейные занятия с детьми',2)]
        s=fixtures.state();s['candidates']=rows;seen=[]
        for row in rows:row['history']=[]
        class Editor:
            def finish(self,state,row):
                seen.append(row['id']);raise ed.p.Blocked('SYNTHETIC_UNSAFE_SOURCE')
        from unittest.mock import Mock
        budget=SimpleNamespace(deadline=float('inf'),can_request=lambda:True)
        with tempfile.TemporaryDirectory() as temp,patch.object(daily,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(daily,'reserve_rows',return_value=[fixtures.RESERVE_FIXTURE]):
            daily.advance(s,s['date'],False,SimpleNamespace(ROOT=fixtures.root(temp)),now=fixtures.NOW.replace(hour=5),editor=Editor())
        self.assertEqual(seen,['1','2','0']);self.assertEqual(len(seen),len(set(seen)))

    def test_compact_report_counts_main_groups_not_light_news(self):
        s=fixtures.state();rows=[candidate('Семейный досуг',1),candidate('История Москвы',2),candidate('Йога и подвижность',3)]
        s['light43']={'records':[candidate('Воспитание ребёнка',4)]}
        report=pr.report(s,rows,[]);self.assertEqual(report['prepared_main_articles'],3);self.assertEqual(report['core_groups'],dict(A=1,B=1,C=1));self.assertEqual(report['missing_core_groups'],[])

if __name__=='__main__':unittest.main()
