"""A compact, deterministic home view of an immutable published overview."""
import re


def compact(page):
    page=page.replace('<body>','<body class="edition-compact">',1)
    page=re.sub(r'<div class="mast-top">.*?</div>','',page,count=1,flags=re.S)
    page=re.sub(r'<div class="motto">.*?</div>','',page,count=1,flags=re.S)
    page=re.sub(r'<section class="front-intro">.*?</section>','<h1 class="visually-hidden">Обзор номера</h1>',page,count=1,flags=re.S)
    return page


def legacy_homepage(overview,date):
    return compact(overview).replace('href="https://387.su/issues/'+date+'/"','href="https://387.su/"',1)

def homepage(overview,date):
    page=legacy_homepage(overview,date)
    if 'data-policy-version="4.4"' not in page:return page
    from scripts import mosaic44,brief_selection44,publication43
    page=mosaic44.enhance(page,date)
    # Current home can improve while its historical overview remains byte-identical.
    from scripts.source_dom41 import Document
    doc=Document();doc.feed(page);items=[]
    for node in doc.root.all():
        if node.tag!='article' or 'light-item' not in node.attrs.get('class','').split():continue
        nodes=list(node.all());link=next((n for n in nodes if n.tag=='a' and n.attrs.get('href','').startswith('http')),None)
        if not link:continue
        title=next((n.text() for n in nodes if n.tag=='h3'),'')
        body=next((n.text() for n in nodes if n.tag=='p' and not n.attrs.get('class')),'')
        label=next((n.text() for n in nodes if 'light-kind' in n.attrs.get('class','').split()),'')
        kind={'Из материалов источника':'source_report','Короткая новость':'news','Исторический факт':'historical_fact','Необычный факт':'unusual_fact'}.get(label,'unusual_fact')
        attribution=next((n.text() for n in nodes if 'light-source' in n.attrs.get('class','').split()),'')
        stamp=re.search(r'\d{4}-\d{2}-\d{2}(?:T[0-9:.+Z-]+)?',attribution)
        foreign=any(n.tag=='a' and n.text()=='На русском' for n in nodes)
        items.append({'kind':kind,'title':title,'text':body,'source':{'url':link.attrs['href'],'publisher':link.text(),'published':stamp[0] if stamp else '', 'language':None if foreign else 'ru'}})
    if items:
        selected=brief_selection44.select(items)
        page=re.sub(r'<section id="light-news".*?</section>',lambda _:publication43.render_light(selected),page,count=1,flags=re.S)
    return page
