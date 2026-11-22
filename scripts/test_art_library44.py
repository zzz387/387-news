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
                self.assertEqual(len(sets),1);self.assertEqual(download.call_count,4)

    def test_insufficient_stock_is_explicit_and_never_fabricates_a_set(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,3);items=self.items(5)
            sets=lib.prepare_sets(temp,state,items,discover=False);lib.attach(temp,state,items,sets)
            self.assertEqual(sets,{});self.assertEqual(state['art_library44']['deficits'],['Импрессионизм'])
            self.assertTrue(all(i['reference_status']=='REFERENCE_SET_UNAVAILABLE' for i in items))
    def test_museum_metadata_and_access_checks_fail_closed(self):
        self.assertTrue(lib.genre_matches('Японская гравюра','Japan Color woodblock print'))
        self.assertFalse(lib.genre_matches('Японская гравюра','European oil painting'))
        museum=lib.Museum();data={'data':[{'id':1,'title':'Fixture painting','artist_title':'Fixture painter','date_display':'1890','image_id':'fixture','artwork_type_title':'Painting','style_titles':['Impressionism'],'is_public_domain':True}]}
        with patch.object(museum,'get',return_value=json.dumps(data).encode()):
            work=next(museum.candidates('Импрессионизм'));self.assertEqual(work['license'],'CC0');self.assertEqual(work['genre_id'],'impressionism')
        with self.assertRaisesRegex(ValueError,'HOST'):museum.get('https://attacker.invalid/image.webp')
    def test_real_multipart_has_four_separate_binary_image_parts(self):
        images=[picture(i) for i in range(4)]
        raw,content=cf.multipart_payload({'prompt':'Different subject','width':1024,'height':768},images)
        message=BytesParser(policy=default).parsebytes(('Content-Type: '+content+'\r\n\r\n').encode()+raw)
        parts=list(message.iter_parts());files=[p for p in parts if p.get_filename()]
        self.assertEqual([p.get_param('name',header='content-disposition') for p in files],['input_image_'+str(i) for i in range(4)])
        self.assertEqual([p.get_payload(decode=True) for p in files],images)
    def test_reference_inference_keeps_shared_free_ledger_and_uses_klein(self):
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);items=self.items(1);sets=lib.prepare_sets(temp,state,items,discover=False);lib.attach(temp,state,items,sets)
            item=items[0];item.update(date=state['date'],genre='Импрессионизм');item['descriptor']['visual_subject_en']='Children play with blocks.'
            ledger={'day':'2026-11-22','requests':47,'models':{}};budget=runtime.RequestBudget(ledger,seconds=1000,gap=0)
            env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'zzz387/387-news','GITHUB_REF_NAME':'main','CLOUDFLARE_ACCOUNT_ID':'a'*32,'CLOUDFLARE_API_TOKEN':'SYNTHETIC'}
            with patch.dict(os.environ,env),patch.object(art.p,'ROOT',Path(temp)),patch.object(cf,'free_usage',return_value=200),patch.object(cf,'api',return_value={'result':{'image':base64.b64encode(picture(99)).decode()}}) as api,patch.object(cf,'_LAST',0):
                cf.generate(item,budget,dict(art.CONFIG,request_gap_seconds=0))
                args,kwargs=api.call_args;self.assertTrue(args[0].endswith(cf.REFERENCE_MODEL));self.assertNotIn('steps',args[1]);self.assertEqual(len(kwargs['images']),4)
                self.assertEqual(ledger['requests'],47);self.assertEqual(ledger['cloudflare_ai']['requests'],1)
                self.assertEqual(ledger['cloudflare_ai']['reserved_neurons'],256)
                item['reference_images']=item['reference_images'][:3]
                with self.assertRaisesRegex(RuntimeError,'FOUR_REFERENCES'):cf.generate(item,budget,art.CONFIG)
                self.assertEqual(api.call_count,1)
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
        with tempfile.TemporaryDirectory() as temp:
            state=self.stock(temp,4);lib.prepare_sets(temp,state,self.items(5),discover=False)
            root=Path(temp);(root/'assets/art.css').write_bytes((art.p.ROOT/'assets/art.css').read_bytes())
            class Response(io.BytesIO):status=200
            def fetch_image(request,**kwargs):return Response((root/request.full_url.split('https://387.su/')[1]).read_bytes())
            with patch.object(site_checks,'fetch',side_effect=web(root)),patch.object(site_checks,'urlopen',side_effect=fetch_image):
                self.assertEqual(site_checks.check_art_library(root)['images_checked'],4)
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
                self.assertEqual(item['reference_set_id'],'2026-11-23/impressionism');self.assertEqual(len(item['reference_images']),4)
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

if __name__=='__main__':unittest.main()
