"""Dynamic reader-only release, including a clearly labelled no-AI link digest."""
import copy,hashlib,json,re,shutil,tempfile
from datetime import datetime
from html import escape
from pathlib import Path
try:
    from scripts import policy41 as p,publication41 as render,editorial43 as e,rights41,news,source41,selection43,light43,layout43,source_links43
except ImportError:
    import policy41 as p,publication41 as render,editorial43 as e,rights41,news,source41,selection43,light43,layout43,source_links43


def digest_bytes(data):return hashlib.sha256(data).hexdigest()

def reader_chrome(page,root=None):
    menu='<a href="/">Обзор номера</a><a href="/archive/">Архив</a>'
    if root is not None and (Path(root)/'art/index.html').is_file():menu+='<a href="/art/">Искусство</a>'
    return re.sub(r'(<nav class="topics wrap"[^>]*>).*?(</nav>)',lambda m:m[1]+menu+m[2],page,count=1,flags=re.S)


def public_article(record):
    if not e.eligible(record):raise p.Blocked('ARTICLE_NOT_APPROVED')
    a=record['article'];source=record['source'];rights41.require(source,a['mode'],record['rights'])
    return {**{k:copy.deepcopy(a.get(k,'')) for k in ('title','teaser','category','kind','mode','slug','blocks','activities')},
        'primary_source':{k:source.get(k,'') for k in ('url','title','publisher','author','published','language')},
        'attribution':copy.deepcopy(record['rights'].get('attribution',{})),'images':[],'public_references':[]}


def overview(date,no,rows,permanent=False):
    moment=datetime.fromisoformat(date+'T06:00').replace(tzinfo=p.TZ)
    html=news.page_header('Обзор источников · '+date,'Проверенные ссылки редакции 387 News',f'/issues/{date}/' if permanent else '/',moment,no).replace('Редакция 2.0','Редакция 4.3')
    html+=f'<main class="wrap" data-policy-version="4.3" data-issue-date="{date}" data-issue-number="{no}" data-article-count="0" data-issue-kind="source_digest" data-reserve-count="{len(rows)}">'
    html+='<h1>Обзор источников</h1><p>Сегодня в выпуске — проверенные ссылки, а не новые полноценные статьи. Этот обзор подготовлен без генерации текста Gemini. Даты ниже относятся к публикациям источников, где они указаны.</p><ul class="source-digest">'
    for row in rows:
        date_label=row.get('published') or 'дата публикации не сохранена в резерве'
        html+='<li><h2><a rel="noopener noreferrer" href="'+escape(row['url'],quote=True)+'">'+escape(row['title'])+'</a></h2><p>'+escape(row['publisher'])+' · '+escape(date_label)+'</p><p>Доступность проверена: '+escape(row['checked_at'])+'</p></li>'
    return reader_chrome(html+'</ul><p><a href="/archive/">Архив выпусков</a></p></main>'+news.page_footer())


def metadata(root,date):
    path=Path(root)/'issues'/date/'release.json'
    data=json.loads(path.read_text())
    if data.get('policy_version') not in ('4.3','4.4') or data.get('date')!=date:raise p.Blocked('PUBLIC_METADATA_INVALID')
    return data


