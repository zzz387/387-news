"""Synthetic final-check transport regressions; no real API/private corpus."""
import copy,unittest
from unittest.mock import patch
from scripts import editorial43 as e,special43 as s,policy41 as p
from scripts.test_daily43 import verdict,state,ready
from scripts.test_policy41 import record
from scripts.test_special43 import ready_issue

class ReviewWireTests(unittest.TestCase):
    def test_short_ids_bind_back_to_real_records(self):
        r=record();wire,aliases=e.review_wire(r);b=r['source']['blocks'][-1]
        self.assertEqual(wire[0]['id'],'s1');self.assertEqual(len(wire[0]['blocks']),len(r['source']['blocks']))
        self.assertEqual(e.bind_witness('s1','q'+str(len(r['source']['blocks'])),b['text'],[r['source']],aliases),(r['source']['id'],b['id'],b['text']))

    def test_only_literal_unambiguous_locations_can_repair_ids(self):
        r=record();r['source']['blocks']=[{'id':'real','text':'Measured 12\n people.'}]
        sources=[r['source']];_,aliases=e.review_wire(r)
        self.assertEqual(e.bind_witness('s1','wrong','12 people.',sources,aliases)[2],'12\n people.')
        self.assertIsNone(e.bind_witness('s1','q1','13 people.',sources,aliases))
        self.assertIsNone(e.bind_witness('s1','q1','12 people!',sources,aliases))
        r['source']['blocks'].append({'id':'second','text':'Measured 12\n people.'})
        self.assertIsNone(e.bind_witness('s1','wrong','12 people.',sources,aliases))

    def test_format_repair_retries_final_only_and_keeps_writer_counts(self):
        r=record();r['category_hint']='Наука';r['status']='preparing';before=copy.deepcopy(r['article']);calls=[]
        r['progress']['v43']={'write_attempts':3,'review_attempts':{'old':3},'history':[]}
        def model(prompt,**kw):
            calls.append(kw['schema']);v=verdict(prompt,r);v.pop('input_hash')
            if len(calls)==1:v['claims'][0]['quote']='Unmatched literal'
            else:v['claims'][0].update(source_id='s1',evidence_id='q'+str(len(r['source']['blocks'])))
            return v
        e.Editor(call=model).finish(state(),r)
        self.assertEqual(calls,['v43_final','v43_final']);self.assertTrue(e.eligible(r));self.assertEqual(r['article'],before)
        self.assertEqual(r['progress']['v43']['write_attempts'],3);self.assertEqual(r['progress']['v43']['review_attempts']['old'],3)

    def test_unbound_witnesses_stop_after_three_final_calls_and_restore_does_not_repeat(self):
        r=record();r['category_hint']='Наука';calls=[]
        def model(prompt,**kw):
            calls.append(kw['schema']);v=verdict(prompt,r);v['claims'][0]['quote']='Not in source';return v
        for attempt in range(2):
            with self.assertRaisesRegex(p.Blocked,'FINAL_REVIEW_ATTEMPTS_EXHAUSTED'):e.Editor(call=model).finish(state(),r)
            r=copy.deepcopy(r)
        self.assertEqual(calls,['v43_final']*3);self.assertFalse(e.eligible(r))

    def test_changed_synchronous_input_never_gets_a_gate(self):
        r=record();r['category_hint']='Наука'
        def model(prompt,**kw):
            v=verdict(prompt,r);r['article']['teaser']='Changed while review was in flight';return v
        with self.assertRaisesRegex(p.Blocked,'REVIEW_INPUT_CHANGED'):e.Editor(call=model).finish(state(),r)
        self.assertNotIn('final43',r['checks'])

    def test_addressed_migration_never_overrides_a_real_veto_or_resets_counts(self):
        issue=ready_issue();issue['_quota_snapshot']={'requests':43};before=copy.deepcopy(issue['candidates'][1:])
        row=issue['candidates'][0];row['status']='needs_review';row['progress']['v43']={'write_attempts':3,'review_attempts':{'old':3},'history':[{'approve':True,**{k:True for k in e.CHECKS},'issues':[],'unresolved':[]}]}
        s.repair_review_protocol_v2(issue)
        self.assertEqual(row['status'],'preparing');self.assertEqual(row['progress']['v43']['write_attempts'],3)
        self.assertEqual(issue['_quota_snapshot'],{'requests':43});self.assertEqual(issue['candidates'][1:],before)
        issue.pop('special43_review_v2');row['status']='needs_review';row['progress']['v43']['history'][-1]['safety']=False
        s.repair_review_protocol_v2(issue);self.assertEqual(row['status'],'needs_review')

    def test_identical_full_material_can_survive_transport_ids_but_real_changes_invalidate_only_one(self):
        for kind in ('transport','text','date','structure'):
            with self.subTest(kind=kind):
                issue=ready_issue();target=issue['candidates'][0];target['mode']='INDEPENDENT_ARTICLE';url=target['source']['url'];before=copy.deepcopy(issue['candidates'][1:])
                originals=iter(copy.deepcopy([src for row in issue['candidates'] for src in [row['source']]+row.get('supporting_sources',[])]))
                def fetch(address):
                    source=next(originals);self.assertEqual(address,source['url'])
                    current=copy.deepcopy(source)
                    if address==url:
                        current['content_hash']='changed'
                        if kind=='transport':
                            for block in current['blocks']:block['id']='transport-'+block['id']
                        if kind=='text':current['blocks'][-1]['text']+=' Additional material fact.'
                        if kind=='date':current['published']='2026-10-25'
                        if kind=='structure':current['blocks'][-1]['kind']='heading'
                    return current
                with patch.object(s.source41,'fetch',side_effect=fetch):
                    if kind=='transport':s.verify_sources(issue,lambda:None);self.assertEqual(target['status'],'ready')
                    else:
                        with self.assertRaisesRegex(p.Blocked,'SPECIAL43_SOURCE_CHANGED_REVIEW_REQUIRED'):s.verify_sources(issue,lambda:None)
                        self.assertEqual(target['status'],'preparing');self.assertNotIn('article',target)
                self.assertEqual(issue['candidates'][1:],before)


