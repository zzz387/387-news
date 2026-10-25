"""Regression tests for 387 News 3.2.3 longform checkpointing (zero API calls)."""
import unittest
from unittest.mock import patch

try:
    from scripts import editorial31 as ed
except ImportError:
    import editorial31 as ed


class Longform323Tests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            'title':'Почему древний артефакт изменил представления об истории',
            'category':'История и культура','kind':'очерк','long':True,
            'source_ids':['S001','S002'], 'editorial_score':24,
        }
        self.dossier = {
            'angle':'Проверенное противоречие',
            'chronology':'Хронология из документа',
            'stakes':'Сомнение в гипотезе',
            'claims':[{'source_id':'S001' if i % 2 else 'S002',
                       'quote':'Подлинный фрагмент источника номер '+str(i)+' про предмет',
                       'explanation':'Содержательное подтверждение факта '+str(i)}
                      for i in range(10)],
        }

    def response(self, index, length=150):
        # Natural ~150-word body, not a 400-word model mock. Distinct per section.
        head = 'Археологическая загадка: новые факты и проверенные свидетельства'
        words = [f'факт{index}абзац{j}слово{k}' for j in range(3)
                 for k in range(length // 3)]
        ps = [{'heading':f'Раздел {index}.{j}',
               'text':' '.join(words[j * (length//3):(j+1) * (length//3)])}
              for j in range(3)]
        return {'title':head, 'teaser':' '.join(['Конкретный']*34),
                'paragraphs':ps}

    def test_150_word_segments_can_make_longform(self):
        responses = [self.response(i) for i in range(8)]
        with patch.object(ed.news, 'gemini', side_effect=responses) as m:
            result = ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(m.call_count,8)
        self.assertGreaterEqual(result['word_count'],1050)
        self.assertEqual(len(self.dossier['_longform_progress']['parts']),8)
        self.assertEqual(len(result['paragraphs']),24)

    def test_small_sections_resume_without_redrafting_accepted(self):
        with patch.object(ed.news,'gemini',side_effect=[self.response(0,185),self.response(1,60)]) as m:
            with self.assertRaisesRegex(ValueError,'segment 2'):
                ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(m.call_count,2)
        self.assertEqual(len(self.dossier['_longform_progress']['parts']),1)
        # Same dossier as persisted in encrypted checkpoint in a later run.
        with patch.object(ed.news,'gemini',side_effect=[self.response(i,185) for i in range(1,8)]) as m:
            result = ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(m.call_count,7)
        self.assertGreaterEqual(result['word_count'],1050)

    def test_extra_sections_if_eight_are_short(self):
        with patch.object(ed.news,'gemini',side_effect=[self.response(i,105) for i in range(10)]) as m:
            result=ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(m.call_count,10)
        self.assertGreaterEqual(result['word_count'],1050)

    def test_below_supported_minimum_never_padded(self):
        with patch.object(ed.news,'gemini',return_value=self.response(0,75)) as m:
            with self.assertRaisesRegex(ValueError,'requires 105'):
                ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(m.call_count,1)
        self.assertEqual(self.dossier['_longform_progress']['parts'],[])

    def test_not_enough_verified_claims_blocks_any_call(self):
        dossier=dict(self.dossier, claims=self.dossier['claims'][:6])
        with patch.object(ed.news,'gemini') as m:
            with self.assertRaisesRegex(ValueError,'8 verified'):
                ed.write_from_dossier(self.plan,dossier,'2026-10-26')
        m.assert_not_called()

    def test_identical_paragraphs_not_accepted(self):
        with patch.object(ed.news,'gemini',side_effect=[self.response(0),self.response(0)]) as m:
            with self.assertRaisesRegex(ValueError,'repeats'):
                ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        self.assertEqual(m.call_count,2)
        self.assertEqual(len(self.dossier['_longform_progress']['parts']),1)

    def test_changed_story_invalidates_cached_sections(self):
        with patch.object(ed.news,'gemini',side_effect=[self.response(0),self.response(1,60)]):
            with self.assertRaises(ValueError):
                ed.write_from_dossier(self.plan,self.dossier,'2026-10-26')
        changed=dict(self.plan,title='Другая документированная история')
        with patch.object(ed.news,'gemini',side_effect=[self.response(9),self.response(10,60)]) as m:
            with self.assertRaises(ValueError):
                ed.write_from_dossier(changed,self.dossier,'2026-10-26')
        self.assertEqual(m.call_count,2)
        self.assertEqual(self.dossier['_longform_progress']['parts'][0]['paragraphs'][0]['heading'],'Раздел 9.0')


if __name__=='__main__':
    unittest.main()
