"""Explicit check acknowledgments preserve real copyright/editorial vetoes."""
import copy,io,json,unittest
from contextlib import redirect_stdout
from scripts import content41 as c,editorial41 as e,policy41 as p,special003r as runner,special_priority41 as q


class IndependenceProtocolTests(unittest.TestCase):
    def response(self,approve=True):
        return {'approve':approve,'issues':[] if approve else ['Actual independence concern'],'unresolved':[],
                **{key+'_checked':True for key in c.INDEPENDENCE_FIELDS}}

    def test_explicit_checks_preserve_a_real_negative_verdict(self):
        result=c.independence_response(self.response(False))
        self.assertFalse(result['approve']);self.assertEqual(result['issues'],['Actual independence concern'])
        with self.assertRaisesRegex(p.Blocked,'REVIEW_REJECTED'):c.approved_review(result,list(c.INDEPENDENCE_FIELDS))
        c.approved_review(c.independence_response(self.response()),list(c.INDEPENDENCE_FIELDS))

    def test_missing_false_and_string_acknowledgments_are_not_accepted(self):
        for value in (None,False,'true'):
            result=self.response();result['examples_checked']=value
            with self.assertRaisesRegex(p.Blocked,'INDEPENDENCE_PROTOCOL_INVALID'):c.independence_response(result)

    def test_migration_rechecks_only_a_positive_verdict_with_bad_coverage(self):
        state=runner.new_state();state['_quota_snapshot']={'day':'2026-10-27','requests':144}
        for index in (0,1):
            r=state['candidates'][index];r['status']='needs_review';r['article']={'title':'Accepted written body '+str(index)}
            r['progress']['article_repair_count']=2
            r['rejected_part']={'scope':'article_independence','result':{'approve':index==0,
                'issues':[] if index==0 else ['Real concern'],'unresolved':[],'covered_ids':['wrong']}}
        before=copy.deepcopy(state['candidates'][1]);body=state['candidates'][0]['article']
        q.repair_independence_protocol_v4(state)
        self.assertEqual(state['candidates'][0]['status'],'preparing');self.assertIs(state['candidates'][0]['article'],body)
        self.assertEqual(state['candidates'][0]['progress']['article_repair_count'],2)
        self.assertEqual(state['candidates'][1],before);self.assertEqual(state['_quota_snapshot']['requests'],144)
        state['candidates'][0]['status']='needs_review';q.repair_independence_protocol_v4(state)
        self.assertEqual(state['candidates'][0]['status'],'needs_review')

    def test_diagnostics_classify_only_concerns_not_technical_identifier_names(self):
        stream=io.StringIO()
        with redirect_stdout(stream):e.review_diagnostic('editorial_checked',{'approve':True,'issues':[],
            'unresolved':[],'covered_ids':['facts','date','PRIVATE_IDENTIFIER']},independence=True)
        value=json.loads(stream.getvalue().split('] ',1)[1]);self.assertEqual(value['categories'],['INDEPENDENCE'])
        self.assertTrue(value['approve']);self.assertFalse(value['coverage_complete'])
        self.assertNotIn('PRIVATE_IDENTIFIER',stream.getvalue())

    def test_legacy_extra_checks_require_all_four_positive_checks_and_no_concerns(self):
        result={'approve':True,'issues':[],'unresolved':[],
                'covered_ids':list(c.INDEPENDENCE_FIELDS)+['facts','date']}
        normalized=c.legacy_independence_response(result)
        self.assertEqual(normalized['covered_ids'],list(c.INDEPENDENCE_FIELDS));self.assertEqual(normalized['legacy_acknowledgments'],result['covered_ids'])
        for change in ({'covered_ids':['composition','facts']},{'approve':False},{'issues':['Real concern']},{'unresolved':['Missing evidence']}):
            self.assertIsNone(c.legacy_independence_response(dict(result,**change)))

    def test_local_positive_revalidation_requires_identical_reviewed_body_and_every_gate(self):
        from scripts.test_special003r import complete_special
        from scripts import editorial41 as e
        state=complete_special();state['all_sources_independence_revision']=1;r=state['candidates'][0]
        r['category_hint']=r['article']['category'];r['status']='needs_review'
        for i,block in enumerate(r['article']['blocks']):block['id']='s/'+str(i)
        fp=e.article_hash(r['article'],r['source'],r['rights'])
        for name in ('content_prepared','fact_checked','completeness_checked'):r['checks'][name]['input_hash']=fp
        parts=c.chunks(r['article']['blocks'])
        r['progress']['reviews']={'editorial_checked':{'input_hash':fp,'parts':{part['id']:{'approve':True,'issues':[],'unresolved':[],'covered_ids':[part['id']]} for part in parts}}}
        r['rejected_part']={'scope':'article_independence','result':{'approve':True,'issues':[],'unresolved':[],
            'covered_ids':list(c.INDEPENDENCE_FIELDS)+['facts']}}
        before=copy.deepcopy(r['article']);self.assertTrue(q.recover_complete_independence(state,r))
        self.assertEqual(r['article'],before);self.assertEqual(r['status'],'ready')
        r['article']['blocks'][0]['text']+=' Changed after review'
        self.assertFalse(q.recover_complete_independence(state,r))
