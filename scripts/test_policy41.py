"""Synthetic v4.1 contracts. No network, proprietary corpus, Secrets or model calls."""
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import policy41 as p, source41 as src, rights41 as rights
from scripts import content41 as c, editorial41 as e, publication41 as pub


def source(number=0, language='ru', text='Законченная вымышленная история.'):
    html=('<html lang="'+language+'"><head><meta name="author" content="Автор фикстуры">'
          '<meta property="article:published_time" content="2026-10-26">'
          '<link rel="license" href="https://creativecommons.org/licenses/by/4.0/"></head>'
          '<body><article><h1>История '+str(number)+'</h1><p>'+text+'</p></article></body></html>')
    result=src.extract(html,'https://example.org/story/'+str(number))
    # Fixed documentary check timestamp makes rights fingerprints reproducible.
    result['access_checked_at']='2026-10-26T00:00:00+00:00'
    return result


def record(number=0):
    s=source(number); mode='ORIGINAL_REPUBLICATION'; r=rights.decision(s,mode)
    article={'title':s['title'],'teaser':'','category':p.CATEGORIES[number%len(p.CATEGORIES)],
             'kind':'статья','mode':mode,'source_id':s['id'], 'activities':[],
             'blocks':[dict(b,source_block_id=b['id']) for b in s['blocks']],
             'primary_source':{k:s[k] for k in ('url','title','publisher','author','published')},
             'attribution':r['attribution'],'images':[]}
    result={'id':str(number),'url':s['url'],'source':s,'rights':r,'mode':mode,'images':[],
            'article':article,'status':'ready','topic_key':'different topic '+str(number),
            'claims':[], 'requirements':[], 'checks':{},'progress':{'analysis':{}},'history':[]}
    fingerprint=e.article_hash(article,s,r)
    for gate in p.STAGES:
        result['checks'][gate]={'approved':True,'input_hash':fingerprint}
    result['checks']['source_verified']['input_hash']=p.digest({'source':s['content_hash'],'rights':r,'images':[]})
    return result


def issue():
    state=e.new_state('2026-10-27'); state['candidates']=[record(i) for i in range(12)]
    state['selected_ids']=[r['id'] for r in state['candidates']]
    state['audit_passed']=True
    state['issue_approval_hash']=p.digest([e.article_hash(r['article'],r['source'],r['rights']) for r in state['candidates']])
    return state


class ExtractionTests(unittest.TestCase):
    def test_full_long_source_no_clipping(self):
        text='Полный учебный текст. '*5000+'ПОСЛЕДНЯЯ ОГОВОРКА'
        s=source(text=text)
        self.assertEqual(s['blocks'][-1]['text'],text.strip())
        self.assertEqual(''.join(x['text'] for x in c.chunks(s['blocks']) if x['block_id']==s['blocks'][-1]['id']),text.strip())

    def test_partial_paywall_pagination_and_ambiguous_rejected(self):
        for html in ('<html><article><p>Оборвано',
                     '<html><article><p>Текст</p></article><div class="paywall"></div></html>',
                     '<html><link rel="next" href="/2"><article><p>Текст</p></article></html>',
                     '<html><article><p>Один</p></article><article><p>Два</p></article></html>'):
            with self.subTest(html=html),self.assertRaises(p.Blocked): src.extract(html,'https://example.org/')

    def test_robots_and_unavailable_never_fall_back_to_rss(self):
        with self.assertRaisesRegex(p.Blocked,'ROBOTS_FORBIDDEN'):
            src.fetch('https://example.org/private',get=lambda url:'User-agent: *\nDisallow: /')
        with self.assertRaisesRegex(p.Blocked,'ROBOTS_UNVERIFIED'):
            src.fetch('https://example.org/private',get=lambda url:(_ for _ in ()).throw(OSError('offline')))

    def test_missing_metadata_requires_review(self):
        result=src.extract('<html><article><h1>Тема</h1><p>Полный текст.</p></article></html>','https://example.org/')
        with self.assertRaisesRegex(p.Blocked,'SOURCE_NEEDS_REVIEW'): rights.select_mode(result)


