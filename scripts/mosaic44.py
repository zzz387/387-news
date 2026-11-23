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
 'nature':['Натурализм','Линогравюра','Ботаническая живопись'],
 'history':['Романтизм','Графика тушью','Темпера'],
 'philosophy':['Символизм','Метафизическая живопись','Абстракционизм'],
 'economy':['Геометрическая абстракция','Супрематизм','Коллаж'],
 'technology':['Конструктивизм','Индустриальная графика','Кубизм'],
 'science':['Сюрреализм','Абстракционизм','Геометрическая абстракция'],
 'culture':['Ар-нуво','Коллаж','Масло']}
THEMES={
 'yoga':r'йог|подвижност|растяж|yoga|mobility',
 'sport':r'вело|велосип|(?<![а-яё])бег(?:[ауеом]|ун|ов)?|кардио|спорт|плаван|cycling|athlet|sport',
 'family':r'реб[её]н|дет[иес]|семь|родител|супруж|parent|child|family',
 'moscow':r'москв|подмосков|усадьб|moscow',
 'architecture':r'архитект|интерьер|здани|architect|interior',
 'nature':r'птиц|природ|животн|растен|лес|болот|эколог|nature|bird|wildlife',
 'health':r'психолог|благополучи|медицин|здоров|сон|сна|диагност|болезн|лечени|мозг|health|medical|sleep',
 'philosophy':r'философ|богослов|христиан|philosoph|theolog',
 'history':r'истори|археолог|древн|historic|archaeolog',
 'economy':r'эконом|предприним|бизнес|банкрот|econom|business',
 'technology':r'технолог|инженер|производ|имплантат|дрон|robot|technolog|engineer',
 'culture':r'музе|искусств|культур|худож|авангард|галере|коллекционер|museum|culture|art',
 'science':r'наук|исследован|уч[её]н|математ|science|research'}
PALETTES=['reference-derived']
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
    if CONFIG.get('provider')=='cloudflare_workers_ai':
        from scripts import cloudflare44
        return cloudflare44.prompt(item)
    return 'Представь сюжет этой статьи в виде самостоятельного произведения изобразительного искусства. Передай центральную идею выразительной визуальной метафорой, не документальной фотографией. Жанр: '+item['genre']+'. Палитра: '+item['palette']+'. '+item['composition']+'. Соотношение сторон '+item['ratio']+'. Не добавляй надписей, букв, заголовков, водяных знаков и логотипов. Не выдумывай события, устройства или факты, противоречащие описанию; не изображай реальных людей и медицинские результаты как документальное свидетельство. '+json.dumps(item['descriptor'],ensure_ascii=False)

def provider_status():
    from scripts import cloudflare44
    return cloudflare44.status(CONFIG)

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
    from scripts import cloudflare44
    return cloudflare44.generate(item,budget,CONFIG)

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

def article_plans(state,rows=None):
    """All final articles, independent of the 8–12 front-page selection."""
    rows=approved_rows(state) if rows is None else rows;genres=Counter();result=[]
    for record in rows:
        article=record['article'];body=' '.join(b.get('text','') for b in article.get('blocks',[]))
        activity=' '.join(a.get('title','')+' '+a.get('benefit','') for a in article.get('activities',[]))
        sentences=[s.strip() for s in re.split(r'(?<=[.!?])\s+',body+' '+activity) if s.strip()]
        subject=theme(article)
        genre=min(STYLES[subject],key=lambda value:(genres[value],STYLES[subject].index(value)))
        i=len(result);text_hash=p.digest(final_text(article))
        basis={'date':state['date'],'article_id':record['id'],'text_hash':text_hash,'prompt_version':CONFIG['prompt_version']}
        key=p.digest(basis)
        previous=next((row for row in (state.get('art44',{}).get('plan') or list(cached(p.ROOT,state['date']).values())) if row.get('key')==key),None)
        item=dict(basis,key=key,protocol=2,genre=genre,ratio=RATIOS[i%len(RATIOS)],palette=PALETTES[i%len(PALETTES)],composition=COMPOSITIONS[i%len(COMPOSITIONS)],
            descriptor={'title':article['title'],'summary':article.get('teaser',''),'idea':sentences[0] if sentences else article['title'],
                'full_text_summary':' '.join(sentences[:4]+sentences[-2:])[:4000], 'key_facts':sentences[:3]+sentences[-2:]})
        if previous:
            for key_name in ('genre','ratio','palette','composition'):
                if key_name in previous:item[key_name]=previous[key_name]
        brief=CONFIG.get('visual_brief_repairs',{}).get(text_hash,{})
        # Repairs are bound to immutable approved text, never to a mutable title/slug.
        source=record.get('source',{})
        source_title=source.get('title','')
        visual=brief.get('scene_en') or article.get('art_brief_en') or (source_title if source_title.isascii() else '')
        if visual:item['descriptor']['visual_subject_en']=visual[:1400]
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
        'complete':bool(items) and ready==len(items),
        'reference_guided':sum(object_valid(objects.get(i['key'],{})) and objects[i['key']].get('reference_status') in ('FOUR_REFERENCES_READY','ONE_REFERENCE_READY') for i in items),'provider_status':saved.get('provider_status',provider_status()),'image_requests':saved.get('requests',0)}

