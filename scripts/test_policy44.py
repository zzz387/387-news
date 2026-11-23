"""4.4 regressions: actual subjects, uncapped issues, cheap resumable briefs."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import policy44 as v,editorial43 as e,selection43 as sel,publication43 as pub,light44 as brief,light43,stock43,news,site_checks,staged_news
from scripts.test_daily43 import state,root,ready,web,NOW
from scripts.test_editorial_visual43 import named,light_ready

TOPICS=['Родители и дети: семейные игры','Супружеские отношения и общение','Здоровое питание и долголетие','Режим сна и профилактика заболеваний','Велосипедные тренировки и выносливость','Йога и подвижность']
def main_row(i):
    title=TOPICS[i] if i<len(TOPICS) else ['Открытие археологов','Инженерный мост','Биография архитектора','Московский маршрут','Музыкальная коллекция','Природа растений'][i%6]+' '+str(i)
    row=named(title,i);row['topic_policy_version']='4.4'
    row['article']['blocks']=[{'kind':'paragraph','text':title+'. Подтверждённый учебный пример '+str(i)+'.'}]
    row['checks']['final43']['input_hash']=e.fingerprint(row)
    return row

def issue(n=8,lights=8):
    s=state();s['policy_version']='4.4';s['brief_policy_revision']=1;s['candidates']=[main_row(i) for i in range(n)]
    s['light43']={'records':[light_ready(i) for i in range(lights)]}
    return s

def response_item():
    source=ready(45)['source'];source['blocks']=[{'id':'proof','kind':'paragraph','text':'The museum restored 21 paintings in its collection.'}]
    item={'id':'note','source_id':source['id'],'title':'Реставрация коллекции','text':'Музей восстановил 21 картину из своего собрания.','time_kind':'unusual_fact','event_date':'','evidence':[{'block_id':'proof','quote':source['blocks'][0]['text']}]}
    return source,item

def synthetic_art(state):
    """Tiny explicitly synthetic WebP objects; never calls a real provider."""
    import io,base64,hashlib
    from PIL import Image
    from scripts import mosaic44
    mosaic44.approve(state);mosaic44.prepare(state)
    for i,item in enumerate(state['art44']['plan']):
        image=Image.new('RGB',(48,32),((80+i*7)%251,105,85));buffer=io.BytesIO();image.save(buffer,format='PNG')
        data,width,height=mosaic44.encode_image(buffer.getvalue())
        state['art44']['objects'][item['key']]={'webp':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest(),'width':width,'height':height,'provider':'synthetic-test','model':'no-api'}

class Policy44Tests(unittest.TestCase):
    def test_relaxed_topic_admission_boundaries_preserve_actual_deficits(self):
        cases=[(13,(2,0,1),12,True,False),(11,(1,1,1),8,True,False),(12,(2,0,0),12,False,False),(10,(2,1,2),12,False,False),(8,(2,2,2),8,True,True),(15,(2,1,1),7,False,False),(13,(2,0,1),13,False,False)]
        for n,groups,lights,allowed,strict in cases:
            with self.subTest(main=n,groups=groups,lights=lights):
                indexes=[i for base,count in zip((0,2,4),groups) for i in range(base,base+count)]
                indexes+=list(range(6,6+n-len(indexes)))
                rows=[main_row(i) for i in indexes];s=issue();s['brief_policy_revision']=2
                report=v.standard(s,rows,[light_ready(i) for i in range(lights)])
                self.assertEqual(report['topics'],dict(zip(v.GROUPS,groups)))
                self.assertEqual(report['total_topic_deficit'],sum(max(0,2-count) for count in groups))
                self.assertEqual(report['compliant'],allowed);self.assertEqual(report['strict_compliant'],strict)
                if allowed and not strict:self.assertEqual(report['admission_reason'],'RELAXED_TOPIC_DEFICIT')
                if not allowed:
                    with self.assertRaisesRegex(Exception,'EDITORIAL_STANDARD_NOT_MET'):v.require(s,rows,[light_ready(i) for i in range(lights)])

    def test_due_relaxed_issue_enters_delivery_without_stock_search_or_model_work(self):
        from scripts import daily43 as daily,mosaic44,catalog43
        rows=[main_row(i) for i in [0,1,4]+list(range(6,16))]
        s=issue();s['brief_policy_revision']=2;s['candidates']=rows
        with tempfile.TemporaryDirectory() as temp,patch.object(sel,'composition',return_value=rows),patch.object(catalog43,'refresh',side_effect=AssertionError('Do not search after due admission')),patch.object(stock43,'draw',side_effect=AssertionError('Do not add more accepted articles')),patch.object(news,'gemini',side_effect=AssertionError('Do not rewrite')),patch.object(mosaic44,'finalize',return_value=True) as final:
            self.assertTrue(daily.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW))
            final.assert_called_once();self.assertEqual(s['editorial_standard44']['admission_reason'],'RELAXED_TOPIC_DEFICIT')
            self.assertEqual(s['editorial_standard44']['topics'],{'family':2,'health':0,'sport':1})
            self.assertEqual(len(s['articles']),13)

    def test_before_release_relaxed_issue_still_attempts_strict_search(self):
        from scripts import daily43 as daily,catalog43,priorities43,mosaic44
        rows=[main_row(i) for i in [0,1,4]+list(range(6,16))]
        s=issue();s['brief_policy_revision']=2;s['candidates']=rows
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_CATALOG_REFRESH='true'),patch.object(sel,'composition',return_value=rows),patch.object(stock43,'restore_backlog'),patch.object(stock43,'balance'),patch.object(stock43,'draw'),patch.object(stock43,'draw_light'),patch.object(daily,'discover'),patch.object(priorities43,'apply_rules'),patch.object(catalog43,'refresh',side_effect=RuntimeError('bounded fixture search')) as search,patch.object(mosaic44,'finalize',return_value=False):
            daily.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW.replace(hour=5))
            search.assert_called_once()

    def test_flux_prompt_uses_english_subject_before_long_russian_prose(self):
        from scripts import cloudflare44 as cf,mosaic44 as art
        row=main_row(0);before=art.final_text(row['article'])
        row['article']['art_brief_en']='Children build a cardboard castle in a sunlit playroom.'
        row['article']['teaser']='Проверенный русский текст. '*300
        expected=art.final_text(row['article'])
        item=art.article_plans({'date':'2026-11-23'},[row])[0]
        self.assertIn('Subject: Children build a cardboard castle',item['prompt'])
        self.assertIn('watercolor',item['prompt']);self.assertNotIn('Проверенный',item['prompt'])
        self.assertLessEqual(len(item['prompt']),2048)
        self.assertEqual(expected,art.final_text(row['article']))
        self.assertNotIn('art_brief_en',art.final_text(row['article']))
        for styles in art.STYLES.values():
            for style in styles:
                with self.subTest(style=style):self.assertIn(style,cf.STYLE_EN)
        del row['article']['art_brief_en'];row['source']['title']='American elm restoration and genetic diversity'
        item=art.article_plans({'date':'2026-11-23'},[row])[0]
        self.assertIn('American elm restoration',item['prompt'])

    def test_cloudflare_auth_failure_waits_for_changed_credentials(self):
        from scripts import cloudflare44 as cf,mosaic44 as art
        import io
        from PIL import Image
        stream=io.BytesIO();Image.new('RGB',(32,32),(70,90,80)).save(stream,format='PNG')
        state={'date':'2026-11-22','art44':{'objects':{},'history':[]}}
        plans=art.article_plans(state,[{'id':'one','article':main_row(0)['article']}])
        env={'CLOUDFLARE_ACCOUNT_ID':'a'*32,'CLOUDFLARE_API_TOKEN':'SYNTHETIC'}
        budget=SimpleNamespace(remaining_seconds=lambda:1000,ledger={})
        with patch.dict(os.environ,env),patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(art,'cached',return_value={}):
            with patch.object(art,'generate',side_effect=RuntimeError('CF_HTTP_403')) as generate:
                art.prepare_items(state,plans);art.prepare_items(state,plans)
                self.assertEqual(generate.call_count,1);self.assertEqual(state['art44']['provider_status'],'CF_HTTP_403')
            with patch.dict(os.environ,CLOUDFLARE_API_TOKEN='SYNTHETIC_UPDATED'),patch.object(art,'generate',return_value=stream.getvalue()) as generate:
                self.assertTrue(art.prepare_items(state,plans)['complete']);generate.assert_called_once()
            with patch.object(cf,'free_usage',side_effect=RuntimeError('CF_HTTP_401')),patch.object(cf,'github_secret_metadata',return_value={}),patch.dict(os.environ,GITHUB_ENV=''):
                report=cf.diagnose(art.CONFIG,probe=True)
                self.assertEqual(report['status'],'CF_HTTP_401');self.assertFalse(report['authorization_verified'])
            with patch.dict(os.environ,CLOUDFLARE_API_TOKEN='  "Bearer SYNTHETIC"  '):
                self.assertEqual(cf.credentials(),('a'*32,'SYNTHETIC'))
            self.assertEqual(cf.authentication_code([{'code':9106}]),'CF_AUTHENTICATION_FAILED_9106')
            with patch.dict(os.environ,NEWS_CF_PROBE_STATUS='CF_AUTHENTICATION_FAILED_9106'):
                self.assertEqual(cf.status(art.CONFIG),'CF_AUTHENTICATION_FAILED_9106')
                empty={'date':'2026-11-22','art44':{'objects':{},'history':[]}}
                with patch.object(art,'generate') as generate:
                    art.prepare_items(empty,plans);generate.assert_not_called()
                self.assertEqual(empty['art44']['provider_status'],'CF_AUTHENTICATION_FAILED_9106')

    def test_cloudflare_free_guard_payload_and_neuron_accounting(self):
        from scripts import cloudflare44 as cf,generation_runtime as rt,mosaic44 as art
        import io,base64
        from PIL import Image
        image=Image.new('RGB',(64,64),(40,90,70));buffer=io.BytesIO();image.save(buffer,format='PNG');raw=buffer.getvalue()
        ledger={'day':'2026-11-21','requests':17,'models':{}};budget=rt.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0,seconds=1000)
        item=art.article_plans({'date':'2026-11-22','art44':{}},[{'id':'one','article':main_row(0)['article']}])[0]
        seen=[]
        def api(path,data=None):
            seen.append((path,data))
            if path.endswith('/subscriptions'):return {'result':[]}
            if path=='/graphql':return {'data':{'viewer':{'accounts':[{'aiInferenceAdaptiveGroups':[{'sum':{'totalNeurons':100}}]}]}}}
            return {'result':{'image':base64.b64encode(raw).decode()}}
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'zzz387/387-news','GITHUB_REF_NAME':'main','CLOUDFLARE_ACCOUNT_ID':'a'*32,'CLOUDFLARE_API_TOKEN':'SYNTHETIC'}
        with patch.dict(os.environ,env),patch.object(cf,'api',side_effect=api),patch.object(cf,'_LAST',0):
            self.assertEqual(cf.generate(item,budget,art.CONFIG),raw)
            posts=[(path,data) for path,data in seen if '/ai/run/' in path]
            self.assertEqual(len(posts),1);self.assertEqual(set(posts[0][1]),{'prompt','steps'});self.assertLessEqual(len(posts[0][1]['prompt']),2048);self.assertEqual(posts[0][1]['prompt'],item['prompt'])
            self.assertIn('$account:string!',next(data['query'] for path,data in seen if path=='/graphql'))
            self.assertEqual(ledger['requests'],17);self.assertEqual(ledger['cloudflare_ai']['requests'],1)
            with patch.object(cf,'free_usage',return_value=9990),self.assertRaises(rt.GenerationPaused):cf.generate(item,budget,art.CONFIG)
            self.assertEqual(len([x for x in seen if '/ai/run/' in x[0]]),1)
            with patch.object(cf,'api',return_value={'result':[{'rate_plan':{'id':'paid'},'price':5}]}),self.assertRaisesRegex(RuntimeError,'CF_FREE_PLAN_UNVERIFIED'):cf.free_usage()
            with patch.object(cf,'api',return_value={'result':[{'rate_plan':{'id':'free'},'price':0}],'result_info':{'total_count':2}}),self.assertRaisesRegex(RuntimeError,'CF_FREE_PLAN_UNVERIFIED'):cf.free_usage()
            bad=dict(art.CONFIG,billing_allowed=True)
            with self.assertRaisesRegex(RuntimeError,'CF_FREE_CONFIGURATION_REQUIRED'):cf.generate(item,budget,bad)
        with patch.dict(os.environ,{'CLOUDFLARE_ACCOUNT_ID':'','CLOUDFLARE_API_TOKEN':''}):self.assertEqual(cf.status(art.CONFIG),'CLOUDFLARE_CREDENTIALS_MISSING')

    def test_cloudflare_ledger_restore_preserves_other_daily_counters(self):
        from scripts import generation_runtime as rt
        ledger={'day':'2026-11-20','requests':20,'models':{},'cloudflare_ai':{'day':'2026-11-21','account_hash':'one','requests':3,'reserved_neurons':768}}
        newer={'day':'2026-11-21','requests':2,'models':{}}
        rt.merge_snapshot(ledger,newer);self.assertEqual(ledger['cloudflare_ai']['reserved_neurons'],768)
        rt.merge_snapshot(ledger,dict(newer,cloudflare_ai={'day':'2026-11-21','account_hash':'one','requests':1,'reserved_neurons':256}))
        self.assertEqual(ledger['cloudflare_ai']['requests'],3)
        before=copy.deepcopy(ledger)
        with self.assertRaises(ValueError):rt.merge_snapshot(ledger,dict(newer,cloudflare_ai={'day':'2026-11-21','account_hash':'other','requests':9,'reserved_neurons':-1}))
        self.assertEqual(ledger,before)

    def test_art_backfill_is_idempotent_and_preserves_all_editorial_text(self):
        from scripts import mosaic44 as art
        for n in (8,13,25):
            with self.subTest(articles=n),tempfile.TemporaryDirectory() as temp:
                s=issue(n,12);s['date']='2026-11-22';s['brief_policy_revision']=2;synthetic_art(s);target=root(temp);pub.build(s,target)
                before={f.relative_to(target).as_posix():f.read_bytes() for f in (target/'issues').rglob('*') if f.is_file()}
                body={slug:pub.without_art44((target/'issues'/s['date']/'articles'/slug/'index.html').read_text()) for slug in pub.metadata(target,s['date'])['pages']}
                # Existing article files are reused; no second picture for backfill.
                with patch.object(art.p,'ROOT',target),patch.object(art,'generate',side_effect=AssertionError('Do not regenerate published artwork')):
                    parent={};pub.backfill_issue_art(target,s['date'],parent,allow_request=False)
                    self.assertFalse(pub.backfill_issue_art(target,s['date'],parent,allow_request=False))
                    image=pub.metadata(target,s['date'])['illustrations'][0];file=target/image['path'];original=file.read_bytes();file.unlink()
                    self.assertTrue(pub.backfill_issue_art(target,s['date'],parent,allow_request=False));self.assertEqual(file.read_bytes(),original)
                data=pub.validate(target,s['date']);self.assertEqual(len(data['illustrations']),n)
                for slug,text in body.items():self.assertEqual(pub.without_art44((target/'issues'/s['date']/'articles'/slug/'index.html').read_text()),text)
                for name,data_bytes in before.items():
                    if name.endswith('.md'):self.assertEqual((target/name).read_bytes(),data_bytes)

    def test_visual_repair_migrates_only_bound_image_and_reuses_it(self):
        from scripts import mosaic44 as art
        import io
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            s=issue();s['date']='2026-11-22';s['brief_policy_revision']=2;synthetic_art(s)
            target=root(temp);pub.build(s,target);old=pub.validate(target,s['date'])
            image=old['illustrations'][0]
            repairs={image['text_hash']:{'replace_prompt_version':image['prompt_version'],'scene_en':'Children build a castle.'}}
            config=dict(art.CONFIG,prompt_version='fixture-visual-repair',visual_brief_repairs=repairs)
            raw=io.BytesIO();Image.new('RGB',(48,32),(230,130,30)).save(raw,format='PNG')
            body={slug:pub.without_art44((target/'issues'/s['date']/'articles'/slug/'index.html').read_text()) for slug in old['pages']}
            budget=SimpleNamespace(remaining_seconds=lambda:1000,ledger={})
            with patch.object(art,'CONFIG',config),patch.object(art.p,'ROOT',target),patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(art,'provider_status',return_value='READY'),patch.object(art,'generate',return_value=raw.getvalue()) as generate:
                parent={};self.assertTrue(pub.backfill_issue_art(target,s['date'],parent))
                generate.assert_called_once();self.assertIn('Children build a castle',generate.call_args.args[0]['prompt'])
                new=pub.validate(target,s['date']);self.assertEqual(new['art44']['ready'],8)
                self.assertTrue((target/image['path']).is_file())
                self.assertEqual(len(set(r['key'] for r in old['illustrations']) & set(r['key'] for r in new['illustrations'])),7)
                self.assertFalse(pub.backfill_issue_art(target,s['date'],parent));generate.assert_called_once()
                for slug,text in body.items():self.assertEqual(pub.without_art44((target/'issues'/s['date']/'articles'/slug/'index.html').read_text()),text)

    def test_historical_recovery_keeps_newer_issue_number_and_home(self):
        from scripts import mosaic44 as art
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);new=issue();new['date']='2026-11-21';new['brief_policy_revision']=2;pub.build(new,target)
            before={f.relative_to(target).as_posix():f.read_bytes() for f in (target/'issues/2026-11-21').rglob('*') if f.is_file()};home=(target/'index.html').read_bytes()
            old=issue();old['date']='2026-11-20';old['brief_policy_revision']=2
            with self.assertRaisesRegex(Exception,'BACKDATED_HOME_REPLACEMENT_FORBIDDEN'):pub.build(old,target)
            env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'zzz387/387-news','GITHUB_REF_NAME':'main','NEWS_HISTORICAL_RECOVERY_DATE':'2026-11-20'}
            with patch.dict(os.environ,env):pub.build(old,target)
            self.assertEqual((target/'index.html').read_bytes(),home)
            self.assertEqual(before,{f.relative_to(target).as_posix():f.read_bytes() for f in (target/'issues/2026-11-21').rglob('*') if f.is_file()})
            self.assertGreater(pub.metadata(target,'2026-11-20')['number'],pub.metadata(target,'2026-11-21')['number'])
            self.assertEqual(pub.validate(target,'2026-11-20')['date'],'2026-11-20')
            from scripts import release_browser41
            with patch.object(release_browser41.p,'ROOT',target),patch.dict(os.environ,ISSUE_DATE='2026-11-20'),patch.object(release_browser41.production_preflight41,'require_pages'),patch.object(release_browser41.browser41,'check',return_value={}) as browser:
                release_browser41.main()
            self.assertEqual(browser.call_args.kwargs['overview_path'],'/issues/2026-11-20/')

    def test_final_art_uses_existing_morning_wait_without_early_public_files(self):
        from scripts import mosaic44 as art,release_queue
        from datetime import datetime,timedelta
        s=issue();s['brief_policy_revision']=2;synthetic_art(s)
        release=datetime.fromisoformat(s['date']+'T06:00').replace(tzinfo=v.p.TZ)
        clock=[release-timedelta(minutes=6)]
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp)
            def wait(date):
                self.assertFalse((target/'issues'/date/'index.html').exists())
                self.assertFalse((target/'assets/illustrations'/date).exists())
                clock[0]=release
            with patch.dict(os.environ,GITHUB_ACTIONS='true',GITHUB_REF_NAME='main',NEWS_RELEASE_APPROVED='true'),patch.object(release_queue,'wait_until_release',side_effect=wait) as gate:
                self.assertTrue(art.finalize(s,target,lambda:None,lambda:clock[0],release,allow_request=False,allow_wait=True))
            gate.assert_called_once_with(s['date'])
            self.assertEqual(pub.validate(target,s['date'])['art44']['ready'],8)

    def test_all_final_articles_have_unique_art_and_one_shared_file(self):
        from scripts import mosaic44 as art,generation_runtime as rt
        from datetime import datetime,timezone
        import io
        from PIL import Image
        for n in (8,12,20,27):
            with self.subTest(articles=n),tempfile.TemporaryDirectory() as temp:
                s=issue(n,12);s['brief_policy_revision']=2;calls=[]
                def fake(item,budget):
                    budget.reserve('fixture-image');calls.append(item['article_id'])
                    image=Image.new('RGB',(48,32),tuple(bytes.fromhex(item['key'][:6])));buffer=io.BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()
                ledger={'day':datetime.now(timezone.utc).date().isoformat(),'requests':0,'models':{},'cooldowns':{}}
                art.approve(s)
                with patch.object(art,'provider_status',return_value='READY'),patch.object(art,'generate',side_effect=fake):
                    for _ in range(2):
                        budget=rt.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0,seconds=5000)
                        with patch.object(news.runtime,'ACTIVE_BUDGET',budget):art.prepare(s)
                        s=json.loads(json.dumps(s))  # Independent restore, not a shared object.
                self.assertEqual(len(calls),n);self.assertEqual(art.art_report(s)['ready'],n)
                self.assertEqual(ledger['requests'],n)
                target=root(temp);pub.build(s,target);data=pub.validate(target,s['date'])
                self.assertEqual(len(data['illustrations']),n);self.assertTrue(data['art44']['status']=='COMPLETE')
                self.assertEqual(len({r['sha256'] for r in data['illustrations']}),n)
                for row in data['illustrations']:
                    page=(target/'issues'/s['date']/'articles'/row['article_slug']/'index.html').read_text()
                    self.assertIn('src="/'+row['path']+'"',page);self.assertIn('Художественная иллюстрация, созданная ИИ',page)
                front=(target/'index.html').read_text()
                for filename in __import__('re').findall(r'<img src="/([^"]+)"',front):self.assertIn(filename,{r['path'] for r in data['illustrations']})

    def test_art_requires_final_approval_and_text_changes_invalidate_only_one_picture(self):
        from scripts import mosaic44 as art
        s=issue();s['brief_policy_revision']=2
        with patch.object(art,'generate',side_effect=AssertionError('Unapproved text must not reach provider')):
            art.prepare(s);self.assertFalse(s['art44'].get('plan'))
        synthetic_art(s);old={r['article_id']:r['key'] for r in s['art44']['plan']}
        record=s['candidates'][0];record['article']['blocks'][0]['text']+=' Новая проверенная подробность.'
        record['checks']['final43']['input_hash']=e.fingerprint(record)
        self.assertFalse(art.approval_valid(s))
        with patch.object(art,'generate',side_effect=AssertionError('Reapproval required')):art.prepare(s)
        art.approve(s);art.prepare(s,allow_request=False)
        changed={r['article_id']:r['key'] for r in s['art44']['plan']}
        self.assertEqual(sum(old[k]!=changed[k] for k in old),1);self.assertEqual(art.art_report(s)['ready'],7)
        self.assertEqual(len(s['art44']['objects']),8)  # Old approved bytes retained, never silently overwritten.

    def test_art_resume_after_eighteen_of_twenty_and_failure_preserves_progress(self):
        from scripts import mosaic44 as art,generation_runtime as rt
        from datetime import datetime,timezone
        import io
        from PIL import Image
        s=issue(20,12);s['brief_policy_revision']=2;synthetic_art(s)
        for row in s['art44']['plan'][18:]:s['art44']['objects'].pop(row['key'])
        before=copy.deepcopy(s['art44']['objects']);ledger={'day':datetime.now(timezone.utc).date().isoformat(),'requests':0,'models':{}};calls=[]
        def fake(item,budget):
            budget.reserve('fixture-image');calls.append(item['key']);image=Image.new('RGB',(48,32),tuple(bytes.fromhex(item['key'][:6])));buffer=io.BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()
        with patch.object(art,'provider_status',return_value='READY'),patch.object(news.runtime,'ACTIVE_BUDGET',rt.RequestBudget(ledger,run_limit=24,day_limit=220,gap=0,seconds=5000)):
            with patch.object(art,'generate',side_effect=RuntimeError('IMAGE_HTTP_503')):art.prepare(s)
            self.assertEqual(s['art44']['objects'],before)
            restored=json.loads(json.dumps(s))
            with patch.object(art,'generate',side_effect=fake):art.prepare(restored);art.prepare(restored)
        self.assertEqual(len(calls),2);self.assertEqual(art.art_report(restored)['ready'],20)
        self.assertEqual({k:restored['art44']['objects'][k] for k in before},before)

    def test_modern_briefs_select_eight_twelve_and_bank_overflow(self):
        for count in (8,12,15):
            with self.subTest(notes=count):
                s=issue(25,count);s['brief_policy_revision']=2
                texts=copy.deepcopy(s['light43']['records'])
                stock43.bank_light(s,NOW)
                self.assertEqual(len(light43.ready(s)),min(count,12))
                self.assertEqual(len(stock43.available(s,s['date'],'light')),max(0,count-12))
                self.assertEqual([r['article'] for r in s['light43']['records']],[r['article'] for r in texts])
                self.assertEqual([r['checks'] for r in s['light43']['records']],[r['checks'] for r in texts])
                self.assertTrue(v.standard(s)['compliant']);self.assertEqual(len(sel.composition(s)),25)
    def test_brief_crime_and_tragedy_filter_is_story_specific(self):
        from scripts import brief_selection44 as rules
        for title,bad in [('Необычное ограбление банка',True),('A criminal gang was arrested',True),('Суд вынес приговор мошеннику',True),('При аварии пострадали люди',True),('Полицейский оркестр сыграл детям',False),('Музей восстановил картину',False),('Добровольцы посадили городской сад',False),('Killer whales reveal an unusual behaviour',False)]:
            with self.subTest(title=title):self.assertEqual(bool(rules.excluded({'title':title})),bad)
        src,item=response_item();src['title']='Police arrested a suspect in a robbery'
        with self.assertRaisesRegex(ValueError,'BRIEF_CRIME'):brief.accept(item,src)
    def test_brief_diversity_prefers_other_subjects_when_available(self):
        from scripts import brief_selection44 as rules
        rows=[{'id':str(i),'title':('Необычная птица '+str(i)) if i<8 else ['Музейная находка','История города','Изобретение робота','Математическая загадка','Семейная традиция','Спортивный рекорд','Предприниматель открыл дело','Музыкальное открытие'][i-8],'source':{'url':'https://example.org/'+str(i),'publisher':'Nature' if i<8 else 'Publisher '+str(i)}} for i in range(16)]
        selected=rules.select(rows)
        self.assertEqual(len(selected),12);self.assertLessEqual(sum(rules.topic(r)=='nature' for r in selected),4)
    def test_mosaic_cache_reuses_generated_objects_and_disabled_provider_is_honest(self):
        from scripts import mosaic44 as art
        s=issue();s['brief_policy_revision']=2
        with patch.object(art,'generate',side_effect=AssertionError('No configured free image API')):art.prepare(s);art.prepare(s)
        self.assertEqual(s['art44']['provider_status'],'CLOUDFLARE_CREDENTIALS_MISSING')
        synthetic_art(s);before=copy.deepcopy(s['art44']['objects'])
        with patch.object(art,'provider_status',return_value='READY'),patch.object(art,'generate',side_effect=AssertionError('Use saved images')):art.prepare(s)
        self.assertEqual(s['art44']['objects'],before)
    def test_mosaic_uses_unique_real_links_and_falls_back_for_missing_images(self):
        from scripts import mosaic44 as art
        s=issue(20,12);s['brief_policy_revision']=2;synthetic_art(s)
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);pub.build(s,target)
            page=(target/'index.html').read_text();self.assertIn('class="art-front"',page);self.assertNotIn('class="front-grid"',page)
            urls=__import__('re').findall(r'class="art-tile[^>]+href="([^"]+)"',page)
            self.assertEqual(len(urls),len(set(urls)));self.assertGreaterEqual(len(urls),8)
            self.assertIn('loading="lazy"',page);self.assertIn('Иллюстрация ИИ',page)
            for url in urls:self.assertTrue((target/url.strip('/')/'index.html').is_file())
            images=list((target/'assets/illustrations'/s['date']).glob('*.webp'));images[0].unlink()
            articles=art.from_overview(page);fallback=art.render(articles,s['date'],target)
            self.assertNotIn(images[0].name,fallback);self.assertIn('art-fallback',fallback)
    def test_content_subjects_table(self):
        cases=[]
        for expected,titles in [('family',['Развитие детей','Общение с детьми','Счастливое детство','A child learns through play','Kids and parents']),('sport',['История спорта','Физиология бега','Плавание для взрослых','Walking and physical activity'])]:
            cases += [('article',title,title+'. '+title+' — основная тема исследования.',expected) for title in titles]
        cases += [('source','Newborn baby health','Health concerns can include symptoms. Medical advice explains when parents should seek help. The guidance discusses healthcare and symptoms.','health'),
                  ('source','Healthy teeth and gums','Brush your teeth. Dental care matters. Your dentist can help with oral hygiene.','health'),
                  ('source','Best way to wash your hands','Handwashing is ordinary hygiene. Wash your hands carefully. Handwashing helps reduce spread.','health'),
                  ('source','Magnus Ditlev sets an Ironman record','The athlete completed the Ironman distance. The report describes swimming, cycling and running. The record was recorded at the finish.','sport')]
        for field,title,text,expected in cases:
            with self.subTest(subject=expected,title=title):self.assertEqual(v.subject({field:{'title':title,'blocks':[{'text':text}]}}),expected)

    def test_false_subjects_table(self):
        tagged=named('Дом в центре города');tagged['article']['category']='Семья';tagged['category_hint']='Семья'
        cases=[('stale category',tagged),('parent company',{'title':'Parent company funds research','summary':'Parent company manages its subsidiaries.'}),('child process',{'title':'Child processes in Linux','summary':'Child processes inherit parent process state.'})]
        texts=[('Картина художницы','Семья обнаружила картину в доме. Полотно изображает горы.'),('Резервное электропитание кухни','Продукты питания сохраняются благодаря батарее.'),('Обучение модели нейросети','Тренировка модели улучшает результат.'),
               ('Зубы мамонта','Зубы мамонта. Зубы мамонта. Зубы мамонта.'),('Родительская забота у птиц','Родители птиц кормят птенцов. Родители птиц заботятся о птенцах. Родители птиц строят гнездо.'),('Тренировки для собак','Тренировки для собак. Бег собак. Спортивные тренировки собак.'),
               ('A Peruvian hotel with a terrifying check-in','Guests sleep in a capsule. The hotel offers places to sleep. Sleeping high above the valley is unusual. Guests sleep after the climb.')]
        cases += [(title,{'article':{'title':title,'blocks':[{'text':text}]}}) for title,text in texts]
        cases += [(title,{'source':{'title':title,'blocks':[{'text':(title+'. ')*5}]}}) for title in ['Healthy forests','Financial health','Здоровье бизнеса']]
        for label,row in cases:
            with self.subTest(risk=label):self.assertIsNone(v.subject(row))

    def test_uncapped_8_12_16_20_25_30_and_lights_8_12_16(self):
        for n,light in [(8,8),(12,8),(16,8),(20,8),(25,12),(30,16)]:
            with self.subTest(main=n,notes=light),tempfile.TemporaryDirectory() as temp:
                s=issue(n,light);target=root(temp)
                self.assertEqual(len(sel.composition(s)),n);self.assertTrue(v.standard(s)['compliant'])
                pub.build(s,target);data=pub.validate(target,s['date'])
                self.assertEqual((data['article_count'],data['light_count']),(n,light))
                with patch.object(site_checks,'fetch',side_effect=web(target)):self.assertEqual(site_checks.check_site(expected_date=s['date'])['articles'],n)
    def test_seven_main_and_five_light_have_exact_deficits(self):
        s=issue(7,5);report=v.standard(s)
        self.assertEqual((report['main_deficit'],report['light_deficit']),(1,3));self.assertFalse(report['compliant'])
        with tempfile.TemporaryDirectory() as temp,self.assertRaisesRegex(ValueError,'EDITORIAL_STANDARD_NOT_MET'):pub.build(s,root(temp))
    def test_six_different_articles_cover_2_2_2(self):
        self.assertEqual(v.counts(issue()['candidates']),dict(family=2,health=2,sport=2))
    def test_last_eighth_article_uses_verified_candidate_before_large_discovery(self):
        from scripts import daily43,catalog43
        s=issue(7,11);row=main_row(9);row['status']='preparing'
        s['candidates'].append(row)
        def finish(state,row):row['status']='ready'
        editor=__import__('unittest.mock',fromlist=['Mock']).Mock();editor.finish.side_effect=finish
        budget=SimpleNamespace(deadline=float('inf'),can_request=lambda:True,remaining_requests=lambda:0)
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_CATALOG_REFRESH='true'),patch.object(daily43,'discover'),patch.object(catalog43,'refresh') as discovery,patch.object(news.runtime,'ACTIVE_BUDGET',budget):
            daily43.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW,editor=editor)
        editor.finish.assert_called_once();discovery.assert_not_called()
        self.assertEqual(v.standard(s)['main_articles'],8)
        self.assertEqual(v.standard(s)['light_notes'],11)
    def test_published_018_art_and_power_are_not_family_or_health(self):
        files=list((Path(__file__).resolve().parents[1]/'issues/2026-11-11/articles').glob('*/index.html'))
        selected=[v.from_html(f.read_text()) for f in files if any(t in f.read_text() for t in ['Утерянный пейзаж Джорджии','Автономность на кухне'])]
        self.assertEqual(len(selected),2)
        for row in selected:self.assertIsNone(v.subject(row))
    def test_cycling_health_overlap_counts_once(self):
        row=main_row(4);row['article']['blocks'][0]['text']+=' Велосипедные тренировки поддерживают здоровье.'
        self.assertEqual(sum(v.counts([row]).values()),1);self.assertEqual(v.subject(row),'sport')
    def test_family_and_sport_sources_do_not_require_second_publication(self):
        for i in (0,1,4,5):self.assertFalse(e.high_risk(main_row(i)))
    def test_risky_treatment_and_dangerous_exercise_remain_protected(self):
        for title in ['Дайте ребёнку лекарство','Лечение заболевания: следует принимать препарат','Как выполнять стойку на голове']:
            self.assertTrue(e.high_risk(named(title)))
    def test_missing_sport_is_prepared_despite_twenty_ready(self):
        s=issue(20);s['candidates']=[r for r in s['candidates'] if v.subject(r)!='sport']
        sports=main_row(4);sports.update(id='new-sport',status='discovered');science=named('Квантовое открытие',99,'discovered');s['candidates'] += [science,sports]
        self.assertIs(sel.order(s,limit=1)[0],sports)
    def test_topic_directed_discovery_includes_three_distinct_streams(self):
        rows=[{'id':g,'priority_ids':[n],'availability':{},'editorial_priority':50} for g,n in [('family',1),('health',12),('sport',13),('science',22)]]
        result=v.publisher_order(rows,issue(0,0));self.assertEqual({r.get('search_group') for r in result[:3]},set(v.GROUPS))
    def test_migration_preserves_text_facts_quota_and_is_idempotent(self):
        s=issue();s['policy_version']='4.3';s['_quota_snapshot']={'requests':219,'cooldowns':{'m':1234}}
        s['candidates'][0]['article']['category']='Наука';s['candidates'][0]['checks']['final43']['input_hash']=e.fingerprint(s['candidates'][0])
        before=copy.deepcopy(s);v.migrate(s);after=copy.deepcopy(s);v.migrate(s)
        self.assertEqual(s,after);self.assertEqual(s['_quota_snapshot'],before['_quota_snapshot'])
        self.assertEqual(s['candidates'][0]['article']['blocks'],before['candidates'][0]['article']['blocks']);self.assertTrue(e.eligible(s['candidates'][0]))
    def test_published_files_are_never_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);s=issue();pub.build(s,target);before={str(f):f.read_bytes() for f in target.rglob('*') if f.is_file()}
            pub.build(issue(20,16),target);self.assertEqual(before,{str(f):f.read_bytes() for f in target.rglob('*') if f.is_file()})
    def test_any_brief_subject_is_allowed_without_animal_whitelist(self):
        for title in ['Люди открыли музей','Культура города','Спортивное событие','Технология печати','Поведение воронов','История открытия','Экономическая жизнь']:
            self.assertTrue(light43.story_suitable({'title':title}))
    def test_simple_brief_has_one_fact_gate_and_no_article_audit(self):
        src,item=response_item();row=brief.accept(item,src)
        self.assertTrue(brief.eligible(row));self.assertNotIn('final43',row['checks'])
        row['article']['blocks'][0]['text']='Подменённый непроверенный текст';self.assertFalse(brief.eligible(row))
    def test_invented_quote_number_copy_or_instruction_is_rejected(self):
        src,item=response_item()
        for field,value in [('text','Музей восстановил 99 картин.'),('text',src['blocks'][0]['text']),('text','Принимайте препарат ежедневно.')]:
            test=copy.deepcopy(item);test[field]=value
            with self.subTest(value=value),self.assertRaises(ValueError):brief.accept(test,src)
        item['evidence'][0]['quote']='A fabricated fact'
        with self.assertRaisesRegex(ValueError,'BRIEF_FACT_NOT_BOUND'):brief.accept(item,src)
    def test_completed_batch_resumes_without_api_or_budget(self):
        src,item=response_item();s=issue(8,0);s['light43']['v44']={'sources':[src],'response':{'items':[item]},'window':'old-run','attempts':1,'http_requests':1,'refusals':[],'completed':[]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',None),patch.object(news,'gemini',side_effect=AssertionError('Already paid')):
            brief.prepare(s);restored=json.loads(json.dumps(s));brief.prepare(restored)
        self.assertEqual(len(brief.ready(restored)),1);self.assertEqual(restored['light43']['v44']['http_requests'],1)
    def test_eight_reserve_notes_form_column_without_gemini(self):
        s=issue(8,0);stock43.ensure(s)['light']=[light_ready(i) for i in range(8)]
        with tempfile.TemporaryDirectory() as temp,patch.object(news,'gemini',side_effect=AssertionError('No inference')):stock43.draw_light(s,root(temp))
        self.assertEqual(len(light43.ready(s)),8);self.assertTrue(v.standard(s)['compliant'])
    def test_independent_encrypted_restore_preserves_completed_stages_and_ledger(self):
        s=issue(20,12);s['_quota_snapshot']={'requests':219};key=bytes(range(32))
        restored=staged_news.decipher(staged_news.cipher(s,key),key)
        self.assertEqual(v.standard(s),v.standard(restored));self.assertEqual(s['_quota_snapshot'],restored['_quota_snapshot']);self.assertEqual(len(sel.composition(restored)),20)


    def test_ready_stock_keeps_unlimited_main_and_caps_modern_briefs(self):
        s=issue(12,0);stock=stock43.ensure(s)
        stock['records']=[main_row(i) for i in range(12,25)]
        stock['light']=[light_ready(i) for i in range(16)]
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);stock43.draw(s,target,NOW);stock43.draw_light(s,target)
        self.assertEqual((len(sel.composition(s)),len(light43.ready(s))),(25,12))
        self.assertEqual(len(brief.all_ready(s)),16)
    def test_short_topics_do_not_use_main_article_family_aliases(self):
        a=named('Живые строительные материалы',30);b=named('Самовосстанавливающийся бетон',31)
        self.assertTrue(sel.duplicate(a,b));self.assertFalse(brief.duplicate(a,b))
    def test_unverified_dates_and_false_recency_are_rejected(self):
        src,item=response_item();item.update(time_kind='news',event_date='2026-11-11',text='Сегодня музей восстановил 21 картину.')
        with self.assertRaisesRegex(ValueError,'BRIEF_EVENT_DATE_UNSUPPORTED'):brief.accept(item,src)
        item.update(time_kind='unusual_fact',text='Сегодня музей восстановил 21 картину.')
        with self.assertRaisesRegex(ValueError,'BRIEF_FALSE_RECENCY'):brief.accept(item,src)
    def test_one_batched_request_is_charged_and_not_repeated_in_same_window(self):
        from scripts import generation_runtime as rt
        src,item=response_item();s=issue(8,0)
        s['candidates'].append({'id':'brief-source','url':src['url'],'source':src,'status':'discovered','progress':{},'history':[],'for_light_only':True})
        s['light43_queue']=['brief-source']  # Production queue stores IDs, not dictionaries.
        budget=rt.RequestBudget({});budget.deadline=__import__('time').monotonic()+1000
        alias=copy.deepcopy(item);alias.update(source_id='s1');alias['evidence'][0]['block_id']='q1'
        def model(*a,**kw):budget.reserve('fixture-model');return {'items':[alias]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(news,'gemini',side_effect=model) as call:
            brief.prepare(s);brief.prepare(s)
        self.assertEqual(call.call_count,1);self.assertEqual(budget.used,1);self.assertEqual(s['light43']['v44']['http_requests'],1)
        self.assertEqual(len(brief.ready(s)),1)


    def test_due_deficit_creates_existing_safe_incident(self):
        from scripts import release_monitor as monitor
        calls=[]
        def github(method,path,payload=None):
            calls.append((method,path,payload));return [] if method=='GET' else {}
        status=monitor.evaluate(Path('/nonexistent'),{'date':NOW.date().isoformat(),'block_code':'EDITORIAL_STANDARD_NOT_MET'},NOW,check_public=lambda **kw:(_ for _ in ()).throw(ValueError('No issue')))
        self.assertEqual(status['code'],'EDITORIAL_DEFICIT');self.assertTrue(status['alert'])
        self.assertEqual(monitor.incident(status['date'],status['code'],False,request=github),'created')
        self.assertNotIn('source',str(calls[-1][2]).lower())


    def test_watchdog_resumes_policy44_deficits_in_the_same_controller(self):
        from scripts import delivery_watchdog as watch
        from scripts.test_delivery_watchdog import Clock,API,at
        clock=Clock(at('07:00'));api=API(clock)
        with patch.dict(os.environ,NEWS_POLICY_VERSION='4.4'):
            result=watch.run(Path('/unused'),clock=clock,sleep=clock.sleep,request=api,check=api.check)
        self.assertTrue(result['verified']);self.assertEqual(api.posts[0][1]['inputs']['phase'],'run')
        self.assertEqual(len(api.posts),1)


    def test_restored_legacy_news_keep_date_checks_and_titles_are_own(self):
        s=issue(8,1);row=s['light43']['records'][0];row['checks']['final43'].update(is_news=True,event_date='2099-01-01')
        self.assertEqual(light43.ready(s),[])
        src,item=response_item();src['title']=item['title']='Долгая история необычного открытия в музее'
        with self.assertRaisesRegex(ValueError,'BRIEF_COPIED_TITLE'):brief.accept(item,src)


    def test_current_sixteen_briefs_are_not_capped_to_build_stock(self):
        s=issue(8,16);stock43.bank_light(s,NOW)
        self.assertEqual(len(light43.ready(s)),16);self.assertEqual(stock43.report(s)['ready_light'],0)
    def test_independent_stock_batch_survives_current_and_next_issue(self):
        src,item=response_item();s=issue(8,16)
        s['light43']['v44']={'sources':[src],'response':{'items':[item]},'window':'stock-run','attempts':1,'http_requests':1,'refusals':[],'completed':[],'destination':'stock'}
        accept=brief.accept
        def checked(*a):
            row=accept(*a);row['ready_checked_at']=NOW.isoformat();return row
        with patch.object(brief,'accept',side_effect=checked),tempfile.TemporaryDirectory() as temp:
            target=root(temp);brief.apply_response(s);stock43.draw_light(s,target)
            self.assertEqual(len(light43.ready(s)),16);self.assertEqual(stock43.report(s)['ready_light'],1)
            restored=json.loads(json.dumps(s));stock43.draw_light(restored,target)
            self.assertEqual(len(light43.ready(restored)),16)
            tomorrow=issue(8,0);tomorrow['date']='2026-10-28';stock43.merge(tomorrow,restored['stock43']);stock43.draw_light(tomorrow,target)
            self.assertEqual(len(light43.ready(tomorrow)),1)


    def test_explicit_main_stock_does_not_reenter_the_current_issue(self):
        s=issue(16);row=main_row(40);row['stock_prepared_for']=s['date'];self.assertTrue(stock43.bank(s,row,NOW))
        with tempfile.TemporaryDirectory() as temp:
            target=root(temp);stock43.draw(s,target,NOW)
            self.assertEqual(len(sel.composition(s)),16);self.assertEqual(stock43.report(s)['ready_articles'],1)
            tomorrow=issue(8);tomorrow['date']='2026-10-28';stock43.merge(tomorrow,s['stock43']);stock43.draw(tomorrow,target,NOW)
            self.assertEqual(len(sel.composition(tomorrow)),9)
    def test_main_stock_commissioning_preserves_uncapped_current_issue(self):
        from scripts import daily43
        s=issue(20);pending=main_row(40);pending.update(id='future-article',status='discovered');s['candidates'].append(pending)
        class Editor:
            def finish(self,state,row):row['status']='ready'
        with tempfile.TemporaryDirectory() as temp,patch.object(daily43,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True)):
            daily43.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW.replace(hour=5),editor=Editor())
        self.assertEqual(len(sel.composition(s)),20);self.assertEqual(stock43.report(s)['ready_articles'],1)


    def test_full_general_reserve_does_not_prevent_missing_subjects(self):
        s=issue(16);stock43.ensure(s)['records']=[main_row(i) for i in range(30,50)]
        row=main_row(0);self.assertTrue(stock43.bank(s,row,NOW))
        self.assertEqual(stock43.report(s)['required_topics']['family'],1)
        self.assertEqual(stock43.report(s)['ready_articles'],21)


    def test_incidental_source_words_do_not_enter_targeted_writing(self):
        row={'title':'Образование и экономика региона','source':{'title':'Образование и экономика региона','blocks':[{'text':'Исследуется промышленность, университеты и экономика. Спортивные тренировки упомянуты в студенческой жизни. Затем рассматриваются бюджет, экспорт, промышленность и занятость. Обсуждаются отрасли экономики и университеты.'}]}}
        self.assertIsNone(v.subject(row))
    def test_focused_publisher_precedes_mixed_convenient_feed(self):
        rows=[{'id':'mixed','priority_ids':[1,3,18,23],'availability':{'full_originals_verified':20}}, {'id':'family','priority_ids':[1,2,3],'availability':{'full_originals_verified':2}}]
        self.assertEqual(v.publisher_order(rows,issue(0,0))[0]['id'],'family')
    def test_equivalent_number_notation_is_not_a_factual_refusal(self):
        self.assertEqual(brief.numbers('1,000 and 2.5','en'),brief.numbers('1 000 и 2,5','ru'))
        self.assertNotEqual(brief.numbers('1,000','en'),brief.numbers('999','ru'))
    def test_surplus_general_articles_do_not_consume_missing_subject_budget(self):
        from scripts import daily43
        s=issue(20);s['candidates']=[r for r in s['candidates'] if v.subject(r) is None];s['candidates'] += [main_row(i) for i in range(40,50)]
        row=main_row(90);row['status']='discovered';s['candidates'].append(row);editor=__import__('unittest.mock',fromlist=['Mock']).Mock()
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_LIGHT_NEWS_ENABLED='true'),patch.object(light43,'prepare') as extra_briefs,patch.object(daily43,'discover'),patch.object(news.runtime,'ACTIVE_BUDGET',SimpleNamespace(deadline=float('inf'),can_request=lambda:True,remaining_requests=lambda:24)):
            daily43.advance(s,s['date'],False,SimpleNamespace(ROOT=root(temp)),now=NOW.replace(hour=5),editor=editor)
        editor.finish.assert_not_called();extra_briefs.assert_not_called();self.assertFalse(s['audit_passed'])


    def test_search_targets_two_candidates_per_missing_subject(self):
        self.assertEqual(v.search_deficits(issue(0,0)),dict(family=2,health=2,sport=2))
        s=issue();self.assertEqual(v.search_deficits(s),dict(family=2,health=2,sport=2))  # Replenish empty protected stock.
    def test_ordinary_bedtime_games_are_not_medical_but_infant_safety_is(self):
        self.assertFalse(e.high_risk(named('Игры с малышом перед сном: пение и дыхание')))
        for title in ['Как кормить младенца','Медицинская помощь младенцу при температуре','Как укладывать младенца спать на живот']:
            self.assertTrue(e.high_risk(named(title)))


    def test_decimal_admission_migration_recovers_saved_response_without_api(self):
        src,item=response_item();src['language']='en';src['blocks'][0]['text']='The museum restored 1,000 paintings in its collection.'
        item['text']='Музей восстановил 1 000 картин из своего собрания.';item['evidence'][0]['quote']=src['blocks'][0]['text']
        s=issue(8,0);s['light43']['v44']={'sources':[src],'response':{'items':[item]},'response_applied':True,'admission_revision':1,'window':'paid-run','attempts':1,'http_requests':1,'refusals':[{'url':src['url'],'code':'BRIEF_NUMBER_UNSUPPORTED'}],'completed':[]}
        with patch.object(news.runtime,'ACTIVE_BUDGET',None),patch.object(news,'gemini',side_effect=AssertionError('Response already paid')):
            brief.prepare(s);brief.prepare(s)
        self.assertEqual(len(light43.ready(s)),1);self.assertEqual(s['light43']['v44']['http_requests'],1)


    def test_source_medical_aside_does_not_force_an_ordinary_c_article_to_be_medical(self):
        row=main_row(0);article=row.pop('article');row['title']=row['source']['title']='Семейные игры'
        row['source']['blocks'].append({'id':'aside','text':'A clinical trial described medication effects in patients.','kind':'paragraph'})
        row['checks'].pop('final43');row['mode']='INDEPENDENT_ARTICLE'
        editor=e.Editor();editor.verify_source(row);self.assertTrue(row['source_risk_pending'])
        row['article']=article;editor.verify_source(row);self.assertFalse(e.high_risk(row))
        row['article']['title']='Дайте ребёнку лекарство'
        with self.assertRaisesRegex(ValueError,'INDEPENDENT_SAFETY_EVIDENCE_REQUIRED'):editor.verify_source(row)




    def test_literary_family_title_is_supported_by_lead_and_repeated_actual_content(self):
        body='Parents can support children at home. Adults often have questions. Each child develops at a different pace. Play can be shared. Parents can listen without judging. New experiences take time. The practical examples explain ordinary communication. Support can be quiet.'
        self.assertEqual(v.subject({'article':{'title':'Small steps together','teaser':'','blocks':[{'text':body}]}}),'family')
    def test_official_stable_guidance_can_be_undated_but_breaking_clinical_news_cannot(self):
        from scripts import catalog43
        src={'title':'Clinical guidance','url':'https://www.nhs.uk/conditions/asthma/','blocks':[{'text':'Medical treatment and medication are discussed.'}]}
        self.assertTrue(catalog43.undated_evergreen(src,{'allow_archive':True}))
        src['title']='New study today';src['url']='https://www.nhs.uk/news/clinical-study'
        self.assertFalse(catalog43.undated_evergreen(src,{'allow_archive':True}))


    def test_missing_groups_keep_searching_in_round_robin_within_existing_budget(self):
        from scripts import catalog43 as catalog
        original=catalog.registry();template=original['publishers'][0];publishers=[]
        for group,direction in [('family',1),('health',12),('sport',13)]:
            for i in range(1,5):
                pub=copy.deepcopy(template);pub.update(id=group+str(i),domain=group+str(i)+'.example.org',homepage='https://'+group+str(i)+'.example.org/',priority_ids=[direction],enabled=True,availability={'status':'verified','full_originals_verified':1})
                publishers.append(pub)
        cfg=dict(original,publishers=publishers,publishers_per_run=5,article_checks_per_run=8)
        calls={g:0 for g in v.GROUPS};limits=[]
        titles={'family':'Воспитание детей','health':'Здоровое питание','sport':'Йога и подвижность'}
        def inspect(pub,session,article_limit=2,exclude=(),now=None,preferred_group=None):
            group=preferred_group or next(g for g in v.GROUPS if pub['id'].startswith(g));calls[group]+=1;limits.append(article_limit);found=[]
            if calls[group]>=3:
                for i in range(min(2,article_limit)):
                    src=copy.deepcopy(ready(90)['source']);src.update(id=pub['id']+str(i),url=pub['homepage']+str(i),title=titles[group]);src['blocks']=[{'id':'proof','kind':'paragraph','text':titles[group]+'. '+titles[group]+'.'}]
                    found.append(({'url':src['url'],'title':src['title']},src))
            return {'publisher':pub['id'],'status':'full_sources_verified' if found else 'discovery_verified','discovered':5,'eligible':len(found),'article_checks':1,'last_article_code':None},found
        s=issue(0,0)
        with patch.object(catalog,'registry',return_value=cfg),patch.object(catalog,'inspect_publisher',side_effect=inspect),patch.dict(os.environ,NEWS_LIGHT_NEWS_ENABLED='false'):
            report=catalog.refresh(s,NOW,shortage=True)['last_run']
        self.assertEqual(limits[:3],[2,2,2]);self.assertTrue(all(calls[g]>=3 for g in v.GROUPS));self.assertTrue(all(report['candidate_groups'][g]>=2 for g in v.GROUPS));self.assertLessEqual(report['article_checks'],24)


    def test_official_nhs_identity_does_not_grant_republication_rights(self):
        from scripts import source41,rights41
        html='<html lang="en"><head><title>Food habits</title></head><body><article><h1>Food habits</h1><p>Nutrition guidance explains ordinary food habits and practical choices for adults.</p><p>The page is an official informational guide for readers.</p></article></body></html>'
        src=source41.extract(html,'https://www.nhs.uk/live-well/eat-well/')
        self.assertEqual(src['metadata_status'],'verified');self.assertTrue(src['full_text_verified'])
        self.assertEqual(rights41.decision(src,'INDEPENDENT_ARTICLE')['status'],'allowed')
        self.assertNotEqual(rights41.decision(src,'ORIGINAL_REPUBLICATION')['status'],'allowed')


    def test_model_date_hint_does_not_block_a_verified_undated_source_report(self):
        src,item=response_item();item.update(time_kind='news',event_date='2026-11-11')
        row=brief.accept(item,src);self.assertEqual(row['light_kind'],'source_report')
        self.assertEqual(row['checks']['brief44']['event_date'],'');self.assertTrue(brief.eligible(row))
        for text in ['Сегодня музей восстановил 21 картину.','Музей откроется завтра.','В 2026 году музей восстановил 21 картину.']:
            case=copy.deepcopy(item);case['text']=text
            with self.assertRaises(ValueError):brief.accept(case,src)


    def test_medlineplus_and_nih_are_not_independent_medical_publishers(self):
        from scripts import editorial41
        self.assertEqual(editorial41.publisher_identity('https://magazine.medlineplus.gov/article'),editorial41.publisher_identity('https://www.nih.gov/article'))
        self.assertNotEqual(editorial41.publisher_identity('https://www.nhs.uk/article'),editorial41.publisher_identity('https://www.nih.gov/article'))


    def test_who_navigation_is_not_a_complete_publication(self):
        from scripts import catalog43
        self.assertFalse(catalog43.article_link({'url':'https://www.who.int/mega-menu/health-topics/resources/questions-and-answers','heading_link':True}))
        self.assertTrue(catalog43.article_link({'url':'https://www.who.int/news-room/feature-stories/detail/an-example','heading_link':True}))




    def test_ordinary_prevention_is_not_disease_treatment_but_clinical_claims_remain_risky(self):
        for title in ['Мытьё рук помогает снижать риск заболеваний','Следует поддерживать обычную гигиену для профилактики болезней','Как контролировать сердечный ритм на обычной тренировке']:
            self.assertFalse(e.high_risk(named(title)))
        for title in ['Рекомендации по нагрузкам при сердечных заболеваниях','Как выполнять упражнения при болезни','Йога лечит все болезни','Диета предотвращает инфаркт','Принимайте препарат ежедневно']:
            self.assertTrue(e.high_risk(named(title)))

if __name__=='__main__':unittest.main()
