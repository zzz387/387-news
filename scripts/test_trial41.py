"""Trial preparation regressions. All prose and credentials here are synthetic."""
import copy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import source41,rights41,content41 as c,editorial41 as e,policy41 as p
from scripts import generation_runtime as runtime,quota41,trial41,staged_news as stage
from scripts.test_policy41 import source,record,issue


class SourceAndRightsTests(unittest.TestCase):
    def test_official_www_and_subdomains_match_authority_without_counting_aliases_twice(self):
        self.assertTrue(e.host_matches('https://www.who.int/example',{'who.int'}))
        self.assertTrue(e.host_matches('https://www.niddk.nih.gov/example',{'nih.gov'}))
        self.assertFalse(e.host_matches('https://who.int.evil.example/',{'who.int'}))
        self.assertEqual(e.publisher_identity('https://www.who.int/a'),e.publisher_identity('https://who.int/b'))

    def test_dateless_institution_is_transparent_not_an_invented_author(self):
        html='<html lang="ru"><main><h1>Учебная тема</h1><div>Первый полный абзац.</div><section><p>Последняя оговорка.</p></section></main></html>'
        s=source41.extract(html,'https://www.unicef.org/example')
        self.assertEqual(s['metadata_status'],'verified'); self.assertEqual(s['author'],''); self.assertEqual(s['published'],'')
        self.assertEqual(set(s['metadata_gaps']),{'author','published'})
        self.assertIn('Последняя оговорка.',' '.join(b['text'] for b in s['blocks']))
        self.assertEqual(rights41.select_mode(s)[0],'INDEPENDENT_ARTICLE')
        unknown=source41.extract(html,'https://unknown.example/example')
        self.assertEqual(unknown['metadata_status'],'needs_review')

    def test_jsonld_metadata_and_nested_list_preserve_final_text(self):
        schema={'@type':'Article','headline':'Учебная тема','datePublished':'2026-10-26',
                'author':[{'name':'Автор один'},{'name':'Автор два'}],'license':'https://creativecommons.org/licenses/by/4.0/'}
        html='<html lang="ru"><head><script type="application/ld+json">'+json.dumps(schema)+'</script></head><body><article><div class="entry-content"><p>Начало.</p><ol><li>Первое действие<ul><li>Вложенная оговорка</li></ul></li><li>Второе действие</li></ol><figure><figcaption>Подпись.</figcaption></figure><p>Финал.</p></div></article></body></html>'
        s=source41.extract(html,'https://example.org/full')
        self.assertEqual(s['author'],'Автор один, Автор два'); self.assertEqual(s['published'],'2026-10-26')
        self.assertEqual(s['blocks'][-1]['text'],'Финал.')
        self.assertTrue(any(b.get('list_depth')==2 and b['text']=='Вложенная оговорка' for b in s['blocks']))
        self.assertEqual(rights41.select_mode(s)[0],'ORIGINAL_REPUBLICATION')
        from scripts import publication41
        rendered=publication41.render_blocks({'title':s['title'],'blocks':s['blocks']})
        self.assertIn('<li>Первое действие<ul><li>Вложенная оговорка</li></ul></li><li>Второе действие</li>',rendered)

    def test_summary_skeleton_and_ambiguous_body_are_blocked(self):
        for html in ('<html lang="en"><main><h1>Study</h1><div class="abstract"><p>Only abstract.</p></div></main></html>',
            '<html><head><title>Just a moment...</title></head><main><h1>Wait</h1><p>Checking browser.</p></main></html>',
            '<html><article><div class="article-body"><p>One</p></div></article><article><div class="article-body"><p>Two</p></div></article></html>'):
            with self.subTest(html=html),self.assertRaises(p.Blocked): source41.extract(html,'https://example.org/')

    def test_news_stays_strict_even_for_trusted_dateless_source(self):
        s=source(); s.update(published='',institutional_source=True)
        r={'id':'x','url':s['url'],'checks':{},'progress':{}}
        editor=e.Editor(fetch=lambda url:s)
        def analyse(record): record.update(kind='новость',claims=[],category='Наука')
        with patch.object(editor,'analyse',side_effect=analyse),self.assertRaisesRegex(p.Blocked,'NEWS_EVENT_FRESHNESS_UNVERIFIED'):
            editor.source_verified(e.new_state('2026-10-27'),r)

    def test_facts_are_not_copying_or_translation_permission(self):
        s=source(); s['declared_license']=None
        legal=rights41.decision(s,'INDEPENDENT_ARTICLE',[])
        self.assertEqual(legal['status'],'allowed')
        for mode in ('ORIGINAL_REPUBLICATION','FULL_TRANSLATION'):
            self.assertEqual(rights41.decision(s,mode,[])['status'],'unknown')
            with self.assertRaisesRegex(p.Blocked,'FACTS_PERMISSION_IS_NOT_COPYRIGHT_LICENSE'): rights41.require(s,mode,legal)
        s['legal_dispute']=True
        self.assertEqual(rights41.decision(s,'INDEPENDENT_ARTICLE',[])['status'],'unknown')

    def test_documented_doubt_and_ai_terms_fail_closed(self):
        s=source(); s['ai_use_restricted']=True
        for mode in p.MODES: self.assertEqual(rights41.decision(s,mode,[])['status'],'unknown')
        s.update(url='https://openstax.org/books/example',ai_use_restricted=False)
        self.assertEqual(rights41.decision(s,'INDEPENDENT_ARTICLE',[])['status'],'unknown')
        s=source(); permit={'status':'unknown','verification':'human_documented','basis':'Specific dispute',
             'evidence_url':'https://example.org/dispute','checked_by':'editor','checked_at':'2026-10-26'}
        grants=[{'url':s['url'],'content_hash':s['content_hash'],'uses':{'INDEPENDENT_ARTICLE':permit}}]
        self.assertEqual(rights41.decision(s,'INDEPENDENT_ARTICLE',grants)['status'],'unknown')

    def test_independence_review_can_veto_a_structurally_valid_article(self):
        r=record(); r['mode']='INDEPENDENT_ARTICLE'; r['article'].update(mode=r['mode'],blocks=[{
            'id':'own','kind':'paragraph','text':'Самостоятельно выглядящий текст с потенциально чужой подборкой.'}])
        r['rights']=rights41.decision(r['source'],r['mode']); r['checks']={}
        r['rejected_part']={'stage':'fact_checked','block_id':'old-section/0'}
        def model(prompt,**kwargs):
            if prompt.startswith('Проверка самостоятельности'):
                return {'approve':False,'issues':['Подборка воспроизведена'],'unresolved':[],
                        **{key+'_checked':True for key in c.INDEPENDENCE_FIELDS}}
            part=json.loads(prompt.split('\nЧасть: ')[1].split('\nПроверенные')[0])
            return {'approve':True,'issues':[],'unresolved':[],'covered_ids':[part['id']]}
        with self.assertRaisesRegex(p.Blocked,'REVIEW_REJECTED'):
            e.Editor(call=model).review(e.new_state('2026-10-27'),r,'editorial_checked')
        self.assertNotIn('editorial_checked',r['checks'])
        self.assertEqual(r['rejected_part']['block_id'],'')