class RightsTests(unittest.TestCase):
    def test_unknown_unicef_is_not_permission(self):
        s=source(); s.update(url='https://www.unicef.org/example',declared_license=None)
        for mode in ('ORIGINAL_REPUBLICATION','FULL_TRANSLATION'):
            self.assertEqual(rights.decision(s,mode,[])['status'],'unknown')
        self.assertEqual(rights.select_mode(s,[])[0],'INDEPENDENT_ARTICLE')
        s['rights_review_required']=True
        with self.assertRaisesRegex(p.Blocked,'RIGHTS_NEEDS_REVIEW'): rights.select_mode(s,[])

    def test_mode_selection_and_human_grant(self):
        self.assertEqual(rights.select_mode(source())[0],'ORIGINAL_REPUBLICATION')
        self.assertEqual(rights.select_mode(source(language='en'))[0],'FULL_TRANSLATION')
        s=source(); s['declared_license']=None
        permit={'status':'allowed','evidence_url':'https://example.org/permission','checked_by':'owner',
                'checked_at':'2026-10-26','basis':'Documented independent factual use',
                'verification':'human_documented'}
        grants=[{'url':s['url'],'content_hash':s['content_hash'],'uses':{'INDEPENDENT_ARTICLE':permit}}]
        self.assertEqual(rights.select_mode(s,grants)[0],'INDEPENDENT_ARTICLE')
        permit['verification']='model_confidence'
        self.assertEqual(rights.select_mode(s,grants)[1]['verification'],'unprotected_facts_rule_v2')

    def test_separate_image_rights_and_license_conditions(self):
        self.assertEqual(rights.image_decision({'url':'https://example.org/photo','sha256':'abc'},[])['status'],'unknown')
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(p.Blocked,'IMAGE_RIGHTS_UNKNOWN'):
            pub.images_valid({'images':[{'url':'https://example.org/photo','sha256':'abc'}]},Path(root))
        s=source(language='en'); r=rights.decision(s,'FULL_TRANSLATION'); r['conditions']=['no_modifications']
        with self.assertRaisesRegex(p.Blocked,'LICENSE_MODIFICATION_FORBIDDEN'): rights.require(s,'FULL_TRANSLATION',r)

    def test_revoked_grant_invalidates_ready_issue(self):
        state=issue()
        with patch.object(rights,'decision',return_value={'status':'forbidden'}),self.assertRaisesRegex(p.Blocked,'RIGHTS_REVIEW_STALE'):
            e.validate_issue(state)


