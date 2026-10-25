#!/usr/bin/env python3
"""387 News 3.2 — 20 approved longform priorities and an evidence-based veto.

Keeps existing news.py scraping, free Gemini client and HTML templates, and
staged_news.py's AES-GCM checkpoint format. External model reviews are useful
signals, NOT guaranteed independent fact-checks. Fail closed on weak evidence.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
from urllib.parse import urljoin
import json
import hashlib
import re
import os
import time
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
# User-approved priorities for full-length (roughly 1200–1800 word) features.
# Original topic numbering is preserved for traceability. Topic 19 (book
# histories) is NOT a longform priority. Ordinary coverage is not banned.
LONGFORM_TOPICS = {
    1: 'Воспитание и развитие детей',
    2: 'Семейные занятия и совместный досуг',
    3: 'Супружеские отношения',
    6: 'Московские усадьбы и дворцы',
    7: 'Необычные места Москвы и Подмосковья',
    8: 'Путешествия выходного дня',
    9: 'История Москвы',
    10: 'Музеи и выставки',
    11: 'Архитектура и дизайн интерьеров',
    12: 'Питание и долголетие',
    13: 'Кардиотренировки и физиология',
    14: 'Велосипедные путешествия (20–60 км)',
    15: 'Йога, подвижность и восстановление',
    16: 'Современная медицина',
    17: 'Исторические загадки и открытия',
    18: 'Выдающиеся люди и необычные судьбы',
    21: 'Христианская история и философия',
    22: 'Научные открытия и загадки природы',
    23: 'Экономика, предпринимательство и право (включая банкротство)',
    24: 'Инженерия, производство и технологии (включая 3D-печать)',
}

# An LLM may propose a priority topic; verify it also fits the real rubric.
_TOPIC_CATEGORIES = {
    1: ('Семья',), 2: ('Семья',), 3: ('Семья',),
    6: ('Москва и путешествия', 'История и культура'),
    7: ('Москва и путешествия',),
    8: ('Москва и путешествия',),
    9: ('Москва и путешествия', 'История и культура'),
    10: ('Москва и путешествия', 'История и культура'),
    11: ('Москва и путешествия', 'История и культура', 'Технологии'),
    12: ('Здоровье и движение', 'Наука'),
    13: ('Здоровье и движение', 'Наука'),
    14: ('Здоровье и движение', 'Москва и путешествия'),
    15: ('Здоровье и движение',),
    16: ('Здоровье и движение', 'Наука'),
    17: ('История и культура', 'Наука'),
    18: ('История и культура', 'Наука', 'Экономика и бизнес'),
    21: ('История и культура',),
    22: ('Наука',),
    23: ('Экономика и бизнес',),
    24: ('Технологии', 'Наука', 'Экономика и бизнес'),
}

LONGFORM_POLICY_BRIEF = '\n'.join(f'{n}. {t}' for n, t in LONGFORM_TOPICS.items())


def normalized_topic_id(candidate: dict) -> int:
    """Priorities are not a license to invent a topic or skip source checks."""
    try:
        n = int(candidate.get('long_topic_id', 0))
    except (ValueError, TypeError, OverflowError):
        return 0
    return n if candidate.get('category') in _TOPIC_CATEGORIES.get(n, ()) else 0


STYLE_RED_FLAGS = ('современный мир', 'в современном мире', 'богатейшее наследие',
                   'динамично развивающ', 'уникальная возможность', 'масштабные проекты',
                   'знаковый проект', 'в условиях стремительно меняющегося',
                   'сложно переоценить', 'не секрет, что', 'каждый человек,',
                   'играет ключевую роль в современном', 'выдающийся пример',
                   'свидетельствует о важности', 'полностью отвечает стратегическим')


# Curated SPECIFIC article pages, not generic parenting landing pages. Sources
# were checked against their published URLs when preparing this patch. Whether
# they are accessible to GitHub Actions is verified at each plan run. These are
# evergreen references, not fabricated fresh news. Pages below must supply
# >=1100 characters of actual retrievable evidence to count.
FAMILY_FEATURES = (
    ('Семья: отношения родителей с подростками', 'https://raisingchildren.net.au/pre-teens/communicating-relationships/family-relationships/relationships-with-parents-teens'),
    ('Семья: занятия всей семьёй с подростками', 'https://raisingchildren.net.au/pre-teens/entertainment-technology/free-time-activities/free-time'),
    ('Семья: разговоры и связь с подростками', 'https://www.cdc.gov/healthy-youth/connecting-conversations/index.html'),
    ('Семья: положительный опыт для подростков', 'https://www.healthychildren.org/English/healthy-living/emotional-wellness/Building-Resilience/Pages/Creating-Positive-Experiences-for-Teens.aspx'),
    ('Семья: роль игры в развитии ребёнка', 'https://www.healthychildren.org/English/family-life/power-of-play/Pages/The-Power-of-Play-How-Fun-and-Games-Help-Children-Thrive.aspx'),
    ('Семья: как поддерживать дружбу детей', 'https://www.healthychildren.org/English/family-life/power-of-play/Pages/What-Parents-Can-Do-to-Support-Friendships.aspx'),
    ('Семья: совместная игра с младенцем', 'https://raisingchildren.net.au/babies/play-learning/play-baby-development/thinking-play-babies'),
    ('Семья: физическое развитие малыша в игре', 'https://raisingchildren.net.au/babies/play-learning/play-baby-development/movement-play-babies'),
    ('Семья: первые игры и воображение малыша', 'https://raisingchildren.net.au/babies/play-learning/play-baby-development/imagining-play-babies'),
    ('Семья: знакомство детей с новорождённым', 'https://www.unicef.org/parenting/child-care/preparing-for-a-new-sibling'),
    ('Семья: занятия с малышом до двух лет', 'https://www.unicef.org/parenting/child-care/21-learning-activities-babies-and-toddlers'),
    ('Семья: занятия с ребёнком первого года', 'https://www.unicef.org/parenting/child-development/baby-tips'),
    ('Семья: открытый разговор с подростком', 'https://www.cdc.gov/free-mind/parents/talk-to-your-teen.html'),
    ('Семья: навыки внимательного слушания', 'https://www.cdc.gov/parenting-toddlers/communication/active-listening.html'),
    ('Семья: исследование времени супругов вместе', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC5798465/'),
    ('Семья: совместные привычки супругов', 'https://www.gottman.com/blog/5-rituals-reconnect-relationship/'),
    ('Семья: новые совместные занятия пары', 'https://greatergood.berkeley.edu/article/item/four_ways_to_refresh_your_relationship'),
)


def extend_family_evidence(sources: list[dict]) -> int:
    """Add real original parenting, marriage and family articles; NEVER assume a URL is accessible.

    Mutates original list so stage checkpoint retains newly fetched evidence.
    Family URLs go FIRST so the capped editorial catalog actually sees them.
    """
    known={x.get('url','').rstrip('/') for x in sources}
    tasks=[(label,url) for label,url in FAMILY_FEATURES if url.rstrip('/') not in known]
    def fetch(task):
        label,url=task
        item={'title':label, 'url':url, 'feed':'Семья — экспертный материал',
              'published':'Вне новостной повестки', 'summary':'',
              'evergreen':True, 'recent':False, 'category_hint':'Семья'}
        return news.fetch_page(item)
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched=list(pool.map(fetch,tasks))
    vetted=[x for x in fetched if x and _reference_quality(x)]
    existing_numbers=[int(x['id'][1:]) for x in sources if re.fullmatch(r'S\d+',str(x.get('id','')))]
    next_id=max(existing_numbers,default=0)+1
    for source in vetted:
        source['id']=f'S{next_id:03d}'
        next_id+=1
    # Prioritize only actually fetched, source-backed pages for model context.
    sources[:0]=vetted
    print(f'[source audit] family leaf articles verified={len(vetted)}/{len(tasks)}, '
          f'total documented sources={len(sources)}',flush=True)
    return len(vetted)


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
        'specificity':I, 'evidence':I, 'fit':I, 'long':B,
        'long_topic_id':I},
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


def shortlist(sources, date, prior=(), feedback=""):
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
Приоритетный круг БОЛЬШИХ очерков (номера фиксированы редакцией):
{LONGFORM_POLICY_BRIEF}
Для каждого кандидата укажи long_topic_id: номер ОДНОЙ наиболее подходящей темы
из списка; если не подходит ни одна — 0. Не подменяй реальный предмет сюжета
ради попадания в приоритет. Тема №19 «Литература и история книг» ИСКЛЮЧЕНА
из списка приоритетных больших очерков: не ставь для неё long_topic_id=19.
Метка long — лишь редакторская гипотеза, НЕ решение о возможности очерка:
для большого текста нужны подробные реальными проверяемыми источники.
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
    if feedback:
        prompt += ('\nПРЕДЫДУЩИЙ ПУЛ НЕ ПОЗВОЛИЛ СОБРАТЬ НОМЕР: ' + feedback[:900]
                   + '\nДобавь прежде всего НОВЫЕ документированные сюжеты недостающих рубрик, '
                   'разные исходные документы и ненаучные интеллектуальные темы. '
                   'Для каждой жизненной рубрики нужно несколько альтернатив. '
                   'Не предлагай заново эти заголовки: '
                   + json.dumps([c['title'] for c in prior], ensure_ascii=False)
                   + '\nВсе прежние пороги качества обязательны. Если фактов нет, не выдумывай.')
    answer=news.gemini(prompt,output_tokens=13500,schema='candidate31')
    original=_read_sources(sources)
    chosen=[]; seen=[]
    def accept_pool(pool):
      for c in pool:
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
        c['long_topic_id']=normalized_topic_id(c)
        chosen.append(c)
    accept_pool(prior)
    accept_pool(answer.get('candidates',[]))
    # Second, focused pass only when a generic news cycle omitted the family
    # section. It has its OWN document-backed source IDs and the same score
    # and evidence threshold; no filler or synthetic stories are accepted.
    family_count=sum(c['category']=='Семья' for c in chosen)
    family_references=[s for s in sources if s.get('category_hint')=='Семья'
        or s.get('feed','').startswith('Дети и образование')]
    if family_count < 2 and family_references:
        family_catalog=news.json_catalog(family_references,max_n=30)
        targeted_prompt=f'''387 News, отдельный строго документальный отбор тем рубрики «Семья».
Планируемая дата {date}. Только конкретные факты из материалов ниже:
{json.dumps(family_catalog,ensure_ascii=False)}
Предложи 5–9 РАЗНЫХ подходящих тем (совместное время супругов,
подросток 14 лет, школьники 10 и 7, младенец 6 месяцев; отношения взрослых
и детей, игры, чтение, совместное время). Категория каждого кандидата СТРОГО «Семья». Тип — «очерк» или
«практический материал» для старых страниц; НЕ называй их свежей новостью.
Каждая тема должна иметь реальную сюжетную интригу, возрастной контекст
и подробные факты из указанного источника. Одна обзорная страница
не заменяет подробный исходный материал. Оцени novelty (новизна УГЛА,
не дата), reader_interest, specificity, evidence, fit: по 0–5.
source_ids указывай только существующие идентификаторы. Для поля
long_topic_id поставь 1 (воспитание), 2 (семейные занятия), 3 (супружеские
отношения), только если сюжет точно подходит; иначе 0. long=true только
при проверяемой документальной глубине; не растягивай общий совет.
Статьи без подтверждения НЕ ПРИДУМЫВАЙ. Формат candidates, JSON по схеме.
Запрет: общие рекомендации без конкретного содержания и  ложные даты.'''
        targeted=news.gemini(targeted_prompt, output_tokens=8000,schema='candidate31')
        # Candidate must be family and must rely at least in part on
        # family/child materials, even if a model misclassified it.
        referenced={x['id'] for x in family_references}
        vetted=[c for c in targeted.get('candidates',[])
                if isinstance(c,dict) and c.get('category')=='Семья'
                and any(i in referenced for i in (c.get('source_ids') or []))]
        accept_pool(vetted)
    print('[candidate audit] '+', '.join(
        f'{cat}={sum(c["category"]==cat for c in chosen)}'
        for cat in news.VALID_CATEGORIES)+'; family source pages='+str(len(family_references)),
        flush=True)
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
    anchors += [x for x in chosen if normalized_topic_id(x)][:8]
    prioritized=[]; seen_titles=set()
    for c in anchors+chosen:
        tag=normalized(c['title'])
        if tag not in seen_titles:
            seen_titles.add(tag)
            prioritized.append(c)
        if len(prioritized)==30:
            break
    return sorted(prioritized,key=lambda x:(-x['score'],normalized(x['title'])))




def _longform_evidence(c: dict, source_map: dict) -> tuple[bool, int, int]:
    """Is there *retrieved* documentary depth to commission a long feature?

    An LLM's `long` boolean is only a proposal, not a factual measurement.
    Require either one substantial original article or independent detailed
    documents; no synthetically expanded, generic landing or abstract pages.
    This is a commissioning screen, not a guarantee the eventual feature is good:
    the dossier, word count and independent review must still succeed.
    """
    if (candidate_score(c) < 20 or
            int(c.get('evidence', 0)) < 4 or
            int(c.get('specificity', 0)) < 4 or
            int(c.get('reader_interest', 0)) < 4):
        return False, 0, 0
    headline = normalized(c.get('title', ''))
    if any(marker in headline for marker in SOFT_PRESS_RELEASE):
        return False, 0, 0
    seen = set()
    pages = []
    for sid in c.get('source_ids', []):
        src = source_map.get(sid)
        if not src or not _reference_quality(src):
            continue
        url = src.get('url', '').rstrip('/')
        if url in seen:
            continue
        seen.add(url)
        pages.append(src)
    if not pages:
        return False, 0, 0
    sizes = [len(p.get('evidence', '').strip()) for p in pages]
    total = sum(sizes)
    domain_count = len(domains(pages))
    strong_single = max(sizes) >= 5400
    independent_sources = (len(pages) >= 2 and domain_count >= 2 and
                           min(sorted(sizes, reverse=True)[:2]) >= 1800 and
                           total >= 5000)
    return strong_single or independent_sources, total, domain_count


def commission_evidence_backed_longforms(candidates: list[dict], sources: list[dict]) -> list[dict]:
    """Evaluate *every* longform pitch against primary source depth.

    Priority topics improve commissioning rank but NEVER replace source evidence.
    Model flags without enough evidence are demoted to regular articles. Work
    from copies to avoid corrupting the candidate audit and past checkpoints.
    """
    pool = [dict(c) for c in candidates]
    source_map = _read_sources(sources)
    original_flags = sum(bool(c.get('long')) for c in pool)
    qualified = []
    for c in pool:
        c['long_topic_id'] = normalized_topic_id(c)
        good, chars, independent_domains = _longform_evidence(c, source_map)
        c['long'] = bool(good)
        if good:
            # Both yes/no calls remain auditable. No source → no long feature.
            c['longform_basis'] = 'source-depth-qualified; further dossier audit required'
            qualified.append((c, chars, independent_domains))
    # Selectable plan must contain at least two long features, preferably one
    # family/health/city story and one intellectual story. Preserve up to five
    # pitches and a balanced range of rubrics, with source depth decisive.
    qualified.sort(key=lambda item: (
        -int(bool(item[0]['long_topic_id'])), -int(item[0].get('score', 0)),
        -item[1], normalized(item[0]['title'])))
    favoured = []
    used_cats = set()
    for different_cat in (True, False):
        for c, chars, independent_domains in qualified:
            if c in favoured or (different_cat and c['category'] in used_cats):
                continue
            favoured.append(c)
            used_cats.add(c['category'])
            if len(favoured) >= 5:
                break
        if len(favoured) >= 5:
            break
    selected_ids = {id(c) for c in favoured}
    for c, _, _ in qualified:
        if id(c) not in selected_ids:
            c['long'] = False
            c.pop('longform_basis', None)
    life_long = sum(bool(c.get('long')) and c['category'] in LIFE for c in pool)
    intellectual_long = sum(bool(c.get('long')) and c['category'] not in LIFE for c in pool)
    print(f'[longform audit v3.2] model-flagged={original_flags}, '
          f'evidence-qualified={len(qualified)}, kept={len(favoured)}, '
          f'priority={sum(bool(c.get("long_topic_id")) for c in favoured)}, '
          f'life={life_long}, intellectual={intellectual_long}; target=2–3', flush=True)
    return pool


def select_balanced_plan(candidates: list[dict], sources: list[dict]) -> list[dict]:
    """Choose a source-backed, category-balanced issue without trusting an LLM's
    ability to count rubrics. The model only suggests and scores candidates.

    Fail closed if eligible sources cannot support the promised editorial mix.
    Never add invented items or lower the candidate-quality threshold.
    """
    candidates=sorted(candidates, key=lambda c:(-c['score'], -int(bool(c.get('long') and normalized_topic_id(c))), normalized(c['title'])))
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
                     'hook':c.get('hook',''),
                     'long_topic_id':normalized_topic_id(c)})
    print('[plan] balanced source-backed selection: '
          +', '.join(f'{cat}={sum(q["category"]==cat for q in plan)}'
                      for cat in news.VALID_CATEGORIES)
          +f'; long={sum(q["long"] for q in plan)}; reviewed={len(candidates)}',
          flush=True)
    return plan


def choose_plan(sources,date, progress=None):
    # Version 3.1 originally asked Gemini to choose exactly 8 from its own
    # shortlist, then rejected the output if it omitted mandatory rubrics.
    # That was an unreliable prompt-following/counting step. Keep Gemini for
    # suggesting & scoring candidates; enforce selection deterministically.
    progress = progress if progress is not None else {}
    if not progress.get("family_researched"):
        extend_family_evidence(sources)
        progress["family_researched"] = True
        news.runtime.checkpoint()
    if not progress.get("candidates"):
        progress["candidates"] = shortlist(sources,date)
        news.runtime.checkpoint()
    while True:
        candidates = commission_evidence_backed_longforms(progress['candidates'], sources)
        try:
            canonical = select_balanced_plan(candidates, sources)
            return canonical, candidates
        except RuntimeError as exc:
            progress['plan_note'] = str(exc)[:900]
            rounds = progress.get('selection_repairs', 0)
            if rounds >= 3:
                raise RuntimeError('Editorial plan still infeasible after 3 source-backed reselections; no fabricated filler. ' + str(exc)) from None
            repaired = shortlist(sources, date, prior=progress['candidates'], feedback=progress['plan_note'])
            progress['candidates'] = repaired
            progress['selection_repairs'] = rounds + 1
            news.runtime.checkpoint()




class _StudyLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs=[]
    def handle_starttag(self,tag, attrs):
        if tag=='a':
            href=dict(attrs).get('href','')
            if href:self.hrefs.append(href)


def enrich_originals(sources, plan, *, strict=True):
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
            if strict:
                raise RuntimeError('New scientific result has no original accessible study or official release; veto')
            item['original_unverified'] = True
    return sources, plan


def select_plan_with_verified_science(sources, candidates, initial_plan=None, *, max_rounds=12):
    """Replace one unsupported scientific NEWS candidate rather than veto the issue.

    Candidate titles, sources, editorial ratings and longform approval must already
    have passed the regular shortlist/commissioning checks. Never manufacture new
    stories, downgrade a news claim to an evergreen item, or waive the primary-source
    rule. Remaining candidates are rebalanced by the same deterministic selector.
    """
    def identity(p):
        return (normalized(p.get('title', '')), p.get('category', ''))

    rejected = set()
    verified = {}  # reuse earlier verified scientific sources across reselections
    attempted = 0
    limit = max(1, min(int(max_rounds), len(candidates) + 1))
    while attempted < limit:
        pool = [c for c in candidates if identity(c) not in rejected]
        if attempted == 0 and initial_plan is not None:
            plan = initial_plan
        else:
            try:
                plan = select_balanced_plan(pool, sources)
            except RuntimeError as exc:
                raise RuntimeError(
                    'No balanced issue after excluding scientific news without '
                    'accessible original studies or official releases; '
                    f'excluded={len(rejected)}. {exc}'
                ) from exc
        unverified = []
        for item in plan:
            cached = verified.get(identity(item))
            if cached is not None:
                item['source_ids'] = cached[:]
                item['original_study_found'] = True
                item.pop('original_unverified', None)
            else:
                unverified.append(item)
        if unverified:
            sources, _ = enrich_originals(sources, unverified, strict=False)
        failed = [item for item in plan if item.get('original_unverified')]
        if not failed:
            print(f'[original source audit] verified plan: {len(plan)} stories; '
                  f'{len(rejected)} unsupported science pitches replaced',flush=True)
            return sources, plan
        for item in plan:
            if (item.get('original_study_found') and
                    item['category'] in ('Наука', 'Здоровье и движение') and
                    item['kind'].lower() == 'новость'):
                verified[identity(item)] = list(item['source_ids'])
        for item in failed:
            rejected.add(identity(item))
            print(f'[original source audit] reject unsupported scientific NEWS '
                  f'candidate (not published): {item["title"][:120]}',flush=True)
        attempted += 1
    raise RuntimeError('Not enough supported scientific reports to build an issue '
                       f'after {limit} verifications. No unsupported science will be published.')


def make_dossier(plan, source_map, date, progress=None):
    """Stage 2: extract verifiable claims before drafting any prose."""
    sources=[source_map[sid] for sid in plan['source_ids']]
    bundle=[{'id':s['id'],'title':s['title'],'date':s['published'],
             'url':s['url'],'excerpt':s['evidence'][:7000],
             'abstract_only':bool(s.get('abstract_only'))} for s in sources]
    prompt=f'''Создай закрытое журналистское досье, НЕ статью, на {date}.
Утверждённый сюжет: {json.dumps(plan,ensure_ascii=False)}
Редакционный приоритет большого очерка: {LONGFORM_TOPICS.get(plan.get('long_topic_id',0),'общая рубрика без привилегий')}
ДОКАЗАТЕЛЬСТВА: {json.dumps(bundle,ensure_ascii=False)}
Извлеки {'10–13' if plan['long'] else '7–10'} НЕПОВТОРЯЮЩИХСЯ конкретных фактов, включая имена, числа,
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
    progress = progress if progress is not None else {}
    min_claims = 8 if plan['long'] else 5
    while progress.get('attempts', 0) < 3:
        prior = progress.get('claims', [])
        feedback = ''
        if progress.get('attempts'):
            feedback = (f'\nРедактор подтвердил только {len(prior)}/{min_claims} точных цитат. '
                        'Найди дополнительные НЕПОВТОРЯЮЩИЕСЯ факты в исходном тексте, '
                        'цитируй непрерывно, не меняй и не переводи цитату. '
                        'Нельзя дополнять факты из памяти. Уже принятые свидетельства: '
                        + json.dumps(prior, ensure_ascii=False))
        result = news.gemini(prompt + feedback, output_tokens=8500, schema='dossier31')
        progress['attempts'] = progress.get('attempts', 0) + 1
        clean = []; distinct = set()
        supplied = result.get('claims') or []
        if not isinstance(supplied, list):
            supplied = []
        for claim in prior + supplied:
            if not isinstance(claim, dict):
                continue
            sid = claim.get('source_id')
            if not isinstance(claim.get('quote'), str):
                continue
            quote = claim['quote'].strip()
            if sid not in source_map or sid not in plan['source_ids'] or not 20 <= len(quote) <= 240:
                continue
            if normalized(quote) not in normalized(source_map[sid].get('evidence', '')):
                continue
            tag = (sid, normalized(quote))
            if tag in distinct:
                continue
            distinct.add(tag)
            clean.append({'source_id':sid, 'quote':quote, 'explanation':str(claim.get('explanation', ''))[:450]})
        progress['claims'] = clean
        news.runtime.checkpoint()
        print(f'[dossier] verified citations={len(clean)}/{min_claims} attempt={progress["attempts"]}/3', flush=True)
        if len(clean) >= min_claims:
            result['claims'] = clean
            return result
    raise news.runtime.EvidenceRejected(f'Insufficient exact source evidence ({len(progress.get("claims", []))}/{min_claims}) after 3 extractions; no invented facts')


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
    prose_quality(a)
    if len(style_flags(a))>=2:
        raise ValueError('Banal/promotional writing: '+', '.join(style_flags(a)[:3]))
    if not 20<=len(a.get('title',''))<=185 or wc(a.get('teaser',''))<25:
        raise ValueError('Title or teaser is incomplete')
    return n


def prose_quality(article):
    texts = [normalized(p['text']) for p in article['paragraphs']]
    tokens = re.findall(r'\w+', ' '.join(texts))
    if len(set(tokens)) / max(1, len(tokens)) < .12:
        raise ValueError('Text lacks substantive vocabulary')
    for i, text in enumerate(texts):
        if any(text == previous or SequenceMatcher(None, text[:2400], previous[:2400]).ratio() > .80
               for previous in texts[:i]):
            raise ValueError('Text repeats substantially identical paragraphs')


def validate_segment(part, previous, index):
    if not isinstance(part, dict):
        raise ValueError('Segment response is not an object')
    if index == 0:
        title = part.get('title'); teaser = part.get('teaser')
        if not isinstance(title, str) or not isinstance(teaser, str):
            raise ValueError('Segment 1 title or teaser missing or not text')
        if not 20 <= len(title) <= 185:
            raise ValueError(f'Segment 1 title has {len(title)} characters; requires 20–185')
        if wc(teaser) < 25:
            raise ValueError(f'Segment 1 teaser has {wc(teaser)} words; requires at least 25 meaningful words')
    para = part.get('paragraphs') or []
    if not isinstance(para, list) or not 2 <= len(para) <= 7 or any(
        not isinstance(p, dict) or not isinstance(p.get('text'), str)
        or len(p['text'].strip()) < 65 for p in para):
        raise ValueError(f'Longform segment {index+1} incomplete')
    words = wc(article_body(part))
    if not 105 <= words <= 400:
        raise ValueError(f'Longform segment {index+1} has {words} words; requires 105–400 meaningful, supported words')
    if len(style_flags(part)) >= 2:
        raise ValueError(f'Longform segment {index+1} contains generic/promotional filler')
    tokens = re.findall(r'\w+', normalized(article_body(part)))
    if len(set(tokens)) / max(1, len(tokens)) < .12:
        raise ValueError(f'Longform segment {index+1} lacks substantive vocabulary')
    prior = [normalized(p['text']) for old in previous for p in old['paragraphs']]
    for p in para:
        text = normalized(p['text'])
        if any(text == old or SequenceMatcher(None, text[:2400], old[:2400]).ratio() > .80
               for old in prior):
            raise ValueError(f'Longform segment {index+1} repeats earlier prose')
        # Check the whole paragraph, including copied tails outside the fuzzy window.
        shingles = lambda v: set(zip(*(v.split()[j:] for j in range(5))))
        new = shingles(text)
        if any(new and len(new & shingles(old)) / len(new) > .55 for old in prior):
            raise ValueError(f'Longform segment {index+1} repeats earlier prose')
        prior.append(text)
    return words


def request_segment(prompt, parts, progress, index):
    attempts = max(1, min(3, int(os.getenv('NEWS_FRAGMENT_ATTEMPTS', '3'))))
    failures = progress.setdefault('failures', {})
    feedback = progress.setdefault('feedback', {})
    slot = str(index)
    if failures.get(slot, 0) >= 9:
        raise news.runtime.EvidenceRejected(f'Segment {index+1} rejected after 9 attempts; source depth or prose insufficient')
    for attempt in range(attempts):
        message = feedback.get(slot, '')
        repair = (f'\nДиагностика предыдущей попытки: {message}. '
                  'Перепиши только текущий фрагмент. Цель 180–240 слов, '
                  'минимум 105. Добавь подтверждённый механизм или подробности '
                  'из цитат, не повторяй тезисы и не добавляй факты из памяти. '
                  'Верни title длиной 20–185 символов и полный teaser на 30–65 слов.') if message else ''
        try:
            part = _paced_section_request(prompt + repair)
            words = validate_segment(part, parts, index)
            return part, words
        except (ValueError, news.GeminiResponseError) as exc:
            failures[slot] = failures.get(slot, 0) + 1
            feedback[slot] = str(exc)[:450]
            news.runtime.checkpoint()
            print(f'[repair] segment={index+1} rejected attempt={failures[slot]}/9: {exc}', flush=True)
            if failures[slot] >= 9:
                raise news.runtime.EvidenceRejected(f'Segment {index+1}: insufficient supported prose after 9 attempts') from None
            if attempt + 1 == attempts:
                raise ValueError(f'{exc}; accepted sections preserved; retry next run') from None


# Editorial pacing applies only to the live run (not to unit tests). On GitHub
# set NEWS_LONGFORM_GAP_SECONDS in the prepare step to stay safely below the
# model's RPM quota; no job runs continuously for hours.
_LONGFORM_LAST_CALL = 0.0


def _paced_section_request(prompt: str) -> dict:
    global _LONGFORM_LAST_CALL
    gap = min(30.0, max(0.0, float(os.getenv('NEWS_LONGFORM_GAP_SECONDS', '0'))))
    now = time.monotonic()
    if gap and _LONGFORM_LAST_CALL:
        remaining = gap - (now - _LONGFORM_LAST_CALL)
        if remaining > 0:
            time.sleep(remaining)
    _LONGFORM_LAST_CALL = time.monotonic()
    return news.gemini(prompt, output_tokens=8500, schema='article')


_LONGFORM_BEATS = (
    'Завязка: конкретный факт, вопрос или парадокс; почему история началась именно так.',
    'Действующие лица, место и исторический либо научный контекст; только проверенные сведения.',
    'Хронология и первые наблюдения: какие факты предшествовали основному событию.',
    'Основное свидетельство: как его получили, обнаружили или зафиксировали, без домыслов.',
    'Механизм или причинно-следственная связь: что действительно следует из источников.',
    'Иная перспектива: конкретные ограничения данных, расхождения или неопределённость.',
    'Изменение понимания: сопоставление с контекстом, основанное только на свидетельствах.',
    'Развязка: что установленное знание объясняет и что остаётся открытым.',
    'Углубление: подтверждённые технические или исторические нюансы, не рассмотренные выше.',
    'Эпилог: аккуратное развитие главного вопроса без общих фраз и повторов.',
)


def _longform_parts(plan: dict, dossier: dict, date: str, revision_reason: str) -> dict:
    """Preserve evidence-backed segments for both long and compact articles.

    Gemini Flash-Lite empirically supplied 150-185 words for a requested
    450-600. Demand manageable ~170-250-word segments, never pad them, and
    reject the COMPLETE feature if it is still below MIN_LONG.

    Intermediate sections are stored only inside the encrypted checkpoint's
    dossier. Nothing in this method can publish or accept an unverified article.
    """
    claims = dossier['claims']
    long = bool(plan['long'])
    minimum_claims = 8 if long else 5
    if len(claims) < minimum_claims:
        raise news.runtime.EvidenceRejected(f'Story needs at least {minimum_claims} verified source excerpts')
    minimum_parts = 8 if long else 4
    minimum_words = MIN_LONG if long else 600  # drafting target; editorial floor remains 440
    beats = _LONGFORM_BEATS if long else (
        'Конкретная завязка: подтверждённый факт и главный вопрос истории.',
        'Механизм и объяснение главного факта с проверенными подробностями.',
        'Контекст, ограничения и существенные детали, которых ещё не было.',
        'Развязка: ответ на главный вопрос и границы установленного знания.',
        'Дополнительные подтверждённые нюансы; без повторения сказанного.',
        'Заверши историю конкретным выводом из ещё не разобранных свидетельств.',
    )
    progress_key = '_longform_progress' if long else '_shortform_progress'

    basis = json.dumps({
        'date':date, 'title':plan['title'], 'category':plan['category'],
        'sources':plan['source_ids'],
        'claims':[(c['source_id'],c['quote']) for c in claims],
    }, ensure_ascii=False, sort_keys=True)
    signature = hashlib.sha256(basis.encode('utf-8')).hexdigest()
    progress = dossier.get(progress_key)
    rebuilds = progress.get('assembly_failures', 0) if isinstance(progress, dict) and progress.get('signature') == signature else 0
    if rebuilds >= 3:
        raise news.runtime.EvidenceRejected('Three complete assemblies failed editorial form; reject story')
    if (not isinstance(progress, dict) or progress.get('signature') != signature
            or progress.get('rebuild_required')):
        progress = {'signature':signature, 'parts':[], 'assembly_failures':rebuilds}
        dossier[progress_key] = progress
    parts = progress['parts']
    if not isinstance(parts, list) or len(parts) > len(beats):
        raise ValueError('Invalid longform checkpoint, refusing to reuse')

    # A passage is useful only if it advances the already researched story.
    # Reuse of the source ID is allowed, but duplicate prose is checked below.
    # Revalidate persisted counts and prose; never trust cached word totals.
    for i, part in enumerate(parts):
        part['words'] = validate_segment(part, parts[:i], i)
    while len(parts) < len(beats):
        index = len(parts)
        current_total = sum(int(p.get('words', 0)) for p in parts)
        if index >= minimum_parts and current_total >= minimum_words:
            break
        if current_total + 400 > MAX_WORDS:
            break

        focus_indices = sorted({index % len(claims),
                                (index+1) % len(claims),
                                (index+3) % len(claims)})
        focus = [{'source_id':claims[j]['source_id'],
                  'source_quote':claims[j]['quote'],
                  'verified_point':claims[j]['explanation']}
                 for j in focus_indices]
        prior = ''
        if parts:
            tail = article_body({'paragraphs':parts[-1]['paragraphs']})
            prior = 'Последняя фраза предыдущего фрагмента (не повторяй): '+tail[-420:]
        prompt = f'''Ты пишешь ОДИН из небольших фрагментов большого очерка «387 News».
Дата номера: {date}. Сюжет: {json.dumps(plan, ensure_ascii=False)}
Угол материала: {dossier.get('angle','')}; хронология: {dossier.get('chronology','')}.
Ставки и смысл: {dossier.get('stakes','')}.
Фрагмент {index+1}/{minimum_parts} (дополнительные фрагменты возможны при недостаточном объёме).
ТВОЙ САМОДОСТАТОЧНЫЙ ВОПРОС: {beats[index]}
Подтверждённые ДОСЛОВНЫЕ фрагменты источников:
{json.dumps(focus, ensure_ascii=False)}
{prior}
Пиши 170–250 РУССКИХ СЛОВ: 2–4 содержательных абзаца.
Нужны только подтверждённые этими цитатами факты, их прозрачное объяснение
и осторожные выводы. Не подменяй недостаток фактов художественным вымыслом,
эмоциями, повторениями, общеизвестными формулами или рекламой.
Не дублируй уже написанные части. Дата новости не равна дате исследования.
Для семейных и практических тем не придумывай цены, время работы, условия.
Если проверенных подробностей не хватает на заданную глубину, отвечай
короче: это приведёт к честному редакционному отказу.
Верни JSON-объект title, teaser (30–65 слов), paragraphs (heading,text).
Нужны точные подробности, а не лозунги и искусственные «части» очерка.
Прежние замечания редактора: {revision_reason[:400]}'''
        part, section_words = request_segment(prompt, parts, progress, index)
        para = part['paragraphs']
        parts.append({'title':str(part.get('title','')),
                      'teaser':str(part.get('teaser','')),
                      'paragraphs':para, 'words':section_words})
        news.runtime.checkpoint()
        tag = 'longform' if long else 'shortform'
        print(f'[{tag}] saved segment {index+1}/{len(beats)}, '
              f'{section_words} words; total={sum(p["words"] for p in parts)}; '
              'encrypted checkpoint on run completion', flush=True)

    # Assemble only from accepted, immutable segments. The complete article's
    # structural, repetition, and length gates remain mandatory.
    all_paragraphs = [p for segment in parts for p in segment['paragraphs']]
    article = {'title':parts[0]['title'], 'teaser':parts[0]['teaser'],
               'paragraphs':all_paragraphs}
    try:
        n = article_form(article, plan)
    except ValueError as exc:
        # An already complete but unacceptable article must not loop forever
        # on the same rejected set of segments in the next scheduled run.
        progress['rebuild_required'] = str(exc)[:250]
        progress['assembly_failures'] = progress.get('assembly_failures', 0) + 1
        raise
    texts = [normalized(x['text']) for x in all_paragraphs]
    for i, a in enumerate(texts):
        for b in texts[i+1:]:
            if SequenceMatcher(None,a[:1200],b[:1200]).ratio() > 0.80:
                raise ValueError('Longform repeats substantially identical paragraphs')
    print(f'[longform] source-grounded narrative assembled, {n} words; '
          'independent editorial review still required', flush=True)
    return article


def write_from_dossier(plan, dossier, date, revision_reason=''):
    """Draft source-backed prose. Long features use focused smaller requests."""
    a = _longform_parts(plan, dossier, date, revision_reason)
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
Написанная статья: {a['title']}\nАнонс (тоже проверь каждое утверждение): {a.get('teaser','')}\n{body}
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
    a['_review_scope'] = 'title_teaser_body_v1'
    return True


def audit_issue(articles,plan,sources):
    if len(articles)!=8 or len(plan)!=8:raise ValueError('Incomplete issue')
    if not LIFE.issubset({a['category'] for a in articles}):
        raise ValueError('Mandatory rubrics missing')
    if sum(a['category'] in LIFE for a in articles)<4:
        raise ValueError('Not enough life / family / health content')
    if not 2 <= sum(bool(a.get('long')) for a in articles) <= 3:
        raise ValueError('Issue requires 2–3 longform features')
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
