import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
try:
    from news import (render_overview, render_article, count_words, xml_items, page_header, VALID_CATEGORIES, slugify)
except ImportError:
    from scripts.news import (render_overview, render_article, count_words, xml_items, page_header, VALID_CATEGORIES, slugify)

class SmokeTests(unittest.TestCase):
    def test_rss(self):
        items = xml_items(b'<rss><channel><item><title>NASA update</title><link>https://nasa.gov/x</link><pubDate>Thu, 22 Oct 2026 12:00:00 GMT</pubDate><description>Detail</description></item></channel></rss>','NASA')
        self.assertEqual(items[0]['title'],'NASA update')
    def test_escape(self):
        self.assertIn('&lt;',page_header('<bad>', 'safe','/',datetime.now(ZoneInfo('Europe/Moscow')),2))
    def test_words(self):
        self.assertEqual(count_words('Раз два три!'),3)
    def test_pages(self):
        sample={'title':'Примерная газета для тестов','teaser':'Тестовый набор материалов с отдельным текстом и техническими ссылками, он не публикуется на сайте.', 'category':'Семья', 'kind':'очерк','slug':'feature-01','word_count':900,'paragraphs':[{'heading':'','text':'Этот текст создан только для тестовой проверки.'}], 'source_ids':['S001']}
        source={'S001':{'url':'https://example.org','title':'Demo','published':'2026-10-24'}}
        date = datetime(2026,10,25,tzinfo=ZoneInfo('Europe/Moscow'))
        self.assertIn('/issues/2026-10-25/articles/feature-01/',render_overview(date,2,[sample]*8))
        self.assertIn('Источники и проверка',render_article(date,2,sample,source))

if __name__ == '__main__':unittest.main()
