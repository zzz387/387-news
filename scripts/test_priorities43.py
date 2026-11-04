"""Personal interests affect search and selection, never the release gates."""
import copy,json,tempfile,unittest
from datetime import timedelta
from unittest.mock import patch
from scripts import priorities43 as interests,selection43 as selection,catalog43 as catalog,publication43,policy41 as p
from scripts import test_editorial_visual43 as fixtures
named=fixtures.named
from scripts.test_daily43 import state,root,NOW,RESERVE_FIXTURE


def sample():
    titles=['Квантовая фаза сверхпроводника','Нейтрино под землёй','Сверхновая в галактике','Новая комета у Солнца','Космическое излучение','Электрон в ловушке','Гравитационный парадокс','Спектр далёкого квазара','Спин частицы','Атомный переход']
    titles+=['Воспитание без спешки','Возрастная психология ребёнка','Семейный досуг за столом','Супружеские отношения и поддержка','Семейные традиции осенью']
    titles+=['Археологическая находка у реки','Биография художника','Музей необычной коллекции','Христианская история монастыря','Архитектура городской библиотеки']
    titles+=['Московские усадьбы и дворцы','Необычные места Москвы','Поездки выходного дня','История Москвы: старые улицы']
    titles+=['Кардиотренировки и физиология','Велосипедный маршрут 40 километров','Йога и подвижность']
    titles+=['Банкротство физических лиц','Экономика повседневной жизни','Инженерия промышленной печати']
    return [named(title,i,'discovered') for i,title in enumerate(titles)]

