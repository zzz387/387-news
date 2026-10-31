"""Rotating RSS/page discovery. Feed text is metadata, NEVER the original article."""
import json,re,time,traceback
from email.utils import parsedate_to_datetime
from datetime import datetime,timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse,urljoin
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET
try:from scripts import policy41 as p,source41,rights41,public_sources41
except ImportError:import policy41 as p,source41,rights41,public_sources41


def registry():return json.loads((p.ROOT/'config/publishers43.json').read_text())


def owned(url,row):
    host=(urlparse(url).hostname or '').removeprefix('www.');domain=row['domain'].removeprefix('www.')
    return host==domain or host.endswith('.'+domain)


def permitted_get(url,session):
    source41.safe_url(url);parts=urlparse(url);robots=parts.scheme+'://'+parts.netloc+'/robots.txt'
    try:text=session.transport(robots)
    except Exception as exc:
        if getattr(exc,'code',None)!=404:raise p.Blocked('ROBOTS_UNVERIFIED') from exc
        text=''
    parser=RobotFileParser();parser.parse(text.splitlines())
    if not parser.can_fetch('387News-Research',url):raise p.Blocked('ROBOTS_FORBIDDEN')
    raw=session.transport(url);resolved=getattr(raw,'resolved_url',url)
    if resolved!=url:
        target=urlparse(resolved);target_robots=target.scheme+'://'+target.netloc+'/robots.txt'
        try:content=session.transport(target_robots)
        except Exception as exc:
            if getattr(exc,'code',None)!=404:raise p.Blocked('ROBOTS_UNVERIFIED') from exc
            content=''
        other=RobotFileParser();other.parse(content.splitlines())
        if not other.can_fetch('387News-Research',resolved):raise p.Blocked('ROBOTS_FORBIDDEN')
    return raw


class Links(HTMLParser):
    def __init__(self,base):super().__init__();self.base=base;self.feeds=[];self.articles=[];self.anchor=None;self.text=[];self.heading=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ('h1','h2','h3','h4'):self.heading+=1
        if tag=='link' and 'alternate' in a.get('rel','') and any(t in a.get('type','') for t in ('rss','atom')):self.feeds.append(urljoin(self.base,a.get('href','')))
        if tag=='a':self.anchor=a.get('href');self.text=[];self.anchor_heading=bool(self.heading)
    def handle_data(self,text):
        if self.anchor:self.text.append(text)
    def handle_endtag(self,tag):
        if tag=='a' and self.anchor:
            title=' '.join(' '.join(self.text).split());url=urljoin(self.base,self.anchor)
            if len(title)>20:self.articles.append({'url':url,'title':title,'heading_link':self.anchor_heading})
            self.anchor=None
        if tag in ('h1','h2','h3','h4'):self.heading=max(0,self.heading-1)


def article_link(item):
    path=urlparse(item['url']).path.rstrip('/').casefold()
    parts=[x for x in path.split('/') if x]
    if not parts or re.search(r'\.(?:pdf|zip|jpg|png|xml|rss)$',path):return False
    if any(x in ('tag','tags','category','categories','authors','author','about','contact','subscribe','subscription','search','privacy','terms','podcasts','video','videos') for x in parts):return False
    if re.search(r'(?:^|/)(?:pdf\d+|about-us|terms-of-use|privacy-policy|for-authors|editorial-board)$',path):return False
    return bool(item.get('feed_date') or item.get('heading_link') or len(parts)>1 or len(parts[-1])>30)


def feed_items(raw,base):
    if re.search(r'<!DOCTYPE|<!ENTITY',raw,re.I):raise p.Blocked('FEED_ENTITY_FORBIDDEN')
    tree=ET.fromstring(raw);items=[]
    if tree.tag.split('}')[-1] not in ('rss','feed','RDF'):raise ValueError('NOT_A_FEED')
    for item in tree.iter():
        if item.tag.split('}')[-1] not in ('item','entry'):continue
        fields={};links=[]
        for child in item:
            tag=child.tag.split('}')[-1]
            if tag in ('title','pubDate','published','updated'):fields[tag]=''.join(child.itertext()).strip()
            if tag=='link' and child.attrib.get('rel','alternate')=='alternate':links.append(child.attrib.get('href') or (child.text or '').strip())
        if links and fields.get('title'):items.append({'url':urljoin(base,links[0]),'title':fields['title'],'feed_date':fields.get('published') or fields.get('pubDate') or fields.get('updated','')})
    return items


