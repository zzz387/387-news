"""Reader-only v4.1 projection and atomic Git-release preparation."""
import copy
from html import escape
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime
try:
    from scripts import policy41 as policy, rights41, content41, editorial41, news
except ImportError:
    import policy41 as policy
    import rights41
    import content41
    import editorial41
    import news


def public_article(record):
    a=record['article']; source=record['source']
    editorial41.content.semantic_structure(a,source)
    rights41.require(source,a['mode'],record['rights'])
    return {**{k:copy.deepcopy(a.get(k,'')) for k in ('title','teaser','category','kind','mode','slug','blocks','activities')},
            'primary_source':{k:source[k] for k in ('url','title','publisher','author','published')},
            'attribution':copy.deepcopy(record['rights'].get('attribution',{})),
            'images':copy.deepcopy(record.get('images',[]))}


def images_valid(article,root):
    for image in article.get('images',[]):
        if rights41.image_decision(image)['status']!='allowed': raise policy.Blocked('IMAGE_RIGHTS_UNKNOWN')
        relative=Path(image.get('asset',''))
        if not relative.parts or relative.parts[0]!='assets' or '..' in relative.parts: raise policy.Blocked('IMAGE_ASSET_INVALID')
        path=root/relative
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=image.get('sha256'):
            raise policy.Blocked('IMAGE_BYTES_NOT_VERIFIED')


def source_block(article):
    s=article['primary_source']; mode=article['mode']
    prefix='Перевод. ' if mode=='FULL_TRANSLATION' else 'Самостоятельная статья на основе материалов. ' if mode=='INDEPENDENT_ARTICLE' else ''
    text=(f'<aside class="source-primary"><p>{prefix}Источник: {escape(s["publisher"])} — '
          f'<a href="{escape(s["url"],quote=True)}" rel="noopener noreferrer">«{escape(s["title"])}»</a>.</p>')
    attribution=article.get('attribution') or {}
    if attribution:
        text+='<p class="license-attribution">'+escape(attribution.get('author') or s['author'])
        if attribution.get('license_url'):
            text+=' · <a rel="license" href="'+escape(attribution['license_url'],quote=True)+'">'+escape(attribution.get('license','Лицензия'))+'</a>'
        text+='</p>'
    for image in article.get('images',[]):
        grant=rights41.image_decision(image)
        if grant.get('attribution'):
            text+='<p>'+escape(grant['attribution'])+'</p>'
    return text+'</aside>'



def render_blocks(article):
    out=[]; stack=[]
    def close_one():
        row=stack.pop()
        if row['item_open']: out.append('</li>')
        out.append('</'+row['kind']+'>')
    for block in article['blocks']:
        if block['kind']=='title' and block['text']==article['title']: continue
        kind=block.get('list_kind')
        if kind in ('ol','ul'):
            depth=max(1,int(block.get('list_depth',1))); group=block.get('list_group')
            while len(stack)>depth: close_one()
            if stack and len(stack)==depth and (stack[-1]['kind']!=kind or stack[-1]['group']!=group): close_one()
            while len(stack)<depth:
                if stack and not stack[-1]['item_open']:
                    out.append('<li>'); stack[-1]['item_open']=True
                index=int(block.get('list_index',1))
                out.append('<'+kind+(' start="'+str(index)+'"' if kind=='ol' else '')+'>')
                stack.append({'kind':kind,'group':group,'item_open':False,'index':None,'next':index})
            current=stack[-1]; index=int(block.get('list_index',1))
            if current['item_open'] and current['index']==index:
                out.append('<p>'+escape(block['text'])+'</p>'); continue
            if current['item_open']: out.append('</li>')
            value=' value="'+str(index)+'"' if kind=='ol' and index!=current['next'] else ''
            out.append('<li'+value+'>'+escape(block['text']))
            current.update(item_open=True,index=index,next=index+1)
        else:
            while stack: close_one()
            tag=('h'+str(min(6,max(2,int(block.get('heading_level',2)))))) if block['kind'] in ('heading','title') else 'blockquote' if block['kind']=='quote' else 'p'
            out.append('<'+tag+'>'+escape(block['text'])+'</'+tag+'>')
    while stack: close_one()
    return ''.join(out)


