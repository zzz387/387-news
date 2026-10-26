import copy
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
try:
    from scripts import audit_policy as policy, audit_repair as repair, editorial31 as editorial, staged_news as stage, release_queue
    from scripts.test_editorial31 import article
except ImportError:
    import audit_policy as policy
    import audit_repair as repair
    import editorial31 as editorial
    import staged_news as stage
    import release_queue
    from test_editorial31 import article


def fixture():
    categories=['Семья','Москва и путешествия','Здоровье и движение','Семья','Наука','История и культура','Технологии','Экономика и бизнес']
    titles=['Детские игры и семейные ритуалы','Петровский дворец и архитектура Москвы',
            'Движение суставов и физическая нагрузка','Воспитание ребёнка и школьная среда',
            'Наблюдения астероидов космическим телескопом','Архив рукописей и судьба писателя',
            'Устройство электродвигателя на заводе','Процентные ставки и семейные сбережения']
    state={'version':31,'date':'2026-10-25','branch':'main','preview':False,'stage':'ready_for_audit',
           'articles':{},'plan':[],'dossiers':{},'sources':[],
           '_quota_snapshot':{'day':'2026-10-25','requests':206,'models':{'lite':206}}}
    for i,category in enumerate(categories):
        a=article(long=i<2,category=category,idx=i+1); a['title']=titles[i]
        a['_review_scope']='title_teaser_body_v1'; a['slug']=f'approved-{i}'
        state['articles'][str(i)]=a
        state['plan'].append({k:a[k] for k in ('title','category','kind','long','source_ids')})
        state['dossiers'][str(i)]={'claims':[{'source_id':f'S{i+1:03d}','quote':'Synthetic invented evidence'}]}
        state['sources'].append({'id':f'S{i+1:03d}','url':f'https://example.org/{i}'})
    return state


def finding(**kw):
    defaults=dict(scope='article',article_ids=[5],repair_ids=[5],action='revise_article',
                  reason='PRIVATE synthetic literary diagnosis',instruction='Correct the concrete opening')
    defaults.update(kw)
    return policy.issue('article_quality',**defaults)