class TranslationTests(unittest.TestCase):
    def test_lists_headings_and_final_caveat_survive_translation_and_html(self):
        s=source(text='Пример.</p><h3>Порядок</h3><ol start="3"><li>Шаг один.</li><li>Шаг два.</li></ol><p>Финальная оговорка.')
        def model(prompt,**kwargs):
            part=json.loads(prompt.split('Техническая часть исходника: ')[1].split('. Верни finished')[0])
            return {'finished':True,'segments':[{'id':member['id'],'text':member['text']} for member in part.get('pieces',[part])]}
        blocks=c.complete_translation(s,{},model)
        article={'title':s['title'],'teaser':'','mode':'FULL_TRANSLATION','category':'Семья','kind':'статья',
                 'blocks':blocks,'activities':[],'images':[],'slug':'lists',
                 'primary_source':{k:s[k] for k in ('url','title','publisher','author','published')},'attribution':{}}
        self.assertTrue(c.semantic_structure(article,s))
        with tempfile.TemporaryDirectory() as directory:
            html=pub.render_article('2026-10-27',1,article,Path(directory))
        self.assertIn('<ol start="3"><li>Шаг один.</li><li>Шаг два.</li></ol>',html)
        self.assertIn('<h3>Порядок</h3>',html); self.assertIn('Финальная оговорка.',html)
        blocks[2]['heading_level']=2
        with self.assertRaisesRegex(p.Blocked,'SOURCE_STRUCTURE_CHANGED'): c.semantic_structure(article,s)

    def test_incomplete_response_repaired_without_length_norm(self):
        s=source(language='en'); progress={}; calls=[]
        def model(prompt,**kwargs):
            piece=json.loads(prompt.split('Техническая часть исходника: ')[1].split('. Верни finished')[0])
            calls.append(prompt)
            if len(calls)==1: return {'finished':False,'segments':[]}
            return {'finished':True,'segments':[{'id':piece['id'],'text':'Да.'}]}
        result=c.complete_translation(s,progress,model)
        self.assertEqual(len(result),len(s['blocks']))
        self.assertIn('Incomplete response',calls[1])
        self.assertTrue(all(b['text']=='Да.' for b in result))

    def test_interruption_resume_and_source_change(self):
        s=source(language='en',text='Текст '*2500); progress={}; calls=[]
        class Stop(Exception): pass
        def model(prompt,**kwargs):
            piece=json.loads(prompt.split('Техническая часть исходника: ')[1].split('. Верни finished')[0])
            calls.append(piece['id'])
            if len(calls)==2: raise Stop()
            return {'finished':True,'segments':[{'id':piece['id'],'text':piece['text']}]}
        with self.assertRaises(Stop): c.complete_translation(s,progress,model)
        # New object emulates an independent restored process, without a real private package.
        restored=json.loads(json.dumps(progress)); first=calls[0]
        result=c.complete_translation(s,restored,model)
        self.assertEqual(calls.count(first),1)
        self.assertEqual([b['text'] for b in result],[b['text'] for b in s['blocks']])
        s['content_hash']='changed'
        with self.assertRaisesRegex(p.Blocked,'TRANSLATION_SOURCE_CHANGED'): c.complete_translation(s,restored,model)

    def test_missing_block_and_original_modification(self):
        r=record(); a=copy.deepcopy(r['article']); a['blocks'].pop()
        with self.assertRaisesRegex(p.Blocked,'SOURCE_COVERAGE_INCOMPLETE'): c.semantic_structure(a,r['source'])
        a=copy.deepcopy(r['article']); a['blocks'][-1]['text']='Изменённый текст'
        with self.assertRaisesRegex(p.Blocked,'ORIGINAL_CHANGED'): c.semantic_structure(a,r['source'])


