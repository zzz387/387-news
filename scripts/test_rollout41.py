"""Production rollover/migration and seed-pool contracts; synthetic closed state only."""
import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import editorial41 as e,release_queue as q,pipeline,policy41 as p


def artifact(date,**extra):
    return dict(name='387news31-production-'+date,workflow_run={'head_branch':'main'},**extra)


class RolloutTests(unittest.TestCase):
    def root(self,temp):
        root=Path(temp);(root/'issues/2026-10-26').mkdir(parents=True)
        (root/'issues/2026-10-26/issue.json').write_text('{}');return root

    def test_after_midnight_resumes_same_unpublished_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root=self.root(temp)
            self.assertEqual(q.unfinished_date(root,'2026-10-28',[artifact('2026-10-27')]),'2026-10-27')
            self.assertEqual(q.unfinished_date(root,'2026-10-28',[artifact('2026-10-27'),artifact('2026-10-28')]),'2026-10-27')

    def test_published_archives_preview_and_future_do_not_rewind_current_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root=self.root(temp)
            self.assertEqual(q.unfinished_date(root,'2026-10-27',[artifact('2026-10-25'),artifact('2026-10-26'),
                artifact('2026-10-28'),{'name':'387news41-trial-2026-10-27'},
                {'name':'387news31-preview-2026-10-27'}]),'2026-10-27')

    def test_expired_progress_never_becomes_silent_new_issue(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(q.unfinished_date(self.root(temp),'2026-10-28',[artifact('2026-10-27',expired=True)]),'2026-10-27')

    def test_unproven_checkpoint_origin_blocks_automatic_routing(self):
        with tempfile.TemporaryDirectory() as temp,self.assertRaisesRegex(RuntimeError,'ORIGIN_UNVERIFIED'):
            q.unfinished_date(self.root(temp),'2026-10-28',[dict(artifact('2026-10-27'),workflow_run={'head_branch':'other'})])

    def test_migration_retains_complete_old_checkpoint_and_quota_and_resumes_v41_unchanged(self):
        old={'version':31,'date':'2026-10-27','articles':{'0':{'text':'Сохранённый вымышленный текст'}},
             'dossiers':{'0':{'segments':['Вымышленный принятый фрагмент']}},'audit_passed':True,
             '_quota_snapshot':{'day':'2026-10-26','requests':207,'cooldown_until':9999999999},'branch':'main','preview':False}
        snapshot=copy.deepcopy(old);new=e.migrate(old,old['date'])
        self.assertEqual(old,snapshot);self.assertEqual(new['legacy_v31'],old)
        self.assertEqual(new['_quota_snapshot'],old['_quota_snapshot']);self.assertFalse(new['audit_passed'])
        new['candidates']=[{'id':'accepted','status':'ready','article':{'text':'Полный принятый текст'}}]
        self.assertIs(e.migrate(new,new['date']),new)

    def test_safe_status_reports_applicable_policy_and_target(self):
        new=e.new_state('2026-10-27');report=pipeline.report(new,{'day':'2026-10-26','requests':207})
        self.assertEqual(report['policy_version'],'4.1');self.assertEqual(report['article_target'],12)
        self.assertEqual(report['requests_used'],207)

    def test_production_seed_pool_has_life_categories_and_independent_verification(self):
        config=json.loads((p.ROOT/'config/candidates.json').read_text())['candidates']
        self.assertGreaterEqual(len(config),12)
        self.assertTrue(set(p.REQUIRED)<={r['category_hint'] for r in config})
        for item in config:
            self.assertTrue(set(item)<= {'url','category_hint','verification_urls'})
            self.assertTrue(item['url'].startswith('https://'))
            if item['category_hint'] in ('Семья','Здоровье и движение'):self.assertTrue(item['verification_urls'])


if __name__=='__main__':unittest.main()


class ProductionBindingsTests(unittest.TestCase):
    def test_production_binds_existing_secrets_without_returning_values(self):
        import base64
        from scripts import production_preflight41 as pre
        key=base64.b64encode(b'x'*32).decode()
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'zzz387/387-news','GITHUB_REF_NAME':'main',
             'GEMINI_API_KEY':'synthetic-key-not-a-real-secret','DRAFT_ENCRYPTION_KEY':key,
             'NEWS_AUTOMATION_V31_ENABLED':'true','NEWS_RELEASE_APPROVED':'true'}
        report=pre.check(env);self.assertNotIn(key,json.dumps(report));self.assertNotIn(env['GEMINI_API_KEY'],json.dumps(report))
        for name,value in [('GITHUB_REF_NAME','other'),('GEMINI_API_KEY',''),('NEWS_AUTOMATION_V31_ENABLED','false'),('NEWS_RELEASE_APPROVED','false')]:
            with self.subTest(name=name),self.assertRaises(RuntimeError):pre.check(dict(env,**{name:value}))

    def test_publication_requires_verified_actions_pages_and_existing_domain(self):
        from scripts import production_preflight41 as pre
        correct={'verified':True,'build_type':'workflow','cname':'387.su','https_enforced':True}
        with patch.object(pre,'pages_status',return_value=correct):self.assertEqual(pre.require_pages(),correct)
        for change in ({'verified':False},{'build_type':'legacy'},{'cname':'other.example'}):
            with patch.object(pre,'pages_status',return_value=dict(correct,**change)),self.assertRaises(RuntimeError):pre.require_pages()
