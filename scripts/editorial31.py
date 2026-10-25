#!/usr/bin/env python3
"""387 News 3.1 — source-grounded editor with a strict publication veto.

Keeps existing news.py scraping, free Gemini client and HTML templates, and
staged_news.py's AES-GCM checkpoint format. External model reviews are useful
signals, NOT guaranteed independent fact-checks. Fail closed on weak evidence.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
from urllib.parse import urljoin
import json
import re
from urllib.parse import urlparse

try:
    from scripts import news
except ImportError:
    import news

MIN_SHORT = 440
MIN_LONG = 1050
TARGET_TOTAL = 5000
MAX_WORDS = 2200
LIFE = set(news.VALID_CATEGORIES[:3])
GENERIC_URLS = {'https://www.unicef.org/parenting', 'https://www.mos.ru/afisha/',
                'https://www.who.int/news-room/fact-sheets/detail/physical-activity',
                'https://www.who.int/news-room/fact-sheets/detail/healthy-diet'}
SOFT_PRESS_RELEASE = ('подписала соглашения', 'началось строительство', 'построят',
                      'состоялось совещание', 'открывает партнерство', 'сотрудничестве с регионами')
STYLE_RED_FLAGS = ('современный мир', 'в современном мире', 'богатейшее наследие',
                   'динамично развивающ', 'уникальная возможность', 'масштабные проекты',
                   'знаковый проект', 'в условиях стремительно меняющегося',
                   'сложно переоценить', 'не секрет, что', 'каждый человек,',
                   'играет ключевую роль в современном', 'выдающийся пример',
                   'свидетельствует о важности', 'полностью отвечает стратегическим')


def _schema(properties: dict, required: list[str]):
    return {'type': 'object', 'properties': properties, 'required': required}

S = {'type':'string'}
I = {'type':'integer'}
B = {'type':'boolean'}

news.SCHEMAS.update({
    'candidate31': _schema({'candidates':{'type':'array', 'items':_schema({
        'title': S, 'category':{'type':'string','enum':list(news.VALID_CATEGORIES)},
        'kind': S, 'source_ids':{'type':'array','items':S}, 'hook': S,
        'why_now': S, 'novelty':I, 'reader_interest':I,
        'specificity':I, 'evidence':I, 'fit':I, 'long':B},
        ['title','category','kind','source_ids','hook','why_now','novelty',
         'reader_interest','specificity','evidence','fit','long'])},
    },['candidates']),
    'plan31': news.SCHEMAS['plan'],
    'dossier31': _schema({'angle':S, 'chronology':S, 'stakes':S,
        'claims':{'type':'array','items':_schema({'source_id':S,'quote':S,'explanation':S},
                                               ['source_id','quote','explanation'])}},
        ['angle','chronology','stakes','claims']),
    'review31': _schema({'approve':B,'reasons':{'type':'array','items':S},
         'unsupported':{'type':'array','items':S}, 'strength':I},
         ['approve','reasons','unsupported','strength']),
    'issue31': _schema({'approve':B,'reasons':{'type':'array','items':S}},
                        ['approve','reasons']),
})


def wc(value):
    return news.count_words(value)


def normalized(s):
    return re.sub(r'\s+', ' ', s).strip().casefold().replace('ё','е')


def domains(sources):
    return {urlparse(s['url']).netloc.lower().removeprefix('www.') for s in sources}


def meaningfully_same(a, b):
    aa=normalized(a); bb=normalized(b)
    return SequenceMatcher(None, aa, bb).ratio()>0.79


def candidate_score(c):
    return sum(max(0, min(5, int(c.get(k,0)))) for k in
               ('novelty','reader_interest','specificity','evidence','fit'))


def _read_sources(sources):
    return {s['id']:s for s in sources}


def _reference_quality(s):
    url=s.get('url','').rstrip('/')
    weak=(s.get('abstract_only') or len(s.get('evidence','').strip())<1100 or
          url in {x.rstrip('/') for x in GENERIC_URLS})
    return not weak


def shortlist(sources, date):
    """Stage 1: grade 20+ concrete stories, not 8 titles from press-release RSS."""
    if len(sources)<16:
        raise RuntimeError('Fewer than 16 sources; editorial selection would be weak')
    catalog=news.json_catalog(sources,max_n=95)
    prompt=f'''Ты не автор, а требовательный редактор 387 News. Дата выпуска (Москва): {date}.
Источники с реальными выдержками: {json.dumps(catalog,ensure_ascii=False)}
Уже использованные ранее заголовки: {json.dumps(news.previous_titles(),ensure_ascii=False)}
Выбери 20–30 действительно разных КОНКРЕТНЫХ сюжетов-кандидатов; для каждого 1–3 реально существующих source_ids.
Критично: при наличии подходящих материалов постарайся представить не менее 3
сильных разных кандидатов для каждой из рубрик «Семья», «Москва и путешествия»,
«Здоровье и движение». Если оригинальные источники не подтверждают нужную тему —
НЕ ПРИДУМЫВАЙ её ради соблюдения квоты. Если есть достаточно материала, предложи
не менее 3 тем для больших очерков; также не выдумывай содержание ради нормы.
Ставь каждой теме ПЯТЬ ОТДЕЛЬНЫХ оценок от 0 до 5: novelty, reader_interest,
specificity, evidence, fit. Низкая оценка у скучных пресс-релизов, обзоров главных
страниц сайтов, общих советов без открытия, рутинного строительства, сплетен, спорта.
Каждый кандидат должен иметь не пересказанную тему, а проверяемый конкретный факт,
интригу, конфликт, малоизвестный механизм или полезную доступную активность.
Семья; музеи/выставки/поездки в Москве; питание/йога/кардио/велосипед 20–60 км
получают приоритет, но не автоматический пропуск в номер. История и культура,
наука, экономика/бизнес — только сильные сюжеты. Не объединяй разнородные новости.
В kind="новость" укажи только то, что действительно произошло/опубликовано
в последние 72 часа. Старый научный результат при свежей перепубликации — НЕ новость.
Не выдумывай источники, даты и факты. Вывод только JSON candidates с полями
из схемы; выдуманную сенсацию оценивать низко. Чем меньше фактов — тем ниже evidence.'''
    answer=news.gemini(prompt,output_tokens=13500,schema='candidate31')
    original=_read_sources(sources)
    chosen=[]; seen=[]
    for c in answer.get('candidates',[]):
        if not isinstance(c,dict) or c.get('category') not in news.VALID_CATEGORIES:
            continue
        ids=c.get('source_ids') or []
        if not (1<=len(ids)<=3 and all(i in original for i in ids)):
            continue
        if candidate_score(c)<19 or min(c.get('evidence',0),c.get('specificity',0))<3:
            continue
        if any(meaningfully_same(c.get('title',''),t) for t in seen+news.previous_titles()):
            continue
        selected_sources=[original[i] for i in ids]
        if not any(_reference_quality(x) for x in selected_sources):
            continue
        if c.get('kind','').strip().lower()=='новость' and not any(x.get('recent') and not x.get('evergreen') for x in selected_sources):
            continue
        if c.get('long') and not any(len(x.get('evidence',''))>=2300 and not x.get('abstract_only') for x in selected_sources):
            continue
        if any(normalized(c.get('title','')).startswith(x) for x in ('все о ', 'как улучшить жизнь', 'общие рекомендации')):
            continue
        # An evergreen landing page is not evidence of a new exhibit or event.
        if all(x.get('evergreen') for x in selected_sources) and c.get('kind','').strip().lower()=='новость':
            continue
        seen.append(c.get('title',''))
        c['score']=candidate_score(c)
        chosen.append(c)
    chosen.sort(key=lambda x:x['score'],reverse=True)
    if len(chosen)<12:
        raise RuntimeError(f'Only {len(chosen)} editorially plausible candidates; refuse to pad issue')
    # Preserve strong life candidates in the top 30 even when a large science
    # news cycle would otherwise crowd them out. Still use exactly the same
    # pre-vetted threshold and evidence checks — never pad with weak candidates.
    anchors=[]
    for category in news.VALID_CATEGORIES[:3]:
        anchors += [x for x in chosen if x['category']==category][:4]
    anchors += [x for x in chosen if x.get('long')][:4]
    prioritized=[]; seen_titles=set()
    for c in anchors+chosen:
        tag=normalized(c['title'])
        if tag not in seen_titles:
            seen_titles.add(tag)
            prioritized.append(c)
        if len(prioritized)==30:
            break
    return sorted(prioritized,key=lambda x:(-x['score'],normalized(x['title'])))


def select_balanced_plan(candidates: list[dict], sources: list[dict]) -> list[dict]:
    """Choose a source-backed, category-balanced issue without trusting an LLM's
    ability to count rubrics. The model only suggests and scores candidates.

    Fail closed if eligible sources cannot support the promised editorial mix.
    Never add invented items or lower the candidate-quality threshold.
    """
    candidates=sorted(candidates, key=lambda c:(-c['score'], normalized(c['title'])))
    cat_avail=Counter(c['category'] for c in candidates)
    long_avail=sum(bool(c.get('long')) for c in candidates)
    life_avail=sum(c['category'] in LIFE for c in candidates)
    missing=[c for c in news.VALID_CATEGORIES[:3] if cat_avail[c]==0]
    if missing or life_avail<4 or long_avail<2 or len(candidates)<8:
        available=', '.join(f'{cat}: {cat_avail[cat]}' for cat in news.VALID_CATEGORIES[:3])
        raise RuntimeError(
            'Insufficient eligible editorial candidates; missing life rubrics: '
            +(', '.join(missing) if missing else 'none')+'; '+available
            +f'; life {life_avail}/4, long {long_avail}/2, total {len(candidates)}/8. '
            'Do not invent stories; improve source discovery and rerun plan.'
        )
    lookup=_read_sources(sources)
    n=len(candidates)
    # Upper bounds help stop infeasible searches early without relaxing rules.
    suffix_life=[0]*(n+1); suffix_long=[0]*(n+1)
    suffix_cats={c:[0]*(n+1) for c in LIFE}
    for pos in range(n-1,-1,-1):
        c=candidates[pos]
        suffix_life[pos]=suffix_life[pos+1]+int(c['category'] in LIFE)
        suffix_long[pos]=suffix_long[pos+1]+int(bool(c.get('long')))
        for cat in LIFE:
            suffix_cats[cat][pos]=suffix_cats[cat][pos+1]+int(c['category']==cat)
    counts=Counter(); source_use=Counter(); names=set()
    picked=[]; result=None; explored=0

    def recurse(pos:int, life_count:int, long_count:int):
        nonlocal result,explored
        explored+=1
        if explored>750_000:
            raise RuntimeError('Balanced issue search exceeded computational budget; '
                               'inspect sources and category constraints')
        slots=8-len(picked)
        if slots==0:
            if life_count>=4 and long_count>=2 and all(counts[cat]>=1 for cat in LIFE):
                result=picked.copy()
                return True
            return False
        if n-pos<slots or life_count+suffix_life[pos]<4 or long_count+suffix_long[pos]<2:
            return False
        if any(counts[cat]==0 and suffix_cats[cat][pos]==0 for cat in LIFE):
            return False
        missing_count=sum(counts[cat]==0 for cat in LIFE)
        if missing_count>slots:
            return False
        if pos>=n:
            return False
        c=candidates[pos]
        cat=c['category']; title=normalized(c['title'])
        source_ids=c['source_ids']
        eligible=(counts[cat]<(3 if cat in LIFE else 2) and title not in names
                  and all(source_use[sid]<2 for sid in source_ids)
                  and all(sid in lookup for sid in source_ids)
                  and (long_count+int(bool(c.get('long')))<=3)
                  and (cat in LIFE or life_count+slots-1+suffix_life[pos+1]>=4))
        if eligible:
            counts[cat]+=1; names.add(title)
            for sid in source_ids:source_use[sid]+=1
            picked.append(c)
            if recurse(pos+1, life_count+int(cat in LIFE),long_count+int(bool(c.get('long')))):
                return True
            picked.pop(); names.remove(title); counts[cat]-=1
            for sid in source_ids:source_use[sid]-=1
        return recurse(pos+1,life_count,long_count)

    if not recurse(0,0,0):
        available=', '.join(f'{cat}: {cat_avail[cat]}' for cat in news.VALID_CATEGORIES[:3])
        raise RuntimeError('No feasible eight-story editorial plan with mandatory rubrics, '
                           '2-3 source-supported longforms, diverse topics, and <=2 uses of '
                           'any source; '+available+'. Revise source pool; never pad.')
    assert result is not None
    # Reuse only candidates already admitted by shortlist; no additional
    # synthetic titles, new sources, events or invented journalist claims.
    plan=[]
    for c in result:
        plan.append({'title':c['title'],'category':c['category'],'kind':c['kind'],
                     'source_ids':list(c['source_ids']),
                     'angle':c.get('hook') or c.get('why_now') or c['title'],
                     'long':bool(c.get('long')),'editorial_score':c['score'],
                     'hook':c.get('hook','')})
    print('[plan] balanced source-backed selection: '
          +', '.join(f'{cat}={sum(q["category"]==cat for q in plan)}'
                      for cat in news.VALID_CATEGORIES)
          +f'; long={sum(q["long"] for q in plan)}; reviewed={len(candidates)}',
          flush=True)
    return plan


def choose_plan(sources,date):
    # Version 3.1 originally asked Gemini to choose exactly 8 from its own
    # shortlist, then rejected the output if it omitted mandatory rubrics.
    # That was an unreliable prompt-following/counting step. Keep Gemini for
    # suggesting & scoring candidates; enforce selection deterministically.
    candidates=shortlist(sources,date)
    canonical=select_balanced_plan(candidates,sources)
    return canonical,candidates



class _StudyLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs=[]
    def handle_starttag(self,tag, attrs):
        if tag=='a':
            href=dict(attrs).get('href','')
            if href:self.hrefs.append(href)


def enrich_originals(sources, plan):
    """Find actual study links from selected aggregator stories where possible.

    Never invent an original paper or treat the date of a secondary report as
    the study's publication date. A missing original is annotated, not hidden.
    """
    primary_domains=('doi.org','nature.com','science.org','cell.com',
                     'journals.plos.org','pubmed.ncbi.nlm.nih.gov',
                     'pnas.org','thelancet.com','bmj.com','arxiv.org',
                     'nasa.gov','esa.int','nih.gov')
    lookup={s['id']:s for s in sources}
    known_urls={s['url'].rstrip('/') for s in sources}
    for item in plan:
        if item['category'] not in ('Наука','Здоровье и движение'):
            continue
        supporting=[lookup[i] for i in item['source_ids']]
        if any(any(domain in urlparse(s['url']).netloc for domain in primary_domains)
               for s in supporting):
            item['original_study_found']=True
            continue
        item['original_study_found']=False
        chosen=[]
        for secondary in supporting[:2]:
            try:
                raw=news.http_get(secondary['url'],limit=260_000,timeout=12).decode('utf-8','replace')
                h=_StudyLinks(); h.feed(raw)
                for href in h.hrefs:
                    u=urljoin(secondary['url'],href)
                    if (u.startswith('https://') and
                        any(domain in urlparse(u).netloc for domain in primary_domains) and
                        u.rstrip('/') not in known_urls):
                        chosen.append(u)
            except Exception:
                continue
        for u in list(dict.fromkeys(chosen))[:3]:
            obj={'title':'Первичный источник научной работы','url':u,
                 'published':'Дата исходной работы должна быть проверена отдельно',
                 'feed':'Оригинальное исследование','evergreen':True,
                 'summary':'','recent':False}
            try:
                obj=news.fetch_page(obj)
            except Exception:
                obj=None
            if not obj or obj.get('abstract_only') or len(obj.get('evidence',''))<900:
                continue
            new_id=f'S{len(sources)+1:03d}'
            obj['id']=new_id
            sources.append(obj)
            lookup[new_id]=obj
            known_urls.add(u.rstrip('/'))
            item['source_ids'].append(new_id)
            item['original_study_found']=True
            break
    for item in plan:
        if (item['category'] in ('Наука','Здоровье и движение')
                and item['kind'].lower()=='новость'
                and not item.get('original_study_found',False)):
            raise RuntimeError('New scientific result has no original accessible study or official release; veto')
    return sources, plan


def make_dossier(plan, source_map, date):
    """Stage 2: extract verifiable claims before drafting any prose."""
    sources=[source_map[sid] for sid in plan['source_ids']]
    bundle=[{'id':s['id'],'title':s['title'],'date':s['published'],
             'url':s['url'],'excerpt':s['evidence'][:7000],
             'abstract_only':bool(s.get('abstract_only'))} for s in sources]
    prompt=f'''Создай закрытое журналистское досье, НЕ статью, на {date}.
Утверждённый сюжет: {json.dumps(plan,ensure_ascii=False)}
ДОКАЗАТЕЛЬСТВА: {json.dumps(bundle,ensure_ascii=False)}
Извлеки 7–13 НЕПОВТОРЯЮЩИХСЯ конкретных фактов, включая имена, числа,
проверяемую хронологию, интересный механизм. Для каждого укажи source_id,
quote — ТОЧНЫЙ НЕПРЕРЫВНЫЙ фрагмент текста источника длиной 20–220
символов (можно на языке источника), и explanation — что именно подтверждает.
Не добавляй фактов из памяти. Не путай дату публикации СМИ с датой научной
статьи или самого события. Если дата события не дана — честно напиши 'не установлена'.
Не придумывай расписание, билеты, адреса, расценки и медицинские результаты.
Наличие оригинального исследования: {plan.get('original_study_found', 'не проверено')}.
Если original_study_found=False, приписывать открытию дату свежего пересказа строго запрещено.
Дай angle, chronology, stakes, claims как JSON. Цель — избежать растянутого
пересказа, спекуляций и псевдонаучных сенсаций.'''
    result=news.gemini(prompt,output_tokens=8500,schema='dossier31')
    clean=[]; distinct=set()
    for claim in result.get('claims',[]):
        if not isinstance(claim,dict):continue
        sid=claim.get('source_id'); quote=claim.get('quote','').strip()
        if sid not in source_map or sid not in plan['source_ids'] or not 20<=len(quote)<=240:
            continue
        # Literal source grounding, not the model's word for it.
        if normalized(quote) not in normalized(source_map[sid].get('evidence','')):
            continue
        tag=(sid,normalized(quote))
        if tag in distinct:continue
        distinct.add(tag)
        clean.append({'source_id':sid,'quote':quote,'explanation':claim.get('explanation','')[:450]})
    min_claims=8 if plan['long'] else 5
    if len(clean)<min_claims:
        raise RuntimeError(f'Insufficient exact source evidence ({len(clean)}/{min_claims}); no invented facts')
    result['claims']=clean
    return result


def article_body(a):
    return ' '.join(p.get('text','') for p in a.get('paragraphs',[]) if isinstance(p,dict))


def style_flags(a):
    body=normalized(article_body(a)); opening=normalized((a.get('paragraphs') or [{}])[0].get('text',''))
    flags=[t for t in STYLE_RED_FLAGS if t in body]
    if opening.startswith(('современный ', 'в современном мире', 'москва продолжает',
                            'всемирная организация ', 'каждый человек,', 'в условиях')):
        flags.append('generic opening')
    return sorted(set(flags))


def article_form(a, plan):
    ps=a.get('paragraphs') or []
    body=article_body(a); n=wc(body)
    if len(ps)<7 or any(not isinstance(p,dict) or len(p.get('text','').strip())<65 for p in ps):
        raise ValueError('Incomplete paragraphs')
    minimum=MIN_LONG if plan['long'] else MIN_SHORT
    if n<minimum or n>MAX_WORDS:
        raise ValueError(f'{n} words; required {minimum}–{MAX_WORDS}')
    if len(style_flags(a))>=2:
        raise ValueError('Banal/promotional writing: '+', '.join(style_flags(a)[:3]))
    if not 20<=len(a.get('title',''))<=185 or wc(a.get('teaser',''))<25:
        raise ValueError('Title or teaser is incomplete')
    return n


def write_from_dossier(plan, dossier, date, revision_reason=''):
    """Stage 3: narrative from vetted quotations, never freeform ungrounded recap."""
    facts=[{'source_id':x['source_id'],'source_quote':x['quote'],
            'verified_point':x['explanation']} for x in dossier['claims']]
    goal='1250–1550' if plan['long'] else '570–720'
    prompt=f'''Ты автор 387 News, сделай законченную СТАТЬЮ на русском языке.
Задание: {json.dumps(plan,ensure_ascii=False)}. Выпуск {date}.
ДОСЬЕ с ТОЧНО ПРОВЕРЕННЫМИ цитатами: {json.dumps(facts,ensure_ascii=False)}
Хронология: {dossier.get('chronology','')}. Что на кону: {dossier.get('stakes','')}.
Причина прежней редакторской браковки (если есть): {revision_reason[:1400]}
Нужен объём {goal} РУССКИХ СЛОВ В ОСНОВНОМ ТЕКСТЕ (не в анонсе).
Пиши связной прозой, НЕ списком, как интеллектуальный журналистский очерк.
Сильное конкретное первое предложение; сюжет — завязка, перипетии, детали,
точные объяснения и содержательный финал. Интеллект читателя уважай. НИКАКИХ
клише 'современный мир', 'богатейшее наследие', 'уникальные возможности',
общих похвал проектам, пресс-релизного тона, рекламных превосходных степеней.
Для московской афиши конкретная польза возможна только при наличии фактов
в досье, иначе пиши как очерк об истории места, не как анонс текущих дат.
Для науки: отделяй работу на клетках, на мышах и клинические результаты.
Не приписывай исходной статье новизну по дате перепубликации в СМИ.
Каждое конкретное имя, цифра, дата, место и утверждение о результатах
должно прямо следовать из досье. Не добавляй фантастических цитат и фактов.
Если данных не хватает для длинного текста, не раздувай текст — редактор
отклонит слабый результат. Верни JSON: title, teaser (50–90 слов),
paragraphs (не менее 8 объектов heading,text с естественной прозой).'''
    a=news.gemini(prompt,output_tokens=18000 if plan['long'] else 10500,schema='article')
    n=article_form(a,plan)
    a.update(category=plan['category'],kind=plan['kind'],long=bool(plan['long']),
             source_ids=list(plan['source_ids']),word_count=n,
             character_count=len(article_body(a)), editorial_score=plan['editorial_score'])
    return a


def verify_article(a,plan,dossier,lookup):
    snippets=[{'source_id':x['source_id'],'exact_quote':x['quote']}
              for x in dossier['claims']]
    body=article_body(a)
    prompt=f'''Ты независимый от автора строгий фактчекер 387 News.
Написанная статья: {a['title']}\n{body}
Проверенные ДОСЛОВНЫЕ выдержки из источников: {json.dumps(snippets,ensure_ascii=False)}
План: {json.dumps(plan,ensure_ascii=False)}
Найди КОНКРЕТНЫЕ неподтвержденные имена, даты, цифры, медицинские обещания,
сроки и цены мероприятий, ложную свежесть научных работ, притворную причинность,
пропагандистскую подачу, многословие, клише. Если нельзя по приведённым
выдержкам проверить конкретное утверждение — ОТКЛОНИ его, а не угадывай.
approve=true только если все проверяемые сведения подтверждены, сюжет интересен,
текст полон и нет существенной фальши. Дай причины и unsupported отдельно.
strength от 0 до 5. Ответ строго JSON.'''
    result=news.gemini(prompt,output_tokens=6500,schema='review31')
    if result.get('approve') is not True or result.get('unsupported') or result.get('strength',0)<4:
        msgs=(result.get('unsupported') or [])+(result.get('reasons') or [])
        raise ValueError('Independent review veto: '+('; '.join(str(x)[:180] for x in msgs[:3]) or 'weak story'))
    return True


def audit_issue(articles,plan,sources):
    if len(articles)!=8 or len(plan)!=8:raise ValueError('Incomplete issue')
    if not LIFE.issubset({a['category'] for a in articles}):
        raise ValueError('Mandatory rubrics missing')
    if sum(a['category'] in LIFE for a in articles)<4:
        raise ValueError('Not enough life / family / health content')
    if sum(bool(a.get('long')) for a in articles)<2:
        raise ValueError('Missing longform features')
    total=0; titles=[]
    for a,p in zip(articles,plan):
        if a.get('category')!=p['category'] or a.get('kind')!=p['kind']:
            raise ValueError('Article mismatched planned category/genre')
        total+=article_form(a,p)
        if any(meaningfully_same(a['title'],t) for t in titles):
            raise ValueError('Near-duplicate headlines')
        titles.append(a['title'])
    if total<TARGET_TOTAL:raise ValueError(f'Total {total} words < {TARGET_TOTAL}')
    summaries=[{'title':a['title'],'category':a['category'],
                'opening':a['paragraphs'][0]['text'][:340],
                'last':a['paragraphs'][-1]['text'][:260],
                'evidence_sources':[sources[s]['url'] for s in a['source_ids']]}
               for a in articles]
    result=news.gemini('Проведи финальную проверку разнообразия и литературного уровня номера 387 News. '
        'Бракуй повторяющиеся сюжеты, банальные зачины, пресс-релизы, сюжетно '
        'не связанные факты, рутинную рекламу и неинтересные материалы. '
        'Ни один вторичный пересказ не должен выдавать старое событие за новое. '
        'Верни JSON approve:boolean,reasons:string[]. Номер: '+
        json.dumps(summaries,ensure_ascii=False),output_tokens=4000,schema='issue31')
    if result.get('approve') is not True:
        raise ValueError('Issue editorial veto: '+'; '.join(result.get('reasons',[])[:4]))
    return total
