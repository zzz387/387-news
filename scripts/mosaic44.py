"""Public art plans, a permanent image cache and a nonblocking artistic front page."""
import base64,hashlib,json,re,os,io
from collections import Counter
from html import escape
from pathlib import Path
from scripts import policy41 as p,selection43

CONFIG=json.loads((p.ROOT/'config/mosaic44.json').read_text())
STYLES={
 'family':['Акварель','Импрессионизм','Пастель'],
 'health':['Символизм','Метафизическая живопись','Сюрреализм'],
 'yoga':['Японская гравюра','Минималистичная живопись','Графика тушью'],
 'sport':['Футуризм','Экспрессионизм','Плакатная графика'],
 'moscow':['Офорт','Историческая живопись','Ар-нуво'],
 'architecture':['Конструктивизм','Кубизм','Ар-деко'],
 'nature':['Ботаническая живопись','Линогравюра','Натурализм'],
 'history':['Романтизм','Графика тушью','Темпера'],
 'philosophy':['Символизм','Метафизическая живопись','Абстракционизм'],
 'economy':['Геометрическая абстракция','Супрематизм','Коллаж'],
 'technology':['Конструктивизм','Индустриальная графика','Кубизм'],
 'science':['Сюрреализм','Абстракционизм','Геометрическая абстракция'],
 'culture':['Ар-нуво','Коллаж','Масло']}
THEMES={
 'yoga':r'йог|подвижност|растяж|yoga|mobility',
 'sport':r'велосип|бег|кардио|спорт|плаван|cycling|athlet|sport',
 'family':r'реб[её]н|дет[иес]|семь|родител|супруж|parent|child|family',
 'moscow':r'москв|подмосков|усадьб|moscow',
 'architecture':r'архитект|интерьер|здани|architect|interior',
 'nature':r'птиц|природ|животн|растен|лес|болот|эколог|nature|bird|wildlife',
 'health':r'медицин|здоров|сон|сна|диагност|болезн|лечени|мозг|health|medical|sleep',
 'philosophy':r'философ|богослов|христиан|philosoph|theolog',
 'history':r'истори|археолог|древн|historic|archaeolog',
 'economy':r'эконом|предприним|бизнес|банкрот|econom|business',
 'technology':r'технолог|инженер|производ|имплантат|дрон|robot|technolog|engineer',
 'culture':r'музе|искусств|культур|худож|museum|culture|art',
 'science':r'наук|исследован|уч[её]н|математ|science|research'}
PALETTES=['приглушённые охра, кремовый и зелёный','монохромная графика и тёплая бумага','индиго, серебристый и мягкий коралловый','пыльная роза, оливковый и слоновая кость','терракота, угольный и бледно-голубой']
COMPOSITIONS=['асимметричная композиция с отрицательным пространством','широкий план с небольшим центральным акцентом','крупный фрагмент и выразительная фактура','ритм диагоналей и несколько масштабов','многослойная спокойная композиция']
RATIOS=['3:2','4:5','1:1','3:4','16:9']

def theme(article):
    value=(article.get('title','')+' '+article.get('teaser','')).casefold()
    return next((key for key,pattern in THEMES.items() if re.search(pattern,value)),'culture')

def plan(articles,date,existing=()):
    pending=list(articles);selected=[];themes=Counter();genres=Counter()
    while pending and len(selected)<CONFIG['maximum_tiles']:
        def rank(article):
            subject=theme(article);interest=article.get('reader_interest',3)
            return (themes[subject],-interest,hashlib.sha256(article.get('title','').encode()).hexdigest())
        article=min(pending,key=rank);pending.remove(article)
        if any(selection43.duplicate({'article':article},{'article':other['_article']}) for other in selected):continue
        subject=theme(article);genre=min(STYLES[subject],key=lambda x:(genres[x],STYLES[subject].index(x)))
        i=len(selected);ratio=RATIOS[i%len(RATIOS)]
        descriptor={'title':re.sub(r'\s+',' ',article['title']).strip(),'summary':re.sub(r'\s+',' ',article.get('teaser','')).strip(),'idea':re.sub(r'\s+',' ',article['title']).strip(),
            'key_facts':[s.strip() for s in re.split(r'(?<=[.!?])\s+',article.get('teaser','')) if s.strip()][:3]}
        identity=p.digest(article['title'])[:16]
        basis={'article_id':date+'/'+identity,'description_hash':p.digest(descriptor),'genre':genre,'ratio':ratio,'prompt_version':CONFIG['prompt_version']}
        prior=next((row for row in existing if row.get('article_id')==basis['article_id'] and row.get('description_hash')==basis['description_hash'] and row.get('prompt_version')==CONFIG['prompt_version']),None)
        if prior:basis.update(genre=prior['genre'],ratio=prior['ratio'])
        selected.append(dict(basis,key=p.digest(basis),theme=subject,palette=PALETTES[i%len(PALETTES)],composition=COMPOSITIONS[i%len(COMPOSITIONS)],descriptor=descriptor,_article=article))
        themes[subject]+=1;genres[genre]+=1
    return selected

