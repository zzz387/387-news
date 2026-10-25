"""Offline regression tests for family-story discovery; no Gemini requests."""
import unittest
from unittest.mock import patch
try:
    from scripts import editorial31 as e
except ImportError:
    import editorial31 as e


class FamilyDiscoveryTests(unittest.TestCase):
    def test_uses_full_article_pages_not_parenting_homepages(self):
        for _title, url in e.FAMILY_FEATURES:
            self.assertTrue(url.startswith('https://'))
            self.assertNotIn(url.rstrip('/'), e.GENERIC_URLS)
        self.assertGreaterEqual(len(e.FAMILY_FEATURES), 10)

    def test_fetch_keeps_only_real_long_evidence_and_preserves_existing_ids(self):
        sources=[{'id':'S005','title':'Existing science','url':'https://example.org/science',
                  'evidence':'a'*2000,'feed':'Наука'}]
        def fetch(item):
            if 'baby-tips' in item['url']:
                return None
            if 'talk-to-your-teen.html' in item['url']:
                return dict(item,evidence='very short')
            return dict(item,evidence='proof text, observed at runtime. '*65)
        with patch.object(e.news,'fetch_page',side_effect=fetch):
            n=e.extend_family_evidence(sources)
        self.assertEqual(n,len(e.FAMILY_FEATURES)-2)
        self.assertEqual(len(sources),n+1)
        self.assertEqual(sources[-1]['id'],'S005')
        self.assertTrue(all(s['id']!='S005' for s in sources[:-1]))
        self.assertEqual(len({s['id'] for s in sources}),len(sources))
        self.assertTrue(all(s['evergreen'] for s in sources[:-1]))

    def test_repeated_fetch_does_not_duplicate_sources(self):
        sources=[]
        with patch.object(e.news,'fetch_page',side_effect=lambda item: dict(item,evidence='a'*1750)) as mocked:
            n=e.extend_family_evidence(sources)
            n2=e.extend_family_evidence(sources)
        self.assertEqual(n,len(e.FAMILY_FEATURES))
        self.assertEqual(n2,0)
        self.assertEqual(mocked.call_count,len(e.FAMILY_FEATURES))

    def test_strict_targeted_recovery_accepts_only_existing_full_evidence(self):
        family=[{'id':'S020','title':'Child and family relationships',
                  'url':'https://raisingchildren.net.au/specific1','feed':'Семья — экспертный материал',
                  'category_hint':'Семья','recent':False,'evergreen':True,'published':'Вне повестки',
                  'evidence':'Family activities and concrete studies '*95},
                {'id':'S021','title':'Ideas for family outings','url':'https://raisingchildren.net.au/specific2',
                  'feed':'Семья — экспертный материал','category_hint':'Семья',
                  'evergreen':True,'recent':False,'published':'Вне повестки',
                  'evidence':'Family outings and games with children '*95}]
        others=[]
        for i in range(20):
            others.append({'id':f'S{i+1:03d}','title':f'Topic {i}',
                           'url':f'https://science.example.org/{i}','feed':'Наука',
                           'evidence':'Science article with verifiable specifics '*70,
                           'recent':True,'published':'2026-10-24','evergreen':False})
        def candidate(i, cat, ids, long=False):
            return {'title':f'{["Астероиды и изотопы","Экспедиция полярников","Микроскопия грибов","Питание морских китов","Материал древних комет","Гравитационные волны","Генетика медоносных пчёл","История космических станций","Эволюция языков","Архитектура маяков","Странствия перелётных птиц","Климатические явления в лесах","Физика цветовых пигментов","Раскопки древних поселений","Механизм образования облаков"][i] if i<15 else ("Игры с грудничком на ковре" if i==101 else "Как провести вечер с подростком" if i==102 else "Вымышленный источник о детях")}','category':cat,
                    'kind':'очерк', 'source_ids':ids,'hook':'Very specific fact',
                    'why_now':'Evergreen or timed','long':long,'novelty':4,
                    'reader_interest':4,'specificity':5,'evidence':5,'fit':5}
        generic=[candidate(i,'Наука',[f'S{i+1:03d}']) for i in range(15)]
        targeted=[candidate(101,'Семья',['S020']),candidate(102,'Семья',['S021']),
                  candidate(103,'Семья',['S099'])] # fabricated id must be refused
        calls=[]
        def api(prompt, **kwargs):
            calls.append(prompt)
            return {'candidates':generic if len(calls)==1 else targeted}
        with patch.object(e.news,'gemini',side_effect=api),patch.object(e.news,'previous_titles',return_value=[]):
            selected=e.shortlist(family+others,'2026-10-26')
        self.assertEqual(len(calls),2)
        family_items=[q for q in selected if q['category']=='Семья']
        self.assertEqual(len(family_items),2)
        self.assertTrue(all(q['source_ids'][0] in {'S020','S021'} for q in family_items))


if __name__=='__main__':
    unittest.main()
