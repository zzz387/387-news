"""Special-only eight-slot exception, zero-production interference and final projections."""
import copy
from datetime import datetime
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from scripts import special003r as runner,special_contract41 as sc,special_publication41 as pub
from scripts import policy41 as p,editorial41 as e,rights41,news
from scripts.test_policy41 import record,issue


def complete_special():
    config=sc.definition();state=runner.new_state()
    records=[]
    for index,slot in enumerate(config['slots']):
        r=record(index);r['id']='003-R-'+str(slot['slot']);r['special_slot']=slot['slot']
        r['url']=r['source']['url']=r['source']['canonical']=slot['url'];r['original_urls']=slot['original_urls']
        r['mode']=r['article']['mode']='INDEPENDENT_ARTICLE'
        r['article']['blocks']=[{'kind':'paragraph','text':'Самостоятельное вымышленное объяснение с подробностью '+str(index)}]
        r['article']['category']=slot['category'];r['article']['activities']=[]
        r['rights']=rights41.decision(r['source'],r['mode']);r['article']['attribution']=r['rights'].get('attribution',{})
        r['supporting_sources']=[{'url':u,'full_text_verified':True} for u in slot['original_urls'][1:]]
        if slot['category']=='Здоровье и движение':
            r['special_study_urls']=['https://doi.org/10.synthetic/'+str(index)]
            r['supporting_sources'] += [{'url':r['special_study_urls'][0],'full_text_verified':True}]
        if slot['slot']==3:
            r['article']['activities']=[{'id':str(i),'title':'Вымышленное занятие '+str(i),'age':'При готовности ребёнка',
                'materials':['Безопасный учебный предмет'],'steps':['Взрослый показывает учебное действие '+str(i)],
                'benefit':'Совместное внимание','safety':'Непрерывное наблюдение взрослого'} for i in range(21)]
        for block in r['article']['blocks']:block.pop('source_block_id',None)
        fingerprint=e.article_hash(r['article'],r['source'],r['rights'])
        r['checks']={name:{'approved':True,'input_hash':fingerprint} for name in p.STAGES}
        r['checks']['source_verified']={'approved':True,'special_evidence_complete':True,
            'input_hash':p.digest({'source':r['source']['content_hash'],'rights':r['rights'],'images':[]})}
        records.append(r)
    state['candidates']=records;state['selected_ids']=[r['id'] for r in records];state['audit_passed']=True
    state['issue_approval_hash']=p.digest([e.article_hash(r['article'],r['source'],r['rights']) for r in records])
    return state