def prepare(state,persist=lambda:None,allow_request=True):
    saved=state.setdefault('art44',{'objects':{},'history':[]})
    saved.setdefault('objects',{});saved.setdefault('history',[])
    saved['provider_status']='IMAGE_PROVIDER_FORBIDDEN' if saved.get('blocked_model')==CONFIG.get('model') and saved.get('blocked_model') else provider_status()
    if not approval_valid(state):
        saved['code']='ART_NOT_EDITORIAL_APPROVED';persist();return art_report(state)
    items=article_plans(state)
    if CONFIG.get('references_enabled') and state['date']>=CONFIG.get('first_reference_issue','9999-12-31'):
        from scripts import art_library44
        from scripts import news
        budget=news.runtime.ACTIVE_BUDGET
        sets=art_library44.prepare_sets(p.ROOT,state,items,persist,discover=bool(allow_request and budget and budget.remaining_seconds()>180))
        art_library44.attach(p.ROOT,state,items,sets)
    return prepare_items(state,items,persist,allow_request)

def prepare_items(state,items,persist=lambda:None,allow_request=True):
    saved=state.setdefault('art44',{'objects':{},'history':[]})
    saved.setdefault('objects',{});saved.setdefault('history',[])
    saved['provider_status']=provider_status()
    from scripts import cloudflare44
    if os.getenv('NEWS_CF_PROBE_STATUS')=='READY':saved.pop('authorization_failure',None)
    if saved['provider_status'].startswith('CF_AUTHENTICATION_FAILED_') or saved['provider_status'] in ('CF_HTTP_401','CF_HTTP_403'):
        saved['authorization_failure']={'credentials_hash':cloudflare44.credential_fingerprint(),'code':saved['provider_status']}
    auth_failure=saved.get('authorization_failure',{})
    if auth_failure.get('credentials_hash')==cloudflare44.credential_fingerprint():
        saved['provider_status']=auth_failure['code']
    elif auth_failure:saved.pop('authorization_failure',None)
    saved['plan']=items;state['assembly_status44']='ART_GENERATION';persist()
    from scripts import news
    budget=news.runtime.ACTIVE_BUDGET
    # One sequential batch, bounded only by the existing request/time budgets.
    for item in items:
        public=cached(p.ROOT,state['date']).get(item['key'])
        if public and valid_image(p.ROOT,state['date'],item['key'],public) and not object_valid(saved['objects'].get(item['key'],{})):
            saved['objects'][item['key']]={**public,'webp':base64.b64encode((p.ROOT/public['path']).read_bytes()).decode(),'status':'READY'}
            persist()
        if object_valid(saved['objects'].get(item['key'],{})):continue
        if item['key'] in saved['objects']:
            saved.setdefault('invalid_objects',{})[item['key']]=saved['objects'].pop(item['key'])
            persist()
        if not allow_request or saved['provider_status']!='READY' or not budget or (budget.remaining_seconds()<90 if CONFIG.get('provider')=='cloudflare_workers_ai' else not budget.can_request()):break
        if sum(h.get('key')==item['key'] for h in saved['history'])>=CONFIG.get('max_retries_per_article',2):continue
        if CONFIG.get('reference_required') and state['date']>=CONFIG.get('first_reference_issue','9999-12-31') and item.get('reference_status')!='ONE_REFERENCE_READY':
            saved['code']='REFERENCE_SET_UNAVAILABLE';continue
        saved['current_key']=item['key'];persist()
        try:
            before=budget.ledger.get('cloudflare_ai',{}).get('requests',0) if CONFIG.get('provider')=='cloudflare_workers_ai' else budget.used
            try:raw=generate(item,budget)
            finally:
                after=budget.ledger.get('cloudflare_ai',{}).get('requests',0) if CONFIG.get('provider')=='cloudflare_workers_ai' else budget.used
                saved['requests']=saved.get('requests',0)+max(0,after-before)
            data,width,height=encode_image(raw);digest=hashlib.sha256(data).hexdigest()
            if item.get('selected_reference_id'):
                from scripts import art_reference44
                item['color_match']=art_reference44.compare(item['palette'],art_reference44.profile(data))
            if any(obj.get('sha256')==digest for obj in saved['objects'].values()):raise ValueError('IMAGE_NOT_UNIQUE')
            saved['objects'][item['key']]={'webp':base64.b64encode(data).decode(),'sha256':digest,'width':width,'height':height,
                'size':len(data),'genre':item['genre'],'provider':CONFIG['provider'],'model':CONFIG['reference_model'] if item.get('reference_images') else CONFIG['model'],'status':'READY',
                **{k:item[k] for k in ('reference_status','reference_set_id','reference_artwork_ids','reference_sha256','selected_reference_id','reference_images_sent','reference_selection_version','reference_selection_score','reference_selection_reason','palette','art_movement','medium','color_match') if k in item},
                'article_id':item['article_id'],'date':state['date'],'text_hash':item['text_hash'],'prompt':item['prompt'],
                'path':'assets/illustrations/'+state['date']+'/'+item['key']+'.webp'}
            persist()  # Keep the first usable result even if its one color retry fails.
            if item.get('color_match',{}).get('status')=='COLOR_MISMATCH' and not saved.setdefault('color_retries',{}).get(item['key']) and budget.remaining_seconds()>120:
                saved['color_retries'][item['key']]=True;persist()
                retry=dict(item,color_retry=True)
                before_retry=budget.ledger.get('cloudflare_ai',{}).get('requests',0)
                try:retry_raw=generate(retry,budget)
                finally:saved['requests']=saved.get('requests',0)+max(0,budget.ledger.get('cloudflare_ai',{}).get('requests',0)-before_retry)
                second,w,h=encode_image(retry_raw);match=art_reference44.compare(item['palette'],art_reference44.profile(second));checksum=hashlib.sha256(second).hexdigest()
                if match['lab_distance']<item['color_match']['lab_distance'] and not any(k!=item['key'] and v.get('sha256')==checksum for k,v in saved['objects'].items()):
                    saved['objects'][item['key']].update(webp=base64.b64encode(second).decode(),sha256=checksum,width=w,height=h,size=len(second),color_match=match)
                saved['objects'][item['key']]['color_retry_attempted']=True
        except Exception as exc:
            if isinstance(exc,news.runtime.GenerationPaused):
                saved['code']='IMAGE_QUOTA_OR_COOLDOWN';persist();break
            code=str(exc) if re.fullmatch(r'[A-Z_0-9]+',str(exc)) else type(exc).__name__
            if code.startswith('CF_') and code!='CF_IMAGE_INVALID':
                if code.startswith('CF_AUTHENTICATION_FAILED_') or code in ('CF_HTTP_401','CF_HTTP_403'):
                    saved['authorization_failure']={'credentials_hash':cloudflare44.credential_fingerprint(),'code':code}
                saved['provider_status']=code;persist();break
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
    historical=publication43.historical_recovery(state['date'])
    if budget and not historical:
        budget.deadline=min(budget.deadline,time.monotonic()+max(0,(release-clock()).total_seconds()-120))
    prepare(state,persist,allow_request=allow_request and not preview and (clock()<release or historical))
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