def validate(root,date,allow_missing_art=False):
    root=Path(root);data=metadata(root,date);issue=root/'issues'/date
    count=data.get('article_count');kind=data.get('kind')
    if type(count) is not int or count<0:raise p.Blocked('PUBLIC_COUNT_INVALID')
    if kind not in ('articles','source_digest') or (count==0)!=(kind=='source_digest'):raise p.Blocked('PUBLIC_KIND_MISMATCH')
    if not data.get('preview') and data.get('minimum_articles',1)>=8 and count<data['minimum_articles']:raise p.Blocked('MINIMUM_ARTICLES_NOT_MET')
    pages=list((issue/'articles').glob('*/index.html'))
    if len(pages)!=count or len(data.get('pages',{}))!=count:raise p.Blocked('PUBLIC_ARTICLE_COUNT')
    for slug,hashes in data['pages'].items():
        if not re.fullmatch(r'[a-z0-9-]+',slug):raise p.Blocked('PUBLIC_SLUG_INVALID')
        file=issue/'articles'/slug/'index.html';md=file.with_name('article.md')
        if digest_bytes(file.read_bytes())!=hashes['html'] or digest_bytes(md.read_bytes())!=hashes['markdown']:raise p.Blocked('PUBLIC_CONTENT_CHANGED')
        render.source_links43.validate(file.read_text(),required=data.get('source_links_version')==1)
        render.validate_page(file.read_text().replace('data-policy-version="'+data['policy_version']+'"','data-policy-version="4.1"',1))
    for name,key in (('index.html','overview_hash'),('overview.md','markdown_hash')):
        if digest_bytes((issue/name).read_bytes())!=data[key]:raise p.Blocked('PUBLIC_OVERVIEW_CHANGED')
    page=(issue/'index.html').read_text()
    if f'data-article-count="{count}"' not in page or f'data-issue-date="{date}"' not in page:raise p.Blocked('PUBLIC_COUNT_INVALID')
    light=data.get('light_news',[])
    if data.get('mosaic_revision'):
        from scripts import mosaic44
        for image in data.get('illustrations',[]):
            if not re.fullmatch(r'assets/illustrations/'+re.escape(date)+r'/[a-f0-9]{64}\.webp',image.get('path','')):raise p.Blocked('PUBLIC_ILLUSTRATION_CHANGED')
            if not allow_missing_art and not mosaic44.valid_image(root,date,image['key'],image):raise p.Blocked('PUBLIC_ILLUSTRATION_CHANGED')
        if data['mosaic_revision']>=2:
            art=data['art44'];images=data['illustrations']
            if art['required']!=count or art['ready']!=len(images) or art['missing']!=count-len(images) or len({r['sha256'] for r in images})!=len(images):raise p.Blocked('PUBLIC_ILLUSTRATION_CHANGED')
            for image in images:
                article_page=(issue/'articles'/image['article_slug']/'index.html').read_text()
                if ('src="/'+image['path']+'"') not in article_page or 'Художественная иллюстрация, созданная ИИ' not in article_page:raise p.Blocked('PUBLIC_ILLUSTRATION_CHANGED')
    if data.get('light_count',len(light))!=len(light):raise p.Blocked('PUBLIC_LIGHT_COUNT')
    if render_light(light) and render_light(light) not in page:raise p.Blocked('PUBLIC_LIGHT_CHANGED')
    if data['policy_version']=='4.4' and not data.get('preview'):
        from scripts import policy44
        policy44.require({'policy_version':'4.4','brief_policy_revision':data.get('brief_policy_revision',1)},[policy44.from_html(f.read_text()) for f in pages],light)
    if count==0:
        rows=data.get('sources',[])
        if not rows or 'Обзор источников' not in page:raise p.Blocked('EMPTY_RESERVE')
        for row in rows:
            source41.safe_url(row['url'])
            if not all(row.get(k) for k in ('title','publisher','checked_at')) or escape(row['url'],quote=True) not in page:raise p.Blocked('PUBLIC_RESERVE_INVALID')
    if f'/issues/{date}/' not in (root/'archive/index.html').read_text():raise p.Blocked('ARCHIVE_LINK_MISSING')
    previous=news.ROOT
    try:
        news.ROOT=root
        if allow_missing_art:
            art_paths={'/'+r['path'] for r in data.get('illustrations',[])}
            for file in pages+[issue/'index.html',root/'archive/index.html']:
                for uri in re.findall(r'(?:href|src)="(/[^"#?]+)',file.read_text()):
                    dest=root/uri.lstrip('/');dest=dest/'index.html' if uri.endswith('/') else dest
                    if uri not in art_paths and not dest.is_file():raise RuntimeError('Broken local link')
        else:news.validate_local_links(pages+[issue/'index.html',root/'archive/index.html'])
    finally:news.ROOT=previous
    return data


def historical_recovery(date):
    import os
    return (date=='2026-11-20' and os.getenv('NEWS_HISTORICAL_RECOVERY_DATE')==date and os.getenv('GITHUB_ACTIONS')=='true'
        and os.getenv('GITHUB_REPOSITORY')=='zzz387/387-news' and os.getenv('GITHUB_REF_NAME')=='main')


