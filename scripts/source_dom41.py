"""Small DOM for complete semantic extraction, not a text/snippet length heuristic."""
from html.parser import HTMLParser
import json
import re

VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
BLOCK={'h1','h2','h3','h4','h5','h6','p','li','blockquote','tr','pre','dt','dd','figcaption'}
IGNORE={'script','style','nav','noscript','svg','footer','form','button','template'}
UTILITY=re.compile(r'(?:^|[-_\s])(?:breadcrumb|social|share|sharing|related|recommendations|cookie|newsletter|pagination|toc|editsection|reflist|mw-editsection)(?:$|[-_\s])',re.I)
BODY_NAMES={'article-body','article-content','entry-content','post-content','story-body','field--name-body','mw-parser-output','bodyContent','content-body','article__body'}


class Node:
    def __init__(self,tag='',attrs=()):
        self.tag=tag; self.attrs=dict(attrs); self.children=[]; self.closed=False; self.parent=None
    def all(self):
        yield self
        for child in self.children:
            if isinstance(child,Node): yield from child.all()
    def text(self):
        return ''.join(child.text() if isinstance(child,Node) else child for child in self.children)


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.root=Node(); self.stack=[self.root]
    def handle_starttag(self,tag,attrs):
        # HTML5 permits omitted closing P/LI tags; make their scope explicit.
        if tag in ('p','li','dt','dd') and self.stack[-1].tag==tag: self.handle_endtag(tag)
        node=Node(tag,attrs); node.parent=self.stack[-1]; self.stack[-1].children.append(node)
        if tag not in VOID: self.stack.append(node)
        else: node.closed=True
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID: self.handle_endtag(tag)
    def handle_data(self,data): self.stack[-1].children.append(data)
    def handle_endtag(self,tag):
        index=next((i for i in range(len(self.stack)-1,0,-1) if self.stack[i].tag==tag),None)
        if index is not None:
            for node in self.stack[index:]: node.closed=True
            del self.stack[index:]


def ignored(node):
    attrs=node.attrs
    return (node.tag in IGNORE or 'hidden' in attrs or attrs.get('aria-hidden')=='true'
            or bool(UTILITY.search(attrs.get('class','')+' '+attrs.get('id',''))))


def metadata(document):
    result={}; schemas=[]
    for node in document.root.all():
        a=node.attrs
        if node.tag=='html': result['lang']=a.get('lang','')
        if node.tag=='meta':
            key=a.get('property') or a.get('name') or a.get('itemprop')
            if key:
                content=a.get('content','')
                result[key]=(result[key]+', '+content) if key=='citation_author' and key in result else content
        if node.tag=='link' and a.get('rel') in ('canonical','next','license'):
            result[a['rel']]=a.get('href','')
        if a.get('itemprop')=='license' and a.get('href'): result['license']=a['href']
        if 'license' in a.get('rel','').split() and a.get('href'): result['license']=a['href']
        if node.tag=='a' and 'creativecommons.org/licenses/' in a.get('href',''):
            surrounding=node.parent.text() if node.parent is not None and node.parent.tag=='p' else ''
            if re.search(r'distributed under|licensed under|под лицензией',surrounding,re.I): result['license']=a['href']
        if node.tag=='script' and a.get('type','').split(';')[0]=='application/ld+json':
            try: schemas.append(json.loads(node.text()))
            except (ValueError,TypeError): pass
        if node.tag=='time' and a.get('datetime') and not result.get('datePublished'): result['datePublished']=a['datetime']
    def visit(value):
        if isinstance(value,list):
            for v in value: yield from visit(v)
        elif isinstance(value,dict):
            yield value
            for v in value.values():
                if isinstance(v,(dict,list)): yield from visit(v)
    articles=[v for s in schemas for v in visit(s) if set(v.get('@type',[]) if isinstance(v.get('@type'),list) else [v.get('@type')]) & {'Article','NewsArticle','BlogPosting','ScholarlyArticle','TechArticle'}]
    # Do not treat unrelated recommendation cards as the primary article.
    exact=[v for v in articles if v.get('url')==result.get('canonical')]
    chosen=exact[0] if len(exact)==1 else articles[0] if len(articles)==1 else {}
    for key in ('headline','datePublished','inLanguage','license','isAccessibleForFree'):
        if key in chosen: result['schema_'+key]=chosen[key]
    author=chosen.get('author')
    if isinstance(author,list): author=', '.join(a.get('name','') if isinstance(a,dict) else str(a) for a in author)
    elif isinstance(author,dict): author=author.get('name')
    if isinstance(author,str): result['schema_author']=author
    return result


