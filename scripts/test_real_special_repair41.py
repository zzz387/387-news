"""Regressions from real 003-R run; all contents here are synthetic."""
import copy,unittest
from unittest.mock import patch
from scripts import special003r as runner,special_priority41 as q,editorial41 as e,content41 as c,policy41 as p
from scripts.test_analysis_repair41 import one_source,answer
from scripts.test_policy41 import record


class RealRepairTests(unittest.TestCase):
    def test_exhausted_historical_date_response_is_revalidated_without_new_http_or_counter_reset(self):
        state=runner.new_state();s=one_source();pieces=c.chunks(s['blocks']);bad=answer(s,pieces)
        bad.update(event_date='2026-10-27',event_evidence_id='not-a-real-id',event_date_quote='fabricated date',kind='новость')
        identity=p.digest([part['id'] for part in pieces])
        attempt={'failures':3,'code':'EVENT_DATE_UNVERIFIED','last_rejected_result':copy.deepcopy(bad)}
        r={'source':s,'progress':{'analysis_repairs':{identity:attempt}}}
        editor=e.Editor(call=lambda *a,**k:self.fail('No new model call for local historical revalidation'))
        editor.state=state;editor.analyse(r)
        self.assertTrue(r['claims']);self.assertEqual(attempt['failures'],3)
        self.assertEqual(r['kind'],'неоперативная статья');self.assertFalse(s.get('event_date'))
        self.assertEqual(attempt['quarantined_event_date']['event_date'],'2026-10-27')

    def test_historical_date_quarantine_does_not_approve_an_unverified_fact(self):
        state=runner.new_state();s=one_source();bad=answer(s,c.chunks(s['blocks']))
        bad['claims'][0]['quote']='Absent literal evidence';bad.update(event_date='2026-10-27',event_date_quote='')
        editor=e.Editor(call=lambda *a,**k:copy.deepcopy(bad));editor.state=state
        with self.assertRaisesRegex(p.Blocked,'CLAIM_NOT_IN_ORIGINAL'):editor.analyse({'source':s,'progress':{}})

    def test_whole_article_repair_retains_reasons_prior_versions_and_other_articles(self):
        state=runner.new_state();r=record();r['mode']='INDEPENDENT_ARTICLE'
        r['rejected_part']={'stage':'editorial_checked','block_id':'','scope':'article_independence',
            'result':{'approve':False,'issues':['Synthetic composition refusal']}}
        r['progress'].update(outline={'title':'Prior'},sections={'one':{'text':'Prior accepted'}},section_attempts={'one':2})
        other=copy.deepcopy(state['candidates'][4]);snapshot=copy.deepcopy(r['article'])
        self.assertTrue(e.begin_article_repair(state,r));self.assertEqual(r['progress']['section_attempts'],{'one':2})
        self.assertEqual(r['progress']['article_repair_history'][0]['article'],snapshot)
        self.assertEqual(state['candidates'][4],other);self.assertIn('Synthetic composition refusal',r['progress']['outline_feedback'])
        self.assertTrue(e.begin_article_repair(state,r));self.assertFalse(e.begin_article_repair(state,r))

    def test_versioned_requeue_preserves_total_quota_and_attempt_history_and_never_repeats(self):
        state=runner.new_state();q.reconcile(state);state['_quota_snapshot']={'day':'2026-10-27','requests':72}
        for index,code in enumerate(('EVENT_DATE_UNVERIFIED','REVIEW_REJECTED')):
            state['candidates'][index].update(status='needs_review',history=[{'code':code}])
            state['candidates'][index]['progress']['section_attempts']={'kept':2}
        for r in state['candidates'][2:]:r['status']='ready'
        self.assertFalse(q.reconcile(state)[0]);untouched=copy.deepcopy(state['candidates'][2:])
        q.repair_real_run_v2(state);self.assertTrue(q.reconcile(state)[0])
        self.assertEqual(state['_quota_snapshot']['requests'],72);self.assertEqual(state['candidates'][2:],untouched)
        self.assertEqual(state['candidates'][0]['progress']['section_attempts'],{'kept':2})
        state['candidates'][0]['status']='needs_review';q.repair_real_run_v2(state)
        self.assertEqual(state['candidates'][0]['status'],'needs_review')


    def test_section_refusal_keeps_specific_missing_ids_for_private_feedback(self):
        from scripts.test_special_priority41 import SectionTests
        r,section,result=SectionTests().fixture();result['covered_requirement_ids']=[]
        with self.assertRaises(p.Blocked) as raised:c.validate_section(result,section,r,{'r1':'Вопрос'})
        self.assertEqual(raised.exception.code,'SECTION_REQUIRED_COVERAGE_MISSING')
        self.assertIn('r1',raised.exception.detail);self.assertNotIn('Вопрос',str(raised.exception))