class BatchingAndQuotaTests(unittest.TestCase):
    def test_all_short_parts_translated_once_and_cache_survives_restore(self):
        s=source(); s['blocks']=[{'id':str(i),'kind':'paragraph','text':'Учебная фраза '+str(i)} for i in range(30)]
        s['content_hash']=p.digest(s['blocks']); calls=[]; progress={}
        def model(prompt,**kwargs):
            payload=json.loads(prompt.split('Техническая часть исходника: ')[1].split('. Верни finished')[0])
            members=payload.get('pieces',[payload]); calls.append(len(members))
            return {'finished':True,'segments':[{'id':x['id'],'text':x['text']} for x in members]}
        result=c.complete_translation(s,progress,model)
        self.assertEqual(calls,[30]); self.assertEqual([b['text'] for b in result],[b['text'] for b in s['blocks']])
        c.complete_translation(s,json.loads(json.dumps(progress)),lambda *a,**k:self.fail('Accepted work must not repeat'))

    def test_incomplete_batch_cannot_approve_missing_segments(self):
        s=source(); s['blocks']=[{'id':str(i),'kind':'paragraph','text':str(i)} for i in range(8)]; s['content_hash']=p.digest(s['blocks'])
        with self.assertRaises(p.Blocked):
            c.complete_translation(s,{},lambda *a,**k:{'finished':True,'segments':[{'id':'0:0:1','text':'Only one'}]})

    def test_shared_analysis_is_bound_to_source_hash_and_survives_restore(self):
        s=source(); state=e.new_state('2026-10-27'); editor=e.Editor(call=lambda *a,**k:self.fail('Shared evidence should be reused'))
        editor.state=state; first={'source':s,'progress':{'analysis':{}}}
        pieces=c.chunks(s['blocks'])
        key=p.digest({'source':s['content_hash'],'url':s['url'],'metadata':[s.get(k) for k in ('author','published','language')],'analysis_revision':'facts-v2'})
        state['analysis_cache']={key:{part['id']:{'claims':[],'requirements':[],'topic_key':'fixture','event_date':'',
            'category':'Наука','kind':'статья','worth_publishing':True,'reader_value':'Учебный пример'} for part in pieces}}
        editor.state=json.loads(json.dumps(state)); editor.analyse(first)
        self.assertEqual(len(first['progress']['analysis']),len(pieces))
        changed=copy.deepcopy(s); changed['content_hash']='different'
        with self.assertRaises(AssertionError): editor.analyse({'source':changed,'progress':{}})

    def test_actual_http_reservations_are_saved_before_a_failed_call(self):
        ledger={}; saved=[]
        budget=runtime.RequestBudget(ledger,lambda:saved.append(copy.deepcopy(ledger)),run_limit=2,day_limit=220,gap=0,seconds=1000)
        r={}; editor=e.Editor(call=lambda *a,**k:(budget.reserve('fixture-model'),(_ for _ in ()).throw(OSError('503')))[1])
        editor.usage_record=r
        with patch.object(runtime,'ACTIVE_BUDGET',budget),self.assertRaises(OSError): editor.call('synthetic',schema='v41_analysis')
        self.assertEqual(r['model_usage']['v41_analysis']['http_requests'],1)
        self.assertEqual(ledger['requests'],1); self.assertEqual(saved[-1]['requests'],1)
        self.assertIsNone(budget.usage_counter)

    def test_quota_scenarios_include_reserve_and_do_not_change_budget(self):
        article=quota41.estimate('INDEPENDENT_ARTICLE',2,3,sections=4)
        self.assertEqual(article['operations'],17)
        report=quota41.issue_scenario([article]*12,reserves=[article]*2)
        self.assertEqual(report['baseline_http_without_retries'],205)
        self.assertFalse(report['fits_daily_budget']); self.assertEqual(report['day_limit'],220)
        small=quota41.estimate('INDEPENDENT_ARTICLE',2,1,sections=4)
        forecast=quota41.issue_scenario([small]*12,reserves=[small]*2,shared_support_operations=6)
        self.assertEqual(forecast['with_retry_allowance'],194); self.assertTrue(forecast['fits_daily_budget'])