class DatedContextRepairTests(unittest.TestCase):
    def fixture(self):
        r=ready(5);r.update(special_slot=6,status='needs_review',category='Наука',kind='Самостоятельная заметка',high_risk=False,commission={})
        v={'approve':True,**{k:True for k in e.CHECKS},'issues':[],'unresolved':[],
           'is_news':True,'event_date':'2020-01-01','event_source_id':r['source']['id'],
           'event_evidence_id':r['source']['blocks'][-1]['id'],'event_quote':r['source']['blocks'][-1]['text']}
        r['progress']['v43']={'write_attempts':3,'review_attempts':{'old':3},'history':[v]}
        issue=state();issue.update(candidates=[r],status='BLOCKED',block_code='SPECIAL43_TOPICS_NEED_REVIEW',_quota_snapshot={'requests':46})
        return issue,r

    def test_true_news_date_is_still_required_and_reason_is_precise(self):
        issue,r=self.fixture();codes=e.news_errors(r['progress']['v43']['history'][-1],r,issue)
        self.assertIn('NEWS_EVENT_TOO_OLD',codes);self.assertIn('NEWS_EVENT_DATE_NOT_IN_WITNESS',codes)
        v=copy.deepcopy(r['progress']['v43']['history'][-1]);v['is_news']=False
        self.assertEqual(e.news_errors(v,r,issue),[])

    def test_one_addressed_write_then_fresh_review_preserves_all_old_counters(self):
        issue,r=self.fixture();s.repair_dated_context_v1(issue);calls=[];before=copy.deepcopy(r['article'])
        def model(prompt,**kw):
            calls.append(kw['schema'])
            if kw['schema']=='v43_article':return {'finished':True,'title':'Датированный разбор','teaser':'','blocks':[{'kind':'paragraph','text':'Самостоятельное ретроспективное объяснение результатов.'}]}
            return verdict(prompt,r)
        with patch.object(s.Editor,'verify_source',return_value=None):s.Editor(call=model).finish(issue,r)
        self.assertEqual(calls,['v43_article','v43_final']);self.assertTrue(e.eligible(r));self.assertEqual(r['progress']['v43']['write_attempts'],3)
        self.assertEqual(r['progress']['v43']['review_attempts']['old'],3);self.assertIn(before,r['progress']['v43']['previous_articles'])
        self.assertEqual(r['special43_dated_context_v1']['attempts'],1);self.assertEqual(issue['_quota_snapshot'],{'requests':46})
        r['status']='needs_review';s.repair_dated_context_v1(issue);self.assertEqual(r['status'],'needs_review')

    def test_substantive_veto_cannot_get_extra_repair_and_incomplete_repair_cannot_repeat(self):
        issue,r=self.fixture();r['progress']['v43']['history'][-1]['facts']=False;s.repair_dated_context_v1(issue)
        self.assertNotIn('special43_dated_context_v1',r)
        r['progress']['v43']['history'][-1]['facts']=True;s.repair_dated_context_v1(issue);calls=[]
        with patch.object(s.Editor,'verify_source',return_value=None):
            for code in ('DATED_CONTEXT_REPAIR_INCOMPLETE','DATED_CONTEXT_REPAIR_EXHAUSTED'):
                with self.assertRaisesRegex(p.Blocked,code):s.Editor(call=lambda *a,**k:(calls.append(1) or {'finished':False})).finish(issue,r)
        self.assertEqual(len(calls),1);self.assertEqual(r['progress']['v43']['write_attempts'],3)

if __name__=='__main__':unittest.main()
