#!/usr/bin/env python3
"""387 News: source-led publication with a local release gate and fail-closed checks.

No dependencies beyond Python's standard library. The API key is read from
GEMINI_API_KEY and is never written to disk or printed.
"""
from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape, unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo('Europe/Moscow')
MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.6-flash')
FEEDS = {
    'Наука — NASA': 'https://www.nasa.gov/feed/',
    'Наука — ScienceDaily': 'https://www.sciencedaily.com/rss/top/science.xml',
    'Здоровье — питание': 'https://www.sciencedaily.com/rss/health_medicine/nutrition.xml',
    'Здоровье — упражнения': 'https://www.sciencedaily.com/rss/health_medicine/fitness.xml',
    'Дети и образование': 'https://www.sciencedaily.com/rss/mind_brain/child_development.xml',
    'Культура': 'https://www.theguardian.com/culture/rss',
    'Афиша Москвы': 'https://www.mos.ru/rss',
    'Московская культура': 'https://www.mskagency.ru/rss/culture.rss',
    'Экономика Москвы': 'https://www.mskagency.ru/rss/business.rss',
    'Наука и общество': 'https://www.theguardian.com/science/rss',
    'Архитектура': 'https://www.archdaily.com/feed',
    'Искусственный интеллект — исследования': 'https://arxiv.org/rss/cs.AI',
}
# Evergreen sources are only a factual base for a dated-as-evergreen essay.
# Never promise a specific event, fare or timetable without its explicit source.
EVERGREEN = {
    'Семья': [
        ('ВОЗ — раннее развитие ребёнка', 'https://www.who.int/health-topics/early-child-development'),
        ('UNICEF — занятия с детьми', 'https://www.unicef.org/parenting'),
    ],
    'Москва и путешествия': [
        ('Официальная афиша Москвы', 'https://www.mos.ru/afisha/'),
        ('Государственный Дарвиновский музей', 'https://www.darwinmuseum.ru/'),
        ('Музей Москвы', 'https://mosmuseum.ru/'),
    ],
    'Здоровье и движение': [
        ('ВОЗ — физическая активность', 'https://www.who.int/news-room/fact-sheets/detail/physical-activity'),
        ('ВОЗ — здоровое питание', 'https://www.who.int/news-room/fact-sheets/detail/healthy-diet'),
    ],
}
VALID_CATEGORIES = ('Семья', 'Москва и путешествия', 'Здоровье и движение', 'Наука', 'История и культура', 'Экономика и бизнес', 'Технологии')
FALLBACK_IMAGE = {
    'Семья': 'family.svg', 'Москва и путешествия': 'museum.svg',
    'Здоровье и движение': 'cycle.svg', 'Наука': 'stars.svg',
    'История и культура': 'sculpture.svg', 'Экономика и бизнес': 'lab.svg',
    'Технологии': 'lab.svg',
}
UA = '387NewsEditorialBot/1.0 (+https://387.su; research bot)'


def http_get(url: str, *, limit: int = 400_000, timeout: int = 14) -> bytes:
    if urlparse(url).scheme != 'https':
        raise ValueError('Only HTTPS inputs are allowed')
    req = Request(url, headers={'User-Agent': UA, 'Accept': 'application/rss+xml,application/xml,text/html,application/json;q=0.9,*/*;q=0.5'})
    with urlopen(req, timeout=timeout) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            data = data[:limit]
        return data


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.collect = 0
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'footer', 'header', 'aside'):
            self.skip += 1
        if tag in ('p', 'h1', 'h2', 'h3') and not self.skip:
            self.collect += 1

    def handle_endtag(self, tag):
        if tag in ('p', 'h1', 'h2', 'h3') and self.collect:
            self.collect -= 1
            self.parts.append('\n')
        if tag in ('script', 'style', 'nav', 'footer', 'header', 'aside') and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.collect and not self.skip:
            self.parts.append(data)


def extract_text(html: str) -> str:
    p = ArticleText()
    p.feed(html)
    s = unescape(''.join(p.parts))
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n\s*\n+', '\n', s)
    return s.strip()[:8500]


def tag_text(el, name):
    child = el.find(name)
    return (''.join(child.itertext()).strip() if child is not None else '')


