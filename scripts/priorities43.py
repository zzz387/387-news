"""Explainable personal-interest preferences. Never a publication gate or AI call."""
import json,re
from functools import lru_cache
from collections import Counter
from datetime import datetime,timedelta
from html import unescape
from urllib.parse import urlparse
from scripts import policy41 as p

RULES_VERSION=3
CORE_GROUPS=('A','B','C')

CONFIG=json.loads((p.ROOT/'config/editorial_priorities43.json').read_text())
DIRECTIONS={d['id']:d for d in CONFIG['directions']}
PATTERNS={i:re.compile(d['pattern'],re.I) for i,d in DIRECTIONS.items()}


def classify(row):
    article=row.get('article',{});source=row.get('source',{})
    title=' '.join(str(x or '') for x in (article.get('title'),row.get('title'),source.get('title'),row.get('topic_key')))
    text=title+' '+str(article.get('teaser',''))+' '+str(row.get('summary',''))
    if not article and source.get('full_text_verified'):
        text+=' '+' '.join(b.get('text','') for b in source.get('blocks',[])[:8])
    if article:
        text=' '.join(str(article.get(k,'')) for k in ('title','teaser'))+' '+' '.join(b.get('text','') for b in article.get('blocks',[])[:8])
    return dict(_classify(text,tuple(i for i in row.get('priority_ids',[]) if i in DIRECTIONS),'Общество'))


