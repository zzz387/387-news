"""Rotating RSS/page discovery. Feed text is metadata, NEVER the original article."""
import json,re,time,traceback,os
from email.utils import parsedate_to_datetime
from datetime import datetime,timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse,urljoin
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET
try:from scripts import policy41 as p,source41,rights41,public_sources41
except ImportError:import policy41 as p,source41,rights41,public_sources41


def registry():return json.loads((p.ROOT/'config/editorial_sources.json').read_text())


def owned(url,row):
    host=(urlparse(url).hostname or '').removeprefix('www.');domain=row['domain'].removeprefix('www.')
    return host==domain or host.endswith('.'+domain)


def secure_discovery_url(url,row):
    parts=urlparse(url)
    if parts.scheme=='http' and owned(url,row) and not parts.username and not parts.password and parts.port in (None,80):
        return parts._replace(scheme='https',netloc=parts.netloc.removesuffix(':80')).geturl()
    return url


def undated_evergreen(source,row):
    from scripts import editorial43,editorial41
    title=source.get('title','')
    if not row.get('allow_archive'):return False
    url=source.get('url','');path=urlparse(url).path
    stable_official=editorial41.host_matches(url,{'who.int','nhs.uk','nih.gov','unicef.org'}) and bool(re.search(r'/(?:health-topics|fact-sheets|live-well|conditions|parenting|health-information|health)(?:/|$)',path)) and not re.search(r'/(?:news|press|research|studies)(?:/|$)',path)
    if editorial43.high_risk({'source':source}) and not stable_official:return False
    if re.search(r'(?i)today|breaking|new study|сегодня|новое исследование|клиническ',title):return False
    from scripts import policy44
    if stable_official or policy44.subject({'source':source}):return True
    return bool(re.search(r'(?i)истор|биограф|архитект|культур|history|historical|biograph|heritage|philosophy|parent|child|famil|play|learn|education|paternity|воспитан|реб[её]н|дет|семейн|обучен|игр|велосипед|cycling|йог|yoga',title))


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
        a={key:(value or '') for key,value in attrs}
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
    if parts and parts[0] in ('rubric','rubrics','section','sections'):return False
    if path in ('/business/technology-of-business','/future','/travel','/science','/business'):return False
    if not parts or re.search(r'\.(?:pdf|zip|jpg|png|xml|rss)$',path):return False
    if any(x in ('tag','tags','category','categories','authors','author','about','contact','subscribe','subscription','search','privacy','terms','podcasts','video','videos') for x in parts):return False
    if re.search(r'(?:^|/)(?:pdf\d+|about-us|terms-of-use|privacy-policy|for-authors|editorial-board)$',path):return False
    return bool(item.get('feed_date') or item.get('heading_link') or len(parts)>1 or len(parts[-1])>30)


def advertising_story(item):
    return bool(re.search(r'(?i)\bsponsored\b|\badvertorial\b|\badvertisement\b|promo code|shop now|black friday deals|промокод|на правах рекламы|рекламн\w* (?:материал|публикац)|купить со скидк',item.get('title','')))


def feed_items(raw,base):
    if re.search(r'<!DOCTYPE|<!ENTITY',raw,re.I):raise p.Blocked('FEED_ENTITY_FORBIDDEN')
    tree=ET.fromstring(raw);items=[]
    if tree.tag.split('}')[-1] not in ('rss','feed','RDF'):raise ValueError('NOT_A_FEED')
    for item in tree.iter():
        if item.tag.split('}')[-1] not in ('item','entry'):continue
        fields={};links=[]
        for child in item:
            tag=child.tag.split('}')[-1]
            if tag in ('title','pubDate','published','updated','description','summary'):fields[tag]=''.join(child.itertext()).strip()
            if tag=='link' and child.attrib.get('rel','alternate')=='alternate':links.append(child.attrib.get('href') or (child.text or '').strip())
        if links and fields.get('title'):items.append({'url':urljoin(base,links[0]),'title':fields['title'],'summary':fields.get('description') or fields.get('summary',''),'feed_published':fields.get('published') or fields.get('pubDate',''),'feed_date':fields.get('published') or fields.get('pubDate') or fields.get('updated','')})
    return items


