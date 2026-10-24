import unittest
from unittest.mock import patch
try:
    import news
except ImportError:
    from scripts import news

class MinimumLengthTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'title':'Длинное название материала для редакционного теста',
                     'category':'Наука','kind':'очерк','source_ids':['S001'],'long':True}
        self.sources = {'S001':{'id':'S001','title':'Источник','url':'https://example.org/source',
                                'published':'2026-10-24','evidence':'Только проверяемые данные. ' * 70}}
        self.teaser = 'Проверяемое содержательное описание тестовой статьи. ' * 3
    def make(self, characters):
        # Seven non-empty paragraphs, enough metadata and a consistent source.
        texts = ['А' * characters] + ['Доказательный поясняющий абзац.' for _ in range(6)]
        return {'title':'Материал для проверки новой длины','teaser':self.teaser,
                'paragraphs':[{'heading':'','text':t} for t in texts]}
    def test_542_words_will_pass_long_article(self):
        # Before this patch it failed at 542 < 780 words.
        words=['описание'] * 542
        segments=[' '.join(words[i::7]) for i in range(7)]
        result={'title':'Материал для проверки новой длины','teaser':self.teaser,
                'paragraphs':[{'heading':'','text':t} for t in segments]}
        with patch.object(news,'gemini',return_value=result):
            a=news.write_article(self.plan,self.sources,'2026-10-24')
        self.assertEqual(a['word_count'],542)
        self.assertGreaterEqual(a['character_count'],580)
    def test_accept_580_characters(self):
        # Inter-paragraph spaces are included just as in the writer's text.
        data=self.make(580-6*len('Доказательный поясняющий абзац.')-6)
        with patch.object(news,'gemini',return_value=data):
            a=news.write_article(self.plan,self.sources,'2026-10-24')
        self.assertEqual(a['character_count'],580)
    def test_reject_579_characters(self):
        data=self.make(579-6*len('Доказательный поясняющий абзац.')-6)
        with patch.object(news,'gemini',return_value=data):
            with self.assertRaisesRegex(RuntimeError,'579 < 580 characters'):
                news.write_article(self.plan,self.sources,'2026-10-24')
    def test_issue_accepts_8_short_but_sourced_articles(self):
        articles=[]
        for i in range(8):
            text='Р' * 580
            articles.append({'title':f'Неповторяющийся содержательный заголовок статьи номер {i}',
                             'long':i<2,'word_count':1,'character_count':580,
                             'source_ids':['S001'], 'paragraphs':[{'text':text}]})
        with patch.object(news,'gemini',return_value={'ok':True,'reasons':[]}):
            self.assertEqual(news.editorial_audit(articles,list(self.sources.values())),8)

if __name__=='__main__':
    unittest.main()