class InterestsTests(unittest.TestCase):
    def test_twenty_original_directions_and_no_compulsory_literature(self):
        expected={1,2,3,6,7,8,9,10,11,12,13,14,15,16,17,18,21,22,23,24}
        self.assertEqual(set(interests.DIRECTIONS),expected)
        for i,d in interests.DIRECTIONS.items():
            self.assertIn(i,{interests.classify({'title':d['name']})['direction'],*interests.classify({'title':d['name']})['additional_directions']},d['name'])
        self.assertFalse(interests.classify({'title':'История книг и чтения'})['direction'])

    def test_thirty_story_pool_prefers_nine_personal_stories_with_diverse_groups(self):
        s=state();s['candidates']=sample();chosen=selection.order(s)[:12]
        personal=[r for r in chosen if interests.classify(r)['direction']]
        self.assertEqual(len(personal),9)
        self.assertGreaterEqual(len({interests.classify(r)['group'] for r in personal}),4)
        self.assertLessEqual(sum(not interests.classify(r)['direction'] for r in chosen),4)

    def test_missing_direction_receives_compensation_and_old_history_expires(self):
        family=named('Семейный досуг за столом');family['date']=NOW.date().isoformat()
        architect=named('Архитектура библиотеки',2)
        self.assertEqual(interests.evaluate(architect,[family],NOW.date().isoformat())['weekly_compensation'],12)
        self.assertEqual(interests.evaluate(family,[family],NOW.date().isoformat())['weekly_compensation'],0)
        family['date']=(NOW-timedelta(days=10)).date().isoformat()
        self.assertEqual(interests.evaluate(family,[family],NOW.date().isoformat())['weekly_compensation'],12)

    def test_publisher_search_compensates_missing_topics_even_with_different_cache_ages(self):
        family={'id':'family','priority_ids':[1],'editorial_priority':90}
        bike={'id':'bike','priority_ids':[14],'editorial_priority':90}
        history=[{'title':'Воспитание ребёнка','date':NOW.date().isoformat()}]
        cache={'publishers':{'family':{'checked_at':'2026-10-20'},'bike':{'checked_at':'2026-10-21'}}}
        self.assertEqual(interests.publisher_order([family,bike],cache,history,NOW.date().isoformat())[0]['id'],'bike')

    def test_all_directions_have_catalogue_coverage_without_duplicate_publishers(self):
        rows=catalog.registry()['publishers'];self.assertEqual(len({(r['domain'].removeprefix('www.'),r['homepage'].rstrip('/')) for r in rows}),len(rows))
        for i in interests.DIRECTIONS:self.assertTrue(any(i in r.get('priority_ids',[]) for r in rows),i)
        for r in rows:
            if r['enabled']:self.assertEqual(r['availability']['status'],'verified')

    def test_activation_uses_live_discovery_proof_not_publisher_reputation(self):
        config=catalog.registry();row=fixtures.CatalogTests().registry_row();config['publishers']=[row]
        bad={'checked_at':NOW.isoformat(),'publishers':[{'publisher':row['id'],'status':'unavailable','discovered':0,'code':403}]}
        self.assertFalse(catalog.apply_verification(config,bad)['publishers'][0]['enabled'])
        good={'checked_at':NOW.isoformat(),'publishers':[{'publisher':row['id'],'status':'discovery_verified','discovered':3,'eligible':0}]}
        activated=catalog.apply_verification(config,good)['publishers'][0]
        self.assertTrue(activated['enabled']);self.assertEqual(activated['availability']['scope'],'public_discovery_only');self.assertEqual(activated['availability']['full_originals_verified'],0)

    def test_unverified_publisher_is_not_activated_by_convenient_rss(self):
        config=catalog.registry();row=fixtures.CatalogTests().registry_row();row['availability']={'status':'unverified'};config['publishers']=[row]
        with patch.object(catalog,'registry',return_value=config),patch.object(catalog,'inspect_publisher',side_effect=AssertionError('Unverified publisher')):
            catalog.refresh(state(),NOW)

    def test_archival_history_keeps_true_date_but_future_date_remains_blocked(self):
        fixture=fixtures.CatalogTests();session=fixture.session();original=session.fetch
        session.fetch=lambda url:dict(original(url),published='2000-01-01')
        report,items=catalog.inspect_publisher(dict(fixture.registry_row(),allow_archive=True),session,now=NOW)
        self.assertEqual(len(items),1);self.assertEqual(items[0][1]['published'],'2000-01-01')

    def test_general_science_remains_available_when_priority_stories_are_missing(self):
        s=state();s['candidates']=sample()[:10]
        self.assertEqual(len(selection.order(s)),10)

    def test_accepted_article_is_resumed_before_starting_another_story(self):
        s=state();s['candidates']=[named('Семейный досуг',1,'discovered'),named('Квантовая фаза',2,'preparing')]
        self.assertEqual(selection.order(s)[0]['status'],'preparing')

    def test_cited_evidence_uses_existing_trusted_links_and_never_guesses_urls(self):
        row=named('Воспитание без спешки');row['source']['blocks'][0]['links']=['https://www.unicef.org/parenting/real-reference','https://untrusted.example/claim']
        self.assertEqual(interests.cited_verification_urls(row),['https://www.unicef.org/parenting/real-reference'])
        row['source']['blocks'][0]['links']=[];self.assertEqual(interests.cited_verification_urls(row),[])
        row['supporting_sources']=[{'url':'https://one.example/'},{'url':'https://two.example/'}]
        before=copy.deepcopy(row['supporting_sources'])
        interests.attach_evidence(row,state());interests.attach_evidence(row,state())
        self.assertEqual(row['supporting_sources'],before)

    def test_actual_cosmic_word_and_supernova_are_detected(self):
        self.assertTrue(selection.profile({'title':'Космический сюжет'})['space'])
        self.assertTrue(selection.profile({'title':'Сверхновая в соседней галактике'})['space'])

    def test_private_composition_report_is_advisory_and_not_exported(self):
        s=state(1);s['editorial_report43']=interests.report(s,s['candidates'],[])
        self.assertTrue(s['editorial_report43']['advisory_only']);self.assertIsNone(s['editorial_report43']['published_main_articles'])
        with tempfile.TemporaryDirectory() as directory:
            target=root(directory);publication43.build(s,target)
            self.assertEqual(publication43.validate(target,s['date'])['article_count'],1)
            self.assertNotIn('missing_week',(target/'index.html').read_text());self.assertNotIn('editorial_report43',json.dumps(publication43.metadata(target,s['date'])))

    def test_report_does_not_call_prepared_stories_published_weekly_coverage(self):
        s=state();r=named('Воспитание ребёнка');report=interests.report(s,[r],[])
        self.assertIn(1,report['missing_week']);self.assertNotIn(1,report['missing_after_prepared'])

    def test_cycling_20_to_60_km_is_a_preference_not_a_distance_requirement(self):
        short=named('Велосипедный маршрут 40 км');long=named('Велосипедный маршрут 150 км',2)
        self.assertGreater(interests.evaluate(short)['usefulness'],interests.evaluate(long)['usefulness'])
        s=state();long['status']='discovered';s['candidates']=[long];self.assertEqual(len(selection.order(s)),1)

    def test_explicit_advertorial_is_removed_without_blocking_real_economic_reporting(self):
        self.assertTrue(catalog.advertising_story({'title':'Sponsored: shop now for new furniture'}))
        self.assertFalse(catalog.advertising_story({'title':'Sale of assets in a bankruptcy case'}))

    def test_machine_learning_architecture_and_training_do_not_impersonate_family_or_cardio(self):
        row={'title':'Machine learning: training the model and neural network architecture'}
        c=interests.classify(row);self.assertNotIn(c['direction'],(1,11,13))
        child=interests.classify({'title':'Machine learning tools in child education'})
        self.assertEqual(child['direction'],1)
        self.assertEqual(interests.classify({'title':'Learning in wild birds'})['direction'],22)
        self.assertNotEqual(interests.classify({'title':'Обучение нейросетевой модели'})['direction'],1)

    def test_no_topic_minimum_blocks_zero_one_or_twelve_articles(self):
        for count in [0,1,12]:
            with tempfile.TemporaryDirectory() as directory:
                s=state(count);target=root(directory);publication43.build(s,target,[RESERVE_FIXTURE])
                self.assertEqual(publication43.validate(target,s['date'])['article_count'],count)

if __name__=='__main__':unittest.main()