def xml_items(xml_data, label):
    try:
        tree = ET.fromstring(xml_data)
    except ET.ParseError:
        return []
    items = []
    candidates = tree.findall('.//item')
    atom = False
    if not candidates:
        atom = True
        candidates = tree.findall('.//{http://www.w3.org/2005/Atom}entry')
    for item in candidates[:18]:
        if atom:
            ns = '{http://www.w3.org/2005/Atom}'
            title = tag_text(item, ns + 'title')
            link_el = item.find(ns+'link')
            link = link_el.get('href', '') if link_el is not None else ''
            date = tag_text(item, ns+'updated') or tag_text(item, ns+'published')
            description = tag_text(item, ns+'summary')
        else:
            title = tag_text(item, 'title')
            link = tag_text(item, 'link')
            date = tag_text(item, 'pubDate')
            description = tag_text(item, 'description')
        if not link.startswith('https://') or not title:
            continue
        description = re.sub('<[^>]+>', ' ', description)
        items.append({'title':unescape(title)[:200], 'url':link, 'published':date[:70], 'summary':unescape(description)[:650], 'feed':label})
    return items


def read_feed(pair):
    label, url = pair
    try:
        return xml_items(http_get(url, timeout=12), label)
    except (OSError, ValueError, URLError, HTTPError) as ex:
        print(f'[source unavailable] {label}: {type(ex).__name__}', file=sys.stderr)
        return []


def fetch_page(item):
    try:
        body = http_get(item['url'], timeout=11).decode('utf-8', 'replace')
        text = extract_text(body)
        if len(text) > 450:
            item['evidence'] = text[:7000]
            return item
    except Exception:
        pass
    # A valid syndicated abstract is a permissible weaker source, marked as such.
    if len(item.get('summary','')) >= 170:
        item['evidence'] = item['summary']
        item['abstract_only'] = True
        return item
    return None


def is_recent(date_string, now):
    try:
        dt = parsedate_to_datetime(date_string)
    except (ValueError, TypeError, IndexError):
        try:
            dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = now.astimezone(timezone.utc) - dt.astimezone(timezone.utc)
    return timedelta(hours=-2) <= age <= timedelta(hours=72)


def gather_sources(now):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        feed_lists = list(pool.map(read_feed, FEEDS.items()))
    # Place the mandatory-life topics first; otherwise a busy news day crowds
    # the 8 verified official pages out of the 95-page download budget.
    items = []
    for category, entries in EVERGREEN.items():
        for label, url in entries:
            items.append({'title':label, 'url':url, 'summary':'', 'published':'Вне новостной повестки', 'feed':category, 'evergreen':True})
    for i in range(8):
        for feed in feed_lists:
            if i < len(feed):
                items.append(feed[i])
    unique = {}
    for it in items:
        unique.setdefault(it['url'], it)
    items = list(unique.values())
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        verified = [v for v in pool.map(fetch_page, items[:95]) if v is not None]
    for n, v in enumerate(verified, 1):
        v['id'] = f'S{n:03d}'
        v['recent'] = is_recent(v.get('published', ''), now) if not v.get('evergreen') else False
    return verified


class GeminiResponseError(RuntimeError):
    """A generation reached the API but did not return a valid JSON object."""


def _parse_gemini_response(result):
    """Return data plus safe diagnostic metadata. Never log generated article text."""
    candidates = result.get('candidates') or []
    if not candidates:
        reason = (result.get('promptFeedback') or {}).get('blockReason', 'NO_CANDIDATES')
        raise GeminiResponseError(f'No answer from Gemini (blockReason={reason})')
    candidate = candidates[0]
    finish = candidate.get('finishReason', 'UNKNOWN')
    usage = result.get('usageMetadata') or {}
    tokens = usage.get('candidatesTokenCount', 'unknown')
    thought_tokens = usage.get('thoughtsTokenCount', 'unknown')
    parts = (candidate.get('content') or {}).get('parts') or []
    text = ''.join(part.get('text', '') for part in parts
                   if isinstance(part, dict) and not part.get('thought'))
    metadata = f'finishReason={finish}, chars={len(text)}, outputTokens={tokens}, thoughtTokens={thought_tokens}'
    if finish not in ('STOP', 'FINISH_REASON_UNSPECIFIED', 'UNKNOWN'):
        raise GeminiResponseError('Generation incomplete or blocked (' + metadata + ')')
    if not text.strip():
        raise GeminiResponseError('Empty model answer (' + metadata + ')')
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise GeminiResponseError('Invalid JSON (' + metadata + ')') from None
    if not isinstance(data, dict):
        raise GeminiResponseError('JSON root must be an object (' + metadata + ')')
    return data


