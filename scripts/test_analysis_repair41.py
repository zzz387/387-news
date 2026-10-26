"""Synthetic literal-quote repair regression; no real dossier, API or key."""
import copy
import unittest
from unittest.mock import patch
from scripts import editorial41 as e,content41 as c,policy41 as p,generation_runtime as runtime
from scripts.test_policy41 import source


def one_source():
    s=source();s['blocks']=[s['blocks'][-1]];s['content_hash']=p.digest(s['blocks']);return s


def answer(s,pieces):
    return {'covered_ids':[x['id'] for x in pieces],'worth_publishing':True,'category':'Наука',
            'kind':'статья','event_date':'','event_date_quote':'','topic_key':'Вымышленная тема',
            'requirements':[],'claims':[{'id':'fact1','source_id':s['id'],'fact':'Вымышленный факт',
                                        'quote':pieces[-1]['text'],'sensitive':False}]}


class AnalysisRepairTests(unittest.TestCase):
    def test_invalid_literal_quote_is_repaired_with_feedback_without_weakening_match(self):
        s=one_source();pieces=c.chunks(s['blocks']);valid=answer(s,pieces)
        bad=copy.deepcopy(valid);bad['claims'][0]['quote']='Такого предложения в оригинале нет'
        prompts=[];results=iter([bad,valid]);record={'source':s,'progress':{}}
        def call(prompt,**kwargs):prompts.append(prompt);return next(results)
        e.Editor(call=call).analyse(record)
        self.assertEqual(len(prompts),2);self.assertIn('CLAIM_NOT_IN_ORIGINAL',prompts[1])
        self.assertEqual(record['claims'][0]['quote'],valid['claims'][0]['quote'])
        self.assertEqual(next(iter(record['progress']['analysis_repairs'].values()))['failures'],1)

    def test_three_invalid_attempts_stop_and_survive_another_run(self):
        s=one_source();bad=answer(s,c.chunks(s['blocks']));bad['claims'][0]['quote']='Неподтверждённая цитата'
        calls=[];record={'source':s,'progress':{}}
        def call(*a,**k):calls.append(1);return copy.deepcopy(bad)
        with self.assertRaisesRegex(p.Blocked,'CLAIM_NOT_IN_ORIGINAL'):e.Editor(call=call).analyse(record)
        self.assertEqual(len(calls),3)
        restored=copy.deepcopy(record)
        with self.assertRaisesRegex(p.Blocked,'CLAIM_NOT_IN_ORIGINAL'):e.Editor(call=call).analyse(restored)
        self.assertEqual(len(calls),3)

    def test_partial_coverage_is_repaired_but_unverified_event_date_never_approved(self):
        s=one_source();pieces=c.chunks(s['blocks']);valid=answer(s,pieces)
        bad=copy.deepcopy(valid);bad['covered_ids']=[]
        results=iter([bad,valid]);record={'source':s,'progress':{}}
        e.Editor(call=lambda *a,**k:next(results)).analyse(record)
        bad=copy.deepcopy(valid);bad.update(event_date='2026-10-27',event_date_quote='')
        with self.assertRaisesRegex(p.Blocked,'EVENT_DATE_UNVERIFIED'):
            e.Editor(call=lambda *a,**k:copy.deepcopy(bad)).analyse({'source':s,'progress':{}})

    def test_quota_pause_keeps_accepted_parts_and_retry_state_between_runs(self):
        s=source();pieces=c.chunks(s['blocks']);record={'source':s,'progress':{}}
        groups=[[piece] for piece in pieces];count=0
        def call(*args,**kwargs):
            nonlocal count
            count+=1
            if count==1:return answer(s,groups[0])
            if count==2:
                bad=answer(s,groups[1]);bad['claims'][0]['quote']='Выдуманная цитата';return bad
            raise runtime.GenerationPaused('503 synthetic cooldown')
        with patch.object(c,'operation_groups',side_effect=lambda pending:[[x] for x in pending]):
            with self.assertRaises(runtime.GenerationPaused):e.Editor(call=call).analyse(record)
            accepted=copy.deepcopy(record['progress']['analysis'])
            restored=copy.deepcopy(record);remaining=[]
            def resume(prompt,**kwargs):remaining.append(1);return answer(s,groups[1])
            e.Editor(call=resume).analyse(restored)
            self.assertEqual(len(remaining),1)
            self.assertEqual(restored['progress']['analysis'][pieces[0]['id']],accepted[pieces[0]['id']])

    def test_legacy_refusal_requeues_only_affected_candidate_once_without_counter_reset(self):
        state=e.new_state('2026-10-27');state['_quota_snapshot']={'requests':207}
        bad={'id':'bad','status':'rejected','history':[{'code':'CLAIM_NOT_IN_ORIGINAL'}],'progress':{}}
        ready={'id':'good','status':'ready','article':{'text':'Принято'}}
        state['candidates']=[bad,ready];before=copy.deepcopy(ready)
        e.restore_analysis_repairs(state);self.assertEqual(bad['status'],'preparing')
        self.assertEqual(bad['progress']['_prior_analysis_failures'],1);self.assertEqual(ready,before)
        bad['status']='rejected';e.restore_analysis_repairs(state);self.assertEqual(bad['status'],'rejected')
        self.assertEqual(state['_quota_snapshot']['requests'],207)


if __name__=='__main__':unittest.main()
