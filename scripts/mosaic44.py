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

def final_text(article):
    return {key:article.get(key,[] if key in ('blocks','activities') else '') for key in ('title','teaser','category','kind','mode','blocks','activities')}

def approved_rows(state):
    return selection43.composition(state)

def approval_signature(state):
    return p.digest([{'id':r['id'],'text':final_text(r['article'])} for r in approved_rows(state)])

def approval_valid(state):
    approval=state.get('art44',{}).get('approval',{})
    return bool(approval and approval.get('date')==state['date'] and approval.get('signature')==approval_signature(state))

def approve(state):
    """Freeze only eligible final texts; no source, writing or image requests."""
    from scripts import policy44
    rows=approved_rows(state);policy44.require(state,rows)
    saved=state.setdefault('art44',{'objects':{},'history':[]})
    saved.setdefault('objects',{});saved.setdefault('history',[])
    signature=approval_signature(state)
    if saved.get('approval',{}).get('signature')!=signature:
        saved['approval']={'date':state['date'],'signature':signature,'articles':[{'article_id':r['id'],'text_hash':p.digest(final_text(r['article']))} for r in rows]}
        state['assembly_status44']='EDITORIAL_APPROVED'
    state['audit_passed']=True
    return saved['approval']

def article_plans(state):
    """All final articles, independent of the 8–12 front-page selection."""
    rows=approved_rows(state);genres=Counter();result=[]
    for record in rows:
        article=record['article'];body=' '.join(b.get('text','') for b in article.get('blocks',[]))
        activity=' '.join(a.get('title','')+' '+a.get('benefit','') for a in article.get('activities',[]))
        sentences=[s.strip() for s in re.split(r'(?<=[.!?])\s+',body+' '+activity) if s.strip()]
        subject=theme({'title':article['title'],'teaser':article.get('teaser','')+' '+body[:2500]})
        genre=min(STYLES[subject],key=lambda value:(genres[value],STYLES[subject].index(value)))
        i=len(result);text_hash=p.digest(final_text(article))
        basis={'date':state['date'],'article_id':record['id'],'text_hash':text_hash,'prompt_version':CONFIG['prompt_version']}
        key=p.digest(basis)
        previous=next((row for row in state.get('art44',{}).get('plan',[]) if row.get('key')==key),None)
        item=dict(basis,key=key,protocol=2,genre=genre,ratio=RATIOS[i%len(RATIOS)],palette=PALETTES[i%len(PALETTES)],composition=COMPOSITIONS[i%len(COMPOSITIONS)],
            descriptor={'title':article['title'],'summary':article.get('teaser',''),'idea':sentences[0] if sentences else article['title'],
                'full_text_summary':' '.join(sentences[:4]+sentences[-2:])[:4000], 'key_facts':sentences[:3]+sentences[-2:]})
        if previous:
            for key_name in ('genre','ratio','palette','composition'):item[key_name]=previous[key_name]
        item['description_hash']=p.digest(item['descriptor'])
        item['prompt']=prompt(item);result.append(item);genres[item['genre']]+=1
    return result

def object_valid(row):
    try:
        data=base64.b64decode(row['webp'],validate=True)
        return 0<row['width']<=4096 and 0<row['height']<=4096 and 0<len(data)<=350000 and data[:4]==b'RIFF' and data[8:12]==b'WEBP' and hashlib.sha256(data).hexdigest()==row['sha256']
    except (KeyError,ValueError,TypeError):return False

def art_report(state):
    saved=state.get('art44',{});items=saved.get('plan',[]);objects=saved.get('objects',{})
    ready=sum(object_valid(objects.get(item['key'],{})) for item in items)
    return {'phase':state.get('assembly_status44','NOT_APPROVED'),'articles':len(items),'ready':ready,'missing':len(items)-ready,
        'complete':bool(items) and ready==len(items),'provider_status':saved.get('provider_status',provider_status()),'image_requests':saved.get('requests',0)}