def render_article(date,no,article,root,*,moment=None):
    images_valid(article,root)
    moment=moment or datetime.fromisoformat(date+'T'+policy.RELEASE_TIME).replace(tzinfo=policy.TZ)
    link=f'/issues/{date}/articles/{article["slug"]}/'
    author=(article['primary_source']['author'] or article['primary_source']['publisher']+' · автор не указан') if article['mode']!='INDEPENDENT_ARTICLE' else 'Редакция 387 News'
    out=[news.page_header(article['title'],article['teaser'],link,moment,no).replace('Редакция 2.0','Редакция 4.1'),
         '<main class="wrap"><article class="article-shell" data-policy-version="4.1">',
         '<div class="meta">'+escape(article['category'])+' · '+escape(article['kind'])+'</div>',
         '<h1>'+escape(article['title'])+'</h1>']
    if article['teaser']: out.append('<p class="dek">'+escape(article['teaser'])+'</p>')
    out.append('<div class="byline">'+escape(author)+' · '+date+'</div>')
    for image in article.get('images',[]):
        out.append('<img class="heroimg" src="/'+escape(image['asset'],quote=True)+'" alt="'+escape(image.get('alt',''),quote=True)+'">')
    out.append('<div class="article-body">')
    out.append(render_blocks(article))
    if article['activities']:
        out.append('<ol class="practical-activities">')
        for activity in article['activities']:
            out.extend(['<li><h2>'+escape(activity['title'])+'</h2>',
                '<p><strong>Возраст и предпосылки:</strong> '+escape(activity['age'])+'</p>',
                '<p><strong>Материалы:</strong> '+escape(', '.join(activity['materials']))+'</p>',
                '<ol>'+''.join('<li>'+escape(step)+'</li>' for step in activity['steps'])+'</ol>',
                '<p><strong>Смысл занятия:</strong> '+escape(activity['benefit'])+'</p>',
                '<p><strong>Безопасность:</strong> '+escape(activity['safety'])+'</p></li>'])
        out.append('</ol>')
    out.extend(['</div>',source_block(article),'</article>',f'<div class="after-article"><a href="/issues/{date}/">← Все статьи номера</a></div></main>',news.page_footer()])
    return ''.join(out)


def render_overview(date,no,articles,permanent=False):
    moment=datetime.fromisoformat(date+'T'+policy.RELEASE_TIME).replace(tzinfo=policy.TZ)
    title=f'Выпуск № {no:03d} · {date}'
    out=[news.page_header(title,'Двенадцать законченных статей 387 News',f'/issues/{date}/' if permanent else '/',moment,no).replace('Редакция 2.0','Редакция 4.1'),
        f'<main class="wrap" data-policy-version="4.1" data-issue-date="{date}" data-issue-number="{no}" data-article-count="{len(articles)}">',
        '<section class="front-intro"><div><h1>Обзор номера</h1><p>Истории, знания и практические открытия. Все статьи доступны целиком.</p></div></section>',
        '<section class="front-grid">']
    for i,a in enumerate(articles[:2]):
        out.append(f'<article class="{"lead" if i==0 else "mid"}"><div class="meta">{escape(a["category"])}</div><h2><a href="/issues/{date}/articles/{a["slug"]}/">{escape(a["title"])}</a></h2><p>{escape(a["teaser"])}</p></article>')
    out.append('</section><section id="contents"><div class="all-top"><h2>В этом выпуске · '+str(len(articles))+' статей</h2></div><div class="contents">')
    anchors=set()
    for i,a in enumerate(articles,1):
        anchor={'Семья':'family','Москва и путешествия':'moscow','Здоровье и движение':'health'}.get(a['category'],a['slug'])
        if anchor in anchors: anchor=a['slug']
        anchors.add(anchor)
        out.append(f'<article class="toc" id="{anchor}"><span class="toc-num">{i:02d}</span><div><div class="meta">{escape(a["category"])}</div><h3><a href="/issues/{date}/articles/{a["slug"]}/">{escape(a["title"])}</a></h3><p>{escape(a["teaser"])}</p></div></article>')
    out.append('</div></section></main>'+news.page_footer())
    return ''.join(out)


def markdown(article):
    out=['# '+article['title'],'']
    for block in article['blocks']:
        if block['kind']=='title' and block['text']==article['title']: continue
        prefix=('#'*min(6,max(2,int(block.get('heading_level',2))))+' ') if block['kind'] in ('heading','title') else (str(block['list_index'])+'. ' if block.get('list_kind')=='ol' else '- ' if block.get('list_kind')=='ul' else '')
        indentation='  '*max(0,int(block.get('list_depth',1))-1) if block.get('list_kind') else ''
        out.extend([indentation+prefix+block['text'],''])
    for item in article['activities']:
        out.extend(['## '+item['title'],'','Возраст и предпосылки: '+item['age'],'Материалы: '+', '.join(item['materials']),''])
        out.extend(f'{i}. {step}' for i,step in enumerate(item['steps'],1))
        out.extend(['','Смысл: '+item['benefit'],'Безопасность: '+item['safety'],''])
    source=article['primary_source']
    prefix='Перевод. ' if article['mode']=='FULL_TRANSLATION' else 'Самостоятельная статья на основе материалов. ' if article['mode']=='INDEPENDENT_ARTICLE' else ''
    out.append(prefix+'Источник: '+source['publisher']+' — ['+source['title']+']('+source['url']+').')
    att=article.get('attribution') or {}
    if att: out.append((att.get('author') or source['author'])+' · '+att.get('license','')+' '+att.get('license_url',''))
    return '\n'.join(out)+'\n'


