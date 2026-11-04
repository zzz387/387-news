"""Explainable personal-interest preferences. Never a publication gate or AI call."""
import json,re
from collections import Counter
from datetime import datetime,timedelta
from html import unescape
from urllib.parse import urlparse
from scripts import policy41 as p

CONFIG=json.loads((p.ROOT/'config/editorial_priorities43.json').read_text())
DIRECTIONS={d['id']:d for d in CONFIG['directions']}
PATTERNS={i:re.compile(d['pattern'],re.I) for i,d in DIRECTIONS.items()}


def classify(row):
    article=row.get('article',{});source=row.get('source',{})
    title=' '.join(str(x or '') for x in (article.get('title'),row.get('title'),source.get('title'),row.get('topic_key')))
    text=title+' '+str(article.get('teaser',''))+' '+str(row.get('summary',''))
    scores={i:len(rx.findall(text)) for i,rx in PATTERNS.items() if rx.search(text)}
    # A publisher's coverage is a weak tie-breaker, not proof that every story matches it.
    hints=[i for i in row.get('priority_ids',[]) if i in DIRECTIONS]
    ordered=sorted(scores,key=lambda i:(-scores[i],-int(i in hints),i))
    primary=ordered[0] if ordered else None
    direction=DIRECTIONS.get(primary,{})
    return {'group':direction.get('group','general'),'direction':primary,'additional_directions':ordered[1:],
            'category':direction.get('category',row.get('category_hint') or row.get('category') or 'Наука'),
            'signals':{str(i):scores[i] for i in ordered}}


def weekly(history,date):
    counts=Counter();cutoff=datetime.fromisoformat(date).date()-timedelta(days=CONFIG['compensation_days'])
    for row in history:
        if row.get('date') and datetime.fromisoformat(row['date']).date()<cutoff:continue
        c=classify(row)
        if c['direction']:counts[c['direction']]+=1
    return counts


def evaluate(row,history=(),date=None,selected=()):
    from scripts import selection43 as selection
    c=classify(row);counts=weekly(history,date) if date else Counter()
    novelty=0 if any(selection.duplicate(row,h) for h in history) else 10
    quality=max(0,min(100,int(row.get('quality_score',50))))
    interest=max(0,min(100,int(row.get('editorial_priority',50))))
    title=' '.join(str(x) for x in (row.get('title',''),row.get('source',{}).get('title',''),row.get('article',{}).get('title','')))
    useful=10 if re.search(r'(?i)маршрут|заняти|семейн|практик|велосип|банкрот|йог|route|parent|family|cycling|how to',title) else 5
    diversity=10-sum(classify(r)['group']==c['group'] for r in selected)
    return dict(c,interest=interest,source_quality=quality,novelty=novelty,usefulness=useful,
                diversity=diversity,weekly_compensation=12 if c['direction'] and not counts[c['direction']] else 0)


def preference(row,history,date,selected):
    score=evaluate(row,history,date,selected)
    priority_count=sum(bool(classify(r)['direction']) for r in selected)
    target=CONFIG['priority_target']
    # Nine personal-interest places and three open places are preferences only.
    preferred=bool(score['direction']) if priority_count<target else not bool(score['direction'])
    group_count=sum(classify(r)['group']==score['group'] for r in selected)
    dir_count=sum(classify(r)['direction']==score['direction'] for r in selected)
    value=(score['weekly_compensation']+score['interest']/20+score['source_quality']/20+
           score['usefulness']+score['novelty']-group_count*6-dir_count*5)
    return (int(not preferred),-value)


def publisher_order(rows,cache,history,date):
    """Search missing directions first; cached timestamps prevent one easy site monopolising search."""
    counts=weekly(history,date)
    def key(row):
        ids=row.get('priority_ids',[])
        missing=sum(not counts[i] for i in ids)
        checked=cache.get('publishers',{}).get(row['id'],{}).get('checked_at','')
        return (not bool(ids),checked, -min(missing,3),-row.get('editorial_priority',50),row['id'])
    # Within equally old/fresh publishers, compensate sparse groups/directions dynamically.
    result=[];covered=Counter()
    pending=list(rows)
    while pending:
        row=min(pending,key=lambda r:(key(r)[0],key(r)[1],sum(covered[i] for i in r.get('priority_ids',[])),*key(r)[2:]))
        result.append(row);pending.remove(row);covered.update(row.get('priority_ids',[]))
    return result


def report(state,rows,history):
    counts=Counter();groups=Counter();categories=Counter();pubs=Counter();languages=Counter();science=0
    for row in rows:
        c=classify(row);counts[c['direction']]+=1;groups[c['group']]+=1;categories[c['category']]+=1
        source=row.get('source',{});pubs[row.get('publisher_id') or source.get('publisher') or urlparse(row.get('url','')).netloc]+=1
        languages['russian' if source.get('language')=='ru' else 'foreign' if source.get('language') else 'unknown']+=1
        science+=int(row.get('science_source',row.get('category_hint')=='Наука'))
    total=len(rows);week=weekly(history,state['date']);week.update({i:n for i,n in counts.items() if i})
    return {'version':1,'date':state['date'],'stage':'prepared','published_main_articles':None,'prepared_main_articles':total,
            'priority_articles':total-counts[None],'directions':{str(i):n for i,n in counts.items() if i},
            'groups':dict(groups),'categories':dict(categories),'publishers':dict(pubs),'languages':dict(languages),
            'science_share':science/total if total else 0,'category_shares':{k:n/total for k,n in categories.items()},
            'missing_week':[i for i in DIRECTIONS if not week[i]],'advisory_only':True}


def attach_evidence(row,state):
    """Reuse already verified, relevant independent evidence; never invent a reference URL."""
    from scripts import editorial43,editorial41,rights41
    if not editorial43.high_risk(row):return
    own=classify(row)['direction']
    if not own:return
    sources=row.setdefault('supporting_sources',[]);known={s['url'] for s in sources}|{row['url']}
    pool=list(state.get('source_cache',{}).values())+[r['source'] for r in state['candidates'] if r.get('source')]
    for source in pool:
        if source['url'] in known or not source.get('full_text_verified') or source.get('metadata_status')!='verified':continue
        if own not in [classify({'source':source})['direction']]+classify({'source':source})['additional_directions']:continue
        if rights41.decision(source,'INDEPENDENT_ARTICLE')['status']!='allowed':continue
        if editorial41.publisher_identity(source['url'])==editorial41.publisher_identity(row['url']):continue
        sources.append(source);known.add(source['url'])
        if len(sources)>=2:break