def prepare(state,persist=lambda:None,allow_request=True):
    saved=state.setdefault('art44',{'objects':{},'history':[]})
    saved.setdefault('objects',{});saved.setdefault('history',[])
    saved['provider_status']='IMAGE_PROVIDER_FORBIDDEN' if saved.get('blocked_model')==CONFIG.get('model') and saved.get('blocked_model') else provider_status()
    if not approval_valid(state):
        saved['code']='ART_NOT_EDITORIAL_APPROVED';persist();return art_report(state)
    items=article_plans(state);saved['plan']=items;state['assembly_status44']='ART_GENERATION';persist()
    from scripts import news
    budget=news.runtime.ACTIVE_BUDGET
    # One sequential batch, bounded only by the existing request/time budgets.
    for item in items:
        if object_valid(saved['objects'].get(item['key'],{})):continue
        if item['key'] in saved['objects']:
            saved.setdefault('invalid_objects',{})[item['key']]=saved['objects'].pop(item['key'])
            persist()
        if not allow_request or saved['provider_status']!='READY' or not budget or not budget.can_request():break
        if sum(h.get('key')==item['key'] for h in saved['history'])>=3:continue
        saved['current_key']=item['key'];persist()
        try:
            before=budget.used
            try:raw=generate(item,budget)
            finally:saved['requests']=saved.get('requests',0)+(budget.used-before)
            data,width,height=encode_image(raw);digest=hashlib.sha256(data).hexdigest()
            if any(obj.get('sha256')==digest for obj in saved['objects'].values()):raise ValueError('IMAGE_NOT_UNIQUE')
            saved['objects'][item['key']]={'webp':base64.b64encode(data).decode(),'sha256':digest,'width':width,'height':height,
                'size':len(data),'genre':item['genre'],'provider':CONFIG['provider'],'model':CONFIG['model'],'status':'READY',
                'article_id':item['article_id'],'date':state['date'],'text_hash':item['text_hash'],'prompt':item['prompt'],
                'path':'assets/illustrations/'+state['date']+'/'+item['key']+'.webp'}
        except Exception as exc:
            if isinstance(exc,news.runtime.GenerationPaused):
                saved['code']='IMAGE_QUOTA_OR_COOLDOWN';persist();break
            code=str(exc) if re.fullmatch(r'[A-Z_0-9]+',str(exc)) else type(exc).__name__
            saved['history'].append({'key':item['key'],'code':code})
            if code in ('IMAGE_HTTP_401','IMAGE_HTTP_403'):
                saved['blocked_model']=CONFIG.get('model');saved['provider_status']='IMAGE_PROVIDER_FORBIDDEN'
            if code in ('IMAGE_HTTP_429','IMAGE_HTTP_503','IMAGE_HTTP_401','IMAGE_HTTP_403'):
                persist();break
        persist()
    saved.pop('current_key',None);report=art_report(state)
    saved['completion']='COMPLETE' if report['complete'] else 'INCOMPLETE'
    print('[art44] '+json.dumps(report),flush=True);persist();return report

def finalize(state,root,persist,clock,release,preview=False,allow_request=True,allow_wait=False):
    """Only the frozen approved issue reaches art; publication never waits past due."""
    from scripts import publication43,pipeline
    if not approval_valid(state):approve(state)
    persist()
    budget=__import__('scripts.news',fromlist=['runtime']).runtime.ACTIVE_BUDGET
    import time
    stage_deadline=budget.deadline if budget else None
    if budget:
        budget.deadline=min(budget.deadline,time.monotonic()+max(0,(release-clock()).total_seconds()-120))
    prepare(state,persist,allow_request=allow_request and not preview and clock()<release)
    report=art_report(state)
    state['art44']['emergency_text']=not report['complete']
    state['assembly_status44']='READY_FOR_PUBLICATION' if report['complete'] or provider_status()!='READY' or clock()>=release else 'ART_GENERATION'
    remaining=(release-clock()).total_seconds()
    if (allow_wait and not preview and 0<remaining<=600 and os.getenv('GITHUB_ACTIONS')=='true' and os.getenv('GITHUB_REF_NAME')=='main'
            and (stage_deadline is None or stage_deadline-time.monotonic()>remaining+90)):
        from scripts import release_queue
        release_queue.wait_until_release(state['date'])
    if clock()<release and not preview:
        pipeline.status(state,'APPROVED','publish_when_due' if state['assembly_status44']=='READY_FOR_PUBLICATION' else 'resume_missing_art');persist();return False
    if preview:
        publication43.build(state,root,preview=True);pipeline.status(state,'APPROVED','preview_complete');persist();return False
    state['assembly_status44']='READY_FOR_PUBLICATION'
    if not pipeline.reserve_delivery(state,clock()):persist();return False
    publication43.build(state,root);pipeline.status(state,'PUBLISHING','commit_and_deploy');persist();return True


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
        bound=next((row for row in images.values() if row.get('protocol')==2 and row.get('article_slug')==article['slug']),None)
        if bound:item.update(key=bound['key'],genre=bound['genre'],ratio=bound['ratio'])
        image=bound or images.get(item['key']);media=''
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

