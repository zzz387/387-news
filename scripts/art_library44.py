"""Append-only public museum library; one immutable quartet per issue and genre."""
import base64,hashlib,io,json,re,time,unicodedata
from datetime import datetime,timezone
from html import escape
from pathlib import Path
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen
from urllib.robotparser import RobotFileParser
from urllib.error import HTTPError
from PIL import Image

AGENT='387News-ArtLibrary/1.0 (+https://387.su)'
GENRES={
 'Импрессионизм':('impressionism','Impressionism'), 'Акварель':('watercolor','Watercolor'),
 'Символизм':('symbolism','Symbolism'), 'Футуризм':('futurism','Futurism'),
 'Метафизическая живопись':('metaphysical','Metaphysical'), 'Сюрреализм':('surrealism','Surrealism'),
 'Конструктивизм':('constructivism','Constructivism'), 'Ар-нуво':('art-nouveau','Art Nouveau'),
 'Пастель':('pastel','Pastel'), 'Японская гравюра':('japanese-print','Japanese woodblock'),
 'Минималистичная живопись':('minimalism','Minimalism'), 'Графика тушью':('ink','Ink'),
 'Экспрессионизм':('expressionism','Expressionism'), 'Плакатная графика':('poster','Poster'),
 'Офорт':('etching','Etching'), 'Историческая живопись':('history-painting','History painting'),
 'Кубизм':('cubism','Cubism'), 'Ар-деко':('art-deco','Art Deco'),
 'Натурализм':('naturalism','Naturalism'), 'Линогравюра':('linocut','Linocut'),
 'Ботаническая живопись':('botanical','Botanical'), 'Романтизм':('romanticism','Romanticism'),
 'Темпера':('tempera','Tempera'), 'Абстракционизм':('abstract','Abstract'),
 'Геометрическая абстракция':('geometric-abstraction','Geometric abstraction'),
 'Супрематизм':('suprematism','Suprematism'), 'Коллаж':('collage','Collage'),
 'Индустриальная графика':('industrial','Industrial'), 'Масло':('oil','Oil on canvas')}
HOSTS={'api.artic.edu','www.artic.edu','openaccess-api.clevelandart.org','www.clevelandart.org','images.clevelandart.org','clevelandart.org'}

def stamp():return datetime.now(timezone.utc).isoformat()
def digest(data):return hashlib.sha256(data).hexdigest()
def normalized(s):return re.sub(r'[^\w]+','',unicodedata.normalize('NFKD',s).casefold())
def identity(work):
    author=re.sub(r'\([^)]*\)','',work['artist']);year=re.search(r'\d{4}',str(work.get('year','')))
    return normalized(author)+'|'+normalized(work['title'])+'|'+(year[0] if year else str(work.get('year','')))
def known(registry,work):return any(w['museum_id']==work['museum_id'] or identity(w)==identity(work) for w in registry['artworks'].values())

def genre_id(genre):
    if genre not in GENRES:raise ValueError('ART_GENRE_UNSUPPORTED')
    return GENRES[genre][0]
def issue_id(state):
    value=state.get('issue_id') or state.get('special_edition',{}).get('id') or state['date']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',value):raise ValueError('ART_ISSUE_ID_INVALID')
    return value

def empty():return {'version':1,'artworks':{},'sets':{},'studies':{}}
def load(root,state=None):
    root=Path(root);path=root/'art/registry.json';public=json.loads(path.read_text()) if path.is_file() else empty()
    saved=(state or {}).get('art_library44',{});registry=saved.get('registry',empty())
    # Public commits and private resume snapshots may arrive in either order.
    for section in ('artworks','sets','studies'):
        for key,row in registry.get(section,{}).items():
            if key in public[section] and public[section][key]!=row:raise ValueError('ART_REGISTRY_CONFLICT')
            public[section][key]=row
    if state is not None:state.setdefault('art_library44',{})['registry']=public
    return public