def choose_region(document):
    def eligible(node):
        current=node
        while current is not None:
            if ignored(current): return False
            current=current.parent
        return True
    nodes=[n for n in document.root.all() if eligible(n)]
    bodies=[n for n in nodes if n.attrs.get('itemprop')=='articleBody' or
            bool(set(n.attrs.get('class','').split()) & BODY_NAMES) or n.attrs.get('id') in BODY_NAMES]
    # Keep only outermost body nodes; split Drupal body fields are all retained in DOM order.
    outer=[]; descendants=set()
    for node in bodies:
        if id(node) not in descendants:
            outer.append(node); descendants.update(id(n) for n in node.all() if n is not node)
    owners=set()
    for node in outer:
        ancestor=node
        while ancestor is not None:
            if ancestor.tag=='article': owners.add(id(ancestor)); break
            ancestor=ancestor.parent
    if len(owners)>1: return [],'ambiguous'
    if outer: return outer,'explicit_body'
    articles=[n for n in nodes if n.tag=='article']
    if len(articles)==1: return articles,'article'
    if articles: return [],'ambiguous'
    mains=[n for n in nodes if n.tag=='main' or n.attrs.get('role')=='main']
    return (mains,'main') if len(mains)==1 else ([], 'ambiguous')


def blocks(regions):
    result=[]; images=[]; listing=[]; list_serial=0
    def emit(text,kind='paragraph',fmt=None,links=()):
        text=' '.join(text.split())
        if text: result.append({'id':f'b{len(result)+1}','kind':kind,'text':text,'links':list(links),**(fmt or {})})
    def walk(node):
        nonlocal list_serial
        if ignored(node): return
        if node.tag=='img':
            url=node.attrs.get('src') or node.attrs.get('data-src')
            if url: images.append({'url':url,'alt':node.attrs.get('alt','')})
            return
        if node.tag in ('ol','ul'):
            list_serial+=1; listing.append({'kind':node.tag,'group':str(list_serial),'index':int(node.attrs.get('start','1'))-1})
        kind='title' if node.tag=='h1' else 'heading' if re.fullmatch('h[2-6]',node.tag) else 'item' if node.tag=='li' else 'quote' if node.tag=='blockquote' else 'table' if node.tag=='tr' else 'paragraph'
        fmt={}
        if re.fullmatch('h[1-6]',node.tag): fmt['heading_level']=int(node.tag[1:])
        if node.tag=='li' and listing:
            listing[-1]['index']+=1; l=listing[-1]
            fmt={'list_kind':l['kind'],'list_group':l['group'],'list_index':int(node.attrs.get('value',l['index'])),'list_depth':len(listing)}
        run=[]; links=[]
        def flush():
            emit(''.join(run),kind,fmt,links); run.clear(); links.clear()
        def inline(child):
            if isinstance(child,str): run.append(child); return
            if ignored(child): return
            if child.tag in BLOCK or child.tag in ('ol','ul','div','section','figure','table','tbody','thead','aside'):
                flush(); walk(child); return
            if child.tag=='br': run.append('\n')
            if child.tag in ('td','th'): run.append(' | ')
            if child.tag=='a' and child.attrs.get('href'): links.append(child.attrs['href'])
            if child.tag=='img': walk(child)
            for grandchild in child.children: inline(grandchild)
        for child in node.children: inline(child)
        flush()
        if node.tag in ('ol','ul'): listing.pop()
    for region in regions: walk(region)
    return result,images