def prompt(item):
    return 'Представь сюжет этой статьи в виде самостоятельного произведения изобразительного искусства. Передай центральную идею выразительной визуальной метафорой, не документальной фотографией. Жанр: '+item['genre']+'. Палитра: '+item['palette']+'. '+item['composition']+'. Соотношение сторон '+item['ratio']+'. Не добавляй надписей, букв, заголовков, водяных знаков и логотипов. Не выдумывай события, устройства или факты, противоречащие описанию; не изображай реальных людей и медицинские результаты как документальное свидетельство. '+json.dumps(item['descriptor'],ensure_ascii=False)

def provider_status():
    if CONFIG['provider']=='disabled' or not CONFIG.get('model'):return 'IMAGE_PROVIDER_NOT_CONFIGURED'
    if CONFIG['provider']!='gemini' or CONFIG.get('free_tier_verified') is not True:return 'IMAGE_FREE_TIER_NOT_VERIFIED'
    return 'READY'

def encode_image(data):
    from PIL import Image
    if len(data)>CONFIG['max_image_bytes']:raise ValueError('IMAGE_TRANSPORT_LIMIT')
    with Image.open(io.BytesIO(data)) as image:
        if image.width*image.height>25000000:raise ValueError('IMAGE_PIXEL_LIMIT')
        image.load();image=image.convert('RGB');image.thumbnail((CONFIG['web_width'],CONFIG['web_width']))
        output=io.BytesIO();image.save(output,format='WEBP',quality=CONFIG['web_quality'],method=6)
        for quality in (75,65,55):
            if len(output.getvalue())<=350000:break
            output=io.BytesIO();image.save(output,format='WEBP',quality=quality,method=6)
        if len(output.getvalue())>350000:raise ValueError('IMAGE_WEB_SIZE_LIMIT')
        return output.getvalue(),image.width,image.height

def generate(item,budget):
    """Disabled until a specific free image model is independently confirmed."""
    if provider_status()!='READY':raise RuntimeError(provider_status())
    if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REPOSITORY')!='zzz387/387-news' or os.getenv('GITHUB_REF_NAME')!='main':raise RuntimeError('IMAGE_PROTECTED_ACTIONS_REQUIRED')
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    model=CONFIG['model']
    if not re.fullmatch(r'[a-zA-Z0-9.-]+',model):raise RuntimeError('IMAGE_MODEL_INVALID')
    budget.reserve(model)
    request=Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
        data=json.dumps({'contents':[{'parts':[{'text':prompt(item)}]}],'generationConfig':{'responseModalities':['IMAGE']}}).encode(),
        headers={'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']},method='POST')
    try:
        with urlopen(request,timeout=60) as response:data=json.loads(response.read(CONFIG['max_image_bytes']*2))
    except HTTPError as exc:
        if exc.code in (429,503):budget.defer(model,1800)
        raise RuntimeError('IMAGE_HTTP_'+str(exc.code)) from None
    for candidate in data.get('candidates',[]):
        for part in candidate.get('content',{}).get('parts',[]):
            inline=part.get('inlineData',{})
            if inline.get('mimeType') in ('image/png','image/jpeg','image/webp'):return base64.b64decode(inline['data'],validate=True)
    raise RuntimeError('IMAGE_RESPONSE_MISSING')

def prepare(state,persist=lambda:None,allow_request=True):
    from scripts import selection43
    rows=selection43.composition(state)
    prepare_plan([r['article'] for r in rows],state['date'],state.setdefault('art44',{'objects':{},'history':[]}),persist,allow_request)

