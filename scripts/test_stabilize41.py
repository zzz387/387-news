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
        for slot in config['slots']:slot.pop('evidence_plan',None)
        config['slots'][6]['requirements'].pop()
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

    def test_read_only_monitor_has_no_pinned_dates_and_merge_does_not_wake_production(self):
        text=(p.ROOT/'.github/workflows/pages-health.yml').read_text()
        self.assertNotIn('2026-10-27',text);self.assertNotIn('2026-10-26',text)
        daily=(p.ROOT/'.github/workflows/daily-v31.yml').read_text()
        self.assertIn("!contains(github.event.head_commit.message, '[maintenance only]')",daily)
        self.assertEqual(p.ARTICLE_COUNT,12)