def inspect_publisher(row,session,*,article_limit=2,exclude=(),now=None,preferred_group=None):
    now=now or datetime.now(p.TZ)
    report={'publisher':row['id'],'name':row['name'],'homepage':row['homepage'],'status':'unavailable','discovered':0,'eligible':0,'article_checks':0};sources=[];items=[];feeds=list(row['discovery']['feeds'])
    pages=[row['homepage']]+row['discovery'].get('pages',[])
    if len(pages)>1:feeds=[]  # A section's RSS must not silently replace another section.
    home=pages[int(now.timestamp()//21600)%len(pages)]
    try:
        raw=permitted_get(home,session);links=Links(getattr(raw,'resolved_url',home));links.feed(raw)
        feeds=list(dict.fromkeys(links.feeds+feeds))
        for feed in feeds[:2]:
            try:
                data=feed_items(permitted_get(feed,session),feed);items.extend(data)
                report['verified_feed']=feed
                if data:break
            except Exception:continue
        items=[dict(item,url=secure_discovery_url(item['url'],row)) for item in (items or links.articles)]
        seen=set();items=[x for x in items if owned(x['url'],row) and article_link(x) and not advertising_story(x) and not(x['url'] in seen or seen.add(x['url'])) and x['url'].rstrip('/')!=row['homepage'].rstrip('/') and x['url'] not in exclude]
        from scripts import selection43
        from scripts import priorities43,policy44
        def item_group(item):return policy44.subject(item) if preferred_group in policy44.GROUPS else priorities43.classify(item)['group']
        items.sort(key=lambda item:(int(bool(preferred_group) and item_group(item)!=preferred_group),int(selection43.profile(item)['space']),not item.get('heading_link',False)))
        report.update(status='discovery_verified',discovered=len(items))
        if preferred_group:
            matching=[item for item in items if item_group(item)==preferred_group]
            report['matching_topic_metadata']=len(matching)
            # A publisher's advertised coverage is not evidence of this story's topic.
            # Do not consume complete-original checks on unrelated section links.
            items=matching
        for item in items[:article_limit]:
            try:
                report['article_checks']+=1
                report['last_checked_url']=item['url']
                src=session.fetch(item['url'])
                if not owned(src.get('canonical',src['url']),row):raise p.Blocked('PUBLISHER_REDIRECT_UNVERIFIED')
                if preferred_group in policy44.GROUPS:
                    actual_group=policy44.subject({'source':src})
                    if not actual_group:raise p.Blocked('SOURCE_SUBJECT_MISMATCH')
                    if actual_group!=preferred_group:report['rerouted_group']=actual_group
                # A publisher's verified RSS publication field can establish a
                # missing bibliographic date. Never substitute updated/event dates.
                if not src.get('published') and item.get('feed_published') and report.get('verified_feed'):
                    src['published']=item['feed_published']
                    src['publication_date_evidence']={'kind':'publisher_feed','url':report['verified_feed'],'field':'published_or_pubDate'}
                    src['metadata_gaps']=[g for g in src.get('metadata_gaps',[]) if g!='published']
                published=str(src.get('published',''))
                try:stamp=datetime.fromisoformat(published.replace('Z','+00:00'))
                except ValueError:
                    try:stamp=parsedate_to_datetime(published)
                    except (ValueError,TypeError):
                        if undated_evergreen(src,row):
                            stamp=None;report['undated_archival_original']=True
                        else:raise p.Blocked('PUBLISHER_ACTIVITY_UNCONFIRMED')
                stamp=(stamp.replace(tzinfo=p.TZ) if stamp.tzinfo is None else stamp) if stamp is not None else None
                if stamp is not None and stamp-now>timedelta(days=1):raise p.Blocked('PUBLISHER_PUBLICATION_IN_FUTURE')
                if stamp is not None and not row.get('allow_archive') and now-stamp>timedelta(days=365):raise p.Blocked('PUBLISHER_ACTIVITY_NOT_CURRENT')
                grant=rights41.decision(src,'INDEPENDENT_ARTICLE');rights41.require(src,'INDEPENDENT_ARTICLE',grant)
                # A journal hosts reviews/editorials too; do not infer research design from its name.
                src['publisher_type']=row['type'];src.setdefault('publication_type','unclassified')
                sources.append(({k:v for k,v in item.items() if k!='summary'},src));report['eligible']+=1
            except Exception as exc:
                report['last_article_code']=getattr(exc,'code',type(exc).__name__)
                if not isinstance(exc,p.Blocked):
                    frame=traceback.extract_tb(exc.__traceback__)[-1];report['diagnostic_location']=Path(frame.filename).name+':'+str(frame.lineno)
        if sources:report['status']='full_sources_verified';report['eligible_urls']=[s['url'] for _,s in sources]
    except Exception as exc:report['code']=getattr(exc,'code',type(exc).__name__)
    return report,sources


def refresh(state,now=None,session=None,shortage=False):
    rotate_candidates(state)
    now=now or datetime.now(p.TZ);config=registry()
    from scripts import editorial43,selection43
    shortage=(len(selection43.ready(state))<editorial43.CONFIG['minimum_articles']) if shortage is None else shortage
    config=dict(config)
    if shortage:
        config['publishers_per_run']=min(15,config['publishers_per_run']*3)
        config['article_checks_per_run']=min(24,config['article_checks_per_run']*3)
    cache=state.setdefault('discovery43',{'publishers':{}})
    from scripts import priorities43,policy44
    def due(row):
        saved=cache['publishers'].get(row['id'],{})
        if policy44.active(state) and saved.get('classifier44_revision')!=policy44.REVISION:return True
        last=saved.get('checked_at')
        return not last or now-datetime.fromisoformat(last)>=timedelta(hours=config['refresh_hours'])
    ordered=priorities43.publisher_order([r for r in config['publishers'] if r.get('enabled') and r.get('availability',{}).get('status')=='verified' and due(r)],cache,state.get('_recent43',[]),state['date'])
    from scripts import policy44
    if policy44.active(state):ordered=policy44.publisher_order(ordered,state)
    if os.getenv('NEWS_LIGHT_NEWS_ENABLED')=='true':
        # One public discovery slot for the independent light column; content,
        # complete originals and rights still decide eligibility, never the flag.
        core=[r for r in ordered if r.get('search_group')]
        other=[r for r in ordered if not r.get('search_group')]
        picks=[r for r in other if policy44.active(state) or r.get('light_suitable')]
        if picks:
            light=min(picks,key=lambda r:(cache['publishers'].get(r['id'],{}).get('checked_at',''),-r.get('availability',{}).get('full_originals_verified',0),r['id']))
            other=[r for r in other if r['id']!=light['id']]
            ordered=core+[dict(light,search_light=True)]+other
    if not ordered:return cache
    from scripts import editorial41
    published_urls={x.get('source_url') for x in editorial41.archive_entries(p.ROOT)}
    selected=[]
    for row in ordered:
        if not due(row):continue
        selected.append(row)
        if len(selected)>=config['publishers_per_run']:break
    known={r['url'] for r in state['candidates']};session=session or public_sources41.Session(timeout=7);deadline=time.monotonic()+(120 if shortage else 75);checks=0
    cache['last_run']={'at':now.isoformat(),'attempted_groups':[],'candidate_groups':{},'publishers_attempted':0,'article_checks':0}
    run=cache['last_run']
    targets=policy44.search_deficits(state) if policy44.active(state) else {g:1 for g in priorities43.CORE_GROUPS}
    run['candidate_targets']=targets
    # Reserve an independent discovery attempt for each core group. Network work
    # overlaps only across public publishers; no model calls or state mutations.
    core=[row for row in selected if row.get('search_group')]
    from concurrent.futures import ThreadPoolExecutor
    initial={}
    if core:
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs={row['id']:pool.submit(inspect_publisher,row,session,article_limit=1,exclude=known|published_urls,now=now,preferred_group=row['search_group']) for row in core[:config['article_checks_per_run']]}
            for key,job in jobs.items():
                try:initial[key]=job.result()
                except Exception as exc:initial[key]=({'article_checks':0,'status':'unavailable','code':type(exc).__name__},[])
    attempted_ids=set();fallback_groups=set();fallback_attempts={g:0 for g in policy44.GROUPS}
    pending=list(selected)
    while pending and len(attempted_ids)<config['publishers_per_run']:
        row=pending.pop(0)
        if row['id'] not in initial and not row.get('search_light'):
            missing=[g for g in (policy44.GROUPS if policy44.active(state) else priorities43.CORE_GROUPS) if run['candidate_groups'].get(g,0)<targets.get(g,1) and (policy44.active(state) or g not in fallback_groups)]
            if policy44.active(state):missing.sort(key=lambda g:fallback_attempts[g])
            for group in missing:
                options=[r for r in ordered if r['id'] not in attempted_ids and r['id'] not in initial and (bool({'family':{1,2,3},'health':{12,16},'sport':{13,14,15}}[group]&set(r.get('priority_ids',[]))) if policy44.active(state) else any(priorities43.DIRECTIONS.get(i,{}).get('group')==group for i in r.get('priority_ids',[])))]
                if options:
                    chosen=min(options,key=lambda item:policy44.publisher_score(item,group)) if policy44.active(state) else options[0]
                    row=dict(chosen,search_group=group);fallback_groups.add(group)
                    if policy44.active(state):fallback_attempts[group]+=1
                    pending=[r for r in pending if r['id']!=row['id']];break
        if row['id'] not in initial and time.monotonic()>=deadline:break
        remaining=config['article_checks_per_run']-checks
        if row['id'] in initial:report,found=initial[row['id']]
        else:
            if remaining<=0:break
            kwargs={'preferred_group':row['search_group']} if row.get('search_group') else {}
            report,found=inspect_publisher(row,session,article_limit=min(2,remaining),exclude=known|published_urls,now=now,**kwargs)
        attempted_ids.add(row['id']);checks+=report['article_checks'];run['publishers_attempted']+=1;run['article_checks']=checks
        if row.get('search_group'):run['attempted_groups'].append(row['search_group'])
        report['requested_group']=row.get('search_group')
        cache['publishers'][row['id']]=dict(report,checked_at=now.isoformat())
        if policy44.active(state):cache['publishers'][row['id']]['classifier44_revision']=policy44.REVISION
        for item,src in found:
            if src['url'] in known:continue
            record=dict(id=p.digest(src['url']),url=src['url'],title=src['title'],source=src,publisher_id=row['id'],publisher_group=row['domain'].removeprefix('www.'),source_kind=row['type'],science_domain=next(iter(row['topics']),''),
                priority_ids=row.get('priority_ids',[]),editorial_priority=row.get('editorial_priority',50),quality_score=row.get('quality_score',50),science_source=row.get('science_source',False),category_hint='Общество',discovered_at=now.isoformat(),light_suitable=row.get('light_suitable',False),status='discovered',progress={},checks={},history=[])
            if policy44.active(state):record['topic_policy_version']='4.4'
            record['editorial43']=priorities43.evaluate(record,state.get('_recent43',[]),state['date'])
            record['category_hint']=record['editorial43']['category']
            if row.get('search_light'):
                from scripts import light43
                if light43.story_suitable(record):
                    record['for_light_only']=True
                    queue=state.setdefault('light43_queue',[])
                    if record['id'] not in queue:queue.append(record['id'])
            group=(policy44.subject(record) or 'general') if policy44.active(state) else record['editorial43']['group'];run['candidate_groups'][group]=run['candidate_groups'].get(group,0)+1
            state['candidates'].append(record);known.add(src['url'])
            state.setdefault('source_cache',{})[src['url']]=src
        print('[catalog43] '+json.dumps({k:v for k,v in report.items() if k not in ('eligible_urls',)},ensure_ascii=False),flush=True)
    rotate_candidates(state)
    run['missing_candidate_groups']=[g for g in (policy44.GROUPS if policy44.active(state) else priorities43.CORE_GROUPS) if run['candidate_groups'].get(g,0)<targets.get(g,1)]
    print('[discovery-coverage43] '+json.dumps(run),flush=True)
    return cache


def rotate_candidates(state,limit=120):
    # Retire only untouched candidates from the active search queue. Keep every
    # original, evidence check and refusal in the SAME encrypted checkpoint.
    pending=[r for r in state['candidates'] if r.get('status')=='discovered' and not r.get('article') and not r.get('progress')]
    for row in pending[:-limit]:
        row['status']='discovery_retired'
        row.setdefault('history',[]).append({'code':'DISCOVERY_POOL_ROTATION','retained_in_checkpoint':True})
    return len(pending[:-limit])


def live_report(output):
    from concurrent.futures import ThreadPoolExecutor
    rows=registry()['publishers'];session=public_sources41.Session(timeout=7)
    def check(row):return inspect_publisher(row,session,article_limit=2)[0]
    with ThreadPoolExecutor(max_workers=6) as pool:reports=list(pool.map(check,rows))
    report={'checked_at':datetime.now(p.TZ).isoformat(),'gemini_requests':0,'publisher_count':len(rows),'publishers':reports}
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('[catalog43-live] '+json.dumps(report,ensure_ascii=False))

def core_report(output):
    # Public-source diagnostic only: no production checkpoint, drafts or model key.
    now=datetime.now(p.TZ);state={'date':now.date().isoformat(),'policy_version':os.getenv('NEWS_POLICY_VERSION','4.3'),'candidates':[]}
    cache=refresh(state,now,shortage=True)
    result={'checked_at':now.isoformat(),'gemini_requests':0,'search':cache.get('last_run',{}),
            'publishers':cache.get('publishers',{}),'candidate_groups':cache.get('last_run',{}).get('candidate_groups',{})}
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('[core-search43-public] '+json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--core-search',action='store_true');args=parser.parse_args()
    (core_report if args.core_search else live_report)(args.output)


def apply_verification(config,report):
    """Enable public discovery only after real robots/homepage/link checks, not article approval."""
    import copy
    config=copy.deepcopy(config);by_id={r['publisher']:r for r in report['publishers']};eligible=[]
    for row in config['publishers']:
        result=by_id.get(row['id'],{});verified=result.get('status') in ('discovery_verified','full_sources_verified') and result.get('discovered',0)>0
        row['availability']={'status':'verified' if verified else 'manual_only','checked_at':report['checked_at'],
            'scope':'public_discovery_only','full_originals_verified':result.get('eligible',0),
            'code':result.get('code') or result.get('last_article_code') or ('VERIFIED_DISCOVERY' if verified else 'NO_VERIFIED_ARTICLE_LINKS')}
        row['enabled']=False
        if verified:
            row['discovery']['feeds']=[result['verified_feed']] if result.get('verified_feed') else []
            row['discovery']['feed_urls_are_hints']=False
            eligible.append(row)
    for row in sorted(eligible,key=lambda r:(-r.get('editorial_priority',0),r['id']))[:90]:row['enabled']=True
    return config