def file_valid(root,work):
    try:
        expected='assets/art/'+work['genre_id']+'/'+work['id']+'.webp'
        if work['path']!=expected or not re.fullmatch(r'[a-f0-9]{64}',work['id']):return False
        data=(Path(root)/expected).read_bytes()
        if digest(data)!=work['sha256'] or work['license']!='CC0' or work['verified'] is not True:return False
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        return True
    except (KeyError,OSError,ValueError):return False

def restore(root,state):
    registry=load(root,state)
    for work in registry['artworks'].values():
        if file_valid(root,work):continue
        encoded=state.get('art_library44',{}).get('objects',{}).get(work['id'])
        if not encoded:continue
        data=base64.b64decode(encoded,validate=True)
        if digest(data)!=work['sha256']:raise ValueError('ART_REFERENCE_HASH_INVALID')
        path=Path(root)/('assets/art/'+work['genre_id']+'/'+work['id']+'.webp');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        if not file_valid(root,work):raise ValueError('ART_REFERENCE_INVALID')
    return registry

class Museum:
    """A bounded official-API client. robots, bytes and deadline fail closed."""
    def __init__(self,seconds=75,requests=24):self.deadline=time.monotonic()+seconds;self.left=requests;self.robots={}
    def get(self,url,limit=5000000,robots=True):
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in HOSTS or parsed.username or parsed.password:raise ValueError('ART_SOURCE_HOST_INVALID')
        if robots:
            origin='https://'+parsed.netloc
            if origin not in self.robots:
                parser=RobotFileParser();parser.set_url(origin+'/robots.txt')
                try:parser.parse(self.get(origin+'/robots.txt',100000,False).decode().splitlines())
                except HTTPError as exc:
                    if exc.code!=404:raise
                    parser.parse([])
                self.robots[origin]=parser
            if not self.robots[origin].can_fetch(AGENT,url):raise ValueError('ART_ROBOTS_DISALLOWED')
        if self.left<=0 or time.monotonic()>=self.deadline:raise ValueError('ART_DISCOVERY_BUDGET')
        self.left-=1
        with urlopen(Request(url,headers={'User-Agent':AGENT}),timeout=min(12,max(1,self.deadline-time.monotonic()))) as response:
            if urlparse(response.url).hostname not in HOSTS:raise ValueError('ART_REDIRECT_HOST_INVALID')
            data=response.read(limit+1)
            if len(data)>limit:raise ValueError('ART_RESPONSE_TOO_LARGE')
            return data
    def candidates(self,genre,start_page=1):
        query=GENRES[genre][1]
        fields='id,title,artist_title,date_display,date_start,image_id,is_public_domain,style_titles,medium_display'
        url='https://api.artic.edu/api/v1/artworks/search?'+urlencode({'q':query,'limit':60,'fields':fields})
        try:
            for page in range(start_page,start_page+2):
                rows=json.loads(self.get(url+'&page='+str(page)))['data']
                for row in rows:
                    tokens=' '.join(row.get('style_titles') or [])+' '+row.get('medium_display','')
                    if row.get('is_public_domain') is not True or not row.get('image_id') or query.casefold() not in tokens.casefold():continue
                    if not row.get('artist_title') or not row.get('date_display') or not row.get('title'):continue
                    yield {'museum':'Art Institute of Chicago','museum_id':'aic:'+str(row['id']),'title':row['title'],'artist':row['artist_title'],'year':row['date_display'],
                        'source_url':'https://www.artic.edu/artworks/'+str(row['id']),'license':'CC0','license_url':'https://www.artic.edu/open-access/open-access-images',
                        'image_url':'https://www.artic.edu/iiif/2/'+row['image_id']+'/full/480,/0/default.jpg','search_page':page,'genre_evidence':tokens,'genre_id':genre_id(genre),'verified':True}
        except Exception as exc:print('[art-museum] '+json.dumps({'museum':'aic','code':safe_code(exc)}),flush=True)
        # Independent museum fallback. Only explicit CC0 records and genre metadata.
        try:
            url='https://openaccess-api.clevelandart.org/api/artworks/?'+urlencode({'search':query,'cc0':1,'has_image':1,'limit':60})
            for row in json.loads(self.get(url))['data']:
                tokens=' '.join(str(row.get(k) or '') for k in ('title','technique','description','culture','type','period'))
                image=(row.get('images') or {}).get('web',{}).get('url')
                if row.get('share_license_status')!='CC0' or not image or query.casefold() not in tokens.casefold():continue
                authors=row.get('creators') or [];artist='; '.join(a.get('description','') for a in authors)
                if not artist or not row.get('creation_date') or not row.get('title'):continue
                yield {'museum':'Cleveland Museum of Art','museum_id':'cma:'+str(row['id']),'title':row['title'],'artist':artist,'year':row['creation_date'],
                    'source_url':row['url'],'license':'CC0','license_url':'https://www.clevelandart.org/open-access','image_url':image,'genre_evidence':tokens[:1000],'genre_id':genre_id(genre),'verified':True}
        except Exception as exc:print('[art-museum] '+json.dumps({'museum':'cleveland','code':safe_code(exc)}),flush=True)

