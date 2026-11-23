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
HOSTS={'api.artic.edu','www.artic.edu','openaccess-api.clevelandart.org','www.clevelandart.org','images.clevelandart.org','clevelandart.org','openaccess-cdn.clevelandart.org','collectionapi.metmuseum.org','images.metmuseum.org','www.metmuseum.org','api.smk.dk','iip.smk.dk','iip-thumb.smk.dk','www.smk.dk','open.smk.dk'}

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

def genre_matches(genre,tokens):
    text=''.join(c for c in unicodedata.normalize('NFKD',tokens) if not unicodedata.combining(c)).casefold().replace('-',' ')
    if genre=='Конструктивизм':return bool(re.search(r'\b(?:constructivis(?:m|t)|konstruktivis(?:m|t))',text))
    if genre=='Романтизм':return bool(re.search(r'\b(?:romantic(?:ism)?|romantik)\b',text))
    if genre=='Кубизм' and 'kubisme' in text:return True
    if genre=='Кубизм' and re.search(r'neo[ -]?plastic|vorticis',text):return False
    if genre=='Японская гравюра':return ('japan' in text or 'ukiyo' in text) and ('woodblock' in text or 'woodcut' in text)
    if genre=='Импрессионизм':return bool(re.search(r'\bimpressionis',text))
    if genre=='Акварель':return 'watercolor' in text or 'watercolour' in text
    if genre=='Масло':return bool(re.search(r'\boil\b',text))
    return GENRES[genre][1].casefold() in text

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
        if digest(data)!=work['sha256'] or work['license'] not in ('CC0','Public Domain Mark') or work['verified'] is not True:return False
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
    def __init__(self,seconds=75,requests=24):self.deadline=time.monotonic()+seconds;self.left=requests;self.robots={};self.blocked_hosts=set();self.known_ids=set()
    def get(self,url,limit=5000000,robots=True):
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in HOSTS or parsed.username or parsed.password:raise ValueError('ART_SOURCE_HOST_INVALID')
        if parsed.hostname in self.blocked_hosts:raise ValueError('ART_SOURCE_UNAVAILABLE')
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
        try:
            with urlopen(Request(url,headers={'User-Agent':AGENT}),timeout=min(12,max(1,self.deadline-time.monotonic()))) as response:
                if urlparse(response.url).scheme!='https' or urlparse(response.url).hostname not in HOSTS:raise ValueError('ART_REDIRECT_HOST_INVALID')
                data=response.read(limit+1)
                if len(data)>limit:raise ValueError('ART_RESPONSE_TOO_LARGE')
                return data
        except HTTPError as exc:
            if exc.code in (401,403,429,500,502,503):self.blocked_hosts.add(parsed.hostname)
            print('[art-museum-access] '+json.dumps({'host':parsed.hostname,'stage':'robots' if parsed.path=='/robots.txt' else 'fetch','http_status':exc.code}),flush=True)
            raise
    def candidates(self,genre,start_page=1):
        query=GENRES[genre][1]
        fields='id,title,artist_title,date_display,date_start,image_id,is_public_domain,style_titles,medium_display,artwork_type_title,place_of_origin'
        url='https://api.artic.edu/api/v1/artworks/search?'+urlencode({'q':query,'limit':60,'fields':fields})
        try:
            for page in range(start_page,start_page+2):
                if 'www.artic.edu' in self.blocked_hosts:break
                rows=json.loads(self.get(url+'&page='+str(page)))['data']
                for row in rows:
                    if 'www.artic.edu' in self.blocked_hosts:break
                    tokens=' '.join(str(x) for x in (row.get('style_titles') or []) if x)+' '+str(row.get('medium_display') or '')+' '+str(row.get('place_of_origin',''))
                    if not any(t in str(row.get('artwork_type_title','')).casefold() for t in ('painting','drawing','print')):continue
                    if row.get('is_public_domain') is not True or not row.get('image_id') or not genre_matches(genre,tokens):continue
                    if not row.get('artist_title') or not row.get('date_display') or not row.get('title'):continue
                    yield {'museum':'Art Institute of Chicago','museum_id':'aic:'+str(row['id']),'title':row['title'],'artist':row['artist_title'],'year':row['date_display'],
                        'source_url':'https://www.artic.edu/artworks/'+str(row['id']),'license':'CC0','license_url':'https://www.artic.edu/open-access/open-access-images',
                        'image_url':'https://www.artic.edu/iiif/2/'+row['image_id']+'/full/480,/0/default.jpg','search_page':page,'genre_evidence':tokens,'genre_id':genre_id(genre),'verified':True}
        except Exception as exc:print('[art-museum] '+json.dumps({'museum':'aic','code':safe_code(exc)}),flush=True)
        # Independent museum fallback. Only explicit CC0 records and genre metadata.
        try:
            query={'Конструктивизм':'Constructivist','Индустриальная графика':'Industrial'}.get(genre,query)
            url='https://openaccess-api.clevelandart.org/api/artworks/?'+urlencode({'search':query,'cc0':1,'has_image':1,'limit':60,**({'type':'Print'} if genre=='Индустриальная графика' else {})})
            for row in json.loads(self.get(url))['data']:
                tokens=' '.join(str(row.get(k) or '') for k in ('title','technique','description','culture','type','period'))
                image=(row.get('images') or {}).get('web',{}).get('url')
                if image and urlparse(image).hostname in self.blocked_hosts:break
                if row.get('type') not in ('Painting','Drawing','Print'):continue
                if row.get('share_license_status')!='CC0' or not image or not genre_matches(genre,tokens):continue
                authors=row.get('creators') or [];artist='; '.join(str(a.get('description') or '') for a in authors if a.get('description'))
                if not artist or not row.get('creation_date') or not row.get('title'):continue
                yield {'museum':'Cleveland Museum of Art','museum_id':'cma:'+str(row['id']),'title':row['title'],'artist':artist,'year':row['creation_date'],
                    'source_url':row['url'],'license':'CC0','license_url':'https://www.clevelandart.org/open-access','image_url':image,'genre_evidence':tokens[:1000],'genre_id':genre_id(genre),'verified':True}
        except Exception as exc:print('[art-museum] '+json.dumps({'museum':'cleveland','code':safe_code(exc)}),flush=True)
        # A third independent open collection, with a deliberately narrow curatorial
        # fallback: documented Monet paintings, not arbitrary search matches.
        if genre=='Импрессионизм':
            try:
                base='https://collectionapi.metmuseum.org/public/collection/v1/'
                search=base.replace('/v1/','/v1.1/')+'search?'+urlencode({'q':'Claude Monet','artistOrCulture':'true','hasImages':'true','medium':'Paintings','offset':0,'limit':60})
                ids=json.loads(self.get(search)).get('objectIDs') or []
                for identity in ids:
                    if 'met:'+str(identity) in self.known_ids:continue
                    if 'images.metmuseum.org' in self.blocked_hosts:break
                    row=json.loads(self.get(base+'objects/'+str(identity)))
                    if row.get('isPublicDomain') is not True or row.get('artistDisplayName')!='Claude Monet' or row.get('classification')!='Paintings':continue
                    image=row.get('primaryImageSmall')
                    if not image or not row.get('objectDate') or not row.get('title'):continue
                    yield {'museum':'The Metropolitan Museum of Art','museum_id':'met:'+str(identity),'title':row['title'],'artist':row['artistDisplayName'],'year':row['objectDate'],
                        'source_url':row['objectURL'],'license':'CC0','license_url':'https://www.metmuseum.org/policies/image-resources',
                        'image_url':image,'genre_evidence':'Curatorial selection: Claude Monet painting; '+row.get('medium',''),'genre_id':genre_id(genre),'verified':True}
            except Exception as exc:print('[art-museum] '+json.dumps({'museum':'met','code':safe_code(exc)}),flush=True)


        # Independent official open collection. Only explicit public-domain rights
        # and matching museum metadata are admitted; no API key or paid service.
        try:
            query={'Конструктивизм':'konstruktivisme','Кубизм':'kubisme','Романтизм':'romantik'}.get(genre,GENRES[genre][1])
            url='https://api.smk.dk/api/v1/art/search/?'+urlencode({'keys':query,'filters':'[public_domain:true],[has_image:true]','offset':0,'rows':40})
            payload=json.loads(self.get(url));items=payload.get('items')
            if not isinstance(items,list):raise ValueError('ART_SOURCE_SCHEMA_INVALID')
            print('[art-museum-source] '+json.dumps({'museum':'smk','technical_access':'verified','records':len(items)}),flush=True)
            for row in items:
                rights=row.get('rights_url','');license={'https://creativecommons.org/publicdomain/zero/1.0/':'CC0','https://creativecommons.org/publicdomain/mark/1.0/':'Public Domain Mark'}.get(rights)
                if row.get('public_domain') is not True or not license:continue
                evidence=' '.join(str(row.get(k) or '') for k in ('titles','techniques','styles','artwork_type','description','object_names'))
                if not genre_matches(genre,evidence):continue
                image=row.get('image_thumbnail')
                if not image or urlparse(image).hostname not in HOSTS:continue
                titles=row.get('titles') or [];production=row.get('production') or [];dates=row.get('production_dates') or []
                title=next((r.get('title') for r in titles if isinstance(r,dict) and r.get('title')),None)
                artist=next((r.get('creator') for r in production if isinstance(r,dict) and isinstance(r.get('creator'),str)),None)
                year=next((r.get('period') or r.get('start') for r in dates if isinstance(r,dict)),None)
                identity=row.get('object_number')
                if not all((identity,title,artist,year)):continue
                yield {'museum':'SMK — National Gallery of Denmark','museum_id':'smk:'+identity,'title':title,'artist':artist,'year':year,
                    'source_url':url,'license':license,'license_url':'https://www.smk.dk/en/article/smk-open/','rights_evidence':rights,'public_domain':True,'image_url':image,
                    'genre_evidence':evidence[:1000],'genre_id':genre_id(genre),'verified':True}
        except Exception as exc:print('[art-museum] '+json.dumps({'museum':'smk','code':safe_code(exc)}),flush=True)


