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
        return response.read(2_000_001).decode('utf-8')


def check_site(base='https://387.su', expected_date=None):
    if urlparse(base).scheme != 'https':
        raise RuntimeError('Public health check requires verified HTTPS')
    base = base.rstrip('/')
    home = fetch(base+'/')
    links = set(re.findall(r'/issues/(\d{4}-\d{2}-\d{2})/articles/([a-z0-9-]+)/',home))
    if not links:
        raise RuntimeError('Homepage has no complete issue article links')
    date = max(d for d,_ in links)
    if expected_date and date != expected_date:
        raise RuntimeError(f'Expected issue {expected_date}; public homepage still shows {date}')
    slugs = sorted(slug for d,slug in links if d == date)
    if expected_date and len(slugs) != 8:
        raise RuntimeError(f'Expected eight public articles, found {len(slugs)}')
    fetch(base+'/archive/')
    fetch(f'{base}/issues/{date}/')
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

if __name__=='__main__': main()