def prepare_plan(articles,date,saved,persist,allow_request=True):
    from scripts import news
    items=plan(articles,date,saved.get('plan') or list(cached(p.ROOT,date).values()));saved['plan']=[{k:v for k,v in item.items() if k!='_article'} for item in items]
    saved['provider_status']=provider_status();persist()
    print('[mosaic44] '+json.dumps({'date':date,'planned':len(items),'cached':len(saved['objects']),'provider_status':saved['provider_status']}),flush=True)
    if saved['provider_status']!='READY' or not allow_request:return
    budget=news.runtime.ACTIVE_BUDGET;window=os.getenv('GITHUB_RUN_ID','local')+':'+os.getenv('GITHUB_RUN_ATTEMPT','1')
    for item in items:
        if item['key'] in saved['objects']:continue
        public=cached(p.ROOT,date).get(item['key'])
        if public and (p.ROOT/public['path']).is_file() and hashlib.sha256((p.ROOT/public['path']).read_bytes()).hexdigest()==public['sha256']:continue
        if sum(h.get('key')==item['key'] for h in saved['history'])>=3:continue
        if not budget or not budget.can_request():break
        if saved.get('window')==window or getattr(budget,'image44_window',None)==window:break
        saved['window']=window;budget.image44_window=window;persist()
        try:
            raw=generate(item,budget);data,width,height=encode_image(raw)
            saved['objects'][item['key']]={'webp':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest(),'width':width,'height':height,'genre':item['genre'],'provider':CONFIG['provider'],'model':CONFIG['model']}
        except Exception as exc:saved['history'].append({'key':item['key'],'code':str(exc) if re.fullmatch(r'[A-Z_0-9]+',str(exc)) else type(exc).__name__})
        persist()

def recover_public(state,root,persist=lambda:None,allow_request=True):
    # Public approved content only; this uses the SAME active quota and controller.
    home=Path(root)/'index.html'
    if not home.is_file():return
    found=re.search(r'data-issue-date="(\d{4}-\d{2}-\d{2})"',home.read_text())
    if not found:return
    date=found[1];issue=Path(root)/'issues'/date
    if not (issue/'release.json').is_file():return
    from scripts import publication43
    publication43.validate(root,date)
    articles=from_overview((issue/'index.html').read_text())
    saved=state.setdefault('art44_public',{}).setdefault(date,{'objects':{},'history':[]})
    prepare_plan(articles,date,saved,persist,allow_request)
    materialize({'date':date,'art44':saved},articles,root)


def cached(root,date):
    file=Path(root)/'assets/illustrations'/date/'manifest.json'
    if not file.exists():return {}
    try:
        data=json.loads(file.read_text());return data.get('images',{}) if data.get('date')==date and isinstance(data.get('images'),dict) else {}
    except (OSError,ValueError):return {}

def valid_image(root,date,key,row):
    try:
        if not re.fullmatch(r'[a-f0-9]{64}',key) or row['path']!='assets/illustrations/'+date+'/'+key+'.webp':return False
        file=Path(root)/row['path']
        if file.is_symlink() or not file.is_file() or not 0<file.stat().st_size<=350000:return False
        data=file.read_bytes()
        return data[:4]==b'RIFF' and data[8:12]==b'WEBP' and hashlib.sha256(data).hexdigest()==row['sha256'] and 0<row['width']<=4096 and 0<row['height']<=4096
    except (KeyError,TypeError,OSError):return False

def render(articles,date,root=None):
    root=Path(root or p.ROOT);images=cached(root,date);items=plan(articles,date,images.values())
    if not items:return ''
    output=['<section class="art-front" data-issue-date="'+date+'" aria-labelledby="art-front-heading"><div class="art-front-heading"><h2 id="art-front-heading">На первой полосе</h2><a href="#contents">Все статьи номера ↓</a></div><div class="art-mosaic" data-tile-count="'+str(len(items))+'">']
    widths={8:[7,5,4,4,4,5,3,4],9:[7,5,4,4,4,3,3,3,3],10:[7,5,4,4,4,5,3,4,6,6],11:[7,5,4,4,4,3,3,3,3,6,6],12:[7,5,4,4,4,5,3,4,3,3,3,3]}.get(len(items),[6]*len(items))
    for i,item in enumerate(items):
        article=item['_article'];url='/issues/'+date+'/articles/'+article['slug']+'/'
        image=images.get(item['key']);media=''
        if image:
            path=Path(image.get('path',''))
            if path.is_absolute() or '..' in path.parts or path.parts[:2]!=('assets','illustrations'):image=None
            elif not (root/path).is_file() or hashlib.sha256((root/path).read_bytes()).hexdigest()!=image.get('sha256'):image=None
        if image:
            media='<img src="/'+escape(image['path'],quote=True)+'" width="'+str(image['width'])+'" height="'+str(image['height'])+'" alt="'+escape('Художественная иллюстрация: '+article['title'],quote=True)+'" loading="'+('eager' if i<2 else 'lazy')+'" decoding="async">'
        output.append('<a class="art-tile art-tile-'+str(i%8)+' '+('has-art' if image else 'text-art')+'" href="'+escape(url,quote=True)+'" data-art-key="'+item['key']+'" style="--art-ratio:'+item['ratio'].replace(':','/')+';--tile-span:'+str(widths[i])+'"><span class="art-media"><span class="art-fallback" aria-hidden="true">'+escape(article['title'])+'</span>'+media+'</span><span class="art-caption"><span class="meta">'+escape(article.get('category',''))+'</span><strong>'+escape(article['title'])+'</strong>'+('<small>Иллюстрация ИИ · '+escape(item['genre'])+'</small>' if image else '')+'</span></a>')
    return ''.join(output)+'</div></section><script src="/assets/mosaic.js" defer></script>'