class TrialSafetyTests(unittest.TestCase):
    def env(self):
        sha='a'*40
        return {'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
            'GITHUB_REF_NAME':'codex/editorial-policy-v41','GITHUB_ACTOR':'owner','GITHUB_REPOSITORY_OWNER':'owner',
            'TRIAL_APPROVED_SHA':sha,'GITHUB_SHA':sha,'TRIAL_CONFIRMATION':trial41.CONFIRMATION,'TRIAL_PREVIEW':'true'}

    def test_trial_requires_owner_dispatch_pinned_commit_and_explicit_permission(self):
        trial41.guard(self.env())
        for key,value in [('GITHUB_ACTIONS','false'),('GITHUB_EVENT_NAME','push'),('GITHUB_ACTOR','someone'),
                          ('GITHUB_REF_NAME','main'),('TRIAL_APPROVED_SHA','b'*40),('TRIAL_CONFIRMATION',''),('TRIAL_PREVIEW','false')]:
            env=self.env(); env[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError): trial41.guard(env)

    def test_unprotected_environment_cannot_start_gemini(self):
        with self.assertRaisesRegex(RuntimeError,'TRIAL_ENVIRONMENT_REVIEWER_REQUIRED'):
            trial41.protected_environment(lambda:{'protection_rules':[]})
        trial41.protected_environment(lambda:{'protection_rules':[{'type':'required_reviewers','reviewers':[{'id':1}]}]})

    def test_synthetic_review_bundle_authentication_no_plaintext(self):
        key=b's'*32; data=b'SYNTHETIC HTML fixture only'
        blob=trial41.seal(data,key)
        self.assertNotIn(data,blob); self.assertEqual(trial41.unseal(blob,key),data)
        with self.assertRaises(Exception): trial41.unseal(blob[:-1]+bytes([blob[-1]^1]),key)

    def test_trial_checkpoint_namespace_isolated_but_quota_shared(self):
        before=stage.quota_label()
        with patch.dict(os.environ,{'NEWS_V41_TRIAL':'true','GITHUB_REF_NAME':'codex/editorial-policy-v41'}):
            self.assertIn('387news41-trial-',stage.artifact_label('2026-10-28',True))
            self.assertEqual(stage.quota_label(),before)
            with self.assertRaises(RuntimeError): stage.artifact_label('2026-10-28',False)

    def test_export_refuses_full_issue_without_required_unicef_and_translation_cases(self):
        with tempfile.TemporaryDirectory() as directory,self.assertRaisesRegex(p.Blocked,'TRIAL_UNICEF_21_INCOMPLETE'):
            trial41.export(issue(),p.ROOT,Path(directory)/'private',browser=lambda *a:self.fail('No render of an incomplete trial'))

    def test_complete_synthetic_trial_exports_all_html_markdown_without_touching_repo(self):
        from scripts.test_policy41 import SemanticTests
        state=issue(); first,second=state['candidates'][:2]
        a,_=SemanticTests().article()
        url='https://www.unicef.org/parenting/child-care/21-learning-activities-babies-and-toddlers'
        first.update(test_id='unicef-21',url=url,mode='INDEPENDENT_ARTICLE')
        first['source'].update(url=url,canonical=url)
        first['article'].update(mode=first['mode'],title=a['title'],blocks=a['blocks'],activities=a['activities'])
        first['rights']=rights41.decision(first['source'],first['mode'])
        second.update(mode='FULL_TRANSLATION'); second['source']['language']='en'
        second['article']['mode']=second['mode']; second['rights']=rights41.decision(second['source'],second['mode'])
        for r in (first,second):
            fp=e.article_hash(r['article'],r['source'],r['rights'])
            for name in p.STAGES: r['checks'][name]={'approved':True,'input_hash':fp}
            r['checks']['source_verified']['input_hash']=p.digest({'source':r['source']['content_hash'],'rights':r['rights'],'images':[]})
        state['issue_approval_hash']=p.digest([e.article_hash(r['article'],r['source'],r['rights']) for r in state['candidates']])
        original=(p.ROOT/'index.html').read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'private'
            report=trial41.export(state,p.ROOT,output,browser=lambda *a:{'pages':36,'mock':True})
            self.assertEqual(report['article_count'],12)
            self.assertEqual(len(list((output/'issues'/state['date']).glob('articles/*/index.html'))),12)
            self.assertEqual(len(list((output/'issues'/state['date']).glob('articles/*/article.md'))),12)
            self.assertFalse((output/'config').exists()); self.assertFalse((output/'scripts').exists())
        self.assertEqual((p.ROOT/'index.html').read_bytes(),original)

    def test_workflow_never_runs_trial_on_push_and_shares_lock_only_after_review(self):
        workflow=(p.ROOT/'.github/workflows/daily-v31.yml').read_text()
        approval=workflow.split('\n  trial-approval:',1)[1].split('\n  trial:',1)[0]
        trial=workflow.split('\n  trial:',1)[1].split('\n  prepare:',1)[0]
        self.assertIn("github.event_name == 'workflow_dispatch'",approval)
        self.assertIn('environment: 387-news-v41-trial',approval)
        self.assertIn('needs: trial-approval',trial); self.assertIn('group: 387-news-stage-v31',trial)
        self.assertIn("NEWS_RELEASE_APPROVED: 'false'",trial)
        self.assertNotIn('pages: write',trial); self.assertNotIn('git push',trial)


if __name__=='__main__': unittest.main()
