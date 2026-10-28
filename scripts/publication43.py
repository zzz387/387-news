"""Dynamic reader-only release, including a clearly labelled no-AI link digest."""
import copy,hashlib,json,re,shutil,tempfile
from datetime import datetime
from html import escape
from pathlib import Path
try:
    from scripts import policy41 as p,publication41 as render,editorial43 as e,rights41,news,source41
except ImportError:
    import policy41 as p,publication41 as render,editorial43 as e,rights41,news,source41


def digest_bytes(data):return hashlib.sha256(data).hexdigest()

def reader_chrome(page):
    return re.sub(r'(<nav class="topics wrap"[^>]*>).*?(</nav>)',r'\1<a href="/">Обзор номера</a><a href="/archive/">Архив</a>\2',page,count=1,flags=re.S)


def public_article(record):
    if not e.eligible(record):raise p.Blocked('ARTICLE_NOT_APPROVED')
    a=record['article'];source=record['source'];rights41.require(source,a['mode'],record['rights'])
    return {**{k:copy.deepcopy(a.get(k,'')) for k in ('title','teaser','category','kind','mode','slug','blocks','activities')},
        'primary_source':{k:source.get(k,'') for k in ('url','title','publisher','author','published')},
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
    if data.get('policy_version')!='4.3' or data.get('date')!=date:raise p.Blocked('PUBLIC_METADATA_INVALID')
    return data


def validate(root,date):
    root=Path(root);data=metadata(root,date);issue=root/'issues'/date
    count=data.get('article_count');kind=data.get('kind')
    if type(count) is not int or count<0:raise p.Blocked('PUBLIC_COUNT_INVALID')
    if kind not in ('articles','source_digest') or (count==0)!=(kind=='source_digest'):raise p.Blocked('PUBLIC_KIND_MISMATCH')
    pages=list((issue/'articles').glob('*/index.html'))
    if len(pages)!=count or len(data.get('pages',{}))!=count:raise p.Blocked('PUBLIC_ARTICLE_COUNT')
    for slug,hashes in data['pages'].items():
        if not re.fullmatch(r'[a-z0-9-]+',slug):raise p.Blocked('PUBLIC_SLUG_INVALID')
        file=issue/'articles'/slug/'index.html';md=file.with_name('article.md')
        if digest_bytes(file.read_bytes())!=hashes['html'] or digest_bytes(md.read_bytes())!=hashes['markdown']:raise p.Blocked('PUBLIC_CONTENT_CHANGED')
        render.validate_page(file.read_text().replace('data-policy-version="4.3"','data-policy-version="4.1"',1))
    for name,key in (('index.html','overview_hash'),('overview.md','markdown_hash')):
        if digest_bytes((issue/name).read_bytes())!=data[key]:raise p.Blocked('PUBLIC_OVERVIEW_CHANGED')
    page=(issue/'index.html').read_text()
    if f'data-article-count="{count}"' not in page or f'data-issue-date="{date}"' not in page:raise p.Blocked('PUBLIC_COUNT_INVALID')
    if count==0:
        rows=data.get('sources',[])
        if not rows or 'Обзор источников' not in page:raise p.Blocked('EMPTY_RESERVE')
        for row in rows:
            source41.safe_url(row['url'])
            if not all(row.get(k) for k in ('title','publisher','checked_at')) or escape(row['url'],quote=True) not in page:raise p.Blocked('PUBLIC_RESERVE_INVALID')
    if f'/issues/{date}/' not in (root/'archive/index.html').read_text():raise p.Blocked('ARCHIVE_LINK_MISSING')
    previous=news.ROOT
    try:
        news.ROOT=root;news.validate_local_links(pages+[issue/'index.html',root/'archive/index.html'])
    finally:news.ROOT=previous
    return data


def build(state,root,reserve=(),preview=False):
    root=Path(root);date=state['date'];existing=root/'issues'/date
    if existing.exists():
        try:from scripts import site_checks
        except ImportError:import site_checks
        site_checks.validate_local_release(root,date)
        return not preview
    records=e.select_ready(state);articles=[]
    for i,r in enumerate(records,1):
        a=public_article(r);a['slug']=news.slugify(a['title'],i);articles.append(a)
    if not articles and not reserve:raise p.Blocked('NO_SAFE_RESERVE')
    if (root/'issues').exists() and any(d.name>date for d in (root/'issues').iterdir() if re.fullmatch(r'\d{4}-\d{2}-\d{2}',d.name)):
        raise p.Blocked('BACKDATED_HOME_REPLACEMENT_FORBIDDEN')
    with tempfile.TemporaryDirectory(prefix='387-daily43-') as directory:
        working=Path(directory)
        for name in ('assets','archive','issues'):
            if (root/name).is_dir():shutil.copytree(root/name,working/name)
        (working/'archive').mkdir(exist_ok=True);(working/'issues').mkdir(exist_ok=True)
        previous=news.ROOT;news.ROOT=working
        try:
            no=news.get_next_number();issue=working/'issues'/date;issue.mkdir()
            data={'date':date,'number':no,'policy_version':'4.3','article_count':len(articles),
                  'kind':'articles' if articles else 'source_digest','pages':{},'published_at':datetime.now(p.TZ).isoformat()}
            for a in articles:
                file=issue/'articles'/a['slug']/'index.html';file.parent.mkdir(parents=True)
                file.write_text(reader_chrome(render.render_article(date,no,a,root,policy_version='4.3')))
                md=file.with_name('article.md');md.write_text(render.markdown(a))
                data['pages'][a['slug']]={'html':digest_bytes(file.read_bytes()),'markdown':digest_bytes(md.read_bytes())}
            rows=[{k:r.get(k,'') for k in ('url','title','publisher','published','checked_at')} for r in reserve] if not articles else []
            if not articles:data['sources']=rows
            for permanent,target in ((True,issue/'index.html'),(False,working/'index.html')):
                target.write_text(reader_chrome(render.render_overview(date,no,articles,permanent,policy_version='4.3')) if articles else overview(date,no,rows,permanent))
            markdown=('# Обзор источников\n\nПроверенные ссылки; не полноценные статьи. Без генерации Gemini.\n\n'+'\n'.join('- ['+r['title']+']('+r['url']+') — '+r['publisher']+'; '+(r.get('published') or 'дата не сохранена') for r in rows)) if not articles else '# Выпуск '+date+'\n\n'+'\n'.join('- ['+a['title']+'](/issues/'+date+'/articles/'+a['slug']+'/)' for a in articles)
            (issue/'overview.md').write_text(markdown+'\n')
            data['homepage_hash']=digest_bytes((working/'index.html').read_bytes())
            data.update(overview_hash=digest_bytes((issue/'index.html').read_bytes()),markdown_hash=digest_bytes((issue/'overview.md').read_bytes()))
            (issue/'release.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
            (working/'archive/index.html').write_text(news.render_archive())
            (working/'sitemap.xml').write_text(news.sitemap());validate(working,date)
        finally:news.ROOT=previous
        if not preview:
            (root/'issues').mkdir(exist_ok=True);(root/'archive').mkdir(exist_ok=True)
            shutil.move(str(issue),str(root/'issues'/date))
            for name in ('index.html','archive/index.html','sitemap.xml'):(root/name).write_bytes((working/name).read_bytes())
    return not preview
