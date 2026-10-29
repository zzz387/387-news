"""Public-only site packaging and HTTPS monitoring; never loads private drafts."""
from __future__ import annotations
import argparse
from datetime import datetime
from html import unescape
import json
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
try:
    from scripts import news
except ImportError:
    import news

PUBLIC_DIRS = ('assets','archive','issues')
PUBLIC_FILES = ('index.html','CNAME','robots.txt','sitemap.xml')
PRIVATE_SUFFIXES = {'.enc','.pem','.key','.env'}


def package(root, destination):
    root = Path(root); destination = Path(destination)
    if destination.exists():
        raise RuntimeError('Public package destination already exists')
    destination.mkdir(parents=True)
    for name in PUBLIC_DIRS:
        source = root/name
        if source.is_dir():
            for file in source.rglob('*'):
                if file.is_symlink() or file.suffix in PRIVATE_SUFFIXES or file.name.startswith('.'):
                    raise RuntimeError('Unexpected private or linked file in the public tree')
            shutil.copytree(source,destination/name)
    for name in PUBLIC_FILES:
        if (root/name).is_file():
            shutil.copyfile(root/name,destination/name)
    previous = news.ROOT
    try:
        news.ROOT = destination
        news.validate_local_links(list(destination.rglob('*.html')))
    finally:
        news.ROOT = previous
    return destination


def fetch(url):
    request = Request(url,headers={'User-Agent':'387-News-Public-Health/1.0'})
    with urlopen(request,timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f'Public URL returned HTTP {response.status}')
        # A technical transfer ceiling must fail closed, never validate a clipped page.
        try:
            from scripts import policy41
        except ImportError: import policy41
        limit=policy41.CONFIG['technical']['source_byte_limit']
        data=response.read(limit+1)
        if len(data)>limit: raise RuntimeError('Public page transport limit exceeded; no truncation allowed')
        return data.decode('utf-8')