# Schema constraints improve JSON stability but do not substitute for fact checking.
SCHEMAS = {
    'plan': {'type':'object', 'properties':{
        'articles':{'type':'array','items':{'type':'object','properties':{
            'title':{'type':'string'}, 'category':{'type':'string','enum':list(VALID_CATEGORIES)},
            'kind':{'type':'string'}, 'source_ids':{'type':'array','items':{'type':'string'}},
            'angle':{'type':'string'}, 'long':{'type':'boolean'}},
            'required':['title','category','kind','source_ids','angle','long']}}},
        'required':['articles']},
    'article': {'type':'object','properties':{
        'title':{'type':'string'}, 'teaser':{'type':'string'},
        'paragraphs':{'type':'array','items':{'type':'object','properties':{
            'heading':{'type':'string'}, 'text':{'type':'string'}},
            'required':['heading','text']}}},
        'required':['title','teaser','paragraphs']},
    'audit': {'type':'object','properties':{
        'ok':{'type':'boolean'}, 'reasons':{'type':'array','items':{'type':'string'}}},
        'required':['ok','reasons']},
}


def gemini(prompt, output_tokens=4800, *, schema=None):
    """Robust free-tier client. Separate Lite quotas, fall back across models.

    Never switch to a paid model. The user has not enabled billing; the
    supported model list can be limited further via GEMINI_MODELS.
    """
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('GEMINI_API_KEY is missing in GitHub Secrets')
    model_list = [x.strip() for x in os.environ.get(
        'GEMINI_MODELS', 'gemini-3.5-flash-lite,gemini-3.1-flash-lite'
    ).split(',') if x.strip()]
    SAFE_MODELS = {'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite',
                   'gemini-3.6-flash', 'gemini-3.8-flash', 'gemini-3-flash-preview'}
    if not model_list or any(x not in SAFE_MODELS for x in model_list):
        raise RuntimeError('Invalid GEMINI_MODELS configuration; refusing unsupported model')
    errors = []
    for model in model_list:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        for attempt in range(3):
            generation = {
                'responseMimeType': 'application/json',
                'maxOutputTokens': min(30000, max(8000, output_tokens * 2)),
                'thinkingConfig': {'thinkingLevel': 'minimal' if 'flash-lite' in model else 'low'},
            }
            if schema:
                generation['responseJsonSchema'] = SCHEMAS[schema]
            payload = json.dumps({'contents':[{'role':'user','parts':[{'text':prompt}]}],
                                   'generationConfig':generation}, ensure_ascii=False).encode('utf-8')
            req = Request(url, data=payload, method='POST', headers={
                'Content-Type':'application/json', 'x-goog-api-key':key})
            try:
                with urlopen(req, timeout=150) as response:
                    return _parse_gemini_response(json.loads(response.read()))
            except HTTPError as e:
                body = e.read(3000).decode('utf-8','replace')
                status = (re.search(r'"status"\s*:\s*"([A-Z_]+)"',body) or [None, 'UNKNOWN'])[1]
                print(f'[Gemini] model={model} HTTP {e.code} status={status} '
                      f'attempt={attempt + 1}/3', file=sys.stderr, flush=True)
                errors.append(f'{model}: HTTP {e.code} ({status})')
                # Daily quota does not recover by waiting a minute; fall back to
                # a different model with its own independent RPD allowance.
                daily_exhausted = (e.code == 429 and (
                    'quota_exceeded' in body.lower() or
                    'perday' in body.lower() or
                    'per_day' in body.lower() or
                    'requestsperday' in body.lower()))
                if daily_exhausted or e.code in (400,401,402,403,404):
                    break
                if e.code in (408,429,500,502,503,504) and attempt < 2:
                    # Backoff helps with temporary server overload. Current
                    # free-tier caps are model-specific, not key-specific.
                    time.sleep([25, 90][attempt])
                    continue
                break
            except (GeminiResponseError, json.JSONDecodeError) as e:
                errors.append(f'{model}: {e}')
                print(f'[Gemini] invalid answer from {model}, try={attempt + 1}/3: {e}',
                      file=sys.stderr,flush=True)
                if attempt < 2:
                    time.sleep(8)
                    continue
            except (URLError, TimeoutError, OSError) as e:
                errors.append(f'{model}: network error {type(e).__name__}')
                if attempt < 2:
                    time.sleep([25, 90][attempt]); continue
    raise RuntimeError('All allowed free Gemini models failed: ' + '; '.join(errors[-6:]))