def inspect_publisher(row,session,*,article_limit=2,exclude=(),now=None):
    now=now or datetime.now(p.TZ)
    report={'publisher':row['id'],'name':row['name'],'homepage':row['homepage'],'status':'unavailable','discovered':0,'eligible':0};sources=[];items=[];feeds=list(row['discovery']['feeds'])
    try:
        raw=permitted_get(row['homepage'],session);links=Links(getattr(raw,'resolved_url',row['homepage']));links.feed(raw)
        feeds=list(dict.fromkeys(links.feeds+feeds))
        for feed in feeds[:2]:
            try:
                data=feed_items(permitted_get(feed,session),feed);items.extend(data)
                report['verified_feed']=feed
                if data:break
            except Exception:continue
        items=items or links.articles
        seen=set();items=[x for x in items if owned(x['url'],row) and article_link(x) and not(x['url'] in seen or seen.add(x['url'])) and x['url'].rstrip('/')!=row['homepage'].rstrip('/') and x['url'] not in exclude]
        from scripts import selection43
        items.sort(key=lambda item:(int(selection43.profile(item)['space']),not item.get('heading_link',False)))
        report.update(status='discovery_verified',discovered=len(items))
        for item in items[:article_limit]:
            try:
                report['last_checked_url']=item['url']
                src=session.fetch(item['url'])
                if not owned(src.get('canonical',src['url']),row):raise p.Blocked('PUBLISHER_REDIRECT_UNVERIFIED')
                published=str(src.get('published',''))
                try:stamp=datetime.fromisoformat(published.replace('Z','+00:00'))
                except ValueError:
                    try:stamp=parsedate_to_datetime(published)
                    except (ValueError,TypeError):raise p.Blocked('PUBLISHER_ACTIVITY_UNCONFIRMED')
                stamp=stamp.replace(tzinfo=p.TZ) if stamp.tzinfo is None else stamp
                if stamp-now>timedelta(days=1):raise p.Blocked('PUBLISHER_PUBLICATION_IN_FUTURE')
                if now-stamp>timedelta(days=365):raise p.Blocked('PUBLISHER_ACTIVITY_NOT_CURRENT')
                grant=rights41.decision(src,'INDEPENDENT_ARTICLE');rights41.require(src,'INDEPENDENT_ARTICLE',grant)
                # A journal hosts reviews/editorials too; do not infer research design from its name.
                src['publisher_type']=row['type'];src.setdefault('publication_type','unclassified')
                sources.append((item,src));report['eligible']+=1
            except Exception as exc:
                report['last_article_code']=getattr(exc,'code',type(exc).__name__)
                if not isinstance(exc,p.Blocked):
                    frame=traceback.extract_tb(exc.__traceback__)[-1];report['diagnostic_location']=Path(frame.filename).name+':'+str(frame.lineno)
        if sources:report['status']='full_sources_verified';report['eligible_urls']=[s['url'] for _,s in sources]
    except Exception as exc:report['code']=getattr(exc,'code',type(exc).__name__)
    return report,sources


def refresh(state,now=None,session=None):
    if len(state['candidates'])>=120:return state.get('discovery43',{})
    now=now or datetime.now(p.TZ);config=registry();cache=state.setdefault('discovery43',{'publishers':{}})
    rows=config['publishers'];en=[r for r in rows if r['language']!='ru'];ru=[r for r in rows if r['language']=='ru'];ordered=[]
    for i in range(max(len(en),len(ru))):
        if i<len(en):ordered.append(en[i])
        if i<len(ru):ordered.append(ru[i])
    from scripts import editorial41
    published_urls={x.get('source_url') for x in editorial41.archive_entries(p.ROOT)}
    cursor=cache.get('cursor',int(now.timestamp()//21600)*config['publishers_per_run'])%len(ordered);selected=[]
    for i in range(len(ordered)):
        row=ordered[(cursor+i)%len(ordered)];last=cache['publishers'].get(row['id'],{}).get('checked_at')
        if last and now-datetime.fromisoformat(last)<timedelta(hours=config['refresh_hours']):continue
        if row.get('enabled'):selected.append(row)
        if len(selected)>=config['publishers_per_run']:break
    cache['cursor']=(cursor+len(selected))%len(ordered);known={r['url'] for r in state['candidates']};session=session or public_sources41.Session();deadline=time.monotonic()+75;checks=0
    for row in selected:
        if time.monotonic()>=deadline:break
        remaining=config['article_checks_per_run']-checks
        report,found=inspect_publisher(row,session,article_limit=min(2,max(0,remaining)),exclude=known|published_urls,now=now);checks+=min(2,max(0,remaining))
        cache['publishers'][row['id']]=dict(report,checked_at=now.isoformat())
        for item,src in found:
            if src['url'] in known:continue
            record=dict(id=p.digest(src['url']),url=src['url'],title=src['title'],source=src,publisher_id=row['id'],source_kind=row['type'],science_domain=next(iter(row['topics']),''),
                category_hint='Наука',light_suitable=row.get('light_suitable',False),status='discovered',progress={},checks={},history=[])
            state['candidates'].append(record);known.add(src['url'])
            state.setdefault('source_cache',{})[src['url']]=src
        print('[catalog43] '+json.dumps({k:v for k,v in report.items() if k not in ('eligible_urls',)},ensure_ascii=False),flush=True)
    return cache


def live_report(output):
    from concurrent.futures import ThreadPoolExecutor
    rows=registry()['publishers'];session=public_sources41.Session(timeout=7)
    def check(row):return inspect_publisher(row,session,article_limit=2)[0]
    with ThreadPoolExecutor(max_workers=4) as pool:reports=list(pool.map(check,rows))
    report={'checked_at':datetime.now(p.TZ).isoformat(),'gemini_requests':0,'publisher_count':len(rows),'publishers':reports}
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('[catalog43-live] '+json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args();live_report(args.output)