def published_records(root,date,allow_missing_art=False):
    from scripts import publication43,source_dom41
    data=publication43.validate(root,date,allow_missing_art=allow_missing_art);rows=[]
    for slug in data['pages']:
        page=(Path(root)/'issues'/date/'articles'/slug/'index.html').read_text()
        doc=source_dom41.Document();doc.feed(page);nodes=list(doc.root.all())
        title=next(n.text() for n in nodes if n.tag=='h1')
        teaser=next((n.text() for n in nodes if 'dek' in n.attrs.get('class','').split()),'')
        body=next(n for n in nodes if 'article-body' in n.attrs.get('class','').split())
        blocks,_=source_dom41.blocks([body])
        meta=next((n.text() for n in nodes if n.tag=='div' and n.attrs.get('class')=='meta'),'Общество')
        article={'title':title,'teaser':teaser,'category':meta.split(' · ')[0],'kind':meta.split(' · ')[-1],
            'mode':'','blocks':blocks,'activities':[],'slug':slug}
        rows.append({'id':'published:'+date+'/'+slug,'article':article})
    return data,rows


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

def materialize(state,articles,root,items=None):
    date=state['date'];folder=Path(root)/'assets/illustrations'/date;folder.mkdir(parents=True,exist_ok=True)
    images={key:row for key,row in cached(root,date).items() if valid_image(root,date,key,row)};saved=state.get('art44',{});items=(article_plans(state) if approval_valid(state) else []) if items is None else items
    active={item['key'] for item in items}
    images={key:row for key,row in images.items() if key in active}
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
            **{k:row[k] for k in ('sha256','width','height','provider','model')},
            **{k:row[k] for k in ('reference_status','reference_set_id','reference_artwork_ids','reference_sha256','selected_reference_id','reference_images_sent','reference_selection_version','reference_selection_score','reference_selection_reason','palette','art_movement','medium','color_match') if k in row},'path':file.relative_to(root).as_posix()}
    (folder/'manifest.json').write_text(json.dumps({'date':date,'images':images,'provider_status':provider_status()},ensure_ascii=False,indent=2)+'\n')
    return images

def diagnose(probe=False):
    from scripts import cloudflare44
    return cloudflare44.diagnose(CONFIG,probe)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--diagnose',action='store_true',required=True);parser.add_argument('--probe-models',action='store_true');args=parser.parse_args()
    diagnose(args.probe_models)
