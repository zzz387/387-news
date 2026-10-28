"""Only the authorized eight-article 003-R projection; never replaces the front page."""
from datetime import datetime
from html import escape
import re
from pathlib import Path
import shutil
import tempfile
try:
    from scripts import special_contract41 as sc,policy41 as p,publication41 as pub,editorial41 as e,news
except ImportError:
    import special_contract41 as sc
    import policy41 as p
    import publication41 as pub
    import editorial41 as e
    import news


def metadata(path):
    text=Path(path).read_text(encoding='utf-8')
    if 'data-special-edition="003-R"' not in text:return None
    def value(key):
        found=re.search(r'\b'+key+r'="([^"]+)"',text)
        if not found:raise p.Blocked('SPECIAL_PUBLIC_METADATA_MISSING')
        return found[1]
    if Path(path).parent.name!=sc.SLUG or value('data-article-count')!='8' or value('data-policy-version') not in ('4.1','4.3'):
        raise p.Blocked('SPECIAL_PUBLIC_CONTRACT_INVALID')
    moment=datetime.fromisoformat(value('data-published-at'))
    if moment.tzinfo is None:raise p.Blocked('SPECIAL_PUBLIC_DATE_INVALID')
    return {'id':sc.ID,'slug':sc.SLUG,'published_at':moment.isoformat(),'date':moment.astimezone(p.TZ).date().isoformat(),'count':8,'policy_version':value('data-policy-version')}


def archive_cards(root):
    path=Path(root)/'issues'/sc.SLUG/'index.html'
    if not path.is_file():return ''
    meta=metadata(path)
    if not meta:raise p.Blocked('SPECIAL_PUBLIC_CONTRACT_INVALID')
    return ('<section class="special-editions"><h2>Специальные выпуски</h2><div class="archive-card"><div>'
        '<div class="meta">№003-R · '+meta['date']+'</div><h2><a href="/issues/'+sc.SLUG+'/">'
        'Внеочередное переиздание от 26 октября 2026 года</a></h2><p>8 материалов · редакция'+meta['policy_version']+'</p></div>'
        '<a href="/issues/'+sc.SLUG+'/">Читать переиздание →</a></div></section>')


def sitemap_urls(root):
    path=Path(root)/'issues'/sc.SLUG/'index.html'
    if not path.is_file():return []
    if not metadata(path):raise p.Blocked('SPECIAL_PUBLIC_CONTRACT_INVALID')
    return ['/issues/'+sc.SLUG+'/']+['/issues/'+sc.SLUG+'/articles/'+x.parent.name+'/'
        for x in sorted((path.parent/'articles').glob('*/index.html'))]


def validate(root):
    root=Path(root);path=root/'issues'/sc.SLUG/'index.html';meta=metadata(path)
    if not meta:raise p.Blocked('SPECIAL_PUBLIC_CONTRACT_INVALID')
    pages=list((path.parent/'articles').glob('*/index.html'))
    if len(pages)!=8:raise p.Blocked('SPECIAL_EIGHT_PUBLIC_PAGES_REQUIRED')
    for page in pages:pub.validate_page(page.read_text().replace('data-policy-version="4.3"','data-policy-version="4.1"',1))
    if any((path.parent/name).exists() for name in ('issue.json','dossier.json','news-draft.enc')):
        raise p.Blocked('SPECIAL_PRIVATE_DATA_IN_PUBLIC_TREE')
    previous=news.ROOT
    try:
        news.ROOT=root;news.validate_local_links(pages+[path,root/'archive/index.html',root/'index.html'])
    finally:news.ROOT=previous
    return meta