class SemanticTests(unittest.TestCase):
    def test_complete_source_to_ready_pipeline_for_original_and_translation(self):
        for language,mode in [('ru','ORIGINAL_REPUBLICATION'),('en','FULL_TRANSLATION')]:
            with self.subTest(mode=mode):
                s=source(language=language); calls=[]
                def model(prompt,**kwargs):
                    calls.append(kwargs['schema'])
                    if kwargs['schema']=='v41_analysis':
                        part=json.loads(prompt.split('Эта часть: ')[1].split('\nМетаданные: ')[0])
                        return {'claims':[{'id':'fact','source_id':s['id'],'quote':part['text'],
                            'fact':'Факт учебного оригинала','sensitive':False}], 'requirements':[],
                            'topic_key':'Учебный сюжет','event_date':'','event_date_quote':'','category':'Семья',
                            'kind':'статья','worth_publishing':True,'reader_value':'Вымышленный пример','covered_ids':[part['id']]}
                    if kwargs['schema']=='v41_translation':
                        part=json.loads(prompt.split('Техническая часть исходника: ')[1].split('. Верни finished')[0])
                        return {'finished':True,'segments':[{'id':member['id'],'text':member['text']} for member in part.get('pieces',[part])]}
                    self.assertEqual(kwargs['schema'],'v41_review')
                    part=json.loads(prompt.split('\nЧасть: ')[1].split('\nПроверенные')[0])
                    return {'approve':True,'issues':[],'unresolved':[],'covered_ids':[part['id']]}
                r={'id':s['id'],'url':s['url'],'status':'preparing','checks':{},'progress':{}}
                e.Editor(call=model,fetch=lambda url:s).finish(e.new_state('2026-10-27'),r)
                self.assertEqual(r['mode'],mode); self.assertEqual(r['status'],'ready')
                self.assertTrue(all(r['checks'][name]['approved'] for name in p.STAGES))
                self.assertEqual(calls.count('v41_review'),6)

    def test_technical_context_limit_never_sends_truncated_input(self):
        editor=e.Editor(call=lambda *a,**k:self.fail('Oversized operation must not be sent'))
        with patch.dict(p.CONFIG['technical'],{'context_characters':10}),self.assertRaisesRegex(p.Blocked,'OPERATION_CONTEXT_NEEDS_REVIEW'):
            editor.call('Полный исходник длиннее технического запроса',schema='v41_analysis')

    def article(self,count=21):
        r=record(); a=r['article']; a.update(mode='INDEPENDENT_ARTICLE',title='21 игра для семьи',
            blocks=[{'id':'own','kind':'paragraph','text':'Самостоятельная вступительная мысль о совместном времени.'}],activities=[])
        for i in range(count):
            a['activities'].append({'id':str(i),'title':'Игра '+str(i),'age':'Взрослый рядом',
              'materials':['Бумага'],'steps':['Положите лист на стол и нарисуйте круг '+str(i)+'.'],
              'benefit':'Совместное внимание','safety':'Не оставляйте ребёнка одного'})
        return a,r['source']

    def test_21_complete_games_pass_without_word_quota(self):
        a,s=self.article(); self.assertTrue(c.semantic_structure(a,s))

    def test_eight_games_and_21_names_fail(self):
        a,s=self.article(8)
        with self.assertRaisesRegex(p.Blocked,'PROMISED_ACTIVITIES_MISSING'): c.semantic_structure(a,s)
        a,s=self.article()
        for item in a['activities']: item['steps']=[item['title']]
        with self.assertRaisesRegex(p.Blocked,'ACTIVITY_NAME_IS_NOT_INSTRUCTION'): c.semantic_structure(a,s)

    def test_disguised_copy_repetition_and_internal_links(self):
        r=record(); a=copy.deepcopy(r['article']); a['mode']='INDEPENDENT_ARTICLE'
        for b in a['blocks']: b.pop('source_block_id')
        with self.assertRaisesRegex(p.Blocked,'DISGUISED_COPY'): c.semantic_structure(a,r['source'])
        a,s=self.article(); a['blocks']*=2
        with self.assertRaisesRegex(p.Blocked,'REPEATED_CONTENT'): c.semantic_structure(a,s)
        a,s=self.article(); a['blocks'][0]['text']='Проверка https://example.org/private'
        with self.assertRaisesRegex(p.Blocked,'INTERNAL_LINK_IN_BODY'): c.semantic_structure(a,s)

    def test_unresolved_or_incomplete_review_blocks(self):
        for result in ({'approve':True,'issues':[],'unresolved':['Unsafe advice'],'covered_ids':['x']},
                       {'approve':True,'issues':[],'unresolved':[],'covered_ids':[]}):
            with self.assertRaisesRegex(p.Blocked,'REVIEW_REJECTED'): c.approved_review(result,['x'])

    def test_dangerous_claim_requires_independent_authority(self):
        r=record(); r['article']['category']='Здоровье и движение'; r['checks'].pop('fact_checked')
        editor=e.Editor(call=lambda *a,**k:self.fail('Model cannot bypass evidence'),grants=[],images=[])
        with self.assertRaisesRegex(p.Blocked,'INDEPENDENT_SAFETY_EVIDENCE_REQUIRED'):
            editor.review(e.new_state('2026-10-27'),r,'fact_checked')


