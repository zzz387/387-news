"""Small synthetic museum fixtures; live model tests run only on protected main."""
import base64,copy,io,json,os,random,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from email.parser import BytesParser
from email.policy import default
from PIL import Image,ImageDraw
from scripts import art_library44 as lib,cloudflare44 as cf,mosaic44 as art,generation_runtime as runtime


def picture(i):
    image=Image.new('RGB',(80,60),(200,210,190));draw=ImageDraw.Draw(image);rng=random.Random(i)
    for _ in range(12):draw.line(tuple(rng.randrange(60) for _ in range(4)),fill=tuple(rng.randrange(256) for _ in range(3)),width=3)
    buffer=io.BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()

class ArtLibraryTests(unittest.TestCase):

    def stock(self,root,n=12,genre='Импрессионизм'):
        state={'date':'2026-11-23'};registry=lib.load(root,state)
        for i in range(n):
            row={'genre_id':lib.genre_id(genre),'museum':'Synthetic museum','museum_id':'fixture:'+str(i),'artist':'Fixture artist '+str(i),'title':'Fixture painting '+str(i),'year':'1890','source_url':'https://www.artic.edu/artworks/'+str(i),'license':'CC0','license_url':'https://www.artic.edu/open-access/open-access-images','verified':True,'genre_evidence':'Impressionism'}
            lib.ingest(root,registry,row,picture(i),state,lambda:None)
        self.assertEqual(len(registry['artworks']),n)
        return state
    def items(self,n,genre='Импрессионизм'):return [{'genre':genre,'descriptor':{'title':'Fixture '+str(i)},'key':str(i)} for i in range(n)]

    def test_one_quartet_for_one_or_five_articles_and_new_issue_rotates(self):
        for count in (1,5):
            with self.subTest(articles=count),tempfile.TemporaryDirectory() as temp:
                state=self.stock(temp);items=self.items(count)
                with patch.object(lib.Museum,'get',side_effect=AssertionError('Do not refetch')):
                    sets=lib.prepare_sets(temp,state,items,discover=True);lib.attach(temp,state,items,sets)
                    ids=sets['Импрессионизм']['artwork_ids'];self.assertEqual(len(ids),4)
                    self.assertTrue(all(item['reference_artwork_ids']==ids for item in items))
                    again=lib.prepare_sets(temp,state,items);self.assertEqual(sets,again)
                    second={'date':'2026-11-24'};sets2=lib.prepare_sets(temp,second,items,discover=False)
                    self.assertTrue(set(ids).isdisjoint(sets2['Импрессионизм']['artwork_ids']))
                    self.assertEqual(len(second['art_library44']['registry']['sets']),2)
    def test_same_date_different_issue_ids_do_not_share_a_quartet(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp);state['issue_id']='daily-029'
            a=lib.prepare_sets(temp,state,self.items(5),discover=False)
            b=lib.prepare_sets(temp,{'date':state['date'],'issue_id':'special-029R'},self.items(5),discover=False)
            self.assertTrue(set(a['Импрессионизм']['artwork_ids']).isdisjoint(b['Импрессионизм']['artwork_ids']))
    def test_three_genres_and_absent_genre_never_gets_a_set(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);registry=state['art_library44']['registry']
            for i,genre in enumerate(('Футуризм','Символизм')):
                for j in range(4):
                    row=copy.deepcopy(next(iter(registry['artworks'].values())));row.update(genre_id=lib.genre_id(genre),museum_id=genre+str(j),title=genre+str(j),artist=genre+str(j))
                    lib.ingest(temp,registry,row,picture(50+i*10+j),state,lambda:None)
            sets=lib.prepare_sets(temp,state,self.items(5)+self.items(3,'Футуризм')+self.items(2,'Символизм'),discover=False)
            self.assertEqual(len(sets),3);self.assertTrue(all(len(s['artwork_ids'])==4 for s in sets.values()))
            other={'date':'2026-11-25'};lib.prepare_sets(temp,other,[],discover=False)
            self.assertFalse(any(s['issue_id']=='2026-11-25' for s in other['art_library44']['registry']['sets'].values()))
    def test_resume_restores_downloads_and_does_not_search_or_reassign(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);sets=lib.prepare_sets(temp,state,self.items(5),discover=False)
            snapshot=json.loads(json.dumps(state));registry=state['art_library44']['registry']
            for w in registry['artworks'].values():(Path(temp)/w['path']).unlink()
            with patch.object(lib.Museum,'get',side_effect=AssertionError('Do not download again')):
                self.assertEqual(sets,lib.prepare_sets(temp,snapshot,self.items(5)))
            self.assertTrue(all(lib.file_valid(temp,w) for w in registry['artworks'].values()))
    def test_duplicate_ids_metadata_and_reproduction_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);reg=state['art_library44']['registry'];work=copy.deepcopy(next(iter(reg['artworks'].values())))
            self.assertIsNone(lib.ingest(temp,reg,work,picture(99),state,lambda:None))
            work['museum_id']='another-museum:same-painting';work['artist']+=' (French, 1840-1926)'
            self.assertIsNone(lib.ingest(temp,reg,work,picture(99),state,lambda:None))
            work.update(title='Another title',artist='Another author')
            self.assertIsNone(lib.ingest(temp,reg,work,picture(0),state,lambda:None))
            work['license']='Unknown'
            with self.assertRaisesRegex(ValueError,'RIGHTS'):lib.ingest(temp,reg,work,picture(99),state,lambda:None)
    def test_next_issue_skips_known_works_before_downloading(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);lib.prepare_sets(temp,state,self.items(1),discover=False)
            old=list(state['art_library44']['registry']['artworks'].values());candidates=[]
            for i,row in enumerate(old):candidates.append(dict(row,image_url='https://www.artic.edu/existing/'+str(i)))
            for i,row in enumerate(old):candidates.append(dict(row,museum_id='new:'+str(i),title='New fixture '+str(i),artist='New author '+str(i),image_url='https://www.artic.edu/new/'+str(i)))
            def get(client,url):
                self.assertNotIn('/existing/',url)
                return picture(100+int(url.rsplit('/',1)[1]))
            with patch.object(lib.Museum,'candidates',return_value=iter(candidates)),patch.object(lib.Museum,'get',autospec=True,side_effect=get) as download:
                sets=lib.prepare_sets(temp,{'date':'2026-11-24'},self.items(1))
                self.assertEqual(len(sets),1);self.assertEqual(download.call_count,1)

    def test_single_reference_and_thirty_day_reuse_preserve_history(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,1);items=self.items(2)
            with patch.object(lib.Museum,'get',side_effect=AssertionError('Use saved library')):
                sets=lib.prepare_sets(temp,state,items);lib.attach(temp,state,items,sets)
                self.assertEqual(len(sets['Импрессионизм']['artwork_ids']),1)
                self.assertTrue(all(i['reference_images_sent']==1 for i in items))
                self.assertEqual(items[0]['selected_reference_id'],items[1]['selected_reference_id'])
                for day,allowed in (('2026-12-22',False),('2026-12-23',True),('2027-01-21',False),('2027-01-22',True)):
                    result=lib.prepare_sets(temp,{'date':day},self.items(1),discover=False)
                    self.assertEqual(bool(result),allowed,day)
                self.assertEqual(len(lib.load(temp)['sets']),3)
                self.assertEqual(sets,lib.prepare_sets(temp,state,items,discover=False))

    def test_museum_metadata_and_access_checks_fail_closed(self):
        for genre,identifier in (('Футуризм',485555),('Метафизическая живопись',435683)):
            artist,title,_=lib.MET_REFERENCE_WORKS[identifier]
            row=dict(objectID=identifier,isPublicDomain=True,artistDisplayName=artist,title=title,classification='Paintings',objectDate='1914',objectURL='https://www.metmuseum.org/art/collection/search/'+str(identifier),primaryImageSmall='https://images.metmuseum.org/fixture.jpg')
            self.assertTrue(lib.rights_valid(lib.met_seed_work(row,identifier,genre)))
            for wrong in ({'isPublicDomain':False},{'artistDisplayName':'Other artist'},{'title':'Other painting'}):
                self.assertIsNone(lib.met_seed_work(dict(row,**wrong),identifier,genre))
        self.assertTrue(lib.genre_matches('Японская гравюра','Japan Color woodblock print'))
        self.assertFalse(lib.genre_matches('Японская гравюра','European oil painting'))
        self.assertTrue(lib.genre_matches('Конструктивизм','Constructivist design'))
        self.assertTrue(lib.genre_matches('Ар-деко','Art Déco'));self.assertTrue(lib.genre_matches('Ар-нуво','Jugendstil'))
        self.assertFalse(lib.genre_matches('Кубизм','Neo-Plasticism evolved from Cubism'))
        self.assertFalse(lib.genre_matches('Кубизм','Mondrian progressed from Cubism to an increasingly abstract style'))
        self.assertTrue(lib.genre_matches('Кубизм','A Cubist composition'))
        self.assertTrue(lib.curated_smk_cubist('KMSr61','Gris, Juan','Guitarspillersken','1926'))
        self.assertFalse(lib.curated_smk_cubist('KMSr61','Another artist','Guitarspillersken','1926'))
        self.assertFalse(lib.curated_smk_cubist('KMSr162','Gris, Juan','Another work','1916'))
        self.assertFalse(lib.genre_matches('Кубизм','Cubo-Futurism is a distinct movement'))
        museum=lib.Museum();data={'data':[{'id':1,'title':'Fixture painting','artist_title':'Fixture painter','date_display':'1890','image_id':'fixture','artwork_type_title':'Painting','style_titles':['Impressionism'],'is_public_domain':True}]}
        with patch.object(museum,'get',return_value=json.dumps(data).encode()):
            work=next(museum.candidates('Импрессионизм'));self.assertEqual(work['license'],'CC0');self.assertEqual(work['genre_id'],'impressionism')
        null_row=dict(data['data'][0],medium_display=None,style_titles=None)
        with patch.object(museum,'get',return_value=json.dumps({'data':[null_row,data['data'][0]]}).encode()):self.assertEqual(next(museum.candidates('Импрессионизм'))['museum_id'],'aic:1')
        with self.assertRaisesRegex(ValueError,'HOST'):museum.get('https://attacker.invalid/image.webp')
    def test_color_profiles_selection_and_style_instructions_are_deterministic(self):
        from scripts import art_reference44 as color
        red=io.BytesIO();Image.new('RGB',(80,80),(200,35,20)).save(red,format='PNG')
        blue=io.BytesIO();Image.new('RGB',(80,80),(15,60,210)).save(blue,format='PNG')
        a=color.profile(red.getvalue());b=color.profile(blue.getvalue())
        self.assertEqual(color.compare(a,a)['status'],'COLOR_MATCH_OK')
        self.assertEqual(color.compare(a,b)['status'],'COLOR_MISMATCH')
        self.assertGreater(color.distance(a,b),50);self.assertEqual(a['dominant'],['#c82314'])
        mass_a={'groups':[{'share':.9,'lab':[50,60,0]},{'share':.1,'lab':[50,-60,0]}],'lightness':50,'saturation_value':.6}
        mass_b=dict(mass_a,groups=[{'share':.1,'lab':[50,60,0]},{'share':.9,'lab':[50,-60,0]}])
        self.assertGreater(color.distance(mass_a,mass_b),90)
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);items=self.items(5);sets=lib.prepare_sets(temp,state,items,discover=False)
            lib.attach(temp,state,items,sets);selected=[i['selected_reference_id'] for i in items]
            lib.attach(temp,state,items,sets);self.assertEqual(selected,[i['selected_reference_id'] for i in items])
            self.assertEqual(len(sets['Импрессионизм']['artwork_ids']),4)
            corrected=dict(items[0],key='corrected-prompt',preferred_reference_id=selected[0]);lib.attach(temp,state,[corrected],sets);self.assertEqual(corrected['selected_reference_id'],selected[0])
            self.assertTrue(all(len(i['reference_images'])==1 and i['reference_images_sent']==1 for i in items))
            self.assertTrue(all(i['selected_reference_id'] in i['reference_artwork_ids'] for i in items))
            for genre in ('Импрессионизм','Конструктивизм','Ар-нуво'):
                item=dict(items[0],genre=genre);prompt=cf.prompt(item)
                self.assertIn('unsigned',prompt);self.assertLess(prompt.index('No text'),prompt.index('ARTICLE SUBJECT'));self.assertIn('corners blank',prompt);self.assertIn('single attached',prompt);self.assertIn(color.direction(genre)['characteristics'],prompt)
                self.assertNotIn('muted ochre, cream, deep green',prompt)
                self.assertNotIn('Use all four',prompt)
            self.assertNotIn('Visible brushwork',cf.prompt(dict(items[0],genre='Конструктивизм')))
            construct=cf.prompt(dict(items[0],genre='Конструктивизм'));self.assertIn('not an architectural visualization',construct);self.assertIn('image 0 (input_image_0)',construct)
            self.assertIn(color.direction('Конструктивизм')['texture'],construct)
            green=io.BytesIO();Image.new('RGB',(80,80),(30,140,40)).save(green,format='PNG')
            green_prompt=cf.prompt(dict(items[0],palette=color.profile(green.getvalue())))
            self.assertNotIn('reference has no dominant green field',green_prompt)
            red_prompt=cf.prompt(dict(items[0],palette=a));self.assertIn('reference has no dominant green field',red_prompt)


    def test_targeted_repair_has_new_keys_but_preserves_two_images_and_all_text(self):
        from scripts.test_policy44 import issue,synthetic_art
        from scripts.test_daily43 import root as site_root
        from scripts import publication43 as pub,art_reference44 as color
        from scripts import generation_runtime as runtime
        with tempfile.TemporaryDirectory() as temp:
            target=site_root(temp);s=issue(13,12);s['date']='2026-11-23';s['brief_policy_revision']=2
            s['art_library44']=self.stock(target,4)['art_library44'];styles={key:['Импрессионизм'] for key in art.STYLES}
            old_config=dict(art.CONFIG,prompt_version='387-art-cloudflare-5',references_enabled=False)
            with patch.object(art,'STYLES',styles),patch.object(art,'CONFIG',old_config),patch.object(pub.news,'get_next_number',return_value=29):
                synthetic_art(s)
                for index,obj in enumerate(s['art44']['objects'].values()):obj['model']=cf.REFERENCE_MODEL if index in (2,5) else cf.MODEL
                pub.build(s,target)
            before=pub.metadata(target,s['date']);originals={r['article_slug']:r for r in before['illustrations']}
            texts={p:p.read_bytes() for p in (target/'issues'/s['date']).rglob('*.md')}
            config=dict(art.CONFIG,repair_legacy_art=dict(art.CONFIG['repair_legacy_art'],stage='pilot'))
            budget=type('Budget',(),{'ledger':{},'remaining_seconds':lambda self:1000})()
            n=[500]
            def generate(item,budget):n[0]+=1;return picture(n[0])
            later={'date':s['date'],'art_library44':s['art_library44']}
            with patch.object(art.p,'ROOT',target),patch.object(art,'CONFIG',config),patch.object(art,'provider_status',return_value='READY'),patch.object(runtime,'ACTIVE_BUDGET',budget),patch.object(lib.Museum,'get',side_effect=AssertionError('Use the same museum set')),patch.object(art,'generate',side_effect=generate) as calls,patch.object(color,'compare',return_value={'status':'COLOR_MATCH_OK','lab_distance':0}):
                self.assertFalse(pub.backfill_issue_art(target,s['date'],later,repair_legacy_images=True));self.assertEqual(calls.call_count,3)
                self.assertEqual(pub.metadata(target,s['date']),before)
                config['repair_legacy_art']['stage']='all'
                self.assertTrue(pub.backfill_issue_art(target,s['date'],later,repair_legacy_images=True));self.assertEqual(calls.call_count,11)
                after=pub.metadata(target,s['date'])
                for image in after['illustrations']:
                    old=originals[image['article_slug']]
                    if old['model']==cf.REFERENCE_MODEL:self.assertEqual(image,old)
                    else:
                        self.assertNotEqual(image['path'],old['path']);self.assertEqual(image['text_hash'],old['text_hash']);self.assertEqual(image['article_id'],old['article_id'])
                        self.assertEqual(image['reference_images_sent'],1);self.assertEqual(image['model'],cf.REFERENCE_MODEL)
                self.assertFalse(pub.backfill_issue_art(target,s['date'],later,repair_legacy_images=True));self.assertEqual(calls.call_count,11)
            self.assertTrue(all(p.read_bytes()==content for p,content in texts.items()))

    def test_dhash_does_not_reject_distinct_verified_flat_color_works(self):
        with tempfile.TemporaryDirectory() as temp:
            state={};registry=lib.empty()
            for i,rgb in enumerate(((200,30,20),(20,50,200))):
                row={'genre_id':'constructivism','museum':'Synthetic museum','museum_id':'flat:'+str(i),'artist':'Fixture artist','title':'Distinct verified composition '+str(i),'year':'1920','source_url':'https://www.artic.edu/artworks/'+str(i),'license':'CC0','license_url':'https://www.artic.edu/open-access/open-access-images','verified':True,'genre_evidence':'Constructivism'}
                raw=io.BytesIO();Image.new('RGB',(80,80),rgb).save(raw,format='PNG')
                self.assertIsNotNone(lib.ingest(temp,registry,row,raw.getvalue(),state,lambda:None))
            self.assertEqual(len(registry['artworks']),2)

    def test_smk_requires_explicit_open_rights_and_matching_metadata(self):
        museum=lib.Museum()
        record={'object_number':'fixture-1','public_domain':True,'rights':'https://creativecommons.org/publicdomain/mark/1.0/',
                'titles':[{'title':'Constructivist study'}],'techniques':['Constructivism, painting'],
                'production':[{'creator':'Fixture painter'}],'production_date':[{'period':'1920'}],
                'image_thumbnail':'https://iip-thumb.smk.dk/fixture.jpg'}
        def get(url,*args,**kwargs):
            if url.startswith('https://api.smk.dk/'):return json.dumps({'items':[dict(record,object_number='private',public_domain=False),record]}).encode()
            raise ValueError('SYNTHETIC_SOURCE_UNAVAILABLE')
        with patch.object(museum,'get',side_effect=get):
            works=list(museum.candidates('Конструктивизм'))
        self.assertEqual(len(works),1);self.assertEqual(works[0]['license'],'Public Domain Mark')
        with tempfile.TemporaryDirectory() as temp:
            state={};registry=lib.empty();key=lib.ingest(temp,registry,works[0],picture(93),state,lambda:None)
            self.assertTrue(lib.file_valid(temp,registry['artworks'][key]));self.assertFalse(lib.file_valid(temp,dict(registry['artworks'][key],public_domain=False)))
            with self.assertRaisesRegex(ValueError,'RIGHTS'):lib.ingest(temp,registry,dict(works[0],public_domain=False),picture(94),state,lambda:None)
        record['rights']='https://creativecommons.org/share-your-work/public-domain/cc0/';record['techniques']=[{'technique':'Constructivism, olie på lærred'}];record['object_names']=[{'name':'maleri'}]
        museum=lib.Museum()
        with patch.object(museum,'get',side_effect=get):self.assertEqual(list(museum.candidates('Конструктивизм'))[0]['license'],'CC0')

    def test_real_multipart_sends_one_selected_binary_image_part(self):
        images=[picture(0)]
        raw,content=cf.multipart_payload({'prompt':'Different subject','width':1024,'height':768},images)
        message=BytesParser(policy=default).parsebytes(('Content-Type: '+content+'\r\n\r\n').encode()+raw)
        parts=list(message.iter_parts());files=[p for p in parts if p.get_filename()]
        self.assertEqual([p.get_param('name',header='content-disposition') for p in files],['input_image_0'])
        self.assertEqual([p.get_payload(decode=True) for p in files],images)
        self.assertEqual(files[0].get_content_type(),'image/png');self.assertTrue(files[0].get_filename().endswith('.png'))
    def test_reference_inference_keeps_shared_free_ledger_and_uses_klein(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);items=self.items(1);sets=lib.prepare_sets(temp,state,items,discover=False);lib.attach(temp,state,items,sets)
            item=items[0];item.update(date=state['date'],genre='Импрессионизм');item['descriptor']['visual_subject_en']='Children play with blocks.'
            ledger={'day':'2026-11-22','requests':47,'models':{}};budget=runtime.RequestBudget(ledger,seconds=1000,gap=0)
            env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'zzz387/387-news','GITHUB_REF_NAME':'main','CLOUDFLARE_ACCOUNT_ID':'a'*32,'CLOUDFLARE_API_TOKEN':'SYNTHETIC'}
            with patch.dict(os.environ,env),patch.object(art.p,'ROOT',Path(temp)),patch.object(cf,'free_usage',return_value=200),patch.object(cf,'api',return_value={'result':{'image':base64.b64encode(picture(99)).decode()}}) as api,patch.object(cf,'_LAST',0):
                cf.generate(item,budget,dict(art.CONFIG,request_gap_seconds=0))
                args,kwargs=api.call_args;self.assertTrue(args[0].endswith(cf.REFERENCE_MODEL));self.assertNotIn('steps',args[1]);self.assertEqual(len(kwargs['images']),1)
                self.assertTrue(kwargs['images'][0].startswith(b'\x89PNG'));self.assertEqual(item['reference_transport']['library_sha256'],item['reference_images'][0]['sha256'])
                self.assertEqual(item['reference_transport']['wire_sha256'],lib.digest(kwargs['images'][0]))
                with Image.open(io.BytesIO(kwargs['images'][0])) as wire,Image.open(Path(temp)/item['reference_images'][0]['path']) as canonical:
                    self.assertEqual(wire.convert('RGB').tobytes(),canonical.convert('RGB').tobytes())
                self.assertEqual(ledger['requests'],47);self.assertEqual(ledger['cloudflare_ai']['requests'],1)
                self.assertGreaterEqual(ledger['cloudflare_ai']['reserved_neurons'],2*(5.37+26.05*4))
                self.assertLessEqual(ledger['cloudflare_ai']['reserved_neurons'],art.CONFIG['reserve_neurons_per_request'])
                before=ledger['cloudflare_ai']['reserved_neurons'];item['ratio']='3:2'
                cf.generate(item,budget,dict(art.CONFIG,request_gap_seconds=0));self.assertEqual(api.call_args.args[1]['width'],768);self.assertEqual(api.call_args.args[1]['height'],512)
                self.assertGreaterEqual(ledger['cloudflare_ai']['reserved_neurons']-before,2*(5.37+26.05*2))
                self.assertLessEqual(ledger['cloudflare_ai']['reserved_neurons']-before,art.CONFIG['reserve_neurons_per_request'])
                item['reference_images']=item['reference_images']*3
                with self.assertRaisesRegex(RuntimeError,'ONE_REFERENCE'):cf.generate(item,budget,art.CONFIG)
                self.assertEqual(api.call_count,2)
    def test_partial_illustration_resume_reuses_three_objects_and_one_quartet(self):
        from scripts.test_policy44 import main_row
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);state['art44']={'objects':{},'history':[]}
            items=art.article_plans(state,[main_row(i) for i in range(5)])
            for item in items:item['genre']='Импрессионизм'
            sets=lib.prepare_sets(temp,state,items,discover=False);lib.attach(temp,state,items,sets)
            budget=type('Budget',(),{'ledger':{},'remaining_seconds':lambda self:1000})()
            with patch.object(art.p,'ROOT',Path(temp)),patch.object(art,'provider_status',return_value='READY'),patch.object(runtime,'ACTIVE_BUDGET',budget):
                with patch.object(art,'generate',side_effect=[picture(i+90) for i in range(3)]+[runtime.GenerationPaused('fixture pause')]) as generate:
                    self.assertEqual(art.prepare_items(state,items)['ready'],3)
                restored=json.loads(json.dumps(state));before=copy.deepcopy(restored['art44']['objects'])
                with patch.object(lib.Museum,'get',side_effect=AssertionError('No new quartet')):
                    again=lib.prepare_sets(temp,restored,items);self.assertEqual(sets,again)
                with patch.object(art,'generate',side_effect=[picture(94),picture(95)]) as generate:
                    self.assertTrue(art.prepare_items(restored,items)['complete']);self.assertEqual(generate.call_count,2)
                    self.assertTrue(all(obj==restored['art44']['objects'][key] for key,obj in before.items()))
                    self.assertEqual(len({o['sha256'] for o in restored['art44']['objects'].values()}),5)
                    self.assertEqual(len({o['reference_set_id'] for o in restored['art44']['objects'].values()}),1)

    def test_https_gallery_verifies_registry_and_binary_hashes(self):
        from scripts import site_checks
        from scripts.test_daily43 import web
        for n in (1,4):
          with self.subTest(references=n),tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,n);lib.prepare_sets(temp,state,self.items(5),discover=False)
            root=Path(temp);(root/'assets/art.css').write_bytes((art.p.ROOT/'assets/art.css').read_bytes())
            class Response(io.BytesIO):status=200
            def fetch_image(request,**kwargs):return Response((root/request.full_url.split('https://387.su/')[1]).read_bytes())
            with patch.object(site_checks,'fetch',side_effect=web(root)),patch.object(site_checks,'urlopen',side_effect=fetch_image):
                self.assertEqual(site_checks.check_art_library(root)['images_checked'],n)
                with patch.object(site_checks,'urlopen',return_value=Response(b'corrupted image')):
                    with self.assertRaisesRegex(RuntimeError,'PUBLIC_ART_IMAGE_CHANGED'):site_checks.check_art_library(root)

    def test_forbidden_image_host_opens_circuit_and_preserves_museum_fallback(self):
        from urllib.error import HTTPError
        museum=lib.Museum()
        with patch.object(lib,'urlopen',side_effect=HTTPError('https://www.artic.edu/image',403,'Forbidden',{},None)) as request:
            with self.assertRaises(HTTPError):museum.get('https://www.artic.edu/image',robots=False)
            with self.assertRaisesRegex(ValueError,'ART_SOURCE_UNAVAILABLE'):museum.get('https://www.artic.edu/other-image',robots=False)
            self.assertEqual(request.call_count,1)
        data={'data':[{'id':i,'title':'Fixture painting '+str(i),'type':'Painting','description':'An Impressionist painting.','share_license_status':'CC0','creation_date':'1890','creators':[{'description':'Fixture artist'}],'images':{'web':{'url':'https://openaccess-cdn.clevelandart.org/fixture'+str(i)+'.jpg'}},'url':'https://www.clevelandart.org/art/fixture'+str(i)} for i in range(4)]}
        with patch.object(museum,'get',return_value=json.dumps(data).encode()) as fetch:
            works=list(museum.candidates('Импрессионизм'))
            self.assertEqual(len(works),4);self.assertTrue(fetch.call_args_list[0].args[0].startswith('https://openaccess-api.clevelandart.org/'))
            self.assertTrue(all(w['museum']=='Cleveland Museum of Art' for w in works))
        self.assertIn('openaccess-cdn.clevelandart.org',lib.HOSTS)

    def test_met_fallback_only_accepts_explicit_public_domain_monet_paintings(self):
        museum=lib.Museum();museum.blocked_hosts.add('www.artic.edu')
        def get(url):
            if 'clevelandart.org' in url:return json.dumps({'data':[]}).encode()
            if '/search?' in url:
                self.assertIn('/v1.1/search?',url);self.assertNotIn('isPublicDomain=',url)
                return json.dumps({'objectIDs':[1,2,3]}).encode()
            identity=int(url.rsplit('/',1)[1])
            return json.dumps({'isPublicDomain':identity!=3,'artistDisplayName':'Claude Monet','classification':'Paintings','title':'Fixture Monet '+str(identity),'objectDate':'1890','objectURL':'https://www.metmuseum.org/art/collection/search/'+str(identity),'primaryImageSmall':'https://images.metmuseum.org/fixture.jpg','medium':'Oil on canvas'}).encode()
        with patch.object(museum,'get',side_effect=get):
            works=list(museum.candidates('Импрессионизм'))
            self.assertEqual(len(works),2);self.assertTrue(all(w['museum']=='The Metropolitan Museum of Art' and w['license']=='CC0' for w in works))

    def test_shared_encrypted_inventory_keeps_unpublished_cross_issue_reservations(self):
        with tempfile.TemporaryDirectory() as first,tempfile.TemporaryDirectory() as second:
            a=self.stock(first,8);sets=lib.prepare_sets(first,a,self.items(5),discover=False)
            shared=lib.checkpoint(a,first)
            b={'date':'2026-11-24'};lib.merge_checkpoint(b,shared)
            with patch.object(lib.Museum,'get',side_effect=AssertionError('Do not redownload shared media')):
                second_sets=lib.prepare_sets(second,b,self.items(5),discover=False)
            self.assertTrue(set(sets['Импрессионизм']['artwork_ids']).isdisjoint(second_sets['Импрессионизм']['artwork_ids']))
            self.assertEqual(len(b['art_library44']['registry']['sets']),2)
            bad=copy.deepcopy(shared);next(iter(bad['registry']['sets'].values()))['status']='tampered'
            with self.assertRaisesRegex(ValueError,'ART_REGISTRY_CONFLICT'):lib.merge_checkpoint(b,bad)

    def test_published_missing_image_resumes_same_quartet_from_next_issue_state(self):
        from scripts.test_policy44 import issue,synthetic_art
        from scripts.test_daily43 import root as site_root
        from scripts import publication43 as pub
        with tempfile.TemporaryDirectory() as temp:
            target=site_root(temp);s=issue();s['date']='2026-11-23';s['brief_policy_revision']=2
            s['art_library44']=self.stock(target,4)['art_library44']
            styles={key:['Импрессионизм'] for key in art.STYLES}
            with patch.object(art,'STYLES',styles),patch.object(art,'CONFIG',dict(art.CONFIG,references_enabled=False)):
                synthetic_art(s);sets=lib.prepare_sets(target,s,self.items(8),discover=False)
                reference=sets['Импрессионизм']
                for obj in s['art44']['objects'].values():obj.update(reference_status='FOUR_REFERENCES_READY',reference_set_id=reference['id'],reference_artwork_ids=reference['artwork_ids'],reference_sha256=reference['sha256'])
                pub.build(s,target)
            metadata=pub.validate(target,s['date']);missing=metadata['illustrations'][-1];(target/missing['path']).unlink()
            later={'date':'2026-11-24'};lib.merge_checkpoint(later,lib.checkpoint(s,target))
            budget=type('Budget',(),{'ledger':{},'remaining_seconds':lambda self:1000})()
            with patch.object(art.p,'ROOT',target),patch.object(art,'provider_status',return_value='READY'),patch.object(runtime,'ACTIVE_BUDGET',budget),patch.object(lib.Museum,'get',side_effect=AssertionError('Do not search another quartet')),patch.object(art,'generate',return_value=picture(888)) as generate:
                self.assertTrue(pub.backfill_issue_art(target,s['date'],later))
                generate.assert_called_once();item=generate.call_args.args[0]
                self.assertEqual(item['reference_set_id'],'2026-11-23/impressionism');self.assertEqual(len(item['reference_images']),1)
                self.assertEqual(pub.validate(target,s['date'])['art44']['ready'],8)

    def test_pages_keep_original_proportions_sources_and_issue_grouping(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,8);folder=Path(temp)/'issues/2026-11-23';folder.mkdir(parents=True);(folder/'index.html').write_text('Synthetic published fixture')
            lib.prepare_sets(temp,state,self.items(5),discover=False,number=29)
            reg=state['art_library44']['registry'];page=(Path(temp)/'art/impressionism/index.html').read_text()
            self.assertIn('Выпуск №29',page);self.assertIn('/issues/2026-11-23/',page);self.assertIn('Вся коллекция',page)
            for work in reg['artworks'].values():
                self.assertIn(work['path'],page);self.assertIn(work['source_url'],page);self.assertEqual((work['width'],work['height']),(80,60))
            self.assertIn('ещё не назначено',page)

    def test_momus_linked_rights_are_bound_to_actual_item_and_attributed(self):
        source='https://www.searchculture.gr/aggregator/edm/momus/000179-1260'
        payload={'@graph':[{'@id':source,'@type':'edm:ProvidedCHO','title':[{'@language':'en','@value':'Linearism'}],
            'creator':[{'@language':'en','@value':'Aleksandr Rodchenko'}],'date':'1920','dc:type':[{'@language':'en','@value':'Painting'}],
            'dc:subject':[{'@language':'en','@value':'Constructivism'}]},
            {'@type':'ore:Aggregation','aggregatedCHO':source,'rights':'http://creativecommons.org/licenses/by-sa/4.0/',
             'object':'https://www.searchculture.gr/aggregator/thumbnails/edm-record/momus/000179-1260'}]}
        work=lib.searchculture_work(payload,source,'Конструктивизм');self.assertTrue(lib.rights_valid(work))
        dc='http://purl.org/dc/elements/1.1/';edm='http://www.europeana.eu/schemas/edm/'
        expanded={'@graph':[{'@id':source,'@type':[edm+'ProvidedCHO'],dc+'title':[{'@language':'en','@value':'Linearism'}],
            dc+'creator':[{'@language':'en','@value':'Aleksandr Rodchenko'}],dc+'date':[{'@value':'1920'}],
            dc+'type':[{'@language':'en','@value':'Painting'}],dc+'subject':[{'@language':'en','@value':'Constructivism'}]},
            {'@type':['http://www.openarchives.org/ore/terms/Aggregation'],edm+'aggregatedCHO':[{'@id':source}],
             edm+'rights':[{'@id':lib.CC_BY_SA}],edm+'object':[{'@id':payload['@graph'][1]['object']}]}]}
        self.assertEqual(lib.searchculture_work(expanded,source,'Конструктивизм'),work)

        self.assertIn('Rodchenko',work['attribution']);self.assertEqual(work['license_scope'],'digital_file_and_thumbnail')
        for invalid in ('https://rightsstatements.org/vocab/InC/1.0/','https://creativecommons.org/licenses/by-nc/4.0/'):
            with self.subTest(rights=invalid):
                bad=copy.deepcopy(payload);bad['@graph'][1]['rights']=invalid;self.assertIsNone(lib.searchculture_work(bad,source,'Конструктивизм'))
        bad=copy.deepcopy(payload);bad['@graph'][1]['aggregatedCHO']='https://example.org/another-item'
        self.assertIsNone(lib.searchculture_work(bad,source,'Конструктивизм'))
        with tempfile.TemporaryDirectory() as temp:
            state={'date':'2026-11-23'};reg=lib.load(temp,state);key=lib.ingest(temp,reg,work,picture(15),state,lambda:None)
            self.assertTrue(lib.file_valid(temp,reg['artworks'][key]));lib.render(temp,reg)
            page=(Path(temp)/'art/constructivism/index.html').read_text()
            for credit in ('Rodchenko','Linearism','CC BY-SA 4.0','WebP'):self.assertIn(credit,page)
        caption=art.art_caption({'genre':'Конструктивизм','artwork_license':lib.CC_BY_SA,'reference_attribution':work['attribution'],'reference_source_url':source})
        self.assertIn('rel="license"',caption);self.assertIn('ИИ-композиция',caption)
        with self.assertRaises(ValueError):art.art_caption({'genre':'Конструктивизм','artwork_license':lib.CC_BY_SA})

    def test_paris_iiif_canvas_license_and_narrow_curatorial_seed(self):
        payload={'label':'Soleil','metadata':[{'label':'Auteur','value':['Mucha, Alphonse']},{'label':"Type d'objet",'value':'Peinture'},
            {'label':'Date de production','value':'<span>1900</span>-1901'},{'label':'Catalogue des œuvres de Paris Musées','value':'https://www.parismuseescollections.paris.fr/fr/oeuvre/soleil'}],
            'thumbnail':{'@id':'https://apicollections.parismusees.paris.fr/thumbnail.jpg'},'sequences':[{'canvases':[{'metadata':[
                {'label':'Droits','value':'CC0 Paris Musées / Carnavalet'},{'label':'Copyright','value':'https://creativecommons.org/publicdomain/zero/1.0/'}]}]}]}
        work=lib.paris_work(payload,320028394,'Ар-нуво');self.assertTrue(lib.rights_valid(work));self.assertEqual(work['artist'],'Mucha, Alphonse')
        self.assertIsNone(lib.paris_work(payload,123,'Ар-нуво'));self.assertIsNone(lib.paris_work(payload,320028394,'Кубизм'))
        bad=copy.deepcopy(payload);bad['sequences'][0]['canvases'][0]['metadata'][1]['value']='all rights reserved'
        self.assertIsNone(lib.paris_work(bad,320028394,'Ар-нуво'))
        met={'objectID':490060,'isPublicDomain':True,'artistDisplayName':'Juan Gris','classification':'Paintings','title':'Juan Legua','objectDate':'1911',
             'objectURL':'https://www.metmuseum.org/art/collection/search/490060','primaryImageSmall':'https://images.metmuseum.org/fixture.jpg','medium':'Oil on canvas'}
        self.assertEqual(lib.met_seed_work(met,490060,'Кубизм')['genre_id'],'cubism')
        self.assertIsNone(lib.met_seed_work(dict(met,isPublicDomain=False),490060,'Кубизм'))
        self.assertIsNone(lib.met_seed_work(dict(met,artistDisplayName='Another artist'),490060,'Кубизм'))
        self.assertIsNone(lib.met_seed_work(met,490060,'Коллаж'))


    def test_color_retry_preserves_first_pass_free_budget_for_unfinished_repair(self):
        from types import SimpleNamespace
        state={'art44':{'objects':{},'required_repair_keys':[str(i) for i in range(11)]}}
        budget=SimpleNamespace(ledger={'cloudflare_ai':{'reserved_neurons':4096,'observed_account_neurons':2244}})
        with patch.object(art,'object_valid',side_effect=lambda obj:bool(obj.get('ready'))):
            self.assertTrue(art.color_retry_available(state,[{'key':'0'}],budget))
            budget.ledger['cloudflare_ai']['reserved_neurons']=4608
            self.assertFalse(art.color_retry_available(state,[{'key':'0'}],budget))
            state['art44']['objects']={str(i):{'ready':True} for i in range(10)}
            self.assertTrue(art.color_retry_available(state,[{'key':'10'}],budget))
            budget.ledger['cloudflare_ai']['observed_account_neurons']=None
            self.assertFalse(art.color_retry_available(state,[{'key':'10'}],budget))

    def test_official_linked_data_negotiates_documented_json_representation(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        url='https://www.searchculture.gr/aggregator/edm/momus/000179-1260/json'
        captured=[]
        def reply(request,**kwargs):
            captured.append(request.get_header('Accept'))
            return nullcontext(SimpleNamespace(url=url,read=lambda size:b'{}'))
        with patch.object(lib,'urlopen',side_effect=reply):
            self.assertEqual(lib.Museum().get(url,robots=False,accept='application/ld+json, application/json;q=0.9'),b'{}')
        self.assertEqual(captured,['application/ld+json, application/json;q=0.9'])

    def test_provider_rejection_preserves_filter_and_continues_other_article_keys(self):
        from scripts.test_policy44 import main_row
        self.assertEqual(cf.output_rejection_code([{'code':3030,'message':'Your output has been flagged'}]),'CF_OUTPUT_REJECTED')
        self.assertIsNone(cf.output_rejection_code([{'code':3030,'message':'Invalid request dimensions'}]))
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);state['art44']={'objects':{},'history':[]}
            items=art.article_plans(state,[main_row(i) for i in range(3)])
            for item in items:item['genre']='Импрессионизм'
            sets=lib.prepare_sets(temp,state,items,discover=False);lib.attach(temp,state,items,sets)
            budget=type('Budget',(),{'ledger':{},'remaining_seconds':lambda self:1000})()
            with patch.object(art.p,'ROOT',Path(temp)),patch.object(art,'provider_status',return_value='READY'),patch.object(runtime,'ACTIVE_BUDGET',budget):
                with patch.object(art,'generate',side_effect=[RuntimeError('CF_OUTPUT_REJECTED'),picture(96),picture(97)]) as generate:
                    report=art.prepare_items(state,items);self.assertEqual(report['ready'],2);self.assertEqual(report['provider_status'],'READY');self.assertEqual(generate.call_count,3)
                before=copy.deepcopy(state['art44']['objects'])
                with patch.object(art,'generate',side_effect=AssertionError('Do not retry rejected key or successful images')):
                    self.assertEqual(art.prepare_items(state,items)['ready'],2)
                self.assertEqual(state['art44']['objects'],before);self.assertEqual(state['art44']['rejected_keys'],{items[0]['key']:'CF_OUTPUT_REJECTED'})

    def test_museum_canonical_negotiation_and_documented_rdf_fallback(self):
        source='https://www.searchculture.gr/aggregator/edm/momus/000179-1260'
        rdf=('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:edm="http://www.europeana.eu/schemas/edm/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:ore="http://www.openarchives.org/ore/terms/">\n<edm:ProvidedCHO rdf:about="SOURCE"><dc:title xml:lang="en">Linearism</dc:title><dc:creator xml:lang="en">Aleksandr Rodchenko</dc:creator><dc:date>1920</dc:date><dc:type xml:lang="en">Painting</dc:type><dc:subject xml:lang="en">Constructivism</dc:subject></edm:ProvidedCHO>\n<ore:Aggregation rdf:about="SOURCE/aggregation"><edm:aggregatedCHO rdf:resource="SOURCE"/><edm:rights rdf:resource="https://creativecommons.org/licenses/by-sa/4.0/"/><edm:object rdf:resource="https://www.searchculture.gr/aggregator/thumbnails/edm-record/momus/000179-1260"/></ore:Aggregation></rdf:RDF>').replace('SOURCE',source).encode()
        work=lib.searchculture_xml(rdf,source,'Конструктивизм');self.assertTrue(lib.rights_valid(work));self.assertEqual(work['year'],'1920')
        bad=rdf.replace(b'by-sa/4.0',b'by-nc/4.0');self.assertIsNone(lib.searchculture_xml(bad,source,'Конструктивизм'))
        client=lib.Museum()
        with patch.object(client,'get',side_effect=[b'{"about":"public-record","proxies":[]}',rdf]) as fetch:
            self.assertEqual(client.linked_work(source,'Конструктивизм'),work)
            self.assertEqual(fetch.call_args_list[0].args,(source,));self.assertEqual(fetch.call_args_list[0].kwargs['accept'],'application/ld+json')
            self.assertEqual(fetch.call_args_list[1].args,(source+'/xml',));self.assertEqual(fetch.call_args_list[1].kwargs['accept'],'application/rdf+xml')
        from urllib.error import HTTPError
        with patch.object(client,'get',side_effect=HTTPError(source,403,'Forbidden',{},None)) as fetch:
            with self.assertRaises(HTTPError):client.linked_work(source,'Конструктивизм')
            self.assertEqual(fetch.call_count,1)

if __name__=='__main__':unittest.main()
