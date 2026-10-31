"""Cheap story comparison and soft variety; no model requests or issue-size gate."""
import re
from collections import Counter
from datetime import datetime,timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse,parse_qs

STOP=set('как почему что когда где это для при или над под после через исследование исследования новое новый новые влияет влияние помогают помогает учёные ученые study research new how why the and for with from about a of in on to'.split())
ALIASES=[(r'недосып\w*|дефицит\w* сна|недостат\w* сна|sleep (?:loss|deprivation|restriction)',' sleep_loss '),
 (r'лишн\w* вес\w*|увелич\w* вес\w*|ожир\w*|хочется есть|аппетит\w*|пищев\w* повед\w*|weight gain|obesity|appetite',' metabolic '),
 (r'царицын\w*|tsaritsyno',' tsaritsyno '),(r'быстр\w* (?:фаз\w* )?сн\w*|rem sleep',' rem_sleep ')]
PLACES={'tsaritsyno':'tsaritsyno','царицыно':'tsaritsyno','петергоф':'peterhof','коломенск':'kolomenskoe','кусков':'kuskovo','эрмитаж':'hermitage','дарвиновск':'darwin_museum','tretyakov':'tretyakov','третьяков':'tretyakov'}


def title(row):return row.get('article',{}).get('title') or row.get('title') or row.get('source',{}).get('title') or row.get('topic_key','')


def normalized(text):
    text=unescape(str(text)).casefold().replace('ё','е')
    for pattern,replacement in ALIASES:text=re.sub(pattern,replacement,text)
    return text


def tokens(text):
    return {w if len(w)<7 or '_' in w else w[:7] for w in re.findall(r'[a-zа-я_0-9]+',normalized(text)) if w not in STOP and len(w)>2}


def profile(row):
    text=title(row);norm=normalized(text);url=row.get('url') or row.get('source',{}).get('url') or ''
    source=row.get('source',{});canonical=source.get('canonical') or url
    doi=source.get('doi') or row.get('study_id') or next(iter(parse_qs(urlparse(canonical).query).get('id',[])),'')
    if not doi:doi=next(iter(re.findall(r'10\.\d{4,9}/[^?#\s]+',canonical)), '')
    doi=doi.casefold().removeprefix('https://doi.org/').rstrip('/.,')
    if not re.fullmatch(r'10\.\d{4,9}/\S+',doi):doi=''
    focus='history' if re.search(r'истор|открыти[ея].*фаз|history|discovered.*rem',norm) else 'restoration' if re.search(r'реставр|restor',norm) else 'architecture' if re.search(r'архитект|architect',norm) else 'general'
    place=row.get('place_hint') or next((v for k,v in PLACES.items() if k in norm),'')
    space=bool(re.search(r'космо|астроно|галактик|спутник|лун[аыуе]|марс|планет|space|astronom|galax|lunar|planet|nasa',norm)) or row.get('science_domain')=='space'
    return {'title':norm,'words':tokens(text),'doi':doi,'focus':focus,'place':place,
        'publisher':row.get('publisher_id') or source.get('publisher') or (urlparse(url).hostname or '').removeprefix('www.'),
        'organisation':row.get('organisation_hint') or ('nasa' if 'nasa.gov' in url else ''),'space':space,'url':url}


def duplicate(a,b):
    x=profile(a);y=profile(b)
    if x['url'] and x['url']==y['url']:return True
    if x['doi'] and x['doi']==y['doi']:return True
    if x['focus']!=y['focus']:return False
    if all(term in x['title'] and term in y['title'] for term in ('sleep_loss','metabolic')):return True
    if x['title'] and x['title']==y['title']:return True
    common=x['words']&y['words'];union=x['words']|y['words']
    return len(common)>=3 and bool(union) and len(common)/len(union)>=0.76


def usefulness(row):
    # A preference, never a length requirement; no rewrite of an accepted work.
    claims=row.get('checks',{}).get('final43',{}).get('claims',[])
    return (row.get('editorial_priority',0),int(row.get('source_kind')=='research_journal'),len(claims),len({b.get('text','') for b in row.get('article',{}).get('blocks',[])}))


def unique_ready(rows):
    selected=[]
    for row in rows:
        same=next((old for old in selected if duplicate(row,old)),None)
        if same is None:selected.append(row)
        elif usefulness(row)>usefulness(same):selected[selected.index(same)]=row
    return selected


def ready(state):
    try:from scripts import editorial43
    except ImportError:import editorial43
    rows=editorial43.select_ready(state)
    return rows if state.get('special43_revision') else unique_ready(rows)


def recent(root,date,days=14):
    result=[];cutoff=datetime.fromisoformat(date).date()-timedelta(days=days)
    for path in Path(root).glob('issues/*/articles/*/index.html'):
        day=path.parts[-4]
        try:published=datetime.fromisoformat(day).date()
        except ValueError:continue
        if not cutoff<=published<datetime.fromisoformat(date).date():continue
        text=path.read_text();heading=re.search(r'<h1[^>]*>(.*?)</h1>',text,re.S)
        if heading:result.append({'title':re.sub('<[^>]+>','',heading[1])})
    return result


def order(state,history=()):
    selected=ready(state);pending=[r for r in state['candidates'] if r.get('status') in ('preparing','retryable_error','discovered')];result=[]
    category=Counter(r.get('category_hint') or r.get('category','') for r in selected)
    places=Counter(profile(r)['place'] for r in selected);publishers=Counter(profile(r)['publisher'] for r in selected);orgs=Counter(profile(r)['organisation'] for r in selected)
    space=sum(profile(r)['space'] for r in selected)
    while pending:
        def score(r):
            p=profile(r);cat=r.get('category_hint') or r.get('category','')
            return (int(r.get('status')=='discovered'),int(any(duplicate(r,h) for h in history))*3+
                int(p['space'] and space>=1)*5+int(bool(p['place']) and places[p['place']]>=1)*3+
                int(publishers[p['publisher']]>=2)*2+int(bool(p['organisation']) and orgs[p['organisation']]>=2)*2+category[cat])
        row=min(pending,key=score);pending.remove(row);result.append(row);p=profile(row)
        category[row.get('category_hint') or row.get('category','')]+=1;places[p['place']]+=1;publishers[p['publisher']]+=1;orgs[p['organisation']]+=1;space+=p['space']
    return result


def title_report(rows):
    values=[title(r).strip() for r in rows]
    openings=Counter(normalized(t).split()[0] for t in values if normalized(t).split())
    return {'titles':len(values),'how_openings':sum(bool(re.match(r'(?i)^как\b',t)) for t in values),'repeated_openings':sum(n-1 for n in openings.values() if n>1),'advisory_only':True}


def prompt_context(state):
    return {'selected':[{'title':title(r),'place':profile(r)['place']} for r in ready(state)],'style':title_report(ready(state))}