class IssueTests(unittest.TestCase):
    def test_v41_restore_validates_all_12_and_refuses_old_approval_flags(self):
        from scripts import restore_ready
        state=issue(); state.update(branch='codex/editorial-policy-v41',preview=True,stage='audited')
        self.assertEqual(restore_ready.validate_prepared(state),12)
        state['candidates'][0]['checks'].pop('completeness_checked')
        with self.assertRaisesRegex(p.Blocked,'ARTICLE_GATE_MISSING_OR_STALE'): restore_ready.validate_prepared(state)

    def test_controller_waits_until_six_and_late_retry_does_not_generate(self):
        state=issue(); state['stage']='audited'; calls=[]
        with tempfile.TemporaryDirectory() as directory,patch.object(pub,'build',return_value=False),patch.dict(
                'os.environ',{'GITHUB_REF_NAME':'main','NEWS_RELEASE_APPROVED':'true'}):
            ops=SimpleNamespace(ROOT=Path(directory),render=lambda *args:calls.append(args) or True)
            editor=e.Editor(call=lambda *a,**k:self.fail('Approved issue must not regenerate'))
            early=datetime.fromisoformat(state['date']+'T05:00').replace(tzinfo=p.TZ)
            self.assertFalse(e.advance(state,state['date'],False,ops,lambda:None,now=early,editor=editor))
            self.assertEqual(state['pipeline_status'],'WAITING_FOR_RELEASE_TIME'); self.assertEqual(calls,[])
            restored=json.loads(json.dumps(state))
            late=datetime.fromisoformat(state['date']+'T06:17').replace(tzinfo=p.TZ)
            self.assertTrue(e.advance(restored,state['date'],False,ops,lambda:None,now=late,editor=editor))
            self.assertEqual(len(calls),1)

    def test_budget_stop_preserves_all_candidates_and_ledger(self):
        from scripts import pipeline
        state=issue(); state['audit_passed']=False; state['discovered']=True
        saved=copy.deepcopy(state['candidates'])
        with tempfile.TemporaryDirectory() as directory,patch.object(pipeline,'capacity',return_value=False):
            ops=SimpleNamespace(ROOT=Path(directory),render=lambda *a:self.fail('Budget pause must not publish'))
            self.assertFalse(e.advance(state,state['date'],True,ops,lambda:None,
                editor=e.Editor(call=lambda *a,**k:self.fail('No quota'))))
        self.assertEqual(state['candidates'],saved); self.assertEqual(state['pipeline_status'],'READY_FOR_AUDIT')

    def test_source_disappearance_or_change_blocks_release(self):
        state=issue()
        with self.assertRaisesRegex(p.Blocked,'SOURCE_RELEASE_UNAVAILABLE'):
            e.verify_publication_sources(state,fetch=lambda url:(_ for _ in ()).throw(OSError('offline')))
        current=copy.deepcopy(state['candidates'][0]['source']); current['content_hash']='changed'
        with self.assertRaisesRegex(p.Blocked,'SOURCE_CHANGED_AFTER_REVIEW'):
            e.verify_publication_sources(state,fetch=lambda url:current)
        self.assertEqual(state['candidates'][0]['status'],'needs_review')
        self.assertTrue(all(r['status']=='ready' for r in state['candidates'][1:]))
        self.assertFalse(state['audit_passed'])
        from scripts import pipeline
        self.assertEqual(pipeline.report(state,{})['articles'],11)

    def test_only_failed_independent_section_is_repaired_then_all_gates_repeat(self):
        r=record(); r.pop('article'); r['mode']='INDEPENDENT_ARTICLE'
        r['rights']=rights.decision(r['source'],r['mode']); r['claims']=[{
            'id':'f1','source_id':r['source']['id'],'quote':r['source']['blocks'][-1]['text'],
            'fact':'Факт из учебной фикстуры','sensitive':False}]
        r['progress']['outline']={'title':'Собственный взгляд','teaser':'', 'category':'Семья','kind':'статья',
            'sections':[{'id':x,'heading':'Собственный раздел '+x,'purpose':'Объяснение','fact_ids':['f1']} for x in ('s1','s2')]}
        generated=[]; reviews=[]; failed=[]
        def model(prompt,**kwargs):
            if kwargs['schema']=='v41_section':
                section=json.loads(prompt.split('План раздела: ')[1].split('\nФакты: ')[0])
                generated.append(section['id'])
                return {'id':section['id'],'finished':True,'blocks':[{'kind':'paragraph',
                    'text':'Собственная завершённая мысль '+section['id']+str(len(generated))}],
                    'activities':[],'covered_requirements':[]}
            self.assertIn(kwargs['schema'],('v41_review','v41_independence'))
            if prompt.startswith('Проверка самостоятельности'):
                return {'approve':True,'issues':[],'unresolved':[],**{key+'_checked':True for key in c.INDEPENDENCE_FIELDS}}
            part=json.loads(prompt.split('\nЧасть: ')[1].split('\nПроверенные')[0]); members=part.get('pieces',[part]); reviews.extend(p['id'] for p in members)
            reject=any(member['block_id']=='s1/0' for member in members) and not failed
            if reject: failed.append(True)
            return {'approve':not reject,'issues':['Исправить конкретную мысль'] if reject else [],
                    'unresolved':[],'covered_ids':[member['id'] for member in members],
                    'affected_ids':[member['id'] for member in members if member['block_id']=='s1/0'] if reject else []}
        e.Editor(call=model).finish(e.new_state('2026-10-27'),r)
        self.assertEqual(generated.count('s1'),2); self.assertEqual(generated.count('s2'),1)
        self.assertEqual(r['status'],'ready'); self.assertEqual(r['progress']['repair_count'],1)
        self.assertTrue(all(r['checks'][name]['approved'] for name in p.STAGES))

    def test_12_required_categories_and_stale_checks(self):
        state=issue(); self.assertTrue(e.validate_issue(state))
        state['selected_ids'].pop()
        with self.assertRaisesRegex(p.Blocked,'TWELVE_READY_ARTICLES_REQUIRED'): e.validate_issue(state)
        state=issue(); state['candidates'][0]['article']['teaser']='Новое непроверенное утверждение'
        with self.assertRaisesRegex(p.Blocked,'ARTICLE_GATE_MISSING_OR_STALE'): e.validate_issue(state)

    def test_required_categories_and_features_are_not_quota(self):
        state=issue(); selected=e.select_ready(state)
        self.assertEqual(len(selected),12)
        self.assertTrue(all(r['article']['kind']=='статья' for r in selected))
        state['candidates']=[r for r in state['candidates'] if r['article']['category']!='Семья']
        self.assertEqual(e.select_ready(state),[])

    def test_semantic_duplicate_against_archive(self):
        r=record(); self.assertTrue(e.duplicate(r['article'],r,[{'topic_key':r['topic_key']}]))
        self.assertTrue(e.duplicate(r['article'],r,[{'source_url':r['source']['canonical']}]))

    def test_general_rejection_preserves_every_article_and_does_not_loop(self):
        state=issue(); state['audit_passed']=False; calls=[]
        def model(*args,**kwargs):
            calls.append(1)
            return {'approve':False,'covered_ids':state['selected_ids'],'issues':[
                {'code':'BALANCE','reason':'Composition unclear','article_ids':[], 'repair_ids':[],'action':'hold'}]}
        editor=e.Editor(call=model)
        for _ in range(2):
            with self.assertRaises(p.Blocked): e.approve_selection(state,state['candidates'],editor)
        self.assertEqual(len(calls),1)
        self.assertTrue(all(r['status']=='ready' for r in state['candidates']))

    def test_attributed_rejection_only_replaces_target_and_preserves_content(self):
        state=issue(); state['audit_passed']=False
        editor=e.Editor(call=lambda *a,**k:{'approve':False,'covered_ids':state['selected_ids'],'issues':[
            {'code':'DUPLICATE','reason':'Same event','article_ids':[2,5],'repair_ids':[5],'action':'replace_story'}]})
        saved=copy.deepcopy(state['candidates'])
        self.assertFalse(e.approve_selection(state,state['candidates'],editor))
        self.assertEqual([i+1 for i,r in enumerate(state['candidates']) if r['status']=='rejected'],[5])
        self.assertEqual([r['article'] for r in saved],[r['article'] for r in state['candidates']])

    def test_migration_keeps_old_draft_and_quota_without_grandfathered_approval(self):
        old={'version':31,'audit_passed':True,'articles':{'0':{'title':'Old'}},'_quota_snapshot':{'used':207}}
        new=e.migrate(old,'2026-10-27')
        self.assertEqual(new['legacy_v31'],old); self.assertEqual(new['_quota_snapshot'],{'used':207})
        self.assertFalse(new['audit_passed']); self.assertEqual(new['articles'],{})