def safe_code(exc):
    value=str(exc)
    return value if re.fullmatch(r'[A-Z_0-9]+',value) else 'HTTP_'+str(exc.code) if isinstance(exc,HTTPError) else type(exc).__name__

def ingest(root,registry,work,raw,state,persist):
    for url in (work['source_url'],work['license_url']):
        if urlparse(url).scheme!='https' or urlparse(url).hostname not in HOSTS:raise ValueError('ART_METADATA_URL_INVALID')
    if work.get('genre_id') not in {g[0] for g in GENRES.values()}:raise ValueError('ART_GENRE_UNSUPPORTED')
    if work.get('license') not in ('CC0','Public Domain Mark') or work.get('verified') is not True:raise ValueError('ART_RIGHTS_UNVERIFIED')
    if work.get('license')=='Public Domain Mark' and (work.get('public_domain') is not True or work.get('rights_evidence')!='https://creativecommons.org/publicdomain/mark/1.0/'):raise ValueError('ART_RIGHTS_UNVERIFIED')
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
    available=[w for w in registry['artworks'].values() if w['genre_id']==gid and w['id'] not in used and file_valid(root,w) and not (genre=='Кубизм' and re.search(r'neo[ -]?plastic|vorticis',w.get('genre_evidence',''),re.I))]
    if len(available)<4:return None
    from scripts import art_reference44 as color
    profiles={w['id']:color.work_profile(root,w,{}) for w in available}
    selected=[available[0]]
    while len(selected)<4:
        remaining=[w for w in available if w not in selected]
        chosen=min(remaining,key=lambda w:(-min(color.distance(profiles[w['id']],profiles[q['id']]) for q in selected),w['id']))
        selected.append(chosen)
    row={'id':key,'issue_id':issue,'issue_date':issue_date,'issue_number':number,'genre_id':gid,'genre':genre,'artwork_ids':[w['id'] for w in selected],
        'selected_at':stamp(),'verification_status':'VERIFIED','assignment_status':'ASSIGNED','status':'READY','sha256':[w['sha256'] for w in selected]}
    registry['sets'][key]=row;persist();return row

