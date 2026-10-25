"""Reader-approved editorial v3.2 longform priority regression checks.
No network, publication, or credentials are used.
"""
import unittest
from unittest.mock import patch
try:
    from scripts import editorial31 as e
except ImportError:
    import editorial31 as e

APPROVED={1,2,3,6,7,8,9,10,11,12,13,14,15,16,17,18,21,22,23,24}


def candidate(topic, category, i=0, evidence_chars=6500, source_id=None):
    source_id=source_id or f'S{i+1:03d}'
    c={'title':f'Оригинальная проверяемая история номер {i+1}',
       'category':category,'kind':'очерк','source_ids':[source_id],
       'hook':'Необычная подробно доказанная история','why_now':'вне текущей повестки',
       'long':False,'long_topic_id':topic,
       'novelty':5,'reader_interest':5,'specificity':5,'evidence':5,'fit':5,'score':25}
    s={'id':source_id,'url':f'https://original{i}.org/long-story',
       'evidence':('Документально подтверждённый фактический материал. '*150)[:evidence_chars],
       'title':c['title'],'abstract_only':False}
    return c,s


class ApprovedLongformPolicyTests(unittest.TestCase):
    def test_exact_user_topic_selection(self):
        self.assertEqual(set(e.LONGFORM_TOPICS),APPROVED)
        self.assertEqual(len(e.LONGFORM_TOPICS),20)
        for i in (9,10,11,15,16,21): self.assertIn(i,e.LONGFORM_TOPICS)
        self.assertNotIn(19,e.LONGFORM_TOPICS)

    def test_removed_topic_not_priority_even_if_model_calls_it_priority(self):
        self.assertEqual(e.normalized_topic_id({'long_topic_id':19,'category':'История и культура'}),0)
        self.assertEqual(e.normalized_topic_id({'long_topic_id':21,'category':'История и культура'}),21)
        self.assertEqual(e.normalized_topic_id({'long_topic_id':9,'category':'Наука'}),0)

    def test_all_six_new_topics_match_legitimate_categories(self):
        for tid, category in ((9,'Москва и путешествия'),(10,'История и культура'),
                              (11,'Москва и путешествия'),(15,'Здоровье и движение'),
                              (16,'Наука'),(21,'История и культура')):
            self.assertEqual(e.normalized_topic_id({'long_topic_id':tid,'category':category}),tid)

    def test_staged_commission_does_not_require_model_long_true(self):
        first, a=candidate(9,'Москва и путешествия',0)
        second,b=candidate(21,'История и культура',1)
        third,c=candidate(19,'История и культура',2)
        pool=e.commission_evidence_backed_longforms([first,second,third],[a,b,c])
        self.assertTrue(pool[0]['long'])
        self.assertTrue(pool[1]['long'])
        self.assertEqual(pool[2]['long_topic_id'],0)
        self.assertFalse(any(x.get('long_topic_id')==19 for x in pool))

    def test_insufficient_evidence_never_becomes_big_feature(self):
        item, source=candidate(16,'Здоровье и движение',0,evidence_chars=1600)
        item['long']=True
        out=e.commission_evidence_backed_longforms([item],[source])
        self.assertFalse(out[0]['long'])

    def test_prompt_mentions_all_priority_topics_but_not_removed_books(self):
        src=[{'id':f'S{i:03d}','url':f'https://source{i}.org/',
              'evidence':'Существенные факты. '*200,
              'title':f'Источник {i}', 'feed':'История', 'published':'Вне новостной повестки'} for i in range(25)]
        seen=[]
        def capture(prompt,**kwargs):
            seen.append(prompt)
            return {'candidates':[]}
        with patch.object(e.news,'gemini',side_effect=capture), \
             patch.object(e.news,'previous_titles',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'refuse to pad'):
                e.shortlist(src,'2026-10-26')
        self.assertIn('9. История Москвы',seen[0])
        self.assertIn('21. Христианская история и философия',seen[0])
        self.assertNotIn('19. Литература',seen[0])

if __name__=='__main__':unittest.main()