def safe_code(exc):
    value=str(exc)
    return value if re.fullmatch(r'[A-Z_0-9]+',value) else 'HTTP_'+str(exc.code) if isinstance(exc,HTTPError) else type(exc).__name__

def ingest(root,registry,work,raw,state,persist):
    for url in (work['source_url'],work['license_url']):
        if urlparse(url).scheme!='https' or urlparse(url).hostname not in HOSTS:raise ValueError('ART_METADATA_URL_INVALID')
    if work.get('genre_id') not in {g[0] for g in GENRES.values()}:raise ValueError('ART_GENRE_UNSUPPORTED')
    if work.get('license')!='CC0' or work.get('verified') is not True:raise ValueError('ART_RIGHTS_UNVERIFIED')
    if known(registry,work):return None
    original_hash=digest(raw)
    if any(w['original_sha256']==original_hash for w in registry['artworks'].values()):return None
    with Image.open(io.BytesIO(raw)) as image:
        if image.width*image.height>30000000:raise ValueError('ART_IMAGE_TOO_LARGE')
        image.load()
        image=image.convert('RGB');image.thumbnail((480,480))
        out=io.BytesIO();image.save(out,format='WEBP',quality=88);data=out.getvalue();width,height=image.size
    if width<32 or height<32:raise ValueError('ART_IMAGE_TOO_SMALL')
    checksum=digest(data)
    with Image.open(io.BytesIO(data)) as check:
        gray=check.convert('L').resize((9,8));pixels=list(gray.getdata())
        visual_hash=sum((pixels[y*9+x]>pixels[y*9+x+1])<<(y*8+x) for y in range(8) for x in range(8))
    if any(w.get('visual_hash') is not None and (int(w['visual_hash'])^visual_hash).bit_count()<=2 for w in registry['artworks'].values()):return None
    if any(w['sha256']==checksum for w in registry['artworks'].values()):return None
    key=digest(identity(work).encode());path='assets/art/'+work['genre_id']+'/'+key+'.webp'
    row=dict(work,id=key,path=path,sha256=checksum,original_sha256=original_hash,visual_hash=str(visual_hash),width=width,height=height,added_at=stamp())
    row.pop('image_url',None)
    registry['artworks'][key]=row
    state.setdefault('art_library44',{}).setdefault('objects',{})[key]=base64.b64encode(data).decode()
    persist()  # Retain successful downloads before moving to the next museum object.
    file=Path(root)/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
    return key

def assign(root,registry,issue,issue_date,genre,number=None,persist=lambda:None):
    gid=genre_id(genre);key=issue+'/'+gid
    if key in registry['sets']:
        row=registry['sets'][key]
        if len(row['artwork_ids'])!=4 or len(set(row['artwork_ids']))!=4 or not all(file_valid(root,registry['artworks'][i]) for i in row['artwork_ids']):raise ValueError('ART_SET_INTEGRITY')
        return row
    used={i for row in registry['sets'].values() for i in row['artwork_ids']}
    available=[w for w in registry['artworks'].values() if w['genre_id']==gid and w['id'] not in used and file_valid(root,w)]
    if len(available)<4:return None
    selected=available[:4]
    row={'id':key,'issue_id':issue,'issue_date':issue_date,'issue_number':number,'genre_id':gid,'genre':genre,'artwork_ids':[w['id'] for w in selected],
        'selected_at':stamp(),'verification_status':'VERIFIED','assignment_status':'ASSIGNED','status':'READY','sha256':[w['sha256'] for w in selected]}
    registry['sets'][key]=row;persist();return row

