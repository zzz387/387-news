import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    from scripts import publication as pub, site_checks as check
except ImportError:
    import publication as pub
    import site_checks as check

class PublicSiteTests(unittest.TestCase):
    def test_public_projection_excludes_private_dossiers_and_nested_context(self):
        state={'date':'2026-10-26','articles':{},'sources':[{'id':'S1','url':'https://example.org/fact','title':'Public document','published':'2026','evidence':'PRIVATE-RESEARCH'}], 'dossiers':{'secret':'PRIVATE-DOSSIER'}}
        for i in range(8):
            state['articles'][str(i)]={'title':f'Final article {i}','teaser':'Final approved teaser','source_ids':['S1'],
                'category':'Семья','kind':'очерк','word_count':560,
                'paragraphs':[{'heading':'Public heading','text':'Final approved paragraph','_private':'PRIVATE-NESTED'}],
                '_editorial_context':'PRIVATE-PROFILE'}
        result=pub.public_issue(state,2)
        self.assertNotIn('PRIVATE-',json.dumps(result))
        self.assertNotIn('PRIVATE-',pub.markdown(result))
        self.assertEqual(len(result['articles']),8)
        self.assertEqual(result['sources']['S1']['url'],'https://example.org/fact')

    def test_package_excludes_repository_and_working_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'source'; root.mkdir()
            (root/'index.html').write_text('<html>Public homepage</html>')
            (root/'.git').mkdir(); (root/'.git/config').write_text('Do not copy credentials')
            (root/'scripts').mkdir(); (root/'scripts/private.py').write_text('Do not serve internal code')
            destination=check.package(root,Path(directory)/'public')
            self.assertTrue((destination/'index.html').exists())
            self.assertFalse((destination/'.git').exists())
            self.assertFalse((destination/'scripts').exists())

    def test_package_refuses_encrypted_drafts_inside_public_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'source'; (root/'issues').mkdir(parents=True)
            (root/'issues/news-draft.enc').write_bytes(b'not-a-real-private-draft')
            with self.assertRaises(RuntimeError): check.package(root,Path(directory)/'public')

    def website(self):
        date='2026-10-26'
        data={'date':date,'articles':[]}
        pages={'https://387.su/': '', 'https://387.su/archive/':'Archive',f'https://387.su/issues/{date}/':'Overview'}
        for i in range(8):
            slug=f'article-{i}'
            body=' '.join(f'word{j}' for j in range(1100 if i<2 else 560))
            data['articles'].append({'slug':slug,'long':i<2,'word_count':check.news.count_words(body)})
            path=f'/issues/{date}/articles/{slug}/'
            pages['https://387.su/']+=f'<a href="{path}">Article</a>'
            pages['https://387.su'+path]='<meta name="viewport"><div class="article-body"><p>'+body+'</p></div>'
        pages[f'https://387.su/issues/{date}/issue.json']=json.dumps(data)
        return pages

    def test_https_monitor_checks_all_eight_complete_articles(self):
        pages=self.website()
        with patch.object(check,'fetch',side_effect=pages.__getitem__) as request:
            result=check.check_site(expected_date='2026-10-26')
        self.assertEqual(result['articles'],8)
        self.assertEqual(request.call_count,12)

    def test_monitor_accepts_existing_relative_article_links(self):
        pages=self.website()
        pages['https://387.su/']=pages['https://387.su/'].replace('href="/issues/','href="issues/')
        with patch.object(check,'fetch',side_effect=pages.__getitem__):
            self.assertEqual(check.check_site()['articles'],8)

    def test_https_monitor_refuses_stale_or_truncated_issue(self):
        pages=self.website()
        with patch.object(check,'fetch',side_effect=pages.__getitem__):
            with self.assertRaisesRegex(RuntimeError,'still shows'): check.check_site(expected_date='2026-10-27')
        pages['https://387.su/issues/2026-10-26/articles/article-0/']='<meta name="viewport"><div class="article-body"><p>Truncated</p></div>'
        with patch.object(check,'fetch',side_effect=pages.__getitem__):
            with self.assertRaisesRegex(RuntimeError,'truncated'): check.check_site(expected_date='2026-10-26')
        with self.assertRaisesRegex(RuntimeError,'HTTPS'): check.check_site('http://387.su')

class DeploymentRetryTests(unittest.TestCase):
    def test_retry_does_not_rewrite_archive_and_refuses_changed_draft(self):
        import copy
        import shutil
        from datetime import datetime
        try:
            from scripts import staged_news as stage
            from scripts.test_editorial31 import article
        except ImportError:
            import staged_news as stage
            from test_editorial31 import article
        state={'date':'2020-01-01','stage':'audited','audit_passed':True,'articles':{},'sources':[]}
        for i in range(8):
            a=article(long=i<2,idx=i+1); a['slug']=f'retry-{i}'
            a['_private_context']='PRIVATE-EDITORIAL-CONTEXT'
            state['articles'][str(i)]=a
            state['sources'].append({'id':f'S{i+1:03d}','url':f'https://example.org/{i}',
                'title':'Public source','published':'2019','evidence':'PRIVATE-RESEARCH'})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('assets','archive','issues'):
                shutil.copytree(stage.ROOT/name,root/name)
            release=datetime.fromisoformat(state['date']+'T06:00:00').replace(tzinfo=stage.TZ)
            stage._assemble(state,release,root)
            manifest=(root/'issues/2020-01-01/issue.json').read_text()
            markdown=(root/'issues/2020-01-01/issue.md').read_text()
            self.assertNotIn('PRIVATE-',manifest+markdown)
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(stage,'ROOT',root), patch.object(stage.news,'ROOT',root), patch.dict('os.environ',{'GITHUB_REF_NAME':'main','NEWS_RELEASE_APPROVED':'true'}):
                self.assertTrue(stage.render(state,False))
                changed=copy.deepcopy(state); changed['articles']['0']['paragraphs'][0]['text']+=' Changed fact'
                with self.assertRaisesRegex(RuntimeError,'refusing overwrite'): stage.render(changed,False)
            after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