@lru_cache(maxsize=2048)
def _classify(text,hints,fallback):
    scores={i:len(rx.findall(text)) for i,rx in PATTERNS.items() if rx.search(text)}
    computing=bool(re.search(r'(?i)machine learning|neural network|нейросет|software architecture|computer architecture|model architecture|training (?:a |the )?model|обучени[ея] (?:модел|нейросет)|нейронн.{0,10}сет',text))
    if computing:
        if not re.search(r'(?i)child|parent|toddler|дет[иеяй]|реб[её]н|родител',text):scores.pop(1,None)
        if not re.search(r'(?i)building|interior|museum|здани|интерьер|усадьб',text):scores.pop(11,None)
        if not re.search(r'(?i)cardio|aerobic|exercise|вынослив|кардио|физиолог',text):scores.pop(13,None)
    if re.search(r'(?i)космическ.{0,20}путешеств|путешеств.{0,20}(?:марс|лун|косм)|space travel|voyage to mars',text) and not re.search(r'(?i)маршрут|турист|weekend|moscow|моск',text):scores.pop(8,None)
    # A publisher's coverage is a weak tie-breaker, not proof that every story matches it.
    ordered=sorted(scores,key=lambda i:(-scores[i],-int(i in hints),i))
    primary=ordered[0] if ordered else None
    direction=DIRECTIONS.get(primary,{})
    return {'group':direction.get('group','general'),'direction':primary,'additional_directions':ordered[1:],
            'category':direction.get('category',general_category(text)),
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
    if c['direction']==14:
        distances=re.findall(r'(?i)\b(\d{1,3})\s*(?:км|kilomet(?:er|re)s?|km)\b',title)
        useful+=3*int(any(20<=int(n)<=60 for n in distances))
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
    """Distinct A/B/C search appointments, then rotate the remaining publishers."""
    counts=weekly(history,date)
    def key(row):
        ids=[i for i in row.get('priority_ids',[]) if i in DIRECTIONS]
        missing=sum(not counts[i] for i in ids)
        checked=cache.get('publishers',{}).get(row['id'],{}).get('checked_at','')
        return (not bool(ids),-missing/max(1,len(ids)),checked,-row.get('editorial_priority',50),row['id'])
    pending=list(rows);result=[]
    groups=sorted(CORE_GROUPS,key=lambda g:(sum(counts[i] for i,d in DIRECTIONS.items() if d['group']==g),CORE_GROUPS.index(g)))
    for group in groups:
        choices=[r for r in pending if any(DIRECTIONS.get(i,{}).get('group')==group for i in r.get('priority_ids',[]))]
        if not choices:continue
        row=min(choices,key=lambda r:(len({DIRECTIONS[i]['group'] for i in r.get('priority_ids',[]) if i in DIRECTIONS}),
            -min(2,cache.get('publishers',{}).get(r['id'],{}).get('eligible',r.get('availability',{}).get('full_originals_verified',0))),key(r)));pending.remove(row)
        result.append(dict(row,search_group=group))
    return result+sorted(pending,key=key)


def general_category(text):
    if re.search(r'(?i)parliament|congress|oversight|парламент|конгресс|правительств|government',text):return 'Общество'
    if re.search(r'(?i)искусств|живопис|art history|painting|renaissance|ренессанс',text):return 'История и культура'
    if re.search(r'(?i)строител|бетон|living materials|self.healing|construction|concrete',text):return 'Технологии'
    if re.search(r'(?i)физик|квант|астрон|косм|нейтрин|биолог|quantum|physics|neutrino|astronom|galax|particle|science|scientific',text):return 'Наука'
    return 'Общество'


def apply_rules(state,now):
    """Addressed metadata migration only. Reviewed articles and quota are immutable."""
    from scripts import catalog43
    catalog=catalog43.registry()
    versions={'rules_version':RULES_VERSION,'classifier_version':CONFIG['version'],
              'catalog_version':catalog['version'],'catalog_hash':p.digest(catalog)}
    previous=state.get('selection_policy43',{})
    changed=any(previous.get(k)!=v for k,v in versions.items())
    if changed:
        state.setdefault('history',[]).append({'code':'SELECTION_RULES_UPDATED','previous':previous.copy(),'current':versions.copy()})
        print('[selection-rules43] '+json.dumps(dict(versions,reviewed_articles_preserved=True,quota_preserved=True)),flush=True)
    for row in state['candidates']:
        if row.get('article') or row.get('status')=='ready':continue
        row['editorial43']=evaluate(row,state.get('_recent43',[]),state['date'])
        row['category_hint']=row['editorial43']['category']
        row['selection_versions43']=versions.copy()
    state['selection_policy43']=dict(versions,candidates_formed_at=previous.get('candidates_formed_at') or now.isoformat(),applied_at=now.isoformat())
    return changed


def report(state,rows,history):
    counts=Counter();groups=Counter();categories=Counter();pubs=Counter();languages=Counter();science=0
    for row in rows:
        c=classify(row);counts[c['direction']]+=1;groups[c['group']]+=1;categories[c['category']]+=1
        source=row.get('source',{});pubs[row.get('publisher_id') or source.get('publisher') or urlparse(row.get('url','')).netloc]+=1
        languages['russian' if source.get('language')=='ru' else 'foreign' if source.get('language') else 'unknown']+=1
        science+=int(c['category']=='Наука')
    total=len(rows);week=weekly(history,state['date']);projected=week.copy();projected.update({i:n for i,n in counts.items() if i})
    from scripts import selection43
    duplicate_count=len(rows)-len(selection43.unique_ready(rows))
    return {'version':2,'core_groups':{g:groups[g] for g in CORE_GROUPS},'missing_core_groups':[g for g in CORE_GROUPS if not groups[g]],
            'duplicate_stories':duplicate_count,'excluded_duplicate_stories':len(state.get('selection43',{}).get('excluded_duplicate_ids',[])),
            'family_articles':groups['A'],'children_articles':sum(bool(re.search(r'(?i)дет|реб[её]н|child|parent',str(r.get('article',{})))) for r in rows if classify(r)['group']=='A'),
            'health_sport_articles':groups['C'],'sport_articles':sum(classify(r)['direction'] in (13,14,15) for r in rows),
            'light_news':len(__import__('scripts.light43',fromlist=['ready']).ready(state)) if 'candidates' in state else None,
            'history_culture':categories['История и культура'],'nature_science':categories['Наука'],
            'economy_technology':categories['Экономика и бизнес']+categories['Технологии'],
            'date':state['date'],'stage':'prepared','published_main_articles':None,'prepared_main_articles':total,
            'priority_articles':total-counts[None],'directions':{str(i):n for i,n in counts.items() if i},
            'groups':dict(groups),'categories':dict(categories),'publishers':dict(pubs),'languages':dict(languages),
            'science_share':science/total if total else 0,'category_shares':{k:n/total for k,n in categories.items()},
            'missing_week':[i for i in DIRECTIONS if not week[i]],'missing_after_prepared':[i for i in DIRECTIONS if not projected[i]],'advisory_only':True}


def attach_evidence(row,state):
    """Reuse already verified, relevant independent evidence; never invent a reference URL."""
    from scripts import editorial43,editorial41,rights41
    if not editorial43.high_risk(row):return
    own=classify(row)['direction']
    if not own:return
    sources=row.setdefault('supporting_sources',[])
    if len(sources)>=2:return
    known={s['url'] for s in sources}|{row['url']}
    pool=list(state.get('source_cache',{}).values())+[r['source'] for r in state['candidates'] if r.get('source')]
    for source in sorted(pool,key=lambda s:not editorial41.host_matches(s['url'],editorial41.TRUSTED)):
        if source['url'] in known or not source.get('full_text_verified') or source.get('metadata_status')!='verified':continue
        if own not in [classify({'source':source})['direction']]+classify({'source':source})['additional_directions']:continue
        if rights41.decision(source,'INDEPENDENT_ARTICLE')['status']!='allowed':continue
        if editorial41.publisher_identity(source['url'])==editorial41.publisher_identity(row['url']):continue
        sources.append(source);known.add(source['url'])
        if len(sources)>=2:break


def reconsider_evidence(state):
    # Reopen only a missing-evidence hold when genuinely new verified sources exist.
    # Article/final-review counters and all previous refusals remain unchanged.
    from scripts import editorial43
    basis=p.digest({'risk_version':editorial43.RISK_VERSION,'sources':sorted((url,src.get('content_hash')) for url,src in state.get('source_cache',{}).items() if src.get('full_text_verified'))})
    for row in state['candidates']:
        if row.get('status')!='deferred' or row.get('support_basis43')==basis:continue
        failures=[h.get('code') for h in row.get('history',[]) if h.get('stage')=='v43_final']
        if not failures or failures[-1] not in ('INDEPENDENT_SAFETY_EVIDENCE_REQUIRED','SAFETY_EVIDENCE_INCOMPLETE'):continue
        row['support_basis43']=basis;attach_evidence(row,state)
        if editorial43.safety_sources_valid(row):
            row['status']='preparing';row['history'].append({'code':'NEW_INDEPENDENT_EVIDENCE_AVAILABLE','stage':'source43'})


def cited_verification_urls(row):
    """Only actual links in a complete original; no guessed law/medical endpoints."""
    from scripts import editorial41,source41
    urls=[]
    for block in row.get('source',{}).get('blocks',[]):
        for url in block.get('links',[]):
            if not isinstance(url,str) or not urlparse(url).path.strip('/') or url in urls or url==row.get('url'):continue
            if not editorial41.host_matches(url,editorial41.TRUSTED):continue
            try:source41.safe_url(url)
            except p.Blocked:continue
            urls.append(url)
            if len(urls)>=6:return urls
    return urls


def published_report(root=None,check_public=None):
    """Aggregate already PUBLIC, HTTPS-verified final pages; never decrypt a draft."""
    from pathlib import Path
    from scripts import selection43,site_checks,publication43,source_dom41
    root=Path(root or p.ROOT);live=(check_public or site_checks.check_site)()
    if live.get('https')!='verified' or live.get('policy_version')!='4.3':raise ValueError('PUBLIC_COMPOSITION_NOT_VERIFIED')
    date=live['issue_date'];metadata=publication43.validate(root,date)
    if metadata['article_count']!=live['articles']:raise ValueError('PUBLIC_COMPOSITION_COUNT_MISMATCH')
    rows=[]
    for path in sorted((root/'issues'/date/'articles').glob('*/index.html')):
        doc=source_dom41.Document();doc.feed(path.read_text());nodes=list(doc.root.all())
        headline=next(n.text() for n in nodes if n.tag=='h1')
        summary=next((n.text()[:1500] for n in nodes if 'article-body' in n.attrs.get('class','').split()),'')
        marker=next((n for n in nodes if n.attrs.get('data-source-links-version')=='1'),None)
        link=next((n for n in nodes if 'source-original' in n.attrs.get('class','').split()),None)
        meta=next((n.text() for n in nodes if n.attrs.get('class')=='meta'),'Наука')
        if marker is None or link is None:raise ValueError('PUBLIC_SOURCE_METADATA_REQUIRED')
        publisher=marker.text().split('Источник:',1)[-1].split(' — ',1)[0].strip()
        language=marker.attrs.get('data-source-language')
        rows.append({'title':headline,'summary':summary,'category_hint':meta.split(' · ',1)[0],
                     'source':{'url':link.attrs['href'],'publisher':publisher,'language':None if language=='und' else language}})
    if len(rows)!=live['articles']:raise ValueError('PUBLIC_COMPOSITION_COUNT_MISMATCH')
    result=report({'date':date},rows,selection43.recent(root,date))
    result.update(stage='published_verified',published_main_articles=len(rows),https_verified=True,
                  verified_at=datetime.now(p.TZ).isoformat(),missing_week=result['missing_after_prepared'])
    return result


if __name__=='__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser();parser.add_argument('--published-report',action='store_true',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    result=published_report();Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('[editorial-composition43] '+json.dumps({'date':result['date'],'published_main_articles':result['published_main_articles'],'https_verified':True,'advisory_only':True}))
