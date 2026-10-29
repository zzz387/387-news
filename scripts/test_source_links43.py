"""No live API calls: source-language presentation and nonblocking target12."""
import copy,json,os,re,tempfile,unittest
from html import unescape
from types import SimpleNamespace
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlsplit
from scripts import source_links43 as links,publication41 as old,publication43 as pub,editorial43 as e,daily43 as daily,policy41 as p,news,production_preflight41 as preflight
from scripts.test_daily43 import ready,state,root,NOW
from scripts.test_policy41 import source

class SourceLinks43Tests(unittest.TestCase):
    def article(self,language='en',url='https://example.org/full?one=1&two=2'):
        a=pub.public_article(ready());a['attribution']={};a['primary_source'].update(language=language,url=url,title='Original <title> & "name"',publisher='Publisher & Co')
        return a

    def test_languages_and_unknown_preserve_one_original_and_one_translation(self):
        for code,label in [('ru','русский'),('EN-us','английский'),('de_DE','немецкий'),('fr','французский'),('es','испанский'),('it','итальянский'),('zh-Hans','китайский'),('ja','японский'),('sv','шведский'),(None,'язык не определён'),('made-up','язык не определён')]:
            with self.subTest(code=code):
                a=self.article(code);html=old.source_block(a);md=old.markdown(a)
                self.assertTrue(links.validate(html,required=True));self.assertIn('('+label+'):',html);self.assertIn('('+label+'):',md)
                self.assertIn('Original &lt;title&gt; &amp; &quot;name&quot;',html);self.assertIn('target="_blank"',html)
                self.assertEqual(html.count('class="source-original"'),1);self.assertEqual(html.count('class="source-translation"'),0 if code=='ru' else 1)
                if code!='ru':
                    params=parse_qs(urlsplit(links.translation_url(a['primary_source']['url'],code,provider='yandex')).query)
                    self.assertEqual(params['lang'],[links.language_code(code)+'-ru' if links.language_code(code) else 'ru'])
                else:self.assertNotIn('translate.yandex',md)

    def test_confirmed_fallback_has_correct_label_and_source_direction(self):
        self.assertEqual(links.DEFAULT_PROVIDER,'google')
        for language in ('en','de','fr',None):
            url='https://example.org/original?x=1&y=2'
            args=parse_qs(urlsplit(links.translation_url(url,language)).query)
            self.assertEqual(args,{'sl':[language or 'auto'],'tl':['ru'],'u':[url]})
            html=old.source_block(self.article(language,url))
            self.assertIn('Google Переводчике',html);self.assertNotIn('Яндекс Переводчике',html)

    def test_archive_links_validate_even_if_future_preferred_provider_changes(self):
        html=old.source_block(self.article('en'))
        with patch.object(links,'DEFAULT_PROVIDER','yandex'):
            self.assertTrue(links.validate(html))
            yandex=old.source_block(self.article('en'));self.assertIn('Яндекс Переводчике',yandex)
        self.assertTrue(links.validate(yandex))

    def test_other_public_reference_and_license_links_have_safe_new_tabs(self):
        a=self.article('en');a['public_references']=[{'url':'https://example.org/support','publisher':'Supporting publisher','title':'Original support'}]
        a['attribution']={'author':'Author','license':'CC BY4.0','license_url':'https://creativecommons.org/licenses/by/4.0/'}
        for anchor in re.findall(r'<a\b[^>]+>',old.source_block(a)):
            self.assertIn('target="_blank"',anchor);self.assertIn('noopener',anchor);self.assertIn('noreferrer',anchor)

    def test_missing_historical_language_is_never_assumed_english(self):
        a=self.article();a['primary_source'].pop('language');html=old.source_block(a)
        self.assertIn('(язык не определён)',html);self.assertIn('sl=auto',unescape(html));self.assertNotIn('sl=en',html)
        self.assertFalse(links.validate('<aside class="source-primary">Historical source</aside>'))
        with self.assertRaisesRegex(p.Blocked,'SOURCE_LINKS_REQUIRED'):links.validate('historical',required=True)

    def test_preserves_unicode_queries_fragments_and_literal_parameter_separators(self):
        url='https://пример.рф/наука/(статья)?x=один&x=два&next=%2Fpage%3Fa%3D1#раздел'
        actual=links.translation_url(url,'en',provider='yandex');self.assertEqual(parse_qs(urlsplit(actual).query)['url'],[url])
        html=old.source_block(self.article('en',url));self.assertIn('&amp;tl=ru',html)
        self.assertTrue(links.validate(html));self.assertIn('%28',old.markdown(self.article('en',url)))
        example='https://www.unicef.org/parenting/child-care/21-learning-activities-babies-and-toddlers'
        self.assertEqual(links.translation_url(example,'en',provider='yandex'),'https://translate.yandex.ru/translate?url=https%3A%2F%2Fwww.unicef.org%2Fparenting%2Fchild-care%2F21-learning-activities-babies-and-toddlers&lang=en-ru')

    def test_unsafe_original_never_reaches_either_link(self):
        for url in ['javascript:alert(1)','http://example.org/','data:text/html,test','https://user:pass@example.org/','https://127.0.0.1/','https://localhost/','https://example.org/\npath','https://example.org:bad/','https://example.org/a b']:
            with self.subTest(url=url):
                with self.assertRaises(p.Blocked):links.translation_url(url,'en')
                with self.assertRaises(p.Blocked):old.source_block(self.article('en',url))

    def test_links_use_verified_metadata_not_text_and_have_no_provider_dependency(self):
        a=self.article('en');a['blocks'][0]['text']='A malicious untrusted javascript: value cannot become a source URL.'
        with patch.object(news,'gemini',side_effect=AssertionError('No model call')),patch('urllib.request.urlopen',side_effect=AssertionError('No translator fetch')):
            html=old.source_block(a)
        self.assertNotIn('javascript:',html);self.assertIn('example.org',html)
        with self.assertRaisesRegex(p.Blocked,'TRANSLATION_SOURCE_MISMATCH'):links.validate(html.replace('tl=ru','tl=de'))
        with self.assertRaisesRegex(p.Blocked,'SOURCE_LINK_SECURITY'):links.validate(html.replace('noopener noreferrer','noopener'))

    def test_public_projection_preserves_actual_source_language_and_body(self):
        r=ready();r['source']['language']='de-DE';before=copy.deepcopy(r['article'])
        a=pub.public_article(r);self.assertEqual(a['primary_source']['language'],'de-DE');self.assertEqual(a['blocks'],before['blocks'])
        self.assertEqual(r['article'],before)
        for mode,prefix in [('FULL_TRANSLATION','Перевод.'),('INDEPENDENT_ARTICLE','Самостоятельная статья на основе материалов.')]:
            a['mode']=mode;self.assertIn(prefix,old.source_block(a));self.assertIn(prefix,old.markdown(a))

