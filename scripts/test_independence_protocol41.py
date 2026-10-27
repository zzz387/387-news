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
