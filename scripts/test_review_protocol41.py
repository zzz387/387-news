"""Review transport must never be confused with factual/editorial approval."""
import copy,unittest
from scripts import content41 as c,editorial41 as e,policy41 as p,special003r as runner,special_priority41 as q
from scripts.test_policy41 import record


class ReviewProtocolTests(unittest.TestCase):
    def test_short_ids_bind_every_part_and_unknown_missing_duplicate_ids_fail(self):
        group=[{'id':'long-first:0:10','text':'first','kind':'paragraph','block_id':'first'},
               {'id':'long-second:0:20','text':'second','kind':'paragraph','block_id':'second'}]
        wire,aliases=c.review_wire(group);self.assertEqual([x['id'] for x in wire['pieces']],['p1','p2'])
        result=c.restore_review_ids({'covered_ids':['p1','p2'],'affected_ids':['p2'],'approve':False},aliases)
        self.assertEqual(result['covered_ids'],[x['id'] for x in group]);self.assertFalse(result['approve'])
        for ids in (['p1'],['p1','p1'],['p1','p99']):
            with self.assertRaisesRegex(p.Blocked,'REVIEW_PROTOCOL_INVALID'):c.restore_review_ids({'covered_ids':ids},aliases)

    def test_transport_retry_does_not_rewrite_article_or_accept_false_review(self):
        import json
        r=record();r['checks']={};responses=[]
        def call(prompt,**kwargs):
            part=json.loads(prompt.split('\\nЧасть: '.replace('\\n','\n'))[1].split('\nПроверенные')[0]);ids=[x['id'] for x in part.get('pieces',[part])]
            responses.append(ids)
            return {'approve':True,'issues':[],'unresolved':[],'covered_ids':['wrong'] if len(responses)==1 else ids,'affected_ids':[]}
        before=copy.deepcopy(r['article']);e.Editor(call=call).review(e.new_state('2026-10-27'),r,'fact_checked')
        self.assertEqual(len(responses),1+len(c.operation_groups(c.review_parts(r['article'],r))));self.assertEqual(r['article'],before)
        self.assertNotIn('article_repair_count',r['progress']);self.assertTrue(r['checks']['fact_checked']['approved'])

    def test_outline_requirement_strings_canonicalize_but_unknown_refs_cannot_reach_writer(self):
        r=record();r['requirements']=['Specific verified question'];r['claims']=[{'id':'f'}]
        outline={'category':'Наука','sections':[{'id':'s','fact_ids':['f'],'requirement_ids':['Specific verified question'],'activity_count':0}]}
        c.validate_outline(outline,r);self.assertEqual(outline['sections'][0]['requirement_ids'],['r1'])
        outline['sections'][0]['requirement_ids']=['unknown']
        with self.assertRaisesRegex(p.Blocked,'OUTLINE_REQUIREMENT_REFERENCE_INVALID'):c.validate_outline(outline,r)

    def test_protocol_migration_requeues_only_formal_refusal_preserving_ready_article(self):
        state=runner.new_state();q.reconcile(state)
        r=record();r.update(special_slot=2,status='needs_review',history=[{'code':'REVIEW_REJECTED'}])
        r['rejected_part']={'stage':'fact_checked','block_id':'','result':{'covered_ids':['wrong'],'approve':True}}
        state['candidates'][1]=r;state['candidates'][0]['status']='ready';before=copy.deepcopy(state['candidates'][0])
        q.reconcile(state);q.repair_protocol_v3(state)
        self.assertEqual(r['status'],'preparing');self.assertTrue(q.reconcile(state)[0]);self.assertEqual(state['candidates'][0],before)
        r['status']='needs_review';q.repair_protocol_v3(state);self.assertEqual(r['status'],'needs_review')