class TargetTwelve43Tests(unittest.TestCase):
    def test_real_config_and_preflight_use_twelve_without_changing_free_quota(self):
        self.assertEqual(e.CONFIG['article_target'],12);self.assertEqual(e.CONFIG['minimum_articles'],1)
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'zzz387/387-news','GITHUB_REF_NAME':'main','NEWS_POLICY_VERSION':'4.3','DRAFT_ENCRYPTION_KEY':'x'*44,'NEWS_AUTOMATION_V31_ENABLED':'true','NEWS_RELEASE_APPROVED':'true'}
        with patch.object(preflight.stage,'validate_key',return_value=b'x'*32):self.assertEqual(preflight.check(env)['article_target'],12)
        text=(p.ROOT/'.github/workflows/daily-v31.yml').read_text();self.assertIn('NEWS_MAX_REQUESTS_PER_RUN: "24"',text);self.assertIn('NEWS_MAX_REQUESTS_PER_DAY: "220"',text)

    def test_restored_eight_accepted_articles_extend_to_twelve_without_reprocessing_them(self):
        s=state(8);accepted=copy.deepcopy(s['candidates'])
        for i in range(8,15):
            row=ready(i);row['status']='discovered';s['candidates'].append(row)
        editor=Mock();editor.finish.side_effect=lambda state,row:row.update(status='ready')
        with tempfile.TemporaryDirectory() as temp,patch.object(daily,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True)):
            target=root(temp);daily.advance(s,s['date'],False,SimpleNamespace(ROOT=target),now=NOW.replace(hour=5,minute=0),editor=editor)
        self.assertEqual(editor.finish.call_count,4);self.assertEqual(len(e.select_ready(s)),12);self.assertEqual(s['candidates'][:8],accepted)
        self.assertFalse(any(r['id'] in {a['id'] for a in accepted} for _,r in (call.args for call in editor.finish.call_args_list)))

    def test_no_quota_or_failed_candidate_still_publishes_ten_when_due(self):
        s=state(10);s['candidates'].append(dict(id='waiting',status='preparing',url='https://example.org/waiting',progress={},checks={}))
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_RELEASE_APPROVED='true',GITHUB_REF_NAME='main'):
            target=root(temp);editor=Mock();editor.finish.side_effect=AssertionError('Delivery first')
            daily.advance(s,s['date'],False,SimpleNamespace(ROOT=target),now=NOW,editor=editor)
            self.assertEqual(pub.validate(target,s['date'])['article_count'],10);editor.finish.assert_not_called()

    def test_soft_diversity_preserves_saved_work_and_has_no_mandatory_categories(self):
        s=state(1);s['candidates'][0]['category_hint']='A'
        for i,category in enumerate(['A','A','B','C','B'],10):
            r=ready(i);r.update(status='discovered',category_hint=category);s['candidates'].append(r)
        saved=ready(30);saved.update(status='preparing',category_hint='A');s['candidates'].append(saved)
        order=daily.preparation_order(s);self.assertIs(order[0],saved)
        self.assertEqual([r['category_hint'] for r in order[1:3]],['B','C'])
        self.assertEqual(len(order),6);self.assertEqual(len({r['id'] for r in order}),6)

    def test_next_release_never_modifies_issue005_or_its_archive_row(self):
        with tempfile.TemporaryDirectory() as temp:
            import shutil
            target=root(temp);shutil.copytree(p.ROOT/'issues/2026-10-29',target/'issues/2026-10-29')
            shutil.copyfile(p.ROOT/'archive/index.html',target/'archive/index.html')
            archive_row=next(row for row in (target/'archive/index.html').read_text().split('<div class="archive-card">') if '/issues/2026-10-29/' in row).split('<div class="archive-card">')[0]
            before={str(f.relative_to(target)):f.read_bytes() for f in (target/'issues/2026-10-29').rglob('*') if f.is_file()}
            s=state(12);s['date']='2026-10-30';pub.build(s,target)
            self.assertEqual(before,{str(f.relative_to(target)):f.read_bytes() for f in (target/'issues/2026-10-29').rglob('*') if f.is_file()})
            self.assertEqual(json.loads((target/'issues/2026-10-29/release.json').read_text())['number'],5)
            self.assertIn(archive_row,(target/'archive/index.html').read_text())
            self.assertTrue(pub.validate(target,'2026-10-29'));self.assertEqual(pub.validate(target,s['date'])['source_links_version'],1)

class HistoricalSpecialLinksTests(unittest.TestCase):
    def test_new_footer_never_silently_rewrites_an_existing_special_issue(self):
        import shutil
        from scripts import special_publication41 as special
        from scripts.test_special43 import ready_issue
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);shutil.copytree(p.ROOT/'issues',target/'issues')
            shutil.copyfile(p.ROOT/'index.html',target/'index.html')
            before={str(f.relative_to(target)):f.read_bytes() for f in (target/'issues/2026-10-26-v41').rglob('*') if f.is_file()}
            with self.assertRaisesRegex(p.Blocked,'SPECIAL_IMMUTABLE_ARCHIVE_CHANGED'):special.build(ready_issue(),target)
            self.assertEqual(before,{str(f.relative_to(target)):f.read_bytes() for f in (target/'issues/2026-10-26-v41').rglob('*') if f.is_file()})


if __name__=='__main__':unittest.main()