def json_catalog(sources, max_n=48):
    return [{'id':s['id'],'title':s['title'], 'date':s['published'], 'feed':s['feed'],
             'excerpt':s['evidence'][:650], 'abstract_only':s.get('abstract_only',False), 'recent':s.get('recent',False)}
            for s in sources[:max_n]]


def previous_titles():
    all_titles = []
    for fn in sorted((ROOT / 'issues').glob('*/issue.json'), reverse=True)[:14]:
        try:
            d = json.loads(fn.read_text(encoding='utf-8'))
            all_titles.extend(x['title'] for x in d.get('articles', []))
        except (KeyError, ValueError):
            pass
    return all_titles[:100]


def choose_plan(sources, today):
    catalog = json.dumps(json_catalog(sources), ensure_ascii=False)
    prompt = f'''Ты выпускающий редактор 387 News, высокие стандарты отбора. Сегодня по Москве {today}.
Имеются ТОЛЬКО ЭТИ РЕАЛЬНО ПОЛУЧЕННЫЕ ИСТОЧНИКИ: {catalog}
Предыдущие сюжеты, которых нельзя повторять без существенного нового события: {json.dumps(previous_titles(), ensure_ascii=False)}
Подготовь план 8 содержательных СИЛЬНЫХ и РАЗНЫХ материалов: 2 больших по 900–1400 русских слов, остальные по 420–650 слов.
Обязательны Семья, Москва и путешествия, Здоровье и движение; около половины выпуска эти категории. Остальные — культура, история, открытия, экономика и технологии (без перекоса в ИИ).
Новость — только действительно свежее 24–72 ч, дату проверять в источнике; evergreen-истории явно помечай как внеповесточные. Для конкретных мероприятий НЕ обещай цену, дату, время или продажу билетов без подтверждения в источнике. Перечисленные источники — единственное доказательное основание, не выдумывай факты.
Указывай kind="новость" ТОЛЬКО при наличии источника с recent=true. Иначе пиши kind="очерк" или kind="путеводитель" и явно отмечай дату источника.
Если сильных материалов недостаточно, верни {{"articles":[]}}: лучше пропуск номера, чем слабая газета.
Верни только JSON вида: {{"articles":[{{"title":"...", "category":"Семья", "kind":"очерк", "source_ids":["S001"], "angle":"в чём содержательный сюжет", "long":true}}]}}.
Категория только из {json.dumps(VALID_CATEGORIES, ensure_ascii=False)}.
Не используй более 2 статей по одному источнику; разные темы обязательны.'''
    plan = gemini(prompt, 8000, schema='plan')
    stories = plan.get('articles', [])
    if len(stories) != 8:
        raise RuntimeError('Editor could not select eight worthwhile articles')
    categories = [s.get('category') for s in stories]
    if not set(VALID_CATEGORIES[:3]).issubset(categories):
        raise RuntimeError('Missing an obligatory life section')
    if sum(1 for c in categories if c in VALID_CATEGORIES[:3]) < 4:
        raise RuntimeError('Insufficient family/Moscow/health coverage')
    if sum(s.get('long') is True for s in stories) < 2:
        raise RuntimeError('Insufficient major features')
    allowed = {s['id'] for s in sources}
    for s in stories:
        if s.get('category') not in VALID_CATEGORIES or not s.get('source_ids'):
            raise RuntimeError('Invalid editorial category or missing sources')
        if any(x not in allowed for x in s['source_ids']):
            raise RuntimeError('Editorial plan references an invented source')
        lookup = {source['id']:source for source in sources}
        if s.get('kind','').lower() == 'новость' and not any(lookup[x].get('recent',False) for x in s['source_ids']):
            raise RuntimeError('Stale event incorrectly described as new')
        if s.get('long') and not any(len(lookup[x]['evidence']) >= 1600 for x in s['source_ids']):
            raise RuntimeError('Major feature lacks enough source material')
    return stories


def count_words(s):
    return len(re.findall(r'(?u)\b[\w-]+\b', s))