class AuditPolicyTests(unittest.TestCase):
    def test_response_requires_explicit_attribution_not_free_form_legacy_guess(self):
        for response in ({'approve':False,'reasons':['rewrite weakest story']},
                         {'approve':False,'issues':[]},{'approve':True,'issues':[finding()]},
                         {'approve':False,'issues':[finding(article_ids=[9],repair_ids=[9])]},
                         {'approve':False,'issues':[finding(article_ids=[2],repair_ids=[5])]},
                         {'approve':False,'issues':[finding(article_ids=[True],repair_ids=[True])]}):
            with self.subTest(response=response):
                with self.assertRaises(policy.AuditRejected): policy.validate_response(response)
        policy.validate_response({'approve':True,'issues':[]})

    def test_individual_veto_retains_all_eight_and_queues_only_identified_article(self):
        state=fixture(); before=copy.deepcopy(state['articles']); logs=io.StringIO()
        with patch.object(editorial,'audit_issue',side_effect=policy.AuditRejected([finding()])),redirect_stdout(logs):
            stage.audit(state)
        self.assertTrue(state['articles']==before)
        self.assertEqual(set(state['audit_repairs']),{'4'})
        self.assertIn('code=article_quality',logs.getvalue())
        self.assertIn('repair=[5]',logs.getvalue())
        self.assertNotIn('PRIVATE',logs.getvalue())
        self.assertIn('PRIVATE',state['audit_history'][0]['issues'][0]['reason'])
        self.assertFalse(state['audit_passed'])

    def test_unattributed_issue_veto_never_chooses_smallest_article(self):
        state=fixture(); before=copy.deepcopy(state['articles'])
        with patch.object(editorial,'audit_issue',side_effect=ValueError('PRIVATE issue-wide weakness')):
            stage.audit(state)
        self.assertTrue(state['articles']==before)
        self.assertFalse(state.get('audit_repairs'))
        self.assertIn('audit_blocked',state)
        with patch.object(editorial,'audit_issue') as api:
            stage.audit(state); stage.write_batch(state)
            api.assert_not_called()
        self.assertTrue(state['articles']==before)

    def test_cross_article_diversity_repairs_only_explicit_minimal_subset(self):
        state=fixture(); before=copy.deepcopy(state['articles'])
        f=policy.issue('diversity',article_ids=[2,7],repair_ids=[7],action='revise_article',
                       reason='Two related angles overlap',instruction='Differentiate article seven using existing evidence')
        with patch.object(editorial,'audit_issue',side_effect=policy.AuditRejected([f])):
            stage.audit(state)
        self.assertEqual(set(state['audit_repairs']),{'6'})
        self.assertTrue(state['articles']==before)

    def test_composition_reorders_without_rewriting_or_researching(self):
        state=fixture(); before=copy.deepcopy(state['articles'])
        order=[3,1,2,4,5,6,7,8]
        f=policy.issue('composition',article_ids=list(range(1,9)),action='reorder_issue',order=order,
                       reason='Change opening sequence',instruction='Change only the order')
        with patch.object(editorial,'audit_issue',side_effect=policy.AuditRejected([f])): stage.audit(state)
        self.assertEqual(state['article_order'],[i-1 for i in order])
        self.assertTrue(state['articles']==before)
        with patch.object(editorial,'audit_issue',return_value=5800) as api: stage.audit(state)
        self.assertEqual(api.call_args.kwargs['article_ids'],order)
        self.assertTrue(state['audit_passed'])
        public=stage.publication.public_issue(state,2)
        self.assertEqual(public['articles'][0]['title'],before['2']['title'])

    def test_targeted_revision_requires_factual_review_and_keeps_unrelated_seven(self):
        state=fixture(); before=copy.deepcopy(state['articles'])
        repair.record_veto(state,[finding()])
        revised=copy.deepcopy(before['4']); revised['paragraphs'][0]['text']+=' Проверенная правка.'
        with patch.object(editorial,'revise_after_audit',return_value=revised) as writer, \
             patch.object(editorial,'verify_article',return_value=True) as reviewer:
            stage.write_batch(state)
        writer.assert_called_once(); reviewer.assert_called_once()
        for slot in before:
            if slot!='4': self.assertTrue(state['articles'][slot]==before[slot])
        self.assertFalse(state['articles']['4']==before['4'])
        self.assertEqual(state['audit_retained_articles'][0]['article'],before['4'])
        self.assertFalse(state['audit_repairs'])
        self.assertEqual(state['_quota_snapshot']['requests'],206)

    def test_quota_pause_keeps_revision_candidate_without_rewriting_again(self):
        state=fixture(); repair.record_veto(state,[finding()]); original=copy.deepcopy(state['articles']['4'])
        revised=copy.deepcopy(original); revised['teaser']+=' Исправление.'
        with patch.object(editorial,'revise_after_audit',return_value=revised) as writer, \
             patch.object(editorial,'verify_article',side_effect=stage.RUNTIME.GenerationPaused('daily budget')):
            with self.assertRaises(stage.RUNTIME.GenerationPaused): stage.write_batch(state)
        self.assertTrue(state['articles']['4']==original)
        self.assertIn('_audit_revision_candidate',state['dossiers']['4'])
        with patch.object(editorial,'revise_after_audit') as writer,patch.object(editorial,'verify_article',return_value=True):
            stage.write_batch(state); writer.assert_not_called()
        self.assertFalse(state['audit_repairs'])

    def test_repeated_failed_correction_is_bounded_without_losing_original(self):
        state=fixture(); before=copy.deepcopy(state['articles']); repair.record_veto(state,[finding()])
        with patch.object(editorial,'revise_after_audit',side_effect=ValueError('PRIVATE unsupported edit')) as api:
            stage.write_batch(state); stage.write_batch(state); stage.write_batch(state); stage.write_batch(state)
        self.assertEqual(api.call_count,2)
        self.assertTrue(state['articles']==before)
        self.assertIn('audit_blocked',state)

    def test_unchanged_veto_fingerprint_prevents_duplicate_audit_request(self):
        state=fixture()
        f=policy.issue('composition',article_ids=list(range(1,9)),action='reorder_issue',order=list(range(1,9)),
                       reason='Ineffective order recommendation',instruction='Retain order')
        with patch.object(editorial,'audit_issue',side_effect=policy.AuditRejected([f])) as api:
            stage.audit(state); stage.audit(state); stage.audit(state)
        self.assertEqual(api.call_count,1)
        self.assertIn('audit_blocked',state)

    def test_global_audit_round_cap_preserves_all_accepted_articles(self):
        state=fixture(); state['audit_rounds']=policy.MAX_AUDITS
        with patch.object(editorial,'audit_issue') as api:
            stage.audit(state); api.assert_not_called()
        self.assertEqual(len(state['articles']),8)
        self.assertFalse(state.get('audit_passed'))

    def test_issue_review_receives_complete_texts_and_explicit_ids(self):
        state=fixture(); articles=list(state['articles'].values())
        with patch.object(editorial.news,'gemini',return_value={'approve':True,'issues':[]}) as api:
            total=editorial.audit_issue(articles,state['plan'],{s['id']:s for s in state['sources']})
        self.assertGreaterEqual(total,5000)
        self.assertIn(articles[4]['paragraphs'][4]['text'],api.call_args.args[0])
        self.assertIn('"article_id": 5',api.call_args.args[0])

    def test_hold_or_operational_error_never_permits_release(self):
        state=fixture()
        with patch.object(editorial,'audit_issue',side_effect=RuntimeError('PRIVATE transport details')):
            stage.audit(state)
        self.assertEqual(len(state['articles']),8)
        with self.assertRaisesRegex(RuntimeError,'No approved'): stage.render(state,False)