def build(state,root):
    if not sc.is_special(state):raise p.Blocked('SPECIAL_STATE_REQUIRED')
    version=state.get('policy_version','4.1')
    if version=='4.3':
        from scripts import special43,publication43
        special43.validate_ready(state)
    else:e.validate_issue(state)
    root=Path(root);sc.check_original(root)
    if not state.get('published_at'):state['published_at']=datetime.now(p.TZ).isoformat()
    moment=datetime.fromisoformat(state['published_at']).astimezone(p.TZ);date=moment.date().isoformat();clock=moment.strftime('%H:%M')+' МСК'
    records={r['id']:r for r in state['candidates']}
    articles=[]
    for identity in state['selected_ids']:
        record=records[identity];a=(publication43.public_article(record) if version=='4.3' else pub.public_article(record));a['slug']='article-'+str(record['special_slot']).zfill(2);articles.append(a)
    with tempfile.TemporaryDirectory(prefix='387-special-final-') as temp:
        work=Path(temp)
        for name in ('issues','archive','assets'):shutil.copytree(root/name,work/name)
        shutil.copyfile(root/'index.html',work/'index.html')
        issue=work/'issues'/sc.SLUG
        existing=issue.exists()
        if existing:shutil.rmtree(issue)
        issue.mkdir()
        for article in articles:
            path=issue/'articles'/article['slug']/'index.html';path.parent.mkdir(parents=True)
            html=pub.render_article(date,3,article,root,moment=moment,policy_version=version).replace('/issues/'+date+'/', '/issues/'+sc.SLUG+'/')
            html=html.replace('№ 003','№003-R').replace('№003<','№003-R<')
            html=html.replace('<main class="wrap">','<main class="wrap"><p class="special-edition">387 News №003-R · переиздание от 26 октября 2026 · опубликовано '+date+' '+clock+'</p>',1)
            if version=='4.3':html=publication43.reader_chrome(html)
            path.write_text(html);path.with_name('article.md').write_text(pub.markdown(article))
        title='387 News №003-R — внеочередное переиздание от 26 октября 2026 года'
        html=news.page_header(title,'Восемь самостоятельных материалов по редакционной политике'+version,'/issues/'+sc.SLUG+'/',moment,3)
        html+='<main class="wrap" data-policy-version="'+version+'" data-special-edition="003-R" data-issue-number="3" data-article-count="8" data-published-at="'+escape(moment.isoformat(),quote=True)+'">'
        html+='<h1>'+title+'</h1><p>Опубликовано '+date+' в '+clock+'. <a href="/issues/2026-10-26/">Оригинальный выпуск№003</a></p><section class="contents">'
        for a in articles:html+='<article class="toc"><div><h2><a href="/issues/'+sc.SLUG+'/articles/'+a['slug']+'/">'+escape(a['title'])+'</a></h2><p>'+escape(a['teaser'])+'</p></div></article>'
        html+='</section><p><a href="/archive/">Все выпуски</a> · <a href="/">Текущая ежедневная газета</a></p></main>'+news.page_footer()
        if version=='4.3':html=publication43.reader_chrome(html).replace('Редакция 2.0','Редакция 4.3')
        (issue/'index.html').write_text(html)
        previous=news.ROOT
        try:
            news.ROOT=work
            archive=news.render_archive()
            if version=='4.3':archive=publication43.reader_chrome(archive).replace('Редакция 2.0','Редакция 4.3')
            (work/'archive/index.html').write_text(archive)
            (work/'sitemap.xml').write_text(news.sitemap())
        finally:news.ROOT=previous
        validate(work)
        if existing:
            old=root/'issues'/sc.SLUG
            wanted={p.relative_to(issue):p.read_bytes() for p in issue.rglob('*') if p.is_file()}
            actual={p.relative_to(old):p.read_bytes() for p in old.rglob('*') if p.is_file()}
            if wanted!=actual:raise p.Blocked('SPECIAL_IMMUTABLE_ARCHIVE_CHANGED')
            return False
        shutil.move(str(issue),str(root/'issues'/sc.SLUG))
        for name in ('archive/index.html','sitemap.xml'):(root/name).write_bytes((work/name).read_bytes())
    return True


def check_public(root=None,fetch=None):
    try:from scripts import site_checks
    except ImportError:import site_checks
    root=Path(root or p.ROOT);fetch=fetch or site_checks.fetch
    base='https://387.su/issues/'+sc.SLUG+'/'
    overview=fetch(base)
    if overview!=(root/'issues'/sc.SLUG/'index.html').read_text(encoding='utf-8'):
        raise p.Blocked('SPECIAL_HTTPS_OVERVIEW_VERSION_MISMATCH')
    if 'data-special-edition="003-R"' not in overview or 'data-article-count="8"' not in overview:
        raise p.Blocked('SPECIAL_HTTPS_OVERVIEW_INVALID')
    links=set(re.findall(r'href="(/issues/'+re.escape(sc.SLUG)+r'/articles/[^/]+/)"',overview))
    if len(links)!=8:raise p.Blocked('SPECIAL_HTTPS_INCOMPLETE')
    for link in links:
        page=fetch('https://387.su'+link);pub.validate_page(page.replace('data-policy-version="4.3"','data-policy-version="4.1"',1))
        if page!=(root/link.lstrip('/')/'index.html').read_text(encoding='utf-8'):
            raise p.Blocked('SPECIAL_HTTPS_ARTICLE_VERSION_MISMATCH')
    original=fetch('https://387.su/issues/'+sc.ORIGINAL+'/')
    if original!=(root/'issues'/sc.ORIGINAL/'index.html').read_text(encoding='utf-8'):
        raise p.Blocked('SPECIAL_ORIGINAL_HTTPS_CHANGED')
    if '/issues/'+sc.SLUG+'/' not in fetch('https://387.su/archive/'):
        raise p.Blocked('SPECIAL_HTTPS_ARCHIVE_MISSING')
    if 'data-special-edition="003-R"' in fetch('https://387.su/'):
        raise p.Blocked('SPECIAL_REPLACED_DAILY_HOMEPAGE')
    return {'id':sc.ID,'articles':8,'https':'verified','status':'PUBLISHED'}