def write_article(plan, source_map, today):
    links = []
    for sid in plan['source_ids'][:3]:
        x = source_map[sid]
        links.append({'id':sid,'title':x['title'],'url':x['url'],'date':x['published'],
                      'content':x['evidence'][:7200], 'abstract_only':x.get('abstract_only', False)})
    want = 1100 if plan['long'] else 490
    prompt = f'''Создай ПОЛНЫЙ русский журналистский материал для 387 News за {today}, объём примерно {want} слов.
План: {json.dumps(plan, ensure_ascii=False)}
Проверяемые исходные материалы: {json.dumps(links, ensure_ascii=False)}
Писать как литературно качественный авторский материал с сильной завязкой, обстоятельным развитием, именами, проверенными деталями и содержательным финалом. Без рекламных восторгов, клише, банальных списков и чрезмерной персонализации. Строго отделяй факты от гипотез. НЕ выдумывай никаких имён, результатов опытов, дат выставок, часов, цен, цитат, статистики, научных выводов, которых нет в представленных источниках. Если исходные материалы кратки — углубляй объяснение контекста без новых неподтвержденных фактов; не выдавай обобщения за новые исследования. Никаких неподтверждённых медицинских обещаний. Не цитируй из оригинальных статей длинные фрагменты, используй собственную оригинальную речь. Ссылки на источники сайт добавит сам.
Верни JSON: {{"title":"...", "teaser":"... (50–90 слов)", "paragraphs":[{{"heading":"возможный подзаголовок или пустая строка", "text":"связный абзац (без HTML и Markdown)"}}]}}. Нужно не менее 8 абзацев и объём около {want} слов. Не включай заметки о том, что ты ИИ.'''
    data = gemini(prompt, 12000 if plan['long'] else 8000, schema='article')
    paragraphs = data.get('paragraphs', [])
    if not isinstance(paragraphs, list) or len(paragraphs) < 7:
        raise RuntimeError(f'Article incomplete: {plan["title"]}')
    full = ' '.join(p.get('text','') for p in paragraphs if isinstance(p,dict))
    n = count_words(full)
    # The reader accepts shorter stories. This gate measures characters in the
    # actual article body, not word count: 580 characters including spaces.
    char_count = len(full.strip())
    minimum_chars = 580
    if char_count < minimum_chars:
        raise RuntimeError(f'Article too short ({char_count} < {minimum_chars} characters): {plan["title"]}')
    if n > 2100 or not (25 <= len(data.get('title','')) <= 190) or len(data.get('teaser','')) < 100:
        raise RuntimeError(f'Article has invalid length/metadata: {plan["title"]}')
    data['category'] = plan['category']
    data['kind'] = plan['kind']
    data['long'] = bool(plan['long'])
    data['source_ids'] = list(plan['source_ids'][:3])
    data['word_count'] = n
    data['character_count'] = char_count
    return data


def editorial_audit(articles, sources):
    if len(articles) != 8 or sum(x['long'] for x in articles) < 2:
        raise RuntimeError('Incomplete issue')
    total_words = sum(a['word_count'] for a in articles)
    total_chars = sum(a.get('character_count', len(' '.join(p['text'] for p in a['paragraphs']).strip()))
                      for a in articles)
    # Preserve eight complete articles and the factual audit, but do not
    # reject a validated issue merely for having fewer than 3,500 words.
    if total_chars < 8 * 580:
        raise RuntimeError(f'Issue too short ({total_chars} < {8 * 580} characters), no publication')
    titles = [x['title'].strip().casefold() for x in articles]
    if len(set(titles)) != 8:
        raise RuntimeError('Duplicate headlines')
    source_map = {x['id']:x for x in sources}
    for a in articles:
        if len(set(a['source_ids'])) < 1 or any(sid not in source_map for sid in a['source_ids']):
            raise RuntimeError('Article has an unverified citation')
        if any(len(p.get('text','')) < 30 for p in a['paragraphs']):
            raise RuntimeError('Article has incomplete paragraphs')
    # An independent model review cannot guarantee truth, but may catch obvious misattribution.
    condensed = [{'title':a['title'],'facts':(' '.join(p['text'] for p in a['paragraphs']))[:4000],
                  'sources':[{'url':source_map[s]['url'],'evidence':source_map[s]['evidence'][:1300]} for s in a['source_ids']]}
                 for a in articles]
    check = gemini('Ты строгий фактчекер. На основе КОНКРЕТНЫХ выдержек из источников найди ясные явные выдумки, неверные даты, придуманные расписания, недоказанные медицинские утверждения. Если нет достаточной информации для проверки утверждения, тоже бракуй. Важна безопасность автоматической публикации. Верни JSON {"ok":true/false,"reasons":["..."]}. Данные: '+json.dumps(condensed, ensure_ascii=False), 5500, schema='audit')
    if check.get('ok') is not True:
        raise RuntimeError('Editorial factual audit failed: ' + ', '.join(check.get('reasons', [])[:2]))
    return total_words