class PublicationTests(unittest.TestCase):
    def test_long_reader_html_has_one_final_source_no_private_evidence(self):
        r=record(); s=source(text='Полное изложение. '*10000+'КОНЕЦ')
        r['source']=s; r['rights']=rights.decision(s,r['mode'])
        r['article']['blocks']=[dict(b,source_block_id=b['id']) for b in s['blocks']]
        r['supporting_sources']=[{'url':'https://example.org/INTERNAL-VERIFY'}]
        article=pub.public_article(r); article['slug']='fixture'
        with tempfile.TemporaryDirectory() as root:
            html=pub.render_article('2026-10-27',1,article,Path(root))
        self.assertTrue(pub.validate_page(html)); self.assertIn('КОНЕЦ',html)
        self.assertEqual(html.count('class="source-primary"'),1)
        self.assertNotIn('INTERNAL-VERIFY',html+pub.markdown(article))
        self.assertLess(html.index('КОНЕЦ'),html.index('class="source-primary"'))

    def test_synthetic_atomic_build_idempotence_and_history(self):
        state=issue()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            shutil.copytree(p.ROOT/'assets',root/'assets'); (root/'archive').mkdir(); (root/'issues').mkdir()
            (root/'archive/index.html').write_text('old archive'); (root/'index.html').write_text('old home')
            historical=root/'issues/2026-10-26'; historical.mkdir(); (historical/'index.html').write_text('immutable old issue')
            self.assertFalse(pub.build(state,root,preview=True)); self.assertEqual((root/'index.html').read_text(),'old home')
            self.assertTrue(pub.build(state,root)); self.assertEqual(pub.validate_local_release(root,state['date'])['count'],12)
            before={str(f.relative_to(root)):f.read_bytes() for f in root.rglob('*') if f.is_file()}
            self.assertTrue(pub.build(state,root))
            self.assertEqual(before,{str(f.relative_to(root)):f.read_bytes() for f in root.rglob('*') if f.is_file()})
            self.assertEqual((historical/'index.html').read_text(),'immutable old issue')
            self.assertFalse((root/'issues'/state['date']/'issue.json').exists())
            # Packager excludes all configuration and editorial code, including public grants.
            (root/'config').mkdir(); (root/'config/rights.json').write_text('technical only')
            from scripts import site_checks
            packaged=site_checks.package(root,root/'package')
            self.assertFalse((packaged/'config').exists()); self.assertFalse((packaged/'scripts').exists())
            shutil.rmtree(packaged); shutil.rmtree(root/'config')
            state['selected_ids'].pop()
            with self.assertRaises(p.Blocked): pub.build(state,root)
            self.assertEqual(before,{str(f.relative_to(root)):f.read_bytes() for f in root.rglob('*') if f.is_file()})

    def test_release_time_config_and_all_priority_topics(self):
        moment=datetime.fromisoformat('2026-10-27T'+p.RELEASE_TIME).replace(tzinfo=p.TZ)
        self.assertEqual(moment.astimezone(__import__('datetime').timezone.utc).hour,3)
        self.assertEqual(set(map(int,p.CONFIG['priority_topics'])),{1,2,3,6,7,8,9,10,11,12,13,14,15,16,17,18,21,22,23,24})
        css=(p.ROOT/'assets/style.css').read_text()
        self.assertNotRegex(css,r'(?:line-clamp|text-overflow\s*:\s*ellipsis)')

    def test_workflow_keeps_schedule_and_isolates_branch_from_secrets(self):
        workflow=(p.ROOT/'.github/workflows/daily-v31.yml').read_text()
        prepare=workflow.split('\n  prepare:',1)[1].split('\n  deploy:',1)[0]
        self.assertIn("if: ${{ github.ref == 'refs/heads/main' &&",prepare)
        self.assertIn("- cron: '54 2 * * *'",workflow)
        self.assertIn('NEWS_MAX_REQUESTS_PER_DAY: "220"',workflow)
        self.assertIn('NEWS_MAX_REQUESTS_PER_RUN: "24"',workflow)


if __name__=='__main__': unittest.main()