def from_overview(page):
    from scripts.source_dom41 import Document
    document=Document();document.feed(page);articles=[]
    for node in document.root.all():
        if node.tag!='article' or 'toc' not in node.attrs.get('class','').split():continue
        nodes=list(node.all());link=next((n for n in nodes if n.tag=='a' and '/articles/' in n.attrs.get('href','')),None)
        if not link:continue
        articles.append({'title':link.text(),'slug':link.attrs['href'].strip('/').split('/')[-1],
            'teaser':next((n.text() for n in nodes if n.tag=='p'),''),'category':next((n.text() for n in nodes if 'meta' in n.attrs.get('class','').split()),'Общество')})
    return articles

def enhance(page,date,root=None):
    articles=from_overview(page)
    if '/assets/mosaic.css' not in page:page=page.replace('</head>','<link rel="stylesheet" href="/assets/mosaic.css"></head>',1)
    if 'class="art-front"' in page:return page
    return re.sub(r'<section class="front-grid">.*?</section>',lambda _:render(articles,date,root),page,count=1,flags=re.S)

def prompt(item):
    return 'Представь сюжет по подтверждённому описанию как самостоятельную художественную картину в жанре '+item['genre']+'. Выразительная визуальная метафора центральной идеи, не документальная фотография. Без надписей, букв, логотипов и водяных знаков. Не изображай выдуманные события как реальные. Соотношение сторон '+item['ratio']+'. Палитра: '+item['palette']+'. Композиция: '+item['composition']+'.\n'+json.dumps(item['descriptor'],ensure_ascii=False)

def materialize(state,articles,root):
    date=state['date'];folder=Path(root)/'assets/illustrations'/date;folder.mkdir(parents=True,exist_ok=True)
    images={key:row for key,row in cached(root,date).items() if valid_image(root,date,key,row)};saved=state.get('art44',{});items=plan(articles,date,saved.get('plan',[]))
    for item in items:
        row=saved.get('objects',{}).get(item['key'])
        if not row:continue
        try:
            data=base64.b64decode(row['webp'],validate=True)
            if hashlib.sha256(data).hexdigest()!=row['sha256'] or len(data)>350000:raise ValueError('IMAGE_CACHE_INTEGRITY')
            file=folder/(item['key']+'.webp')
            if file.exists() and file.read_bytes()!=data:raise ValueError('IMAGE_ARCHIVE_OVERWRITE_FORBIDDEN')
            file.write_bytes(data)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            failure={'key':item['key'],'code':'IMAGE_CACHE_UNAVAILABLE'}
            if failure not in saved.setdefault('history',[]):saved['history'].append(failure)
            continue
        images[item['key']]={**{k:item[k] for k in ('key','article_id','description_hash','genre','ratio','prompt_version')},
            **{k:row[k] for k in ('sha256','width','height','provider','model')},'path':file.relative_to(root).as_posix()}
    (folder/'manifest.json').write_text(json.dumps({'date':date,'images':images,'provider_status':provider_status()},ensure_ascii=False,indent=2)+'\n')
    return images

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--diagnose',action='store_true',required=True);parser.parse_args()
    print('[mosaic44-capability] '+json.dumps({'status':provider_status(),'image_model':CONFIG.get('model') or None,
        'configured_text_models':os.getenv('GEMINI_MODELS','').split(','),'free_image_tier_verified':CONFIG['free_tier_verified'],
        'image_api_requests':0,'publication_blocking':False,'next_action':'configure_verified_free_image_api' if provider_status()!='READY' else 'resume_existing_quota_and_cache'}))