def slugify(value, index):
    return f'feature-{index:02d}'


def page_header(title, description, canonical, date_obj, no, root=''):
    date_ru = date_obj.strftime('%d.%m.%Y')
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#263d36"><title>{escape(title)} — 387 News</title><meta name="description" content="{escape(description[:165],quote=True)}"><link rel="canonical" href="https://387.su{escape(canonical,quote=True)}"><link rel="stylesheet" href="/assets/style.css"><script defer src="/assets/main.js"></script></head><body><div class="readingprogress"></div><div class="top"><div class="wrap"><span>Ежедневная газета · Москва</span><span>{date_ru} · № {no:03d} · Редакция 2.0</span></div></div><header class="mast wrap"><div class="mast-top"><span>Личный ежедневный журнал</span><span>06:00 · московское время</span></div><a class="logo" href="/">387 <span>NEWS</span></a><div class="motto">Каждый день есть что открыть</div></header><nav class="topics wrap" aria-label="Рубрики"><a href="/">Обзор номера</a><a href="/#contents">Все статьи</a><a href="/#family">Семья</a><a href="/#moscow">Москва</a><a href="/#health">Здоровье</a><a href="/archive/">Архив</a></nav>'''


def page_footer():
    return '''<footer class="foot"><div class="wrap foot-inner"><div><b>387 NEWS</b><p>Независимая подборка материалов. Указанные источники позволяют проверить ключевые сведения; в газете нет рекламы.</p></div><div class="footnav"><a href="/">Главная</a><a href="/archive/">Архив</a><a href="#top" onclick="window.scrollTo({top:0,behavior:'smooth'});return false">Наверх ↑</a></div></div></footer></body></html>'''


def render_overview(date_obj, no, articles, permanent=False):
    ds = date_obj.date().isoformat()
    intro = 'В этом выпуске — семейные практики, московские открытия, здоровье и самые содержательные истории мира. Все статьи доступны целиком.'
    r = [page_header(f'Выпуск № {no:03d} · {ds}', intro, f'/issues/{ds}/' if permanent else '/', date_obj, no),
         '<main class="wrap"><section class="front-intro"><div><h1>Обзор номера</h1><p>'+intro+'</p></div><div class="right">'+str(len(articles))+' самостоятельных материалов<br>Каждый — на отдельной странице</div></section>',
         '<section class="front-grid">']
    for i,a in enumerate(articles[:5]):
        link = f'/issues/{ds}/articles/{a["slug"]}/'
        img = '/assets/'+FALLBACK_IMAGE[a['category']]
        tag = escape(a['category'])+' · '+str(max(2,round(a['word_count']/165)))+' минут чтения'
        if i==0:
            r.append(f'<article class="lead"><a href="{link}"><img src="{img}" alt="Авторская иллюстрация редакции, не документальная фотография"></a><div class="meta">Главная история · {tag}</div><h2><a href="{link}">{escape(a["title"])}</a></h2><p>{escape(a["teaser"])}</p></article>')
        elif i==1:
            r.append(f'<article class="mid"><a href="{link}"><img src="{img}" alt="Авторская иллюстрация редакции"></a><div class="meta">{tag}</div><h3><a href="{link}">{escape(a["title"])}</a></h3><p>{escape(a["teaser"])}</p></article><div class="tiny">')
        else:
            r.append(f'<article><div class="meta">{tag}</div><h3><a href="{link}">{escape(a["title"])}</a></h3><p>{escape(a["teaser"])}</p></article>')
    r += ['</div></section><div class="front-details"><section id="contents"><div class="all-top"><h2>В этом выпуске · '+str(len(articles))+' статей</h2><span>Читать можно в любом порядке</span></div><div class="contents">']
    for i,a in enumerate(articles, 1):
        anchor = {'Семья':'family','Москва и путешествия':'moscow','Здоровье и движение':'health'}.get(a['category'], a['slug'])
        r.append(f'<article class="toc" id="{anchor if not any(x.get("toc_anchor")==anchor for x in articles[:i-1]) else a["slug"]}"><span class="toc-num">{i:02d}</span><div><div class="meta">{escape(a["category"])} · {max(2,round(a["word_count"]/165))} мин.</div><h3><a href="/issues/{ds}/articles/{a["slug"]}/">{escape(a["title"])}</a></h3><p>{escape(a["teaser"])}</p></div></article>')
        a['toc_anchor'] = anchor
    r += ['</div></section><aside class="sidebar"><h3>Сегодня в газете</h3><p>Обзор номера собран на этой странице. Большие тексты открываются отдельно, чтобы к ним было удобно возвращаться.</p><h3>Как читать</h3><p>Источники указаны под каждым материалом. Иллюстрации носят редакционный характер и не заменяют документальные фотографии.</p></aside></div></main>',page_footer()]
    return ''.join(r)