def build(state,root,reserve=(),preview=False):
    root=Path(root);date=state['date'];existing=root/'issues'/date
    if existing.exists():
        try:from scripts import site_checks
        except ImportError:import site_checks
        site_checks.validate_local_release(root,date)
        return not preview
    from scripts import policy44
    records=selection43.composition(state);articles=[]
    version='4.4' if policy44.active(state) else '4.3'
    if version=='4.4' and not preview:policy44.require(state,records)
    if len(records)<e.CONFIG['minimum_articles'] and not preview and (records or e.CONFIG['minimum_articles']>=8):raise p.Blocked('MINIMUM_ARTICLES_NOT_MET')
    for i,r in enumerate(records,1):
        a=public_article(r);a['slug']=news.slugify(a['title'],i);articles.append(a)
    if not articles and not reserve:raise p.Blocked('NO_SAFE_RESERVE')
    if not historical_recovery(date) and (root/'issues').exists() and any(d.name>date for d in (root/'issues').iterdir() if re.fullmatch(r'\d{4}-\d{2}-\d{2}',d.name)):
        raise p.Blocked('BACKDATED_HOME_REPLACEMENT_FORBIDDEN')
    with tempfile.TemporaryDirectory(prefix='387-daily43-') as directory:
        working=Path(directory)
        for name in ('assets','archive','issues','art'):
            if (root/name).is_dir():shutil.copytree(root/name,working/name)
        (working/'archive').mkdir(exist_ok=True);(working/'issues').mkdir(exist_ok=True)
        previous=news.ROOT;news.ROOT=working
        preserved_home=(root/'index.html').read_bytes() if historical_recovery(date) and (root/'index.html').is_file() else None
        try:
            no=news.get_next_number();issue=working/'issues'/date;issue.mkdir()
            data={'date':date,'number':no,'policy_version':version,'article_count':len(articles),
                  'kind':'articles' if articles else 'source_digest','minimum_articles':e.CONFIG['minimum_articles'],
                  'standard_issue':len(articles)>=e.CONFIG['minimum_articles'],'preview':preview,'pages':{},'source_links_version':1,'prepared_at':datetime.now(p.TZ).isoformat(),'release_not_before':date+'T06:00:00+03:00'}
            if version=='4.4':data['brief_policy_revision']=state.get('brief_policy_revision',2)
            if historical_recovery(date):data['recovered_at']=datetime.now(p.TZ).isoformat()
            if version=='4.4':
                from scripts import mosaic44
                if not preview and not mosaic44.approval_valid(state):mosaic44.approve(state)
                images=mosaic44.materialize(state,articles,working)
                data['mosaic_revision']=2;data['illustrations']=list(images.values())
                current={row['article_slug']:row for row in images.values() if row.get('protocol')==2}
                for a in articles:a['artwork44']=current.get(a['slug'])
                complete=len(current)==len(articles) and bool(articles)
                data['art44']={'status':'COMPLETE' if complete else 'ARTWORK_INCOMPLETE','required':len(articles),'ready':len(current),'missing':len(articles)-len(current),'emergency_text':not complete,'provider_status':mosaic44.provider_status()}
            for a in articles:
                file=issue/'articles'/a['slug']/'index.html';file.parent.mkdir(parents=True)
                file.write_text(reader_chrome(render.render_article(date,no,a,working,policy_version=version),working))
                md=file.with_name('article.md');md.write_text(render.markdown(a))
                data['pages'][a['slug']]={'html':digest_bytes(file.read_bytes()),'markdown':digest_bytes(md.read_bytes())}
            if version=='4.4':
                items=mosaic44.article_plans(state) if mosaic44.approval_valid(state) else []
                data['art44']['bindings']=[{**{k:item[k] for k in ('key','date','article_id','text_hash','prompt_version','description_hash','genre','ratio','protocol')},'article_slug':a['slug']} for item,a in zip(items,articles)]
            light=public_light(state)
            data['light_news']=light;data['light_count']=len(light)
            rows=[{k:r.get(k,'') for k in ('url','title','publisher','published','checked_at')} for r in reserve] if not articles else []
            if not articles:data['sources']=rows
            for permanent,target in ((True,issue/'index.html'),(False,working/'index.html')):
                page=reader_chrome(render.render_overview(date,no,articles,permanent,policy_version=version),working) if articles else overview(date,no,rows,permanent)
                target.write_text(page.replace('</main>',render_light(light)+'</main>',1))
            markdown=('# Обзор источников\n\nПроверенные ссылки; не полноценные статьи. Без генерации Gemini.\n\n'+'\n'.join('- ['+r['title']+']('+r['url']+') — '+r['publisher']+'; '+(r.get('published') or 'дата не сохранена') for r in rows)) if not articles else '# Выпуск '+date+'\n\n'+'\n'.join('- ['+a['title']+'](/issues/'+date+'/articles/'+a['slug']+'/)' for a in articles)
            if light:markdown+='\n\n# НЕ ВСЁ ТАК СЕРЬЁЗНО\n\nМаленькие новости, от которых мир становится интереснее\n\n'+'\n\n'.join('## '+x['title']+'\n\n'+x['text']+'\n\nИсточник: ['+x['source']['publisher']+']('+x['source']['url']+')' for x in light)
            (issue/'overview.md').write_text(markdown+'\n')
            data['homepage_hash']=digest_bytes((working/'index.html').read_bytes())
            data.update(overview_hash=digest_bytes((issue/'index.html').read_bytes()),markdown_hash=digest_bytes((issue/'overview.md').read_bytes()))
            (issue/'release.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
            (working/'archive/index.html').write_text(reader_chrome(news.render_archive(),working).replace('Редакция 2.0','Редакция 4.3'))
            (working/'sitemap.xml').write_text(news.sitemap())
            if preserved_home is not None:(working/'index.html').write_bytes(preserved_home)
            validate(working,date)
        finally:news.ROOT=previous
        if not preview:
            (root/'issues').mkdir(exist_ok=True);(root/'archive').mkdir(exist_ok=True)
            shutil.move(str(issue),str(root/'issues'/date))
            illustration_dir=working/'assets/illustrations'/date
            if illustration_dir.is_dir():shutil.copytree(illustration_dir,root/'assets/illustrations'/date,dirs_exist_ok=True)
            for name in ('index.html','archive/index.html','sitemap.xml'):(root/name).write_bytes((working/name).read_bytes())
            if state.get('art_library44'):
                from scripts import art_library44
                art_library44.render(root,art_library44.load(root,state))
    return not preview


def public_light(state):
    result=[]
    for row in light43.ready(state):
        source=row['source']
        result.append({'kind':row.get('light_kind','unusual_fact'),'title':row['article']['title'],'text':' '.join(b['text'] for b in row['article']['blocks']),
            'source':{k:source.get(k,'') for k in ('url','title','publisher','language','published')}})
    return result


def render_light(items):
    if not items:return ''
    html='<section id="light-news" class="light-news" aria-labelledby="light-news-heading"><h2 id="light-news-heading">НЕ ВСЁ ТАК СЕРЬЁЗНО</h2><p>Маленькие новости, от которых мир становится интереснее</p><div class="light-grid">'
    for item in items:
        source=item['source'];url=source_links43.safe_source_url(source['url'])
        label={'source_report':'Из материалов источника','news':'Короткая новость','historical_fact':'Исторический факт','unusual_fact':'Необычный факт'}.get(item.get('kind'))
        label_html='<p class="meta light-kind">'+label+'</p>' if label else ''
        html+='<article class="light-item">'+label_html+'<h3>'+escape(item['title'])+'</h3><p>'+escape(item['text'])+'</p><p class="light-source">Источник: <a href="'+escape(url,quote=True)+'" target="_blank" rel="noopener noreferrer">'+escape(source['publisher'])+'</a>'
        if source.get('published'):html+=' · '+('Дата публикации: ' if item.get('kind')=='source_report' else '')+escape(source['published'])
        if item.get('kind')=='source_report':html+=' · Дата события не установлена'
        translated=source_links43.translation_url(url,source.get('language'))
        if translated:html+=' · <a href="'+escape(translated,quote=True)+'" target="_blank" rel="noopener noreferrer">На русском</a>'
        html+='</p></article>'
    return html+'</div></section>'


def refresh_home(root=None):
    root=Path(root or p.ROOT);page=(root/'index.html').read_text()
    found=re.search(r'data-issue-date="(\d{4}-\d{2}-\d{2})"',page)
    if not found:return False,None
    date=found[1];validate(root,date);data=metadata(root,date)
    overview=(root/'issues'/date/'index.html').read_text()
    target=layout43.homepage(overview,date)
    if digest_bytes(page.encode())!=data['homepage_hash'] and page not in (target,layout43.legacy_homepage(overview,date)):raise p.Blocked('PUBLIC_HOME_CHANGED')
    if page==target:return False,date
    (root/'index.html').write_text(target);return True,date


if __name__=='__main__':
    import argparse,os
    parser=argparse.ArgumentParser();parser.add_argument('--refresh-home',action='store_true',required=True);parser.parse_args()
    changed,date=refresh_home()
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:out.write('ready='+str(changed).lower()+'\nissue_date='+str(date or '')+'\n')
    print('[home43] '+json.dumps({'changed':changed,'date':date,'archives_unchanged':True}))


def without_art44(page):
    page=re.sub(r'<figure class="article-art44">.*?</figure>','',page,flags=re.S)
    return page.replace('<link rel="stylesheet" href="/assets/mosaic.css">','')


def backfill_issue_art(root,date,parent,persist=lambda:None,allow_request=True,repair_legacy_images=False):
    """Owner-authorized artwork-only transaction on one verified public issue."""
    from scripts import mosaic44
    root=Path(root)
    allowed=date in ('2026-11-20','2026-11-21') or date>=mosaic44.CONFIG.get('first_automatic_issue','9999-12-31')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) or not allowed:raise p.Blocked('ART_BACKFILL_DATE_NOT_AUTHORIZED')
    data,rows=mosaic44.published_records(root,date,allow_missing_art=True)
    sub=parent.setdefault('art44_backfills',{}).setdefault(date,{'date':date,'art44':{'objects':{},'history':[]}})
    legacy=None
    if repair_legacy_images:
        config=mosaic44.CONFIG['repair_legacy_art']
        if date!=config['date'] or data['number']!=29:raise p.Blocked('ART_REPAIR_SCOPE_INVALID')
        legacy=sub.setdefault('legacy_repair',{'images':{r['article_slug']:copy.deepcopy(r) for r in data['illustrations']},
            'markdown':{slug:digest_bytes((root/'issues'/date/'articles'/slug/'article.md').read_bytes()) for slug in data['pages']}})
        for slug,checksum in legacy['markdown'].items():
            if digest_bytes((root/'issues'/date/'articles'/slug/'article.md').read_bytes())!=checksum:raise p.Blocked('ART_REPAIR_TEXT_CHANGED')
        for slug,old in legacy['images'].items():
            if old['model']!=mosaic44.CONFIG['model']:
                current=next(r for r in data['illustrations'] if r['article_slug']==slug)
                if current['sha256']!=old['sha256'] or current['path']!=old['path']:raise p.Blocked('ART_REPAIR_PRESERVED_IMAGE_CHANGED')
        persist()
    items=mosaic44.article_plans(sub,rows)
    bindings={r['article_slug']:r for r in data.get('art44',{}).get('bindings',data.get('illustrations',[]))}
    for item,row in zip(items,rows):
        item['article_slug']=row['article']['slug']
        prior=bindings.get(row['article']['slug'])
        if prior:
            basis={k:prior[k] for k in ('date','article_id','text_hash','prompt_version')}
            if basis['date']!=date or p.digest(basis)!=prior['key']:raise p.Blocked('ART_PUBLIC_BINDING_INVALID')
            repair=mosaic44.CONFIG.get('visual_brief_repairs',{}).get(prior['text_hash'],{})
            if repair_legacy_images and next((r for r in data['illustrations'] if r['article_slug']==item['article_slug']),{}).get('model')==mosaic44.CONFIG['model']:
                basis['prompt_version']=mosaic44.CONFIG['prompt_version'];item.update(basis,key=p.digest(basis),genre=prior['genre'])
                item['prompt']=mosaic44.prompt(item)
            elif prior.get('prompt_version')==repair.get('replace_prompt_version'):
                # Public reconstruction lacks the private record's mode/category metadata.
                # Bind the one-time visual correction to the validated original text identity.
                basis['prompt_version']=mosaic44.CONFIG['prompt_version']
                item.update(basis,key=p.digest(basis))
                item['descriptor']['visual_subject_en']=repair['scene_en']
                item['description_hash']=p.digest(item['descriptor'])
                item['prompt']=mosaic44.prompt(item)
            else:
                for k in ('key','date','article_id','text_hash','prompt_version','description_hash','genre','ratio','protocol'):item[k]=prior[k]
    sub['assembly_status44']='EDITORIAL_APPROVED'
    sub['art44']['approval']={'date':date,'manifest_hash':p.digest(data),'signature':p.digest([{'id':r['id'],'article':mosaic44.final_text(r['article'])} for r in rows])}
    if mosaic44.CONFIG.get('references_enabled') and date>=mosaic44.CONFIG.get('first_reference_issue','9999-12-31'):
        from scripts import art_library44,news
        reference_state={'date':date,'issue_id':data.get('issue_id',date),'art_library44':parent.setdefault('art_library44',{})}
        budget=news.runtime.ACTIVE_BUDGET
        sets=art_library44.prepare_sets(root,reference_state,items,persist,discover=bool(allow_request and budget and budget.remaining_seconds()>180),number=data.get('number'))
        art_library44.attach(root,reference_state,items,sets);persist()
    prepared=items
    if repair_legacy_images:
        stage=mosaic44.CONFIG['repair_legacy_art']['stage']
        slugs=set(mosaic44.CONFIG['repair_legacy_art']['pilot_slugs']) if stage=='pilot' else set(legacy['images'])
        prepared=[i for i in items if i['article_slug'] in slugs and legacy['images'][i['article_slug']]['model']==mosaic44.CONFIG['model']]
    progress=mosaic44.prepare_items(sub,prepared,persist,allow_request)
    # Retain the complete plan for manifest assembly and idempotent future retries.
    sub['art44']['plan']=items
    if repair_legacy_images:
        from scripts import art_reference44,art_library44
        sub['_comparison_registry']=art_library44.load(root,reference_state)
        import os
        output=os.getenv('NEWS_ART_COMPARISON_DIR')
        if output:art_reference44.comparison(root,sub,items,legacy,output)
        sub.pop('_comparison_registry',None)
        targets=[i for i in items if legacy['images'][i['article_slug']]['model']==mosaic44.CONFIG['model']]
        completed=[i for i in targets if mosaic44.object_valid(sub['art44']['objects'].get(i['key'],{})) and sub['art44']['objects'][i['key']].get('reference_images_sent')==1]
        sub['legacy_repair_report']={'targets':len(targets),'ready':len(completed),'stage':stage,'pilot_ready':all(any(i['article_slug']==slug for i in completed) for slug in mosaic44.CONFIG['repair_legacy_art']['pilot_slugs'])}
        print('[art-legacy-repair] '+json.dumps(sub['legacy_repair_report']),flush=True);persist()
        if stage=='pilot' or len(completed)!=len(targets):
            parent['art44_backfill_status']={'date':date,**progress,**sub['legacy_repair_report']};persist();return False
    parent['art44_backfill_status']={'date':date,**progress};persist()
    articles=[r['article'] for r in rows]
    before={slug:(root/'issues'/date/'articles'/slug/'index.html').read_text() for slug in data['pages']}
    # Work in a private temporary tree. Commit only after the complete issue validates.
    with tempfile.TemporaryDirectory(prefix='387-art-backfill-') as temp:
        work=Path(temp)
        for name in ('assets','issues','archive','art'):
            if (root/name).is_dir():shutil.copytree(root/name,work/name)
        (work/'index.html').write_bytes((root/'index.html').read_bytes())
        images=mosaic44.materialize(sub,articles,work,items)
        bound={r.get('article_slug'):r for r in images.values() if r.get('protocol')==2}
        if not bound:return False
        updated=copy.deepcopy(data);updated['illustrations']=list(images.values());updated['mosaic_revision']=2
        updated['art44']={'status':'COMPLETE' if len(bound)==len(rows) else 'ARTWORK_INCOMPLETE','required':len(rows),'ready':len(bound),'missing':len(rows)-len(bound),'emergency_text':len(bound)!=len(rows),'provider_status':mosaic44.provider_status()}
        updated['art44']['bindings']=[{**{k:item[k] for k in ('key','date','article_id','text_hash','prompt_version','description_hash','genre','ratio','protocol')},'article_slug':a['slug']} for item,a in zip(items,articles)]
        for slug,page in before.items():
            art=bound.get(slug)
            if not art:
                changed=without_art44(page)
                (work/'issues'/date/'articles'/slug/'index.html').write_text(changed)
                updated['pages'][slug]['html']=digest_bytes(changed.encode())
                continue
            base=without_art44(page)
            figure='<figure class="article-art44"><img src="/'+escape(art['path'],quote=True)+'" width="'+str(art['width'])+'" height="'+str(art['height'])+'" alt="'+escape('Художественная иллюстрация: '+next(a['title'] for a in articles if a['slug']==slug),quote=True)+'" decoding="async"><figcaption>Художественная иллюстрация, созданная ИИ · '+escape(art['genre'])+'</figcaption></figure>'
            changed=base.replace('</head>','<link rel="stylesheet" href="/assets/mosaic.css"></head>',1).replace('<div class="article-body">',figure+'<div class="article-body">',1)
            if without_art44(changed)!=without_art44(page):raise p.Blocked('ART_BACKFILL_CONTENT_CHANGED')
            file=work/'issues'/date/'articles'/slug/'index.html';file.write_text(changed)
            updated['pages'][slug]['html']=digest_bytes(changed.encode())
        overview=(root/'issues'/date/'index.html').read_text()
        front=mosaic44.render(articles,date,work)
        if 'class="art-front"' in overview:
            overview=re.sub(r'<section class="art-front".*?</section>(?:<script src="/assets/mosaic.js" defer></script>)?',lambda _:front,overview,count=1,flags=re.S)
        else:
            overview=re.sub(r'<section class="front-grid">.*?</section>',lambda _:front,overview,count=1,flags=re.S)
        if '/assets/mosaic.css' not in overview:overview=overview.replace('</head>','<link rel="stylesheet" href="/assets/mosaic.css"></head>',1)
        (work/'issues'/date/'index.html').write_text(overview);updated['overview_hash']=digest_bytes(overview.encode())
        projected=layout43.homepage(overview,date);updated['homepage_hash']=digest_bytes(projected.encode())
        if 'data-issue-date="'+date+'"' in (root/'index.html').read_text():(work/'index.html').write_text(projected)
        (work/'issues'/date/'release.json').write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n')
        validate(work,date)
        changed=any((work/'issues'/date/f).read_bytes()!=(root/'issues'/date/f).read_bytes() for f in ('index.html','release.json'))
        changed=changed or any((work/'issues'/date/'articles'/slug/'index.html').read_text()!=page for slug,page in before.items())
        changed=changed or any(not (root/image['path']).is_file() or (root/image['path']).read_bytes()!=(work/image['path']).read_bytes() for image in images.values())
        if changed:
            shutil.copytree(work/'issues'/date,root/'issues'/date,dirs_exist_ok=True)
            shutil.copytree(work/'assets/illustrations'/date,root/'assets/illustrations'/date,dirs_exist_ok=True)
            (root/'index.html').write_bytes((work/'index.html').read_bytes())
    print('[art-backfill44] '+json.dumps({'date':date,'images':len(bound),'articles':len(rows),'complete':len(bound)==len(rows),'changed':changed,'article_text_unchanged':True,'other_archives_unchanged':True}),flush=True)
    return changed
