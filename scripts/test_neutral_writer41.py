"""Facts -> independent writing is resumable, grounded and quota safe."""
import copy,json,unittest
from datetime import datetime
from scripts import content41 as c,policy41 as p,special003r as runner,special_priority41 as q,editorial41 as e,generation_runtime as rt
from scripts.test_policy41 import record,source


def facts_record():
    return {'source':source(),'claims':[{'id':'same-id','source_id':'first','fact':'Original narrative one',
        'quote':'PROTECTED_EXPRESSION_ONE'},{'id':'same-id','source_id':'second','fact':'Original narrative two','quote':'PROTECTED_EXPRESSION_TWO'}], 'progress':{}}


def answer(prompt):
    payload=json.loads(prompt.split('Входные утверждения с доказательствами: ')[1].split('\nМетаданные')[0])
    return {'finished':True,'items':[{'id':item['id'],'finished':True,'kind':'unprotected_fact','subject':('Zeta' if item['source_id']=='first' else 'Alpha'),
        'relation':'measured_value','value':'2','qualifiers':['documented context'],'reason':''} for item in payload]}


class NeutralWriterTests(unittest.TestCase):
    def test_source_id_collision_does_not_drop_facts_or_pass_author_prose_to_writer(self):
        r=facts_record();before=copy.deepcopy(r['claims']);calls=[]
        self.assertEqual(len(runner.merge_claims(r['claims'],r['claims'][:1])),2)
        def model(prompt,**kwargs):calls.append(1);self.assertEqual(kwargs['schema'],'v41_fact_inventory');return answer(prompt)
        table=c.neutral_fact_inventory(r,model)
        self.assertEqual([row['subject'] for row in table],['Alpha','Zeta']);self.assertEqual([row['id'] for row in table],['fact1','fact2'])
        self.assertNotIn('PROTECTED_EXPRESSION',str(table));self.assertNotIn('Original narrative',str(table));self.assertEqual(r['claims'],before)
        self.assertEqual(c.neutral_fact_inventory(copy.deepcopy(r),lambda *a,**k:self.fail('Already accepted facts must resume locally')),table)
        self.assertEqual(len(calls),1)

    def test_missing_input_ids_retry_three_times_and_remain_exhausted_after_restore(self):
        r=facts_record();calls=[]
        def bad(*a,**k):calls.append(1);return {'finished':True,'items':[]}
        with self.assertRaisesRegex(p.Blocked,'NEUTRAL_FACT_PROTOCOL_EXHAUSTED'):c.neutral_fact_inventory(r,bad)
        self.assertEqual(len(calls),3)
        with self.assertRaisesRegex(p.Blocked,'NEUTRAL_FACT_PROTOCOL_EXHAUSTED'):c.neutral_fact_inventory(copy.deepcopy(r),bad)
        self.assertEqual(len(calls),3)

    def test_pause_preserves_accepted_fact_groups_between_independent_runs(self):
        from unittest.mock import patch
        r=facts_record();technical=dict(p.CONFIG['technical'],review_operation_characters=1)
        calls=[]
        def first(prompt,**kwargs):
            calls.append(1)
            if len(calls)>1:raise rt.GenerationPaused('Synthetic quota boundary')
            return answer(prompt)
        with patch.dict(p.CONFIG,technical=technical):
            with self.assertRaises(rt.GenerationPaused):c.neutral_fact_inventory(r,first)
            resumed=[]
            result=c.neutral_fact_inventory(copy.deepcopy(r),lambda prompt,**kw:(resumed.append(1) or answer(prompt)))
        self.assertEqual(len(resumed),1);self.assertEqual(len(result),2)

    def test_neutral_writer_migration_keeps_prior_drafts_and_all_request_repair_counts(self):
        state=runner.new_state();r=state['candidates'][0];r.update(mode='INDEPENDENT_ARTICLE',status='needs_review',article={'title':'Old refused draft'})
        r['progress']={'outline':{'sections':[]},'sections':{'one':{'text':'Old'}},'article_repair_count':2,'section_attempts':{'one':2}}
        r['rejected_part']={'scope':'article_independence','result':{'approve':False,'issues':['Actual form concern']}}
        state['_quota_snapshot']={'requests':220};untouched=copy.deepcopy(state['candidates'][1:])
        q.enable_neutral_writer_v1(state)
        self.assertEqual(r['status'],'preparing');self.assertNotIn('article',r)
        self.assertEqual(r['progress']['prior_writer_bases'][0]['article']['title'],'Old refused draft')
        self.assertEqual(r['progress']['article_repair_count'],2);self.assertEqual(r['progress']['section_attempts'],{'one':2})
        self.assertEqual(state['_quota_snapshot']['requests'],220);self.assertEqual(state['candidates'][1:],untouched)
        r['status']='needs_review';q.enable_neutral_writer_v1(state);self.assertEqual(r['status'],'needs_review')

    def test_quota_wait_uses_existing_next_utc_period_window_without_reset(self):
        now=datetime(2026,10,27,10,tzinfo=p.TZ);ledger={'day':'2026-10-27','requests':220,'models':{'lite':220},'cooldowns':{}}
        before=copy.deepcopy(ledger)
        self.assertEqual(q.next_scheduled_attempt(ledger,now),'2026-10-28T03:17:00+03:00');self.assertEqual(ledger,before)

    def test_new_writer_uses_only_neutral_facts_for_outline_and_sections(self):
        r=record();r.pop('article');r['mode']='INDEPENDENT_ARTICLE';r['rights']=e.rights41.decision(r['source'],r['mode']);r['requirements']=[]
        r['claims']=[{'id':'raw','source_id':'first','fact':'RAW_AUTHOR_NARRATIVE','quote':'PROTECTED_LITERAL'}];r['progress']={}
        def model(prompt,**kwargs):
            schema=kwargs['schema']
            if schema=='v41_fact_inventory':self.assertIn('PROTECTED_LITERAL',prompt);return answer(prompt)
            self.assertNotIn('PROTECTED_LITERAL',prompt);self.assertNotIn('RAW_AUTHOR_NARRATIVE',prompt)
            if schema=='v41_outline':return {'title':'Own work','teaser':'','category':'Наука','kind':'статья',
                'sections':[{'id':'s','heading':'Own context','purpose':'Explain','fact_ids':['fact1'],'requirement_ids':[],'activity_count':0}]}
            self.assertEqual(schema,'v41_section')
            section=json.loads(prompt.split('План раздела: ')[1].split('\nФакты: ')[0])
            return {'id':section['id'],'finished':True,'blocks':[{'kind':'paragraph','text':'Самостоятельное нейтральное объяснение.'}],
                    'activities':[],'covered_requirements':[],'covered_requirement_ids':[]}
        e.Editor(call=model).prepare(e.new_state('2026-10-27'),r)
        self.assertIn('neutral_inventories',r['progress']);self.assertIn('article',r)


    def test_partial_answer_keeps_complete_items_and_requests_only_missing_fact(self):
        r=facts_record();calls=[]
        def model(prompt,**kwargs):
            data=answer(prompt);calls.append(data)
            if len(calls)==1:data['finished']=False;data['items']=data['items'][:1]
            else:self.assertEqual(len(data['items']),1)
            return data
        result=c.neutral_fact_inventory(r,model)
        self.assertEqual(len(calls),2);self.assertEqual(len(result),2)

    def test_no_supported_facts_rejects_without_inventing_content(self):
        r=facts_record();calls=[]
        def model(prompt,**kwargs):
            result=answer(prompt);calls.append(1)
            for item in result['items']:item.update(kind='not_supported',reason='Not supported by the synthetic evidence')
            return result
        with self.assertRaisesRegex(p.Blocked,'INDEPENDENT_FACT_BASE_EMPTY'):c.neutral_fact_inventory(r,model)
        with self.assertRaisesRegex(p.Blocked,'INDEPENDENT_FACT_BASE_EMPTY'):c.neutral_fact_inventory(copy.deepcopy(r),model)
        self.assertEqual(len(calls),1)
