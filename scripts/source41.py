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


class ArticleParser(HTMLParser):
    def __init__(self,preferred="article"):
        super().__init__(convert_charrefs=True)
        self.preferred=preferred; self.stack=[]; self.region=None; self.region_depth=None; self.finished=False
        self.block=None; self.block_depth=None; self.parts=[]; self.links=[]; self.blocks=[]; self.images=[]
        self.meta={}; self.title_parts=[]; self.license=None; self.html_closed=False; self.ambiguous=False
        self.unmapped_text=[]
        self.block_format={}; self.list_stack=[]; self.list_serial=0; self.complex_structure=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs); void=tag in ('img','meta','link','br','hr','input','source','wbr')
        depth=len(self.stack)
        if self.region and tag in ('ol','ul'):
            self.list_serial+=1
            self.list_stack.append({'tag':tag,'group':str(self.list_serial),'index':int(a.get('start','1'))-1})
            if self.block: self.complex_structure=True
        if tag=='meta':
            key=a.get('property') or a.get('name') or a.get('itemprop')
            if key: self.meta[key]=a.get('content','')
        if tag=='html': self.meta['lang']=a.get('lang','')
        if a.get('rel')=='next': self.meta['pagination_next']=a.get('href','')
        if self.block and tag in ('td','th'): self.parts.append(' | ')
        if tag=='link' and a.get('rel')=='canonical': self.meta['canonical']=a.get('href','')
        if (a.get('rel')=='license' or a.get('itemprop')=='license') and a.get('href'):
            self.license=a['href']
        if tag==self.preferred and self.region is None and not self.finished:
            self.region=tag; self.region_depth=depth
        elif tag==self.preferred and self.finished:
            self.ambiguous=True
        if self.region and tag=='img' and a.get('src'):
            self.images.append({'url':a['src'],'alt':a.get('alt','')})
        if self.region and tag in ('h1','h2','h3','h4','h5','h6','p','li','blockquote','tr','figcaption','pre','dt','dd') and self.block is None:
            self.block=tag; self.block_depth=depth; self.parts=[]; self.links=[]
            self.block_format={}
            if tag.startswith('h') and tag[1:].isdigit(): self.block_format['heading_level']=int(tag[1:])
            if tag=='li' and self.list_stack:
                listing=self.list_stack[-1]; listing['index']+=1
                self.block_format={'list_kind':listing['tag'],'list_group':listing['group'],'list_index':listing['index']}
        if self.block and tag=='a' and a.get('href'): self.links.append(a['href'])
        if not void: self.stack.append(tag)
        if tag=='br' and self.block: self.parts.append('\n')
    def handle_data(self,data):
        ignored=any(t in ('script','style','nav','noscript','svg','footer') for t in self.stack)
        if self.stack and self.stack[-1]=='title': self.title_parts.append(data)
        if self.block and not ignored: self.parts.append(data)
        elif self.region and not ignored and data.strip(): self.unmapped_text.append(data)
    def handle_endtag(self,tag):
        if self.block==tag and len(self.stack)-1==self.block_depth:
            text=' '.join(''.join(self.parts).split())
            if text:
                kind='title' if tag=='h1' else 'heading' if tag.startswith('h') and tag[1:].isdigit() else 'item' if tag=='li' else 'table' if tag=='tr' else 'quote' if tag=='blockquote' else 'paragraph'
                self.blocks.append({'id':f'b{len(self.blocks)+1}','kind':kind,'text':text,'links':list(self.links),**self.block_format})
            self.block=None; self.parts=[]
        if self.region==tag and len(self.stack)-1==self.region_depth:
            self.finished=True; self.region=None
        if tag=='html': self.html_closed=True
        if tag in ('ol','ul') and self.list_stack: self.list_stack.pop()
        if tag in self.stack:
            i=len(self.stack)-1-self.stack[::-1].index(tag)
            del self.stack[i:]


def extract(html,url):
    safe_url(url)
    parser=ArticleParser("article" if re.search(r'<article(?:\s|>)',html,re.I) else "main"); parser.feed(html); parser.close()
    lower=html.lower()
    if re.search(r'"isaccessibleforfree"\s*:\s*false',lower) or any(v in lower for v in ('class="paywall','id="paywall','data-paywall="true')):
        raise policy.Blocked('SOURCE_ACCESS_RESTRICTED')
    if parser.meta.get('pagination_next'): raise policy.Blocked('SOURCE_PAGINATED_NEEDS_REVIEW')
    if not parser.finished or not parser.html_closed or parser.ambiguous or not parser.blocks:
        raise policy.Blocked('SOURCE_EXTRACTION_PARTIAL')
    if parser.unmapped_text or parser.complex_structure: raise policy.Blocked('SOURCE_EXTRACTION_UNMAPPED')
    paragraphs=[b for b in parser.blocks if b['kind'] not in ('heading','title')]
    if not paragraphs: raise policy.Blocked('SOURCE_EXTRACTION_EMPTY')
    title=parser.meta.get('og:title') or next((b['text'] for b in parser.blocks if b['kind'] in ('title','heading')),'') or ''.join(parser.title_parts).strip()
    if not title: raise policy.Blocked('SOURCE_METADATA_INCOMPLETE')
    if not any(b['kind']=='title' for b in parser.blocks):
        parser.blocks.insert(0,{'id':'title','kind':'title','text':title,'links':[]})
    for block in parser.blocks: block['links']=[urljoin(url,link) for link in block['links']]
    source={'id':policy.digest(url),'url':url,'canonical':urljoin(url,parser.meta.get('canonical') or url),
            'title':title,'publisher':parser.meta.get('og:site_name') or urlparse(url).hostname,
            'author':parser.meta.get('author') or parser.meta.get('article:author',''),
            'published':parser.meta.get('article:published_time') or parser.meta.get('datePublished',''),
            'event_date':None,'language':parser.meta.get('lang','').split('-')[0],
            'blocks':parser.blocks,'content_hash':policy.digest(parser.blocks),
            'raw_hash':policy.digest(html),'full_text_verified':True,'extraction_status':'complete',
            'access_checked_at':datetime.now(timezone.utc).isoformat(),
            'declared_license':urljoin(url,parser.license) if parser.license else None,
            'images':[dict(image,url=urljoin(url,image['url'])) for image in parser.images]}
    if not source['author'] or not source['language'] or not source['published']:
        source['metadata_status']='needs_review'
    else: source['metadata_status']='verified'
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
