"""Regression tests for segmented source-grounded longform drafting (no API)."""
import unittest
from unittest.mock import patch

try:
    from scripts import editorial31 as ed
except ImportError:
    import editorial31 as ed


class Longform322Tests(unittest.TestCase):
    def setUp(self):
        self.plan={'title':'Почему древний артефакт изменил представления об истории',
                   'category':'История и культура','kind':'очерк','long':True,
                   'source_ids':['S001','S002'], 'editorial_score':24}
        self.dossier={'angle':'Проверенное противоречие',
                      'chronology':'Хронология из документа',
                      'stakes':'Сомнение в гипотезе',
                      'claims':[{'source_id':'S001' if i%2 else 'S002',
                                 'quote':'Подлинный фрагмент источника номер '+str(i)+' про предмет',
                                 'explanation':'Содержательное подтверждение факта '+str(i)}
                                for i in range(9)]}

    def mock_response(self,index,length=425):
        # Simulate a separate shorter (~425-word) model response for each call.
        chunks=[]
        for j in range(4):
            text=' '.join(f'свидетельство{index}_{j}_{n}' for n in range(length//4))
            chunks.append({'heading':f'Секция {index}, фрагмент {j}', 'text':text})
        return {'title':'Разгадка музейной истории и неизвестного древнего артефакта',
                'teaser':' '.join('Факт' for _ in range(42)),
                'paragraphs':chunks}

    def test_three_short_sections_become_one_long_article(self):
        parts=[self.mock_response(i) for i in range(3)]
        with patch.object(ed.news,'gemini',side_effect=parts) as model:
            result=ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(model.call_count,3)
        self.assertEqual(len(result['paragraphs']),12)
        self.assertGreaterEqual(result['word_count'],1050)
        self.assertTrue(result['long'])
        self.assertEqual(result['source_ids'],['S001','S002'])
        self.assertTrue(all(call.kwargs['schema']=='article' for call in model.call_args_list))

    def test_any_short_segment_blocks_article(self):
        parts=[self.mock_response(0),self.mock_response(1,length=120),self.mock_response(2)]
        with patch.object(ed.news,'gemini',side_effect=parts) as model:
            with self.assertRaisesRegex(ValueError,'section 2/3'):
                ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(model.call_count,2)

    def test_unverified_dossier_prevents_any_model_request(self):
        data=dict(self.dossier, claims=self.dossier['claims'][:5])
        with patch.object(ed.news,'gemini') as model:
            with self.assertRaisesRegex(ValueError,'8 verified'):
                ed.write_from_dossier(self.plan,data,'2026-10-26')
        model.assert_not_called()

    def test_no_padding_if_three_sections_insufficient(self):
        parts=[self.mock_response(i,length=332) for i in range(3)]
        with patch.object(ed.news,'gemini',side_effect=parts) as model:
            with self.assertRaisesRegex(ValueError,'1050'):
                ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(model.call_count,3)


if __name__=='__main__':
    unittest.main()