def prepare_sets(root,state,items,persist=lambda:None,discover=True,identity_override=None,number=None):
    registry=restore(root,state);issue=identity_override or issue_id(state);result={};client=Museum()
    client.known_ids={w['museum_id'] for w in registry['artworks'].values()}
    genres=list(dict.fromkeys(item['genre'] for item in items))
    attempts=state['art_library44'].setdefault('discovery_attempts',{})
    genres.sort(key=lambda g:attempts.get(issue+'/'+genre_id(g),''))
    for genre in genres:
        try:
            row=assign(root,registry,issue,state['date'],genre,number,persist)
            if row is None and discover:
                if client.left<=0 or time.monotonic()>=client.deadline:continue
                attempts[issue+'/'+genre_id(genre)]=stamp()
                start_page=max((w.get('search_page',1) for w in registry['artworks'].values() if w['genre_id']==genre_id(genre)),default=1)
                for work in client.candidates(genre,start_page=start_page):
                    if client.left<=0 or time.monotonic()>=client.deadline:break
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
    from scripts import art_reference44 as color
    registry=load(root,state);previous=[]
    for item in items:
        row=sets.get(item['genre'])
        item['reference_status']='REFERENCE_SET_UNAVAILABLE'
        if not row:continue
        work,choice=color.select(root,state,item,row,registry,previous)
        item.update({k:v for k,v in choice.items() if k!='sha256'})
        item.update(reference_status='ONE_REFERENCE_READY',reference_set_id=row['id'],reference_artwork_ids=row['artwork_ids'],reference_sha256=row['sha256'],reference_images_sent=1)
        item['reference_images']=[{'path':work['path'],'sha256':work['sha256']}]
        item.update({k:color.direction(item['genre'])[k] for k in ('art_movement','medium')})
        from scripts import cloudflare44
        item['prompt']=cloudflare44.prompt(item)
        previous.append(choice['palette'])
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
            heading='<a href="'+url+'">'+escape(label)+'</a>' if is_study or (root/url.strip('/')/'index.html').is_file() else escape(label)+' · готовится'
            content+='<section class="art-set"><h3>'+heading+'</h3><ul>'+''.join('<li><a href="#'+i+'">'+escape(registry['artworks'][i]['title'])+'</a></li>' for i in s['artwork_ids'])+'</ul></section>'
        content+='<h2>Вся коллекция</h2><div class="art-gallery">'
        for w in works:
            assigned=used.get(w['id']);status=('Назначено: '+assigned['issue_id']) if assigned else 'В запасе · ещё не назначено выпуску'
            content+='<figure id="'+w['id']+'"><img loading="lazy" src="/'+w['path']+'" width="'+str(w['width'])+'" height="'+str(w['height'])+'" alt="'+escape(w['title'],quote=True)+'"><figcaption><strong>'+escape(w['title'])+'</strong> · '+escape(w['artist'])+' · '+escape(str(w['year']))+'<p>'+escape(w['museum'])+' · <a href="'+escape(w['source_url'],quote=True)+'">Музейный оригинал</a> · <a href="'+escape(w['license_url'],quote=True)+'">'+escape(w['license'])+'</a></p><small>Добавлено '+escape(w['added_at'][:10])+' · '+escape(status)+'</small></figcaption></figure>'
        folder=target/gid;folder.mkdir(exist_ok=True);(folder/'index.html').write_text(page(groups[gid],'/art/'+gid+'/',content+'</div>'))
    body+='</ul>'
    if registry['studies']:body+='<p><a href="/art/studies/">Пробы генерации по музейным референсам</a></p>'
    (target/'index.html').write_text(page('Искусство','/art/',body))
    if registry['studies'] or any(s['issue_id'].startswith('art-study-') for s in registry['sets'].values()):
        body='<p>Технические художественные пробы на основе уже опубликованных статей. Это не новый выпуск газеты.</p><div class="art-gallery">'
        for row in registry['studies'].values():body+='<figure><img src="/'+row['path']+'" width="'+str(row['width'])+'" height="'+str(row['height'])+'" alt="'+escape(row['title'],quote=True)+'"><figcaption>'+escape(row['title'])+'<p>'+('Один выбранный музейный референс' if row.get('reference_images_sent')==1 else 'Четыре музейных референса')+' · '+escape(row['reference_set_id'])+' · <a href="'+row['article_url']+'">Статья</a></p></figcaption></figure>'
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
            'reference_images_sent':1,'selected_reference_id':item['selected_reference_id'],'reference_set_id':item['reference_set_id'],'reference_artwork_ids':item['reference_artwork_ids'],'reference_sha256':item['reference_sha256'],'model':a.CONFIG['reference_model'],'created_at':stamp()}
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
    print('[art-library-rollout] '+json.dumps({'artworks':len(registry['artworks']),'sets':len(registry['sets']),'real_studies':len(registry['studies']),'references_per_request':1 if registry['studies'] else 0,'archives_unchanged':True}),flush=True)
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