def issue_metadata(path):
    text=Path(path).read_text(encoding='utf-8')
    def value(key):
        found=re.search(r'\b'+key+r'="([^"]+)"',text)
        return found.group(1) if found else None
    if value('data-policy-version')!=policy.VERSION: return None
    return {'date':value('data-issue-date'),'number':int(value('data-issue-number')),
            'count':int(value('data-article-count')),'policy_version':policy.VERSION,
            'title':next(iter(re.findall(r'<h[23]><a[^>]+>(.*?)</a>',text,re.S)),'387 News')}


def build(state,root,preview=False):
    editorial41.validate_issue(state)
    root=Path(root); date=state['date']; records={r['id']:r for r in state['candidates']}
    articles=[]
    for i,identity in enumerate(state['selected_ids'],1):
        article=public_article(records[identity]); article['slug']=news.slugify(article['title'],i); articles.append(article)
    existing=root/'issues'/date
    if existing.exists():
        meta=issue_metadata(existing/'index.html')
        if not meta: raise policy.Blocked('ARCHIVE_POLICY_MISMATCH')
        for article in articles:
            path=existing/'articles'/article['slug']/'index.html'
            if path.read_text()!=render_article(date,meta['number'],article,root): raise policy.Blocked('IMMUTABLE_ARCHIVE_CHANGED')
        return False if preview else True
    # Work only in a private temporary tree; no output is committed until every page passes.
    with tempfile.TemporaryDirectory(prefix='387-v41-build-') as directory:
        working=Path(directory)
        for name in ('assets','archive','issues'):
            if (root/name).is_dir(): shutil.copytree(root/name,working/name)
        previous=news.ROOT; news.ROOT=working
        try:
            no=news.get_next_number(); issue=working/'issues'/date; issue.mkdir(parents=True)
            files=[]
            for article in articles:
                path=issue/'articles'/article['slug']/'index.html'; path.parent.mkdir(parents=True)
                path.write_text(render_article(date,no,article,root),encoding='utf-8'); files.append(path)
                path.with_name('article.md').write_text(markdown(article),encoding='utf-8')
            (issue/'index.html').write_text(render_overview(date,no,articles,True),encoding='utf-8')
            (working/'index.html').write_text(render_overview(date,no,articles),encoding='utf-8')
            (working/'archive/index.html').write_text(news.render_archive(),encoding='utf-8')
            (working/'sitemap.xml').write_text(news.sitemap(),encoding='utf-8')
            files.extend([issue/'index.html',working/'index.html',working/'archive/index.html'])
            news.validate_local_links(files)
            validate_local_release(working,date)
        finally: news.ROOT=previous
        if not preview:
            shutil.move(str(issue),str(root/'issues'/date))
            for name in ('index.html','archive/index.html','sitemap.xml'):
                (root/name).write_bytes((working/name).read_bytes())
    return not preview


def validate_page(page):
    if 'data-policy-version="4.1"' not in page or not page.rstrip().endswith('</html>'):
        raise policy.Blocked('PUBLIC_HTML_INCOMPLETE')
    if len(re.findall(r'class="source-primary"',page))!=1: raise policy.Blocked('PUBLIC_SOURCE_BLOCK_COUNT')
    if any(marker in page for marker in ('_quota_snapshot','source_ids','exact_quote','fact_checked','word_count','character_count','Источники и проверка')):
        raise policy.Blocked('INTERNAL_DATA_IN_PUBLIC_PAGE')
    before=page.split('<aside class="source-primary">')[0]
    body=re.search(r'<div class="article-body">(.*)</div>$',before,re.S)
    if not body or not re.sub('<[^>]+>','',body.group(1)).strip(): raise policy.Blocked('PUBLIC_BODY_EMPTY')
    if re.search(r'<a\b|https?://',body.group(1),re.I): raise policy.Blocked('INTERNAL_LINK_IN_BODY')
    return True


def validate_local_release(root,date):
    root=Path(root); meta=issue_metadata(root/'issues'/date/'index.html')
    if not meta or meta['date']!=date or meta['count']!=policy.ARTICLE_COUNT: raise policy.Blocked('TWELVE_READY_ARTICLES_REQUIRED')
    pages=list((root/'issues'/date/'articles').glob('*/index.html'))
    if len(pages)!=policy.ARTICLE_COUNT: raise policy.Blocked('PUBLIC_ARTICLE_COUNT')
    for path in pages: validate_page(path.read_text(encoding='utf-8'))
    if (root/'issues'/date/'issue.json').exists(): raise policy.Blocked('SERVICE_JSON_IN_NEW_ISSUE')
    previous=news.ROOT
    try:
        news.ROOT=root
        news.validate_local_links(pages+[root/'issues'/date/'index.html',root/'archive/index.html',root/'index.html'])
    finally: news.ROOT=previous
    return meta