class LegacyRecoveryTests(unittest.TestCase):
    def legacy(self):
        prior=fixture(); state=copy.deepcopy(prior)
        state['articles'].pop('4'); state['stage']='audit_veto'
        state['audit_note']='Issue editorial veto: PRIVATE overall issue weakness'
        state['_quota_snapshot']['requests']=206; prior['_quota_snapshot']['requests']=205
        return state,prior

    def test_recover_evicted_reviewed_article_preserves_new_quota_and_other_seven(self):
        state,prior=self.legacy(); before=copy.deepcopy(state['articles']); quota=copy.deepcopy(state['_quota_snapshot'])
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REF_NAME':'main'}):
            repair.recover_legacy_article(state,prior)
        self.assertEqual(len(state['articles']),8)
        for slot in before: self.assertTrue(state['articles'][slot]==before[slot])
        self.assertEqual(state['_quota_snapshot'],quota)
        self.assertFalse(state['audit_passed'])
        self.assertTrue(state['legacy_audit_recovered'])

    def test_recovery_rejects_local_execution_and_wrong_provenance(self):
        state,prior=self.legacy()
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false','GITHUB_REF_NAME':'main'}):
            with self.assertRaises(RuntimeError): repair.recover_legacy_article(state,prior)
        prior['plan'][4]['title']='Different commission'
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REF_NAME':'main'}):
            with self.assertRaisesRegex(RuntimeError,'plan mismatch'): repair.recover_legacy_article(state,prior)
        self.assertEqual(len(state['articles']),7)

    def test_routing_after_quota_day_rollover_uses_current_day_not_legacy_backlog(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            phase,preview,date=release_queue.context('write',False,'','schedule',root,datetime(2026,10,26,3,17))
            self.assertEqual((phase,preview,date),('run',False,'2026-10-26'))
            (root/'issues/2026-10-25').mkdir(parents=True)
            (root/'issues/2026-10-25/issue.json').write_text('{}')
            self.assertEqual(release_queue.context('write',False,'','schedule',root,datetime(2026,10,26,3,17)),('run',False,'2026-10-26'))
            self.assertEqual(release_queue.context('audit',True,'2026-10-27','workflow_dispatch',root,datetime(2026,10,26)),('audit',True,'2026-10-27'))

if __name__=='__main__': unittest.main()