def render_article(date_obj,no,article,source_map):
    ds = date_obj.date().isoformat()
    link = f'/issues/{ds}/articles/{article["slug"]}/'
    t = [page_header(article['title'],article['teaser'],link,date_obj,no),
         f'<main class="wrap"><div class="art-top"><div class="breadcrumbs"><a href="/">Главная</a> / <a href="/issues/{ds}/">№ {no:03d}</a> / {escape(article["category"])}</div></div>',
         f'<article class="article-shell"><div class="meta">{escape(article["category"])} · {escape(article["kind"])}</div>',
         f'<h1>{escape(article["title"])}</h1><p class="dek">{escape(article["teaser"])}</p>',
         f'<div class="byline"><span>Редакция 387 News · {ds}</span><span>Примерно {max(2,round(article["word_count"]/165))} минут чтения</span></div>',
         f'<img class="heroimg" src="/assets/{FALLBACK_IMAGE[article["category"]]}" alt="Авторская иллюстрация редакции"><div class="caption">Редакционная иллюстрация; не фотография описываемых событий.</div>',
         '<div class="article-body">']
    for p in article['paragraphs']:
        if p.get('heading'):
            t.append(f'<h2>{escape(p["heading"])}</h2>')
        t.append(f'<p>{escape(p["text"])}</p>')
    t.append('</div><div class="sources"><h2>Источники и проверка</h2><ol>')
    for source_id in article['source_ids']:
        x = source_map[source_id]
        t.append(f'<li><a href="{escape(x["url"],quote=True)}" rel="noopener noreferrer" target="_blank">{escape(x["title"])}</a> — {escape(x["published"])}'+(' (использован анонс/аннотация)' if x.get('abstract_only') else '')+'</li>')
    t += ['</ol></div></article>',f'<div class="after-article"><a href="/issues/{ds}/">← Все статьи номера</a><button class="bookmark" data-bookmark="{link}" aria-pressed="false">Сохранить статью</button></div></main>',page_footer()]
    return ''.join(t)


def get_next_number():
    nums = []
    for fn in (ROOT/'issues').glob('*/issue.json'):
        try:
            nums.append(int(json.loads(fn.read_text(encoding='utf-8'))['number']))
        except Exception:
            pass
    # Existing first issue is № 001, without JSON metadata.
    return max(nums+[1])+1


def render_archive():
    entries = []
    for directory in (ROOT/'issues').glob('20??-??-??'):
        if not (directory/'index.html').exists():
            continue
        try:
            issue = json.loads((directory/'issue.json').read_text(encoding='utf-8'))
            no = issue['number']
            title = escape(issue['articles'][0]['title'])
            desc = f'{len(issue["articles"])} материалов'
        except (FileNotFoundError, KeyError, ValueError):
            no, title, desc = 1, 'Пилотный выпуск 387 News', '10 материалов'
        entries.append((directory.name,no,title,desc))
    entries.sort(reverse=True)
    latest_date = datetime.fromisoformat(entries[0][0]) if entries else datetime.now(TZ)
    no = entries[0][1] if entries else 1
    r = [page_header('Архив выпусков','Архив всех выпусков 387 News','/archive/',latest_date,no), '<main class="wrap archive"><div class="overline">Ретроспектива номеров</div><h1>Архив 387 News</h1>']
    for dt, num, title, desc in entries:
        r.append(f'<div class="archive-card"><div><div class="meta">№ {num:03d} · {escape(dt)}</div><h2><a href="/issues/{dt}/">{title}</a></h2><p>{desc}</p></div><a href="/issues/{dt}/">Обзор выпуска →</a></div>')
    r.append('</main>'+page_footer())
    return ''.join(r)