def merge_checkpoint(state,incoming):
    """Merge immutable reservations from the shared encrypted inventory."""
    if not incoming:return
    target=state.setdefault('art_library44',{})
    registry=target.setdefault('registry',empty())
    for section in ('artworks','sets','studies'):
        for key,row in incoming.get('registry',{}).get(section,{}).items():
            if key in registry[section] and registry[section][key]!=row:raise ValueError('ART_REGISTRY_CONFLICT')
            registry[section][key]=json.loads(json.dumps(row))
    for section in ('objects','study_objects','reference_choices','color_profiles'):
        for key,data in incoming.get(section,{}).items():
            previous=target.setdefault(section,{}).get(key)
            if previous is not None and previous!=data:raise ValueError('ART_CACHE_CONFLICT')
            target[section][key]=data


def checkpoint(state,root):
    """Share unpublished media; committed immutable files stay in Git, not duplicated."""
    import subprocess
    from functools import lru_cache
    # One tracked-file snapshot per stage, before the later Git commit step.
    if not hasattr(checkpoint,'tracked'):
        @lru_cache(maxsize=4)
        def tracked(path):
            try:return set(subprocess.check_output(['git','ls-files','assets/art','assets/illustrations'],cwd=path,stderr=subprocess.DEVNULL,text=True).splitlines())
            except (OSError,subprocess.CalledProcessError):return set()
        checkpoint.tracked=tracked
    value=state.get('art_library44',{})
    if not value:return {}
    saved={'registry':json.loads(json.dumps(value.get('registry',empty()))),'objects':{},'study_objects':{}}
    for section in ('reference_choices','color_profiles'):saved[section]=json.loads(json.dumps(value.get(section,{})))
    tracked=checkpoint.tracked(str(Path(root).resolve()))
    for key,data in value.get('objects',{}).items():
        work=saved['registry']['artworks'].get(key)
        if work and work['path'] in tracked and file_valid(root,work):continue
        saved['objects'][key]=data
    for key,data in value.get('study_objects',{}).items():
        work=saved['registry']['studies'].get(key)
        if work and work['path'] in tracked and (Path(root)/work['path']).is_file() and digest((Path(root)/work['path']).read_bytes())==work['sha256']:continue
        saved['study_objects'][key]=data
    return saved