def prepare_sets(root,state,items,persist=lambda:None,discover=True,identity_override=None,number=None):
    registry=restore(root,state);issue=identity_override or issue_id(state);result={};client=Museum()
    genres=list(dict.fromkeys(item['genre'] for item in items))
    for genre in genres:
        try:
            row=assign(root,registry,issue,state['date'],genre,number,persist)
            if row is None and discover:
                start_page=max((w.get('search_page',1) for w in registry['artworks'].values() if w['genre_id']==genre_id(genre)),default=1)
                for work in client.candidates(genre,start_page=start_page):
                    if known(registry,work):continue
                    try:ingest(root,registry,work,client.get(work.pop('image_url')),state,persist)
                    except Exception as exc:
                        print('[art-reference] '+json.dumps({'genre':genre,'code':safe_code(exc)}),flush=True)
                    row=assign(root,registry,issue,state['date'],genre,number,persist)
                    if row:break
            if row:result[genre]=row
        except Exception as exc:print('[art-reference] '+json.dumps({'genre':genre,'code':safe_code(exc)}),flush=True)
    state['art_library44']['deficits']=[g for g in genres if g not in result]
    persist();render(root,registry)
    print('[art-reference-sets] '+json.dumps({'issue_id':issue,'genres':len(genres),'ready':len(result),'missing':len(genres)-len(result),'artworks':len(registry['artworks'])}),flush=True)
    return result

def attach(root,state,items,sets):
    registry=load(root,state)
    for item in items:
        row=sets.get(item['genre'])
        item['reference_status']='FOUR_REFERENCES_READY' if row else 'REFERENCE_SET_UNAVAILABLE'
        if not row:continue
        item['reference_set_id']=row['id'];item['reference_artwork_ids']=row['artwork_ids'];item['reference_sha256']=row['sha256']
        item['reference_images']=[{'path':registry['artworks'][i]['path'],'sha256':registry['artworks'][i]['sha256']} for i in row['artwork_ids']]
    return items

