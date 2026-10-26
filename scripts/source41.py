"""Complete, bounded transport and semantic article extraction; never snippet fallback."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from html import unescape
import ipaddress
import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
try:
    from scripts import policy41 as policy
except ImportError:
    import policy41 as policy


def safe_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise policy.Blocked('SOURCE_URL_UNSAFE')
    if parsed.hostname in ('localhost','metadata.google.internal') or parsed.hostname.endswith(('.local','.internal')):
        raise policy.Blocked('SOURCE_URL_UNSAFE')
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global: raise policy.Blocked('SOURCE_URL_UNSAFE')
    except ValueError: pass
    return url


def transport(url,limit=None):
    safe_url(url)
    limit=limit or policy.CONFIG['technical']['source_byte_limit']
    with urlopen(Request(url,headers={'User-Agent':'387News-Research/4.1'}),timeout=25) as response:
        safe_url(response.geturl())
        if response.status!=200: raise policy.Blocked('SOURCE_UNAVAILABLE')
        data=response.read(limit+1)
        if len(data)>limit: raise policy.Blocked('SOURCE_TRANSPORT_LIMIT','Source is not truncated; review a larger safe transport budget')
        return data.decode(response.headers.get_content_charset() or 'utf-8',errors='strict')


def publisher_metadata(document,host):
    """Explicit publisher bylines/publication labels, never last-modified or event dates."""
    result={}
    if host=='sciencedaily.com' or host.endswith('.sciencedaily.com'):
        for node in document.root.all():
            if node.tag!='dt' or node.text().strip().rstrip(':').casefold()!='date' or node.parent is None:continue
            siblings=[child for child in node.parent.children if hasattr(child,'tag')]
            index=siblings.index(node)
            if index+1<len(siblings) and siblings[index+1].tag=='dd':
                raw=' '.join(siblings[index+1].text().split())
                try:result['published']=datetime.strptime(raw,'%B %d, %Y').date().isoformat()
                except ValueError:pass
                if result:break
    if host=='greatergood.berkeley.edu':
        rows=set()
        for node in document.root.all():
            text=' '.join(node.text().split())
            if len(text)>500:continue  # metadata transport bound; article text is never clipped
            match=re.fullmatch(r'By (.+?)\s*\|\s*([A-Za-z]+ \d{1,2}, \d{4})',text)
            if match:
                try:rows.add((match[1],datetime.strptime(match[2],'%B %d, %Y').date().isoformat()))
                except ValueError:pass
        if len(rows)==1:result['author'],result['published']=next(iter(rows))
    return result


def extract(html,url):
    safe_url(url)
    try:
        from scripts import source_dom41 as dom
    except ImportError: import source_dom41 as dom
    import json
    document=dom.Document(); document.feed(html); document.close()
    meta=dom.metadata(document)
    page_title=next((n.text() for n in document.root.all() if n.tag=='title'),'')
    if re.search(r'just a moment|access denied|verify you are human|enable javascript|404.*not found',page_title,re.I):
        raise policy.Blocked('SOURCE_INTERACTIVE_OR_ERROR_PAGE')
    if (meta.get('schema_isAccessibleForFree') is False or
            re.search(r'"isaccessibleforfree"\s*:\s*false',html,re.I) or
            re.search(r'(?:class|id)=["\'][^"\']*\bpaywall|data-paywall=["\']true',html,re.I)):
        raise policy.Blocked('SOURCE_ACCESS_RESTRICTED')
    if meta.get('next'): raise policy.Blocked('SOURCE_PAGINATED_NEEDS_REVIEW')
    regions,method=dom.choose_region(document)
    if method=='abstract_only': raise policy.Blocked('SOURCE_ABSTRACT_ONLY')
    if not regions or any(not region.closed for region in regions):
        raise policy.Blocked('SOURCE_EXTRACTION_PARTIAL')
    blocks,images=dom.blocks(regions)
    if not any(b['kind'] not in ('title','heading') for b in blocks): raise policy.Blocked('SOURCE_EXTRACTION_EMPTY')
    title=(next((b['text'] for b in blocks if b['kind']=='title'),'') or
           meta.get('schema_headline') or meta.get('og:title') or
           next((n.text().strip() for n in document.root.all() if n.tag=='h1'),''))
    if not isinstance(title,str) or not title: raise policy.Blocked('SOURCE_METADATA_INCOMPLETE')
    if not any(b['kind']=='title' for b in blocks):
        blocks.insert(0,{'id':'title','kind':'title','text':title,'links':[],'heading_level':1})
    for block in blocks: block['links']=[urljoin(url,link) for link in block['links']]
    host=urlparse(url).hostname
    profiles=json.loads((policy.ROOT/'config/source-profiles.json').read_text())['institutions']
    profile=next((v for domain,v in profiles.items() if host==domain or host.endswith('.'+domain)),None)
    publisher_fields=publisher_metadata(document,host)
    author=publisher_fields.get('author') or meta.get('schema_author') or meta.get('author') or meta.get('article:author') or meta.get('citation_author') or ''
    published=publisher_fields.get('published') or meta.get('article:published_time') or meta.get('datePublished') or meta.get('schema_datePublished') or meta.get('citation_date') or ''
    language=meta.get('lang') or meta.get('schema_inLanguage') or meta.get('og:locale') or ''
    language=language.split('-')[0].split('_')[0] if isinstance(language,str) else ''
    license_url=meta.get('license') or meta.get('schema_license')
    source={'id':policy.digest(url),'url':url,'canonical':urljoin(url,meta.get('canonical') or url),
            'title':title,'publisher':meta.get('og:site_name') or (profile or {}).get('publisher') or host,
            'author':author,'published':published,'event_date':None,'language':language,
            'blocks':blocks,'content_hash':policy.digest(blocks),'raw_hash':policy.digest(html),
            'full_text_verified':True,'extraction_status':'complete','extraction_method':method,
            'access_checked_at':datetime.now(timezone.utc).isoformat(),
            'declared_license':urljoin(url,license_url) if isinstance(license_url,str) else None,
            'images':[dict(image,url=urljoin(url,image['url'])) for image in images],
            'institutional_source':bool(profile),'ai_use_restricted':bool((profile or {}).get('ai_use_restricted')),
            'metadata_gaps':[name for name,value in (('author',author),('published',published)) if not value]}
    source['metadata_status']='verified' if language and (bool(author and published) or profile) else 'needs_review'
    if profile: source['publisher_evidence_url']=profile['evidence_url']
    return source


def fetch(url,get=transport):
    safe_url(url)
    host=urlparse(url)
    robots_url=host.scheme+'://'+host.netloc+'/robots.txt'
    try:
        robots=get(robots_url)
    except Exception as exc:
        # An explicit missing robots file is absence of robots restrictions, not a paywall bypass.
        if getattr(exc,'code',None)!=404: raise policy.Blocked('ROBOTS_UNVERIFIED') from exc
        robots=''
    rp=RobotFileParser(); rp.parse(robots.splitlines())
    if not rp.can_fetch('387News-Research',url): raise policy.Blocked('ROBOTS_FORBIDDEN')
    return extract(get(url),url)
