"""Cheap story-level exclusion and diverse 8–12 brief selection, no model calls."""
import re
from collections import Counter

REVISION=2
MAXIMUM=12

def text(row):
    article=row.get('article',{});source=row.get('source',{})
    return ' '.join(str(x) for x in [row.get('title',''),row.get('text',''),row.get('summary',''),article.get('title',''),article.get('teaser',''),
        ' '.join(b.get('text','') for b in article.get('blocks',[])),source.get('title',''),source.get('description',''),source.get('section','')])

def excluded(row):
    source=row.get('source',{})
    value=text(row).casefold()
    # Benign institutional mentions and animal names are not criminal events.
    value=re.sub(r'killer whales?|murder of crows|stole the show|steal the show|никто не пострадал|без пострадавших|no one was injured','',value)
    hard=r'криминальн|насили|грабител|воровств|\bвор(?:ы|а|у)?\b|похитител|\bburglary\b|\bscam\b|\bthief\b|\bstolen\b|\brobb(?:ed|ing)\b|domestic violence|убийств|ограб|граб[её]ж|разбой|мошеннич|краж[аиу]?\b|похищен|изнасил|взятк|наркоторг|уголовн|приговор|осужд[её]н|арестован|задержан|террорист|расстрел|преступн|\bmurder\b|robber|\btheft\b|\bfraud\b|\barrest(?:ed|s)?\b|charged with|convicted|sentenced|criminal (?:case|trial|gang)|sexual assault|kidnapp|homicide'
    if re.search(hard,value):return 'BRIEF_CRIME'
    if re.search(r'погиб|пострада|ранен[ыао]?\b|смертельн.{0,20}(?:авари|случа|травм)|\bfatal\b|people (?:died|killed)|injured (?:people|children)|casualties',value):return 'BRIEF_TRAGEDY'
    institution=re.search(r'полици|прокуратур|следовател|\bpolice\b|prosecutor|law enforcement',value)
    action=re.search(r'расслед|розыск|подозрева|обвин|investigat|suspect|offen[cs]e|manhunt',value)
    if institution and action:return 'BRIEF_CRIME_AMBIGUOUS'
    if re.search(r'/(?:crime|criminal|accidents)/',row.get('url') or source.get('url','')):return 'BRIEF_CRIME_SECTION'
    return None

TOPICS={
 'nature':r'животн|птиц|ворон|кит\b|дельфин|собак|кошк|растени|лес\b|экосистем|animal|bird|whale|dolphin|wildlife|plant|forest',
 'culture':r'музе|выстав|искусств|худож|живопис|театр|музык|museum|gallery|artist|painting|music|theatre',
 'history':r'истори|археолог|древн|наслед|history|historic|archaeolog|ancient|heritage',
 'sport':r'спорт|велосип|бегун|марафон|йог|рекорд|athlete|cycling|sport|marathon|record',
 'technology':r'технолог|робот|изобрет|производ|3d|technology|robot|invention|engineer',
 'science':r'уч[её]н|исследован|эксперимент|математ|scientist|research|experiment|mathemat',
 'city':r'город|москв|парк|улиц|архитект|city|urban|park|street|architect',
 'people':r'человек|семь|дет|добровол|волонт|благотвор|традиц|people|family|child|volunteer|charit|tradition',
 'business':r'бизнес|экономик|компани|предприним|business|econom|company|entrepreneur'}

def topic(row):
    value=text(row).casefold()
    return next((key for key,pattern in TOPICS.items() if re.search(pattern,value)),'curiosity')

def select(rows,limit=MAXIMUM):
    """Soft subject/publisher balance, hard exclusions and same-event duplicates."""
    from scripts import light44
    pending=[r for r in rows if not excluded(r)];result=[];topics=Counter();publishers=Counter()
    while pending and len(result)<min(MAXIMUM,limit):
        def rank(row):
            group=topic(row);publisher=row.get('source',{}).get('publisher','')
            animal_penalty=10 if group=='nature' and topics[group]>=max(2,round(min(limit,len(rows))*.3)) else 0
            quality=row.get('quality_score',50)
            return (animal_penalty+topics[group]*3+publishers[publisher]*2,-quality,str(row.get('id') or row.get('title') or row.get('article',{}).get('title','')))
        row=min(pending,key=rank);pending.remove(row)
        if any(light44.duplicate(row,other) for other in result):continue
        result.append(row);topics[topic(row)]+=1;publishers[row.get('source',{}).get('publisher','')]+=1
    return result