def sitemap():
    urls = ['/','/archive/']
    for issue in sorted((ROOT/'issues').glob('20??-??-??')):
        if not (issue/'index.html').exists():
            continue
        urls.append(f'/issues/{issue.name}/')
        for d in sorted((issue/'articles').glob('*/index.html')):
            urls.append(f'/issues/{issue.name}/articles/{d.parent.name}/')
    return '<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>https://387.su'+escape(url)+'</loc></url>' for url in urls)+'</urlset>'


def validate_local_links(paths):
    for path in paths:
        html = path.read_text(encoding='utf-8')
        for uri in re.findall(r'(?:href|src)="(/[^"#?]+)', html):
            rel = ROOT / uri.lstrip('/')
            dest = rel / 'index.html' if uri.endswith('/') else rel
            if not dest.is_file():
                raise RuntimeError(f'Broken local link: {path.name} -> {uri}')


def wait_until_release():
    release = datetime.now(TZ).replace(hour=6, minute=0, second=0, microsecond=0)
    if datetime.now(TZ) >= release:
        return
    remaining = (release-datetime.now(TZ)).total_seconds()
    if remaining > 45*60:
        raise RuntimeError('Prepared unusually early; refusing publication')
    print(f'Validated private draft. Holding release until 06:00 MSK ({round(remaining)} seconds).',flush=True)
    time.sleep(max(0,remaining))


def run(mode):
    now = datetime.now(TZ)
    ds = now.date().isoformat()
    issue_dir = ROOT/'issues'/ds
    if issue_dir.exists():
        print(f'Already exists: {ds}. No duplicate issue produced.')
        return
    if not (ROOT/'index.html').is_file() or not (ROOT/'assets/style.css').is_file():
        raise RuntimeError('Existing website is missing. Upload the original 387 News first.')
    print(f'[research] {ds} (Moscow), collecting available original sources...',flush=True)
    sources = gather_sources(now)
    if len(sources) < 12:
        raise RuntimeError('Too few independently retrieved sources; no issue published')
    plan = choose_plan(sources, ds)
    source_map = {s['id']:s for s in sources}
    articles = []
    for n, item in enumerate(plan,1):
        print(f'[writing] {n}/{len(plan)} {item["category"]}',flush=True)
        a = write_article(item, source_map, ds)
        a['slug'] = slugify(a['title'],n)
        articles.append(a)
        time.sleep(1)
    print('[audit] verifying issue...', flush=True)
    total = editorial_audit(articles, sources)
    no = get_next_number()
    issue_dir.mkdir(parents=True, exist_ok=False)
    page_paths = []
    for a in articles:
        p = issue_dir/'articles'/a['slug']/'index.html'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(render_article(now,no,a,source_map),encoding='utf-8')
        page_paths.append(p)
    issue_dir.joinpath('issue.json').write_text(json.dumps({'date':ds,'number':no,'articles':articles},ensure_ascii=False,indent=2),encoding='utf-8')
    overview = render_overview(now,no,articles,permanent=True)
    (issue_dir/'index.html').write_text(overview,encoding='utf-8')
    page_paths.append(issue_dir/'index.html')
    (ROOT/'index.html').write_text(render_overview(now,no,articles),encoding='utf-8')
    page_paths.append(ROOT/'index.html')
    (ROOT/'archive/index.html').write_text(render_archive(),encoding='utf-8')
    page_paths.append(ROOT/'archive/index.html')
    (ROOT/'sitemap.xml').write_text(sitemap(),encoding='utf-8')
    validate_local_links(page_paths)
    print(f'[approved] no {no:03d} — {len(articles)} articles, {total} words, no broken local links',flush=True)
    if mode == 'scheduled':
        wait_until_release()
    elif mode == 'dry-run':
        # The preview is an Actions artifact only; no git commit.
        print('DRY RUN: draft is attached to this Actions run, not published.',flush=True)
    else:
        print('MANUAL PUBLISH REQUESTED: validation passed, files are ready to commit.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('scheduled','dry-run','publish'),default='dry-run')
    args=parser.parse_args()
    try:
        run(args.mode)
    except Exception as exc:
        print(f'NOT PUBLISHED: {exc}', file=sys.stderr)
        sys.exit(1)
