"""Dynamic monitoring, safe model metadata and additive recovery of candidate reserves."""
import copy,io,json,os,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from scripts import health41 as health,editorial41 as e,policy41 as p


class StabilizeTests(unittest.TestCase):
    def test_dynamic_checkpoint_tracks_next_day_and_oldest_unfinished_date(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'issues/2026-11-03').mkdir(parents=True)
            (root/'issues/2026-11-03/issue.json').write_text('{}')
            now=datetime(2026,11,3,15,tzinfo=p.TZ)
            self.assertEqual(health.checkpoint_date(root,now,[]),'2026-11-04')
            self.assertEqual(health.checkpoint_date(root,now,[{'name':'387news31-production-2026-11-04','workflow_run':{'head_branch':'main'}}]),'2026-11-04')
            now=datetime(2026,11,5,1,tzinfo=p.TZ)
            self.assertEqual(health.checkpoint_date(root,now,[{'name':'387news31-production-2026-11-04','workflow_run':{'head_branch':'main'}}]),'2026-11-04')

    def test_recent_runs_paginates_and_covers_exact_twelve_hours(self):
        now=datetime(2026,11,1,12,tzinfo=timezone.utc);calls=[]
        def fetch(path):
            calls.append(path)
            if len(calls)==1:return {'workflow_runs':[{'id':i,'created_at':'2026-11-01T11:00:00Z'} for i in range(100)]}
            return {'workflow_runs':[{'id':100,'created_at':'2026-11-01T00:00:00Z'},{'id':101,'created_at':'2026-10-31T23:59:59Z'}]}
        rows=health.recent_runs(now,fetch)
        self.assertEqual(len(rows),101);self.assertEqual(len(calls),2)

    def test_model_metadata_uses_two_gets_no_generation_and_sanitizes_errors(self):
        calls=[]
        def get(request,timeout):
            calls.append(request)
            if len(calls)==1:return io.StringIO(json.dumps({'supportedGenerationMethods':['generateContent'],'outputTokenLimit':65536}))
            raise HTTPError(request.full_url,503,'UNAVAILABLE',{},io.BytesIO(b'private error body'))
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REF_NAME':'main','GEMINI_API_KEY':'synthetic-test-key'}),patch.object(health,'emit') as output:
            rows=health.model_metadata(get)
        self.assertEqual([r.get_method() for r in calls],['GET','GET'])
        self.assertTrue(all(':generateContent' not in r.full_url and 'key=' not in r.full_url for r in calls))
        self.assertEqual(rows[1],{'model':'gemini-3.1-flash-lite','http':503})
        self.assertNotIn('private error body',str(output.call_args))

    def test_refresh_appends_candidates_without_reprocessing_accepted_articles(self):
        state=e.new_state('2026-11-04');r={'id':'existing','url':'https://example.org/accepted','status':'ready','article':{'title':'Synthetic accepted'},'progress':{'done':True}}
        state.update(discovered=True,candidates=[copy.deepcopy(r)],_quota_snapshot={'requests':207})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            (root/'config/candidates.json').write_text(json.dumps({'candidates':[{'url':r['url']},{'url':'https://example.org/new'}]}))
            with patch.object(p,'ROOT',root),patch.dict(os.environ,{},clear=True),patch.object(e.news,'read_feed',side_effect=AssertionError('No repeated discovery network')):
                e.discover(state);e.discover(state)
        self.assertEqual(state['candidates'][0],r);self.assertEqual(len(state['candidates']),2)
        self.assertEqual(state['_quota_snapshot'],{'requests':207})

    def test_special_alternative_migration_preserves_quota_and_unrelated_progress(self):
        from scripts import special003r as runner,special_contract41 as sc
        config=copy.deepcopy(sc.definition())
        for slot in config['slots']:
            slot.pop('evidence_plan',None);slot.pop('replacement_topic',None)
        config['slots'][6]['requirements'].pop();config['slots'][7]['requirements'].pop()
        self.assertEqual(p.digest(config),runner.PREVIOUS_DEFINITION_HASH)
        with patch.object(sc,'definition',return_value=config):old=runner.new_state()
        accepted=old['candidates'][2];accepted['status']='ready';accepted['article']={'title':'Synthetic accepted article'}
        accepted['progress']={'saved':'synthetic stage'}
        old['_quota_snapshot']={'day':'2026-10-26','requests':207,'models':{'lite':207},'cooldowns':{'lite':9999999999}}
        before=copy.deepcopy(old['_quota_snapshot']);runner.refresh_definition(old)
        self.assertIs(old['candidates'][2],accepted);self.assertEqual(accepted['progress'],{'saved':'synthetic stage'})
        self.assertEqual(old['_quota_snapshot'],before);self.assertTrue(sc.is_special(old))
        self.assertIn('https://www.mos.ru/news/item/177660073/',old['candidates'][1]['unused_original_urls'])
        self.assertNotEqual(old['candidates'][1]['url'],config['slots'][1]['url'])

    def test_source_reserve_never_accepts_unreadable_independent_reference(self):
        from scripts import source_reserve41 as reserve
        from scripts.test_policy41 import record
        catalog={'candidates':[{'topic_id':'1','url':'https://example.org/primary','verification_urls':['https://example.org/blocked']}]}
        def fetch(url):
            if url.endswith('blocked'):raise p.Blocked('ROBOTS_FORBIDDEN')
            source=record(0)['source'];source['url']=url;return source
        report=reserve.run(catalog,fetch)
        self.assertEqual(report['unique_eligible'],0);self.assertEqual(report['gemini_requests'],0)
        self.assertEqual(report['rejected_candidates'][0]['failures'][0]['code'],'ROBOTS_FORBIDDEN')

    def test_russian_institution_can_omit_language_but_latin_text_is_not_assumed_english(self):
        from scripts import source41
        html='<html><head><title>Инфляция</title></head><body><main><h1>Инфляция</h1><p>Устойчивый рост цен изменяет покупательную способность денег.</p></main></body></html>'
        source=source41.extract(html,'https://www.cbr.ru/dkp/about_inflation/')
        self.assertEqual(source['language'],'ru');self.assertEqual(source['language_evidence'],'extracted_cyrillic_script')
        self.assertEqual(source['metadata_status'],'verified');self.assertEqual(source['author'],'');self.assertEqual(source['published'],'')
        other=source41.extract(html.replace('Устойчивый рост цен изменяет покупательную способность денег.','A complete English looking sentence with Latin letters but no declared language.'),'https://www.cbr.ru/eng/example')
        self.assertEqual(other['language'],'');self.assertEqual(other['metadata_status'],'needs_review')
        unrelated=source41.extract(html,'https://www.unicef.org/parenting/example')
        self.assertEqual(unrelated['language'],'');self.assertEqual(unrelated['metadata_status'],'needs_review')

    def test_nist_complete_body_is_domain_scoped_and_partial_body_stays_blocked(self):
        from scripts import source41
        html='<html lang="en"><head><title>Manufacturing</title></head><body><div class="nist-page__region--content-top-full">Header</div><div class="nist-page__region--content"><h1>Manufacturing</h1><p>Complete synthetic original.</p></div></body></html>'
        source=source41.extract(html,'https://www.nist.gov/additive-manufacturing/what-additive-manufacturing')
        self.assertEqual(source['extraction_method'],'nist_complete_body')
        self.assertNotIn('Header',' '.join(b['text'] for b in source['blocks']))
        with self.assertRaises(p.Blocked):source41.extract(html,'https://example.org/ambiguous')
        with self.assertRaises(p.Blocked):source41.extract(html.split('</div></body>')[0],'https://www.nist.gov/partial')

    def test_already_published_primary_is_rejected_before_spending_model_quota(self):
        from scripts import pipeline
        from types import SimpleNamespace
        state=e.new_state('2026-11-04');state['discovered']=True
        state['candidates']=[{'id':'old','url':'https://example.org/published','status':'discovered','checks':{},'progress':{}}]
        state['_quota_snapshot']={'requests':207}
        with tempfile.TemporaryDirectory() as directory,patch.object(e,'discover'),patch.object(e,'archive_entries',return_value=[{'source_url':'https://example.org/published'}]),patch.object(pipeline,'capacity',return_value=True):
            self.assertFalse(e.advance(state,state['date'],True,SimpleNamespace(ROOT=Path(directory)),lambda:None,
                editor=e.Editor(call=lambda *a,**k:self.fail('Published material must not consume Gemini again'))))
        self.assertEqual(state['candidates'][0]['history'][-1]['code'],'SOURCE_ALREADY_PUBLISHED')
        self.assertEqual(state['_quota_snapshot'],{'requests':207})

    def test_public_source_throttle_does_not_retry_other_urls_on_the_same_origin(self):
        from scripts.public_sources41 import Session
        from scripts import source41
        session=Session();failure=HTTPError('https://example.org/a',429,'Too Many Requests',{},None)
        with patch.object(source41,'transport',side_effect=failure) as transport,patch('time.sleep'):
            for url in ('https://example.org/a','https://example.org/b'):
                with self.assertRaises(HTTPError):session.transport(url)
        self.assertEqual(transport.call_count,1)

    def test_theatre_news_complete_region_ignores_modal_and_requires_closing_boundary(self):
        from scripts import source41
        html='<html lang="ru"><head><title>Премьера</title></head><body><div class="modal-body">Реклама</div><div class="studio-content"><h1>Премьера</h1><p>Полный вымышленный оригинал театра.</p></div></body></html>'
        url='https://dmtya.ru/theatre/news/theatre/synthetic'
        source=source41.extract(html,url)
        self.assertEqual(source['extraction_method'],'dmtya_complete_news')
        self.assertNotIn('Реклама',' '.join(b['text'] for b in source['blocks']))
        with self.assertRaises(p.Blocked):source41.extract(html.split('</div></body>')[0],url)

    def test_special_transient_source_hold_stops_after_three_without_touching_quota(self):
        from scripts import special003r as runner
        from types import SimpleNamespace
        state=runner.new_state();state['_quota_snapshot']={'requests':207};calls=[]
        def finish(state,record):calls.append(record['id']);raise p.Blocked('SOURCE_EXTRACTION_PARTIAL')
        editor=SimpleNamespace(finish=finish)
        with tempfile.TemporaryDirectory() as directory:
            for _ in range(3):self.assertFalse(runner.advance(state,editor,Path(directory),lambda:None))
        self.assertEqual(calls,['003-R-1']*3);self.assertEqual(state['candidates'][0]['status'],'needs_review')
        self.assertTrue(all(r['status']=='discovered' for r in state['candidates'][1:]))
        self.assertEqual(state['_quota_snapshot'],{'requests':207})

    def test_frontiers_full_research_region_requires_methods_results_and_closed_body(self):
        from scripts import source41
        html='<html lang="en"><head><title>Synthetic study</title></head><body><article class="Card">Unrelated card</article><main><h1>Synthetic study</h1><div class="ArticleDetailsV4__main__content"><h2>Abstract</h2><p>Synthetic abstract.</p><h2>2 Methods</h2><p>Complete synthetic methods.</p><h2>3 Results</h2><p>Complete synthetic results.</p></div></main></body></html>'
        url='https://www.frontiersin.org/journals/nutrition/articles/10.synthetic/full'
        source=source41.extract(html,url);self.assertEqual(source['extraction_method'],'frontiers_complete_research')
        self.assertNotIn('Unrelated card',' '.join(b['text'] for b in source['blocks']))
        with self.assertRaises(p.Blocked):source41.extract(html.split('<h2>2 Methods')[0]+'</div></main></body></html>',url)
        with self.assertRaises(p.Blocked):source41.extract(html.split('</div>')[0],url)

    def test_read_only_monitor_has_no_pinned_dates_and_release_requirements_are_preserved(self):
        text=(p.ROOT/'.github/workflows/pages-health.yml').read_text()
        self.assertNotIn('2026-10-27',text);self.assertNotIn('2026-10-26',text)
        daily=(p.ROOT/'.github/workflows/daily-v31.yml').read_text()
        self.assertIn("cron: '54 2 * * *'",daily);self.assertEqual(p.RELEASE_TIME,'06:00')
        self.assertIn("!contains(github.event.head_commit.message, '[maintenance only]')",daily)
        self.assertEqual(p.ARTICLE_COUNT,12)