def check_site(base='https://387.su', expected_date=None):
    if urlparse(base).scheme != 'https':
        raise RuntimeError('Public health check requires verified HTTPS')
    base = base.rstrip('/')
    home = fetch(base+'/')
    if 'data-policy-version="4.3"' in home:
        return check_v43(base,home,expected_date)
    links = set(re.findall(r"href=[\"']/?issues/(\d{4}-\d{2}-\d{2})/articles/([a-z0-9-]+)/",home))
    if not links:
        raise RuntimeError('Homepage has no complete issue article links')
    date = max(d for d,_ in links)
    if expected_date and date != expected_date:
        raise RuntimeError(f'Expected issue {expected_date}; public homepage still shows {date}')
    slugs = sorted(slug for d,slug in links if d == date)
    archive=fetch(base+'/archive/')
    overview=fetch(f'{base}/issues/{date}/')
    if 'data-policy-version="4.1"' in overview:
        try: from scripts import policy41, publication41
        except ImportError:
            import policy41
            import publication41
        if len(slugs)!=policy41.ARTICLE_COUNT or f'/issues/{date}/' not in archive:
            raise RuntimeError('Public v4.1 issue is incomplete')
        for slug in slugs: publication41.validate_page(fetch(f'{base}/issues/{date}/articles/{slug}/'))
        return {'https':'verified','issue_date':date,'articles':len(slugs),'expected_date':expected_date,'policy_version':'4.1','status':'ok'}
    if expected_date and len(slugs)!=8: # published v31 compatibility, never a v4.1 production gate
        raise RuntimeError(f'Expected historical article count, found {len(slugs)}')
    issue = json.loads(fetch(f'{base}/issues/{date}/issue.json')) if expected_date else None
    if issue and (issue['date'] != date or len(issue['articles']) != 8):
        raise RuntimeError('Public release manifest is incomplete')
    if issue:
        if not 2 <= sum(bool(a.get('long')) for a in issue['articles']) <= 3:
            raise RuntimeError('Public issue has an invalid feature count')
        if sum(a['word_count'] for a in issue['articles']) < 5000:
            raise RuntimeError('Public issue is below the required total volume')
        if any(a['word_count'] < (1050 if a.get('long') else 440) or a['word_count'] > 2200 for a in issue['articles']):
            raise RuntimeError('Public article volume is outside editorial limits')
    lookup = {a['slug']:a for a in issue['articles']} if issue else {}
    for slug in slugs:
        page = fetch(f'{base}/issues/{date}/articles/{slug}/')
        if '<meta name="viewport"' not in page or 'article-body' not in page:
            raise RuntimeError('Public article lost responsive layout or full body')
        if issue:
            body = re.search(r'<div class="article-body">(.*?)</div>',page,re.S)
            paragraphs = re.findall(r'<p>(.*?)</p>',body.group(1) if body else '',re.S)
            text = unescape(' '.join(re.sub('<[^>]+>','',p) for p in paragraphs))
            if news.count_words(text) != lookup[slug]['word_count']:
                raise RuntimeError('Public article is truncated or mismatches the approved manifest')
    return {'https':'verified','issue_date':date,'articles':len(slugs),'expected_date':expected_date,'status':'ok'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--package', type=Path)
    parser.add_argument('--expected-date')
    parser.add_argument('--base',default='https://387.su')
    parser.add_argument('--attempts',type=int,default=3)
    args=parser.parse_args()
    if args.expected_date:
        datetime.strptime(args.expected_date,'%Y-%m-%d')
    if args.package:
        package(news.ROOT,args.package)
        print('[public-package] only published site files included; links validated')
        return
    for attempt in range(max(1,min(args.attempts,5))):
        try:
            result=check_site(args.base,args.expected_date)
            print(json.dumps(result,ensure_ascii=False))
            return
        except Exception as exc:
            print(f'[public-health] attempt={attempt+1}: {type(exc).__name__}: {exc}',file=sys.stderr)
            if attempt+1 < max(1,min(args.attempts,5)):
                time.sleep(15)
    raise RuntimeError('Public HTTPS/issue verification failed; existing site was not modified')



def validate_local_release(root, date):
    """Validate the immutable public archive without opening a private checkpoint."""
    root=Path(root)
    if (root/'issues'/date/'release.json').is_file():
        try: from scripts import publication43
        except ImportError: import publication43
        return publication43.validate(root,date)
    if (root/'issues'/date/'index.html').is_file() and 'data-policy-version="4.1"' in (root/'issues'/date/'index.html').read_text(encoding='utf-8'):
        try: from scripts import publication41
        except ImportError: import publication41
        return publication41.validate_local_release(root,date)
    issue=json.loads((root/'issues'/date/'issue.json').read_text(encoding='utf-8'))
    if issue.get('date')!=date or len(issue.get('articles',[]))!=8:
        raise RuntimeError('Public archive date or article count mismatch')
    articles=issue['articles']
    if (len({a['slug'] for a in articles})!=8
            or not 2<=sum(bool(a.get('long')) for a in articles)<=3
            or sum(a['word_count'] for a in articles)<5000
            or any(not (1050 if a.get('long') else 440)<=a['word_count']<=2200 for a in articles)):
        raise RuntimeError('Public archive fails editorial volume requirements')
    files=[]
    for article in articles:
        path=root/'issues'/date/'articles'/article['slug']/'index.html'
        page=path.read_text(encoding='utf-8'); files.append(path)
        body=re.search(r'<div class="article-body">(.*?)</div>',page,re.S)
        paragraphs=re.findall(r'<p>(.*?)</p>',body.group(1) if body else '',re.S)
        text=unescape(' '.join(re.sub('<[^>]+>','',p) for p in paragraphs))
        if '<meta name="viewport"' not in page or news.count_words(text)!=article['word_count']:
            raise RuntimeError('Public archive contains truncated or invalid article HTML')
    overview=root/'issues'/date/'index.html'; files.extend([overview,root/'index.html',root/'archive/index.html'])
    if f'/issues/{date}/' not in (root/'archive/index.html').read_text(encoding='utf-8'):
        raise RuntimeError('Public archive index has no link to the issue')
    previous=news.ROOT
    try:
        news.ROOT=root
        news.validate_local_links(files)
    finally:
        news.ROOT=previous
    return issue


def check_v43(base,home,expected_date=None):
    try:from scripts import publication43,publication41
    except ImportError:import publication43,publication41
    found=re.search(r'data-issue-date="(\d{4}-\d{2}-\d{2})"',home)
    if not found:raise RuntimeError('PUBLIC_DATE_MISSING')
    date=found[1]
    if expected_date and date!=expected_date:raise RuntimeError('PUBLIC_DATE_MISMATCH')
    data=json.loads(fetch(base+'/issues/'+date+'/release.json'))
    if data.get('date')!=date or data.get('policy_version')!='4.3':raise RuntimeError('PUBLIC_METADATA_INVALID')
    if publication43.digest_bytes(home.encode())!=data.get('homepage_hash'):raise RuntimeError('PUBLIC_HOME_CHANGED')
    count=data.get('article_count');pages=data.get('pages',{})
    if type(count) is not int or count<0 or len(pages)!=count:raise RuntimeError('PUBLIC_COUNT_INVALID')
    overview=fetch(base+'/issues/'+date+'/')
    if publication43.digest_bytes(overview.encode())!=data.get('overview_hash'):raise RuntimeError('PUBLIC_OVERVIEW_CHANGED')
    markdown=fetch(base+'/issues/'+date+'/overview.md')
    if publication43.digest_bytes(markdown.encode())!=data.get('markdown_hash'):raise RuntimeError('PUBLIC_MARKDOWN_CHANGED')
    if '/issues/'+date+'/' not in fetch(base+'/archive/'):raise RuntimeError('PUBLIC_ARCHIVE_LINK_MISSING')
    slugs=set(re.findall(r'href="/issues/'+re.escape(date)+r'/articles/([a-z0-9-]+)/"',home))
    if slugs!=set(pages):raise RuntimeError('PUBLIC_LINK_COUNT_MISMATCH')
    if count==0:
        if data.get('kind')!='source_digest' or not data.get('sources') or 'Обзор источников' not in overview:raise RuntimeError('EMPTY_OR_MISLABELLED_RESERVE')
        for row in data['sources']:
            try:from scripts import source41
            except ImportError:import source41
            source41.safe_url(row['url'])
            if not all(row.get(k) for k in ('title','publisher','checked_at')) or row['url'] not in unescape(overview):raise RuntimeError('PUBLIC_RESERVE_INVALID')
    elif data.get('kind')!='articles':raise RuntimeError('PUBLIC_KIND_MISMATCH')
    for slug,hashes in pages.items():
        if not re.fullmatch(r'[a-z0-9-]+',slug):raise RuntimeError('PUBLIC_SLUG_INVALID')
        page=fetch(base+'/issues/'+date+'/articles/'+slug+'/')
        md=fetch(base+'/issues/'+date+'/articles/'+slug+'/article.md')
        if publication43.digest_bytes(page.encode())!=hashes['html'] or publication43.digest_bytes(md.encode())!=hashes['markdown']:raise RuntimeError('PUBLIC_CONTENT_CHANGED')
        publication41.source_links43.validate(page,required=data.get('source_links_version')==1)
        publication41.validate_page(page.replace('data-policy-version="4.3"','data-policy-version="4.1"',1))
    return {'https':'verified','issue_date':date,'articles':count,'kind':data['kind'],'policy_version':'4.3','expected_date':expected_date,'status':'ok'}


if __name__=='__main__': main()
