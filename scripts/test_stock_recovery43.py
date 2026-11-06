"""Synthetic keys only: private production inventory stays in GitHub Actions."""
import copy,json,os,tempfile,unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from scripts import stock43 as stock,staged_news as stage,editorial43 as e,source41 as source,catalog43 as cat,light43 as light,news
from scripts import test_daily43 as fixture,test_editorial_visual43 as visual

class StockRecoveryTests(unittest.TestCase):
    def env(self):return dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='zzz387/387-news',GITHUB_REF_NAME='main')

    def test_expected_download_failure_is_not_an_empty_inventory(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,self.env()):
            with self.assertRaisesRegex(RuntimeError,'download missing'):stage.restore_editorial_stock(fixture.state(),bytes(range(32)),{},Path(temp)/'absent.enc',True)

    def test_protected_loader_preserves_quota_cooldown_and_inventory(self):
        s=fixture.state();inventory=stock.empty();inventory['records']=[fixture.ready(99)];inventory['quota_snapshot']={'day':'2026-10-27','requests':219,'models':{'fixture':219},'cooldowns':{'fixture':9999999999}}
        ledger={'day':'2026-10-27','requests':218,'models':{'fixture':218},'cooldowns':{}}
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,self.env()):
            path=Path(temp)/'stock.enc';path.write_bytes(stage.cipher(inventory,bytes(range(32))))
            report=stage.restore_editorial_stock(s,bytes(range(32)),ledger,path,True)
        self.assertEqual(report['ready_articles'],1);self.assertEqual(ledger['requests'],219);self.assertEqual(ledger['cooldowns']['fixture'],9999999999)

    def test_newer_inventory_recovers_a_completed_stage_when_issue_artifact_was_lost(self):
        s=fixture.state();old=fixture.ready(99);old['status']='preparing';old['checks'].pop('final43');s['candidates']=[old]
        inventory=stock.empty();approved=fixture.ready(99);approved['stock_issue_date']=s['date'];approved['progress']['v43']={'write_attempts':2,'review_attempts':{'old':2}}
        inventory['backlog']=[approved];inventory['updated_at']='2026-10-27T08:00:00+03:00'
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,self.env()):
            path=Path(temp)/'bank.enc';path.write_bytes(stage.cipher(inventory,bytes(range(32))))
            stage.restore_editorial_stock(s,bytes(range(32)),{},path,True)
        self.assertTrue(e.eligible(s['candidates'][0]));self.assertEqual(s['candidates'][0]['progress']['v43']['write_attempts'],2)

    def test_newer_inventory_recovers_written_unreviewed_work_without_writing_again(self):
        s=fixture.state();old=fixture.ready(99);old.pop('article');old['status']='preparing';old['checks'].pop('final43');s['candidates']=[old]
        stock.sync_backlog(s);s['stock43']['updated_at']='2026-10-27T07:00:00+03:00'
        draft=fixture.ready(99);draft.update(status='preparing',stock_issue_date=s['date']);draft['checks'].pop('final43');draft['progress']['v43']={'write_attempts':2,'review_attempts':{}}
        inventory=stock.empty();inventory.update(backlog=[draft],updated_at='2026-10-27T08:00:00+03:00')
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,self.env()):
            path=Path(temp)/'bank.enc';path.write_bytes(stage.cipher(inventory,bytes(range(32))))
            stage.restore_editorial_stock(s,bytes(range(32)),{},path,True)
        self.assertEqual(s['candidates'][0]['article'],draft['article']);self.assertEqual(s['candidates'][0]['progress']['v43']['write_attempts'],2)

    def test_unprotected_or_corrupt_stock_cannot_be_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'stock.enc';path.write_bytes(b'not a protected checkpoint')
            with patch.dict(os.environ,GITHUB_ACTIONS='false'):
                with self.assertRaisesRegex(RuntimeError,'PROTECTED_ACTIONS'):stage.restore_editorial_stock(fixture.state(),bytes(range(32)),{},path,True)
            with patch.dict(os.environ,self.env()):
                with self.assertRaisesRegex(RuntimeError,'invalid header'):stage.restore_editorial_stock(fixture.state(),bytes(range(32)),{},path,True)

    def test_new_global_reservation_wins_over_an_old_issue_snapshot(self):
        s=fixture.state();row=fixture.ready(99);stock.ensure(s)['records']=[copy.deepcopy(row)]
        global_stock=stock.empty();row['stock_reserved_for']='2026-10-28';global_stock['records']=[row]
        stock.merge(s,global_stock);self.assertEqual(s['stock43']['records'][0]['stock_reserved_for'],'2026-10-28')

    def test_light_surplus_and_unpublished_fact_type_survive_in_stock(self):
        s=fixture.state(8);s['light43']={'records':[visual.light_ready(i) for i in range(8)]}
        stock.bank_light(s,fixture.NOW)
        self.assertEqual(len(light.ready(s)),3);self.assertEqual(stock.report(s)['ready_light'],5)
        revived=fixture.state(8);revived['date']='2026-10-28';stock.merge(revived,copy.deepcopy(s['stock43']))
        with tempfile.TemporaryDirectory() as temp:stock.draw_light(revived,fixture.root(temp))
        self.assertEqual(len(light.ready(revived)),3)

    def test_complete_alternative_markup_is_accepted_but_clipped_and_paywall_are_not(self):
        html='<html lang="ru"><head><meta property="article:published_time" content="2026-10-26"></head><body><h1>История архитектуры</h1><div data-testid="article-body"><p>Полное начало.</p><p>Подтверждённое окончание.</p></div></body></html>'
        original=source.extract(html,'https://example.org/history');self.assertTrue(original['full_text_verified']);self.assertIn('окончание',str(original['blocks']))
        for invalid in (html.split('</div>')[0],html.replace('data-testid="article-body"','data-testid="article-body" data-paywall="true"')):
            with self.assertRaises(e.p.Blocked):source.extract(invalid,'https://example.org/history')

    def test_shortage_search_expands_publishers_without_model_requests(self):
        config=cat.registry();prototype=visual.CatalogTests().registry_row();config['publishers']=[dict(prototype,id=str(i),priority_ids=[]) for i in range(20)]
        counts=[]
        def inspect(row,session,**kw):counts.append(kw['article_limit']);return {'article_checks':kw['article_limit'],'status':'unavailable'},[]
        with patch.object(cat,'registry',return_value=config),patch.object(cat,'inspect_publisher',side_effect=inspect),patch.object(news,'gemini',side_effect=AssertionError('Public search only')):
            cat.refresh(fixture.state(),fixture.NOW,visual.CatalogTests().session(),shortage=True)
        self.assertGreater(len(counts),5);self.assertLessEqual(len(counts),15);self.assertLessEqual(sum(counts),24)

    def test_new_independent_evidence_can_reopen_a_hold_without_resetting_attempts(self):
        from scripts import priorities43
        s=fixture.state();row=fixture.ready(5);row.pop('article');row.update(title='Воспитание ребёнка',status='deferred',history=[{'code':'INDEPENDENT_SAFETY_EVIDENCE_REQUIRED','stage':'v43_final'}])
        row['progress']={'v43':{'write_attempts':2,'review_attempts':{'old':3}}};row['category_hint']='Семья'
        src=copy.deepcopy(row['source']);src.update(url='https://www.unicef.org/parenting/independent',canonical='https://www.unicef.org/parenting/independent',title='Воспитание ребёнка')
        s['candidates']=[row];s['source_cache']={src['url']:src};before=copy.deepcopy(row['progress'])
        priorities43.reconsider_evidence(s);self.assertEqual(row['status'],'preparing');self.assertEqual(row['progress'],before)
        self.assertTrue(e.safety_sources_valid(row));self.assertEqual(row['history'][0]['code'],'INDEPENDENT_SAFETY_EVIDENCE_REQUIRED')

    def test_inspection_cannot_report_inherited_one_article_approval(self):
        s=fixture.state(1);s['audit_passed']=True;before=copy.deepcopy(s['candidates'])
        stage.inspection_status(s)
        self.assertFalse(s['audit_passed']);self.assertEqual(s['pipeline_status'],'PREPARING');self.assertEqual(s['candidates'],before)

    def test_safe_report_distinguishes_no_light_from_failed_light_calls(self):
        from scripts import pipeline
        s=fixture.state(2);s['light43']={'write_attempts':1,'review_attempts':1,'http_requests':2,'code':'GEMINI_HTTP_503','records':[]}
        report=pipeline.report(s,{})
        self.assertEqual(report['light_news_ready'],0);self.assertEqual(report['light_preparation']['http_requests'],2);self.assertEqual(report['light_preparation']['code'],'GEMINI_HTTP_503')
        self.assertNotIn('records',report['light_preparation'])

    def test_inventory_upload_is_ciphertext_only_and_keeps_existing_mutex(self):
        text=(e.p.ROOT/'.github/workflows/daily-v31.yml').read_text()
        section=text.split('Save only encrypted shared editorial inventory',1)[1].split('Project compact',1)[0]
        self.assertIn('editorial-stock.enc',section);self.assertNotIn('.md',section);self.assertNotIn('.json',section)
        self.assertIn("'387-news-stage-v31'",text);self.assertIn('run-id: ${{ steps.checkpoint.outputs.stock_run_id }}',text)

if __name__=='__main__':unittest.main()