def render(root,registry):
    from scripts import news
    root=Path(root);target=root/'art';target.mkdir(exist_ok=True)
    (target/'registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n')
    current=max(registry['sets'].values(),key=lambda s:s['selected_at'],default={'issue_date':datetime.now().date().isoformat(),'issue_number':0})
    date=current['issue_date'];number=current.get('issue_number') or 0
    def page(title,canonical,body):
        header=news.page_header(title,title,canonical,datetime.fromisoformat(date),number)
        header=header.replace('<a href="/archive/">Архив</a></nav>','<a href="/archive/">Архив</a><a href="/art/">Искусство</a></nav>')
        header=re.sub(r'<span>[^<]* · №[^<]*</span>','<span>Музейная коллекция</span>',header,count=1)
        return header.replace('</head>','<link rel="stylesheet" href="/assets/art.css"></head>')+'<main class="wrap art-library"><h1>'+escape(title)+'</h1>'+body+'</main>'+news.page_footer()
    groups={}  # Only verified, nonempty genre collections.
    for label,(gid,_) in GENRES.items():
        if any(w['genre_id']==gid for w in registry['artworks'].values()):groups[gid]=label
    body='<p>Открытая коллекция музейных произведений. Референсы помогают изучать художественный язык; иллюстрации газеты создаются отдельно.</p><ul class="art-genres">'
    for gid,label in groups.items():
        count=sum(w['genre_id']==gid for w in registry['artworks'].values());body+='<li><a href="/art/'+gid+'/">'+escape(label)+'</a> · '+str(count)+'</li>'
        works=sorted((w for w in registry['artworks'].values() if w['genre_id']==gid),key=lambda w:w['added_at'],reverse=True)
        sets=sorted((s for s in registry['sets'].values() if s['genre_id']==gid),key=lambda s:s['selected_at'],reverse=True)
        used={i:s for s in sets for i in s['artwork_ids']}
        content='<a href="/art/">Все направления</a><h2>Наборы по выпускам</h2>'
        for s in sets:
            is_study=s['issue_id'].startswith('art-study-');url='/art/studies/' if is_study else '/issues/'+s['issue_id']+'/'
            label='Художественная проба · '+s['issue_date'] if is_study else 'Выпуск '+('№'+str(s['issue_number'])+' · ' if s.get('issue_number') else '')+s['issue_date']
            content+='<section class="art-set"><h3><a href="'+url+'">'+escape(label)+'</a></h3><ul>'+''.join('<li><a href="#'+i+'">'+escape(registry['artworks'][i]['title'])+'</a></li>' for i in s['artwork_ids'])+'</ul></section>'
        content+='<h2>Вся коллекция</h2><div class="art-gallery">'
        for w in works:
            assigned=used.get(w['id']);status=('Назначено: '+assigned['issue_id']) if assigned else 'В запасе · ещё не назначено выпуску'
            content+='<figure id="'+w['id']+'"><img loading="lazy" src="/'+w['path']+'" width="'+str(w['width'])+'" height="'+str(w['height'])+'" alt="'+escape(w['title'],quote=True)+'"><figcaption><strong>'+escape(w['title'])+'</strong> · '+escape(w['artist'])+' · '+escape(str(w['year']))+'<p>'+escape(w['museum'])+' · <a href="'+escape(w['source_url'],quote=True)+'">Музейный оригинал</a> · <a href="'+escape(w['license_url'],quote=True)+'">CC0</a></p><small>Добавлено '+escape(w['added_at'][:10])+' · '+escape(status)+'</small></figcaption></figure>'
        folder=target/gid;folder.mkdir(exist_ok=True);(folder/'index.html').write_text(page(groups[gid],'/art/'+gid+'/',content+'</div>'))
    body+='</ul>'
    if registry['studies']:body+='<p><a href="/art/studies/">Пробы генерации по четырём референсам</a></p>'
    (target/'index.html').write_text(page('Искусство','/art/',body))
    if registry['studies'] or any(s['issue_id'].startswith('art-study-') for s in registry['sets'].values()):
        body='<p>Технические художественные пробы на основе уже опубликованных статей. Это не новый выпуск газеты.</p><div class="art-gallery">'
        for row in registry['studies'].values():body+='<figure><img src="/'+row['path']+'" width="'+str(row['width'])+'" height="'+str(row['height'])+'" alt="'+escape(row['title'],quote=True)+'"><figcaption>'+escape(row['title'])+'<p>Четыре музейных референса · '+escape(row['reference_set_id'])+' · <a href="'+row['article_url']+'">Статья</a></p></figcaption></figure>'
        folder=target/'studies';folder.mkdir(exist_ok=True);(folder/'index.html').write_text(page('Художественная мастерская','/art/studies/',body+'</div>'))