class SpecialTests(unittest.TestCase):
    def test_daily_twelve_is_unchanged_and_narrow_special_requires_exact_eight(self):
        self.assertEqual(p.ARTICLE_COUNT,12);daily=issue();self.assertTrue(e.validate_issue(daily))
        daily['selected_ids']=daily['selected_ids'][:8]
        with self.assertRaises(p.Blocked):e.validate_issue(daily)
        special=complete_special();self.assertTrue(e.validate_issue(special))
        special['selected_ids']=special['selected_ids'][:7]
        with self.assertRaises(p.Blocked):e.validate_issue(special)

    def test_forged_contract_topic_and_primary_source_cannot_publish(self):
        for mutation in ('definition','slot','source','category'):
            state=complete_special()
            if mutation=='definition':state['special_edition']['definition_hash']='wrong'
            elif mutation=='slot':state['candidates'][0]['special_slot']=2
            elif mutation=='source':state['candidates'][0]['source']['url']='https://example.org/other'
            else:state['candidates'][0]['article']['category']='Наука'
            with self.subTest(mutation=mutation),self.assertRaises(p.Blocked):e.validate_issue(state)

    def test_21_instructions_study_and_all_companions_are_required(self):
        for mutation in ('activities','study','companions'):
            state=complete_special()
            if mutation=='activities':state['candidates'][2]['article']['activities'].pop()
            elif mutation=='study':state['candidates'][5]['special_study_urls']=[]
            else:state['candidates'][0]['supporting_sources']=[]
            with self.subTest(mutation=mutation),self.assertRaises(p.Blocked):e.validate_issue(state)

    def test_daily_priority_quota_and_cooldown_are_read_only(self):
        now=datetime(2026,10,26,15,30,tzinfo=p.TZ);daily=issue();daily.update(branch='main',preview=False)
        ledger={'day':'2026-10-26','requests':194,'models':{},'cooldowns':{}}
        before=copy.deepcopy((daily,ledger))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'issues/2026-10-26').mkdir(parents=True)
            (root/'issues/2026-10-26/issue.json').write_text('{}')
            self.assertTrue(runner.admit(root,daily,ledger,now)[0])
            self.assertEqual(runner.admit(root,None,ledger,now)[1],'DAILY_NOT_READY')
            self.assertEqual(runner.admit(root,daily,dict(ledger,requests=196),now)[1],'NO_SPARE_QUOTA_WITH_DAILY_RESERVE')
            self.assertEqual(runner.admit(root,daily,dict(ledger,cooldowns={'lite':now.timestamp()+60}),now)[1],'GEMINI_COOLDOWN')
            self.assertEqual(runner.admit(root,daily,ledger,now.replace(hour=5))[1],'OUTSIDE_SPARE_DAYTIME_WINDOW')
        self.assertEqual((daily,ledger),before)

    def test_new_state_uses_fixed_slots_and_separate_identity_without_legacy_approval(self):
        state=runner.new_state()
        self.assertEqual(len(state['candidates']),8);self.assertFalse(state['audit_passed'])
        self.assertTrue(sc.is_special(state));self.assertNotEqual(runner.LABEL,'387news31-production-2026-10-27')

    def test_publication_keeps_original_and_home_bytes_and_uses_actual_publication_date(self):
        state=complete_special();config=copy.deepcopy(sc.definition());original={'number':3,'date':sc.ORIGINAL,'articles':[{'title':'Исходная вымышленная тема '+str(i)} for i in range(8)]}
        config['original_manifest_hash']=p.digest(original)
        state['special_edition']['definition_hash']=p.digest(config)
        state['published_at']='2026-10-28T13:22:00+03:00'
        with tempfile.TemporaryDirectory() as temp,patch.object(sc,'definition',return_value=config):
            root=Path(temp);shutil.copytree(p.ROOT/'assets',root/'assets')
            (root/'archive').mkdir();(root/'issues'/sc.ORIGINAL).mkdir(parents=True)
            (root/'issues'/sc.ORIGINAL/'issue.json').write_text(json.dumps(original))
            # Fixture baseline pages only; real source/closed data is never loaded.
            (root/'issues'/sc.ORIGINAL/'index.html').write_text('<html><body>Оригинал</body></html>')
            (root/'index.html').write_text('<html><body>Ежедневная главная</body></html>')
            original_bytes=(root/'issues'/sc.ORIGINAL/'index.html').read_bytes();home=(root/'index.html').read_bytes()
            self.assertTrue(pub.build(state,root));self.assertEqual(pub.validate(root)['count'],8)
            self.assertEqual((root/'index.html').read_bytes(),home)
            self.assertEqual((root/'issues'/sc.ORIGINAL/'index.html').read_bytes(),original_bytes)
            overview=(root/'issues'/sc.SLUG/'index.html').read_text()
            self.assertIn('2026-10-28',overview);self.assertIn('№003-R',overview)
            self.assertIn('/issues/'+sc.SLUG+'/',(root/'archive/index.html').read_text())
            self.assertIn('/issues/'+sc.SLUG+'/',(root/'sitemap.xml').read_text())
            self.assertFalse(pub.build(state,root));self.assertEqual(news.ROOT,p.ROOT)
            self.assertEqual(len(list((root/'issues'/sc.SLUG/'articles').glob('*/article.md'))),8)

    def test_shared_mutex_and_no_independent_cron_or_daily_checkpoint_upload(self):
        text=(p.ROOT/'.github/workflows/special-003-r.yml').read_text()
        self.assertNotIn('cron:',text);self.assertNotIn('workflow_dispatch:',text)
        self.assertNotIn('path: ${{ runner.temp }}/read-only-daily/news-draft.enc',text)
        main=(p.ROOT/'.github/workflows/daily-v31.yml').read_text()
        self.assertIn('needs: [prepare, deploy, monitor]',main);self.assertIn("'387-news-stage-v31'",main)

    def test_initialize_writes_only_independent_ciphertext_and_no_api_or_ledger_updates(self):
        import base64,os
        from scripts import staged_news as stage
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'incoming').mkdir();(root/'output').write_text('')
            (root/'config').mkdir();shutil.copyfile(p.ROOT/'config/special-003-r.json',root/'config/special-003-r.json')
            ledger={'day':datetime.now(__import__('datetime').timezone.utc).date().isoformat(),'requests':207,'models':{},'cooldowns':{}}
            quota=root/'quota.json';quota.write_text(json.dumps(ledger));before=quota.read_bytes()
            env={'GITHUB_ACTIONS':'true','GITHUB_REF_NAME':'main','GITHUB_REPOSITORY':'zzz387/387-news',
                 'NEWS_SPECIAL_EDITION':'003-R','SPECIAL_INITIALIZE_ONLY':'true',
                 'DRAFT_ENCRYPTION_KEY':base64.b64encode(b'x'*32).decode(),
                 'SPECIAL_CHECKPOINT_FILE':str(root/'incoming/special-003-r.enc'),
                 'DAILY_CHECKPOINT_FILE':str(root/'daily.enc'),'QUOTA_CHECKPOINT_FILE':str(quota),
                 'SPECIAL_EXPECTED':'false','DAILY_EXPECTED':'false','QUOTA_EXPECTED':'true',
                 'RUNNER_TEMP':str(root),'GITHUB_OUTPUT':str(root/'output')}
            with patch.dict(os.environ,env),patch.object(runner.p,'ROOT',root),patch.object(sc,'check_original'),\
                 patch.object(news.runtime,'RequestBudget',side_effect=AssertionError('No API budget in initialize')),\
                 patch.object(stage,'request_json',side_effect=AssertionError('No new run dispatch')):
                runner.run()
            self.assertEqual(quota.read_bytes(),before);self.assertFalse((root/'daily.enc').exists())
            state=stage.decipher((root/'special-003-r.enc').read_bytes(),b'x'*32)
            self.assertEqual(state['_quota_snapshot']['requests'],207);self.assertEqual(len(state['candidates']),8)
            self.assertNotIn('quota=true',(root/'output').read_text())

    def test_stale_shared_ledger_cannot_erase_special_counter_snapshot(self):
        import base64,os
        from scripts import staged_news as stage
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'output').write_text('')
            (root/'config').mkdir();shutil.copyfile(p.ROOT/'config/special-003-r.json',root/'config/special-003-r.json')
            day=datetime.now(__import__('datetime').timezone.utc).date().isoformat()
            old=runner.new_state();old['_quota_snapshot']={'day':day,'requests':210,'models':{}}
            (root/'special-input.enc').write_bytes(stage.cipher(old,b'x'*32))
            quota=root/'quota.json';quota.write_text(json.dumps({'day':day,'requests':207,'models':{}}))
            env={'GITHUB_ACTIONS':'true','GITHUB_REF_NAME':'main','GITHUB_REPOSITORY':'zzz387/387-news',
                 'NEWS_SPECIAL_EDITION':'003-R','SPECIAL_INITIALIZE_ONLY':'true',
                 'DRAFT_ENCRYPTION_KEY':base64.b64encode(b'x'*32).decode(),
                 'SPECIAL_CHECKPOINT_FILE':str(root/'special-input.enc'),'DAILY_CHECKPOINT_FILE':str(root/'none'),
                 'QUOTA_CHECKPOINT_FILE':str(quota),'RUNNER_TEMP':str(root),'GITHUB_OUTPUT':str(root/'output')}
            with patch.dict(os.environ,env),patch.object(runner.p,'ROOT',root),patch.object(sc,'check_original'):
                runner.run()
            restored=stage.decipher((root/'special-003-r.enc').read_bytes(),b'x'*32)
            self.assertEqual(restored['_quota_snapshot']['requests'],210)
            self.assertEqual(json.loads(quota.read_text())['requests'],207)



if __name__=='__main__':unittest.main()
