"""Independent commissions retain the original reference without copying its inventory."""
import copy,unittest
from unittest.mock import patch
from scripts import special003r as runner,special_contract41 as sc,special_priority41 as q,policy41 as p,publication41 as pub
from scripts.test_policy41 import record,source


class IndependentBasisTests(unittest.TestCase):
    def test_neutral_fact_base_excludes_original_selection_and_requires_all_supports(self):
        plan={'fact_base_urls':['development','safety']}
        evidence={'original':{'claims':[{'fact':'Original protected selection'}]},
                  'development':{'claims':[{'fact':'General developmental principle','source_id':'dev'}]},
                  'safety':{'claims':[{'fact':'Verified safety principle','source_id':'safe'}]}}
        facts=runner.neutral_fact_base(plan,evidence)
        self.assertEqual(len(facts),2);self.assertNotIn('Original protected selection',str(facts))
        facts[0]['fact']='Changed';self.assertEqual(evidence['development']['claims'][0]['fact'],'General developmental principle')
        with self.assertRaises(p.Blocked):runner.neutral_fact_base(plan,{'development':evidence['development']})

    def test_hundred_flowers_are_not_hundred_shades(self):
        self.assertTrue(runner.unsupported_palette('На фасаде будут 100 различных оттенков.'))
        self.assertTrue(runner.unsupported_palette('Используют сотню цветовых вариантов.'))
        self.assertFalse(runner.unsupported_palette('Фасад украсят почти 100 цветов из стеклофибробетона. Акцент — синий.'))

    def test_definition_migration_changes_only_two_commissions_and_keeps_request_counters(self):
        old=copy.deepcopy(sc.definition());slot=old['slots'][1]
        slot.pop('replacement_topic');slot['requirements']=slot['requirements'][:1]
        slot['evidence_plan']['support']=slot['evidence_plan']['support'][:1]
        for key in ('public_citation_urls','commission_revision'):slot['evidence_plan'].pop(key)
        old['slots'][2].pop('evidence_plan')
        self.assertEqual(p.digest(old),runner.PREVIOUS_BASIS_HASH)
        with patch.object(sc,'definition',return_value=old):state=runner.new_state()
        first=state['candidates'][0];first['status']='ready';first['article']={'title':'Synthetic accepted'}
        state['candidates'][1]['progress']['article_repair_count']=2
        state['candidates'][1]['model_usage']={'v41_section':{'http_requests':11}}
        state['_quota_snapshot']={'day':'2026-10-27','requests':120}
        runner.refresh_definition(state)
        self.assertIs(state['candidates'][0],first);self.assertEqual(state['_quota_snapshot']['requests'],120)
        self.assertEqual([x['special_slot'] for x in state['prior_source_plans']],[2,3])
        self.assertEqual(state['candidates'][1]['progress']['article_repair_count'],2)
        self.assertEqual(state['candidates'][1]['model_usage']['v41_section']['http_requests'],11)
        self.assertTrue(sc.is_special(state))

    def test_pending_other_topics_continue_but_exhausted_terminal_issue_releases_daily(self):
        state=runner.new_state();q.reconcile(state);state['candidates'][1]['status']='needs_review'
        self.assertTrue(q.reconcile(state)[0])
        for r in state['candidates']:
            if r['status']!='needs_review':r['status']='ready'
        self.assertFalse(q.reconcile(state)[0]);self.assertFalse(state.get('publication_verified'))

    def test_only_explicit_public_citation_metadata_is_projected(self):
        r=record();public=source(2);private=source(3)
        public['PRIVATE_DOSSIER']='Hidden';public['blocks'][0]['text']='DO_NOT_EXPORT_SOURCE_BODY'
        r['supporting_sources']=[public,private];r['public_reference_urls']=[public['url']]
        projected=pub.public_article(r);self.assertEqual(len(projected['public_references']),1)
        self.assertNotIn('PRIVATE_DOSSIER',str(projected['public_references']))
        self.assertNotIn('DO_NOT_EXPORT_SOURCE_BODY',str(projected['public_references']))
        block=pub.source_block(projected);self.assertIn(public['url'],block);self.assertNotIn(private['url'],block)
        self.assertEqual(block.count('class="source-primary"'),1)

    def test_independence_audit_compares_full_supporting_originals_and_can_veto(self):
        import json
        from scripts import editorial41 as e,rights41
        r=record();r['mode']=r['article']['mode']='INDEPENDENT_ARTICLE';r['rights']=rights41.decision(r['source'],r['mode'])
        r['article']['blocks']=[{'id':'s/0','kind':'paragraph','text':'Новый самостоятельный учебный рассказ.'}];r['checks']={}
        companion=source(2,text='SYNTHETIC_SUPPORT_EXPRESSION');r['supporting_sources']=[companion]
        def model(prompt,**kwargs):
            if prompt.startswith('Проверка самостоятельности'):
                self.assertIn('SYNTHETIC_SUPPORT_EXPRESSION',prompt)
                return {'approve':False,'issues':['Synthetic support expression concern'],'unresolved':[],
                        'covered_ids':['composition','wording','examples','explanations'],'affected_ids':[]}
            part=json.loads(prompt.split('\nЧасть: ')[1].split('\nПроверенные')[0])
            return {'approve':True,'issues':[],'unresolved':[],'covered_ids':[x['id'] for x in part.get('pieces',[part])],'affected_ids':[]}
        with self.assertRaisesRegex(p.Blocked,'REVIEW_REJECTED'):e.Editor(call=model).review(e.new_state('2026-10-27'),r,'editorial_checked')
        self.assertNotIn('editorial_checked',r['checks'])


    def test_vm_complete_end_marked_body_excludes_recommendation_and_lazy_articles(self):
        from scripts import source41
        url='https://vm.ru/moscow/1340223-publication'
        html='<html lang="ru"><head><title>Full publication</title><meta property="og:title" content="Full publication"></head><body><main>'
        html+='<article class="topic"><p>Unrelated recommendation</p></article>'
        html+='<div class="article marticle_first"><h1>Full publication</h1><div class="article-view with-end-mark"><p>Full introduction.</p>'
        html+=''.join('<h3>Section '+str(i)+'</h3><p>Complete section '+str(i)+'.</p>' for i in range(7))+'<p>FINAL_FULL_BODY</p></div></div>'
        html+='<div class="article lazyarticle"><article><p>Not part of this article</p></article></div></main></body></html>'
        result=source41.extract(html,url);text=' '.join(b['text'] for b in result['blocks'])
        self.assertIn('FINAL_FULL_BODY',text);self.assertIn('Complete section 6.',text)
        self.assertNotIn('Unrelated recommendation',text);self.assertNotIn('Not part of this article',text)
        self.assertEqual(result['extraction_method'],'vm_complete_publication')

    def test_vm_missing_end_marker_or_truncated_body_never_becomes_full_original(self):
        from scripts import source41
        url='https://vm.ru/moscow/1340223-publication'
        for html in ('<html><body><div class="marticle_first"><div class="article-view"><p>Only a fragment.</p></div></div></body></html>',
                     '<html><body><div class="marticle_first"><div class="article-view with-end-mark"><p>Truncated'):
            with self.assertRaisesRegex(p.Blocked,'SOURCE_EXTRACTION_PARTIAL'):source41.extract(html,url)
