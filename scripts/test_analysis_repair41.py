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

    def test_selected_evidence_binds_literal_quote_and_source_id_without_translation(self):
        s=one_source();pieces=c.chunks(s['blocks']);valid=answer(s,pieces)
        evidence=c.evidence_units(pieces)[0]
        valid['claims'][0].update(source_id='model-typo',quote='A translated or mistyped quotation',evidence_id=evidence['id'])
        record={'source':s,'progress':{}};e.Editor(call=lambda *a,**k:valid).analyse(record)
        self.assertEqual(record['claims'][0]['quote'],evidence['text'])
        self.assertEqual(record['claims'][0]['source_id'],s['id']);self.assertNotIn('evidence_id',record['claims'][0])
        self.assertIn(record['claims'][0]['quote'],pieces[0]['text'])

    def test_literal_evidence_does_not_bypass_independent_fact_review(self):
        import json
        from scripts.test_policy41 import record as fixture
        r=fixture(0);r['checks']={};r['claims']=[{'id':'claim','fact':'Synthetic unsupported conclusion','quote':r['source']['blocks'][-1]['text'],'source_id':r['source']['id'],'sensitive':False}]
        r['article']['category']='Наука';r['article']['activities']=[]
        def reject(prompt,**kwargs):
            part=json.loads(prompt.split('\nЧасть: ')[1].split('\nПроверенные')[0]);members=part.get('pieces',[part])
            return {'approve':False,'issues':['Claim is not entailed by the literal source'],'unresolved':[],
                    'covered_ids':[m['id'] for m in members],'affected_ids':[m['id'] for m in members]}
        with self.assertRaisesRegex(p.Blocked,'REVIEW_REJECTED'):
            e.Editor(call=reject).review(e.new_state('2026-10-27'),r,'fact_checked')
        self.assertNotIn('fact_checked',r['checks'])

    def test_unknown_evidence_identifier_does_not_approve_a_claim(self):
        s=one_source();bad=answer(s,c.chunks(s['blocks']));bad['claims'][0]['evidence_id']='foreign-q'
        record={'source':s,'progress':{}}
        with self.assertRaisesRegex(p.Blocked,'CLAIM_NOT_IN_ORIGINAL'):
            e.Editor(call=lambda *a,**k:copy.deepcopy(bad)).analyse(record)
        attempt=next(iter(record['progress']['analysis_repairs'].values()))
        self.assertEqual(attempt['failures'],3);self.assertEqual(attempt['diagnosis'],'UNKNOWN_EVIDENCE_ID')
        self.assertEqual(record['progress'].get('analysis',{}),{})

    def test_selected_event_evidence_must_exist_and_date_is_never_created_from_metadata(self):
        s=one_source();bad=answer(s,c.chunks(s['blocks']));bad.update(event_date='2026-10-27',event_evidence_id='missing-q')
        with self.assertRaisesRegex(p.Blocked,'EVENT_DATE_UNVERIFIED'):
            e.Editor(call=lambda *a,**k:copy.deepcopy(bad)).analyse({'source':s,'progress':{}})

    def test_every_evidence_unit_is_an_exact_span_of_its_declared_part(self):
        pieces=[{'id':'first','text':'First sentence. Second sentence! A third line?\nFourth line.'},
                {'id':'second','text':'Русский оригинал — без перевода.'}]
        units=c.evidence_units(pieces);self.assertGreater(len(units),2)
        by_id={piece['id']:piece for piece in pieces}
        self.assertEqual(len({unit['id'] for unit in units}),len(units))
        for unit in units:self.assertIn(unit['text'],by_id[unit['piece_id']]['text'])

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