def rollout(root,date,state,persist):
    """Two real reference-guided studies; existing newspaper/archive bytes stay intact."""
    from scripts import mosaic44 as a,news,publication43 as pub
    data,rows=a.published_records(root,date);study='art-study-'+date
    items=a.article_plans({'date':date},rows)
    # Use two different approved subjects with one shared impressionist quartet.
    chosen=[i for i in items if i['article_id'].endswith(('feature-06','feature-08'))] or items[-2:]
    for item in chosen:
        item['genre']='Импрессионизм'
        prior=next((r for r in data['art44']['bindings'] if r['article_slug']==item['article_id'].split('/')[-1]),None)
        brief=a.CONFIG.get('visual_brief_repairs',{}).get((prior or {}).get('text_hash'),{})
        if brief:item['descriptor']['visual_subject_en']=brief['scene_en']
        item['key']=digest((study+'|'+item['article_id']).encode())
    sets=prepare_sets(root,state,chosen,persist,identity_override=study)
    attach(root,state,chosen,sets);registry=load(root,state)
    for item in chosen:
        if item['key'] in registry['studies']:continue
        if not item.get('reference_images'):break
        raw=a.generate(item,news.runtime.ACTIVE_BUDGET);encoded,w,h=a.encode_image(raw)
        key=item['key'];path='assets/illustrations/'+study+'/'+key+'.webp'
        row={'key':key,'path':path,'width':w,'height':h,'sha256':digest(encoded),'title':item['descriptor']['title'],'article_url':'/issues/'+date+'/articles/'+item['article_id'].split('/')[-1]+'/',
            'reference_set_id':item['reference_set_id'],'reference_artwork_ids':item['reference_artwork_ids'],'reference_sha256':item['reference_sha256'],'model':a.CONFIG['reference_model'],'created_at':stamp()}
        if any(study['sha256']==row['sha256'] for study in registry['studies'].values()):raise ValueError('ART_STUDY_NOT_UNIQUE')
        registry['studies'][key]=row
        state['art_library44'].setdefault('study_objects',{})[key]=base64.b64encode(encoded).decode();persist()
    for key,row in registry['studies'].items():
        file=Path(root)/row['path']
        if not file.is_file():
            raw=base64.b64decode(state['art_library44']['study_objects'][key],validate=True)
            if digest(raw)!=row['sha256']:raise ValueError('ART_STUDY_HASH_INVALID')
            file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(raw)
    render(root,registry)
    from scripts import layout43
    (Path(root)/'index.html').write_text(layout43.homepage((Path(root)/'issues'/date/'index.html').read_text(),date))
    print('[art-library-rollout] '+json.dumps({'artworks':len(registry['artworks']),'sets':len(registry['sets']),'real_studies':len(registry['studies']),'references_per_request':4,'archives_unchanged':True}),flush=True)
    return True

def check_browser(root,output):
    """Reuse the existing browser and four production viewport widths."""
    from scripts import browser41
    from playwright.sync_api import sync_playwright
    from functools import partial
    from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
    from threading import Thread
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    registry=load(root);paths=['/art/']+['/art/'+g+'/' for g in sorted({w['genre_id'] for w in registry['artworks'].values()})]
    if registry['studies']:paths.append('/art/studies/')
    class Silent(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Silent,directory=str(root)));thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    count=0
    try:
        with sync_playwright() as p:
            browser=browser41.launch_browser(p)
            for width in (320,390,768,1440):
                page=browser.new_page(viewport={'width':width,'height':900})
                for path in paths:
                    response=page.goto('http://127.0.0.1:'+str(server.server_port)+path,wait_until='networkidle')
                    if response.status!=200:raise ValueError('ART_BROWSER_PAGE_MISSING')
                    page.locator('img').evaluate_all('(nodes)=>nodes.slice(0,8).forEach(n=>n.loading="eager")')
                    page.wait_for_function('Array.from(document.images).slice(0,8).every(i=>i.complete && i.naturalWidth>0)')
                    if page.evaluate('document.documentElement.scrollWidth>innerWidth+1'):raise ValueError('ART_BROWSER_OVERFLOW')
                    if page.locator('img').evaluate_all('(nodes)=>nodes.slice(0,8).some(i=>Math.abs(i.getBoundingClientRect().width/i.getBoundingClientRect().height-i.naturalWidth/i.naturalHeight)>.04)'):raise ValueError('ART_BROWSER_PROPORTIONS_CHANGED')
                    page.screenshot(path=str(output/(path.strip('/').replace('/','-')+'-'+str(width)+'.png')),full_page=False);count+=1
                page.close()
            browser.close()
    finally:server.shutdown();server.server_close();thread.join()
    result={'pages':count,'viewports':[320,390,768,1440],'overflow':False,'images_loaded':True};print('[art-library-browser] '+json.dumps(result),flush=True);return result