def materialize(state,articles,root):
    date=state['date'];folder=Path(root)/'assets/illustrations'/date;folder.mkdir(parents=True,exist_ok=True)
    images={key:row for key,row in cached(root,date).items() if valid_image(root,date,key,row)};saved=state.get('art44',{});items=article_plans(state) if approval_valid(state) else []
    for item,article in zip(items,articles):item['article_slug']=article['slug']
    for item in items:
        row=saved.get('objects',{}).get(item['key'])
        if not row:continue
        try:
            data=base64.b64decode(row['webp'],validate=True)
            if not object_valid(row):raise ValueError('IMAGE_CACHE_INTEGRITY')
            if any(other.get('sha256')==row['sha256'] and key!=item['key'] for key,other in images.items()):raise ValueError('IMAGE_NOT_UNIQUE')
            file=folder/(item['key']+'.webp')
            if file.exists() and file.read_bytes()!=data:raise ValueError('IMAGE_ARCHIVE_OVERWRITE_FORBIDDEN')
            file.write_bytes(data)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            failure={'key':item['key'],'code':'IMAGE_CACHE_UNAVAILABLE'}
            if failure not in saved.setdefault('history',[]):saved['history'].append(failure)
            continue
        images[item['key']]={**{k:item[k] for k in ('key','article_id','description_hash','genre','ratio','prompt_version','date','text_hash','protocol','article_slug')},
            **{k:row[k] for k in ('sha256','width','height','provider','model')},'path':file.relative_to(root).as_posix()}
    (folder/'manifest.json').write_text(json.dumps({'date':date,'images':images,'provider_status':provider_status()},ensure_ascii=False,indent=2)+'\n')
    return images

def diagnose(probe=False):
    result={'status':provider_status(),'image_model':CONFIG.get('model') or None,'free_image_tier_verified':CONFIG['free_tier_verified'],
        'image_api_requests':0,'publication_blocking':False,'pricing_url':'https://aistudio.google.com/docs/pricing',
        'pricing_checked':'2026-11-19','image_generation_access':'UNVERIFIED','billing_access':'NOT_AVAILABLE',
        'free_image_tier':'NOT_AVAILABLE_FOR_DOCUMENTED_GEMINI_IMAGE_MODELS','next_action':'authorized_image_api_required'}
    if probe:
        if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REPOSITORY')!='zzz387/387-news' or os.getenv('GITHUB_REF_NAME')!='main':raise RuntimeError('IMAGE_PROTECTED_ACTIONS_REQUIRED')
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        result['models']=[]
        for model in ('gemini-3.1-flash-lite-image','gemini-3.1-flash-image','gemini-2.5-flash-image'):
            row={'model':model,'generation_smoke':'NOT_RUN_PAID_ACCESS_NOT_AUTHORIZED'}
            try:
                request=Request('https://generativelanguage.googleapis.com/v1beta/models/'+model,headers={'x-goog-api-key':os.environ['GEMINI_API_KEY']})
                with urlopen(request,timeout=15) as response:data=json.loads(response.read(100000))
                row.update(metadata='AVAILABLE',methods=data.get('supportedGenerationMethods',[]))
            except HTTPError as exc:row['metadata']='HTTP_'+str(exc.code)
            except Exception as exc:row['metadata']=type(exc).__name__
            result['models'].append(row)
    print('[mosaic44-capability] '+json.dumps(result),flush=True)
    return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--diagnose',action='store_true',required=True);parser.add_argument('--probe-models',action='store_true');args=parser.parse_args()
    diagnose(args.probe_models)
