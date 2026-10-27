"""Reader-visible title and teaser cannot bypass factual or copyright review."""
import copy,json,unittest
from scripts import content41 as c,editorial41 as e,policy41 as p,rights41,special_contract41 as sc
from scripts.test_policy41 import record
from scripts.test_special003r import complete_special


class ReaderMetadataTests(unittest.TestCase):
    def test_title_and_teaser_are_distinct_review_parts_alongside_complete_body(self):
        r=record();r['article']['teaser']='A reader-visible assertion'
        parts=c.review_parts(r['article'],r)
        self.assertIn('reader-meta/title',{part['block_id'] for part in parts})
        self.assertIn('reader-meta/teaser',{part['block_id'] for part in parts})
        self.assertEqual({part['id'] for part in c.chunks(r['article']['blocks'])},
            {part['id'] for part in parts if not part['block_id'].startswith('reader-meta/')})

    def test_attributed_teaser_error_repairs_only_header_and_repeats_all_gates(self):
        r=record();r['mode']=r['article']['mode']='INDEPENDENT_ARTICLE';r['rights']=rights41.decision(r['source'],r['mode'])
        r['article'].update(title='Own title',teaser='UNSUPPORTED_TEASER',blocks=[{'id':'s/0','kind':'paragraph','text':'Самостоятельное учебное объяснение.'}])
        r['claims']=[{'id':'claim','source_id':r['source']['id'],'quote':r['source']['blocks'][-1]['text'],'fact':'A supported synthetic assertion','sensitive':False}]
        fp=e.article_hash(r['article'],r['source'],r['rights'])
        for name in p.STAGES:r['checks'][name]={'approved':True,'input_hash':fp}
        r['checks']['source_verified']['input_hash']=p.digest({'source':r['source']['content_hash'],'rights':r['rights'],'images':[]})
        body=copy.deepcopy(r['article']['blocks']);calls=[]
        state=e.new_state('2026-10-27');other=record(1);state['candidates']=[r,other];untouched=copy.deepcopy(other)
        def model(prompt,**kwargs):
            schema=kwargs['schema'];calls.append(schema)
            if schema=='v41_fact_inventory':return {'finished':True,'items':[{'id':'f1','finished':True,'kind':'unprotected_fact',
                'subject':'Fixture','relation':'supports','value':'Synthetic fact','qualifiers':[],'reason':''}]}
            if schema=='v41_header':return {'finished':True,'title':'Own supported title','teaser':'Supported teaser'}
            if schema=='v41_independence':return {'approve':True,'issues':[],'unresolved':[],**{key+'_checked':True for key in c.INDEPENDENCE_FIELDS}}
            self.assertEqual(schema,'v41_review')
            part=json.loads(prompt.split('\nЧасть: ')[1].split('\nПроверенные')[0]);members=part.get('pieces',[part])
            affected=[member['id'] for member in members if member['text']=='UNSUPPORTED_TEASER']
            return {'approve':not affected,'issues':['Unsupported teaser claim'] if affected else [],'unresolved':[],
                    'covered_ids':[member['id'] for member in members],'affected_ids':affected}
        e.Editor(call=model).finish(state,r)
        self.assertEqual(r['status'],'ready');self.assertEqual(r['article']['blocks'],body);self.assertEqual(other,untouched)
        self.assertEqual(calls.count('v41_header'),1);self.assertNotIn('v41_section',calls)
        self.assertEqual(r['progress']['repair_count'],1);self.assertNotIn('article_repair_count',r['progress'])
        for name in ('fact_checked','completeness_checked','editorial_checked'):
            self.assertEqual(r['checks'][name]['review_scope'],c.READER_REVIEW_SCOPE)

    def test_production_special_contract_requires_header_review_even_if_old_checks_pass(self):
        state=complete_special();state['header_review_revision']=2
        with self.assertRaisesRegex(p.Blocked,'SPECIAL_READER_HEADER_REVIEW_REQUIRED'):e.validate_issue(state)
        for r in state['candidates']:
            for name in ('fact_checked','completeness_checked','editorial_checked'):r['checks'][name]['review_scope']=c.READER_REVIEW_SCOPE
            r['progress'].setdefault('reviews',{}).setdefault('editorial_checked',{})['independence_scope']=c.INDEPENDENCE_REVIEW_SCOPE
        self.assertTrue(e.validate_issue(state))
