#!/usr/bin/env python3
"""Nonpublishing, bounded, spaced Gemini API endurance probe for 387 News.

Records metadata only: no generated drafts, key or source text are stored.
Python stdlib, intended for GitHub Actions workflow_dispatch.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo('Europe/Moscow')
MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.6-flash')
BASE = Path(os.environ.get('GEMINI_PROBE_OUT', 'diagnostics/gemini-probe'))
API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'
# Schema is aligned with the existing 387 News scripts/news.py generator.
ARTICLE_SCHEMA = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string'}, 'teaser': {'type': 'string'},
        'paragraphs': {'type': 'array', 'items': {
            'type': 'object', 'properties': {'heading': {'type': 'string'}, 'text': {'type': 'string'}},
            'required': ['heading', 'text']}}
    }, 'required': ['title', 'teaser', 'paragraphs']
}
PLAN_SCHEMA = {
    'type': 'object', 'properties': {'articles': {'type': 'array', 'items': {
        'type': 'object', 'properties': {
            'title': {'type': 'string'}, 'category': {'type': 'string'},
            'kind': {'type': 'string'}, 'source_ids': {'type': 'array', 'items': {'type': 'string'}},
            'angle': {'type': 'string'}, 'long': {'type': 'boolean'}},
        'required': ['title', 'category', 'kind', 'source_ids', 'angle', 'long']}}},
    'required': ['articles']
}
AUDIT_SCHEMA = {
    'type': 'object', 'properties': {'ok': {'type': 'boolean'}, 'reasons': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['ok', 'reasons']
}

# Simulated factual context. Not copied from a website; no resulting texts are published.
# Expanded to resemble the contextual payload size of genuine source-led articles.
CONTEXT = ("ТЕСТОВЫЙ КОНТЕКСТ, НЕ ИСТОЧНИК ДЛЯ ПУБЛИКАЦИИ. Семейная жизнь складывается из разных "
           "возрастных интересов, свободного времени взрослых, расписания детей, погоды и доступности дорог. "
           "При подготовке маршрута следует отдельно оценить продолжительность дороги, сложность для младших "
           "детей, возможность прогулки с коляской, возможность вернуться домой, питание и ограничения музея. "
           "Для материалов о здоровье нужно разделять наблюдательные исследования и эксперименты, указывать "
           "ограничения выборки и не превращать результаты в лечебные рекомендации. Для литературного очерка "
           "нужны обстоятельная завязка, последовательно развивающийся сюжет, конкретные детали и ясный финал. "
           "Для новости нужно подтверждать дату события по оригиналу, а не по дате перепечатки. ") * 7
CATEGORIES = ['Семья', 'Москва и путешествия', 'Здоровье и движение', 'История и культура', 'Экономика и бизнес', 'Наука']


def make_prompt(kind: str, index: int) -> tuple[str, dict, int]:
    cat = CATEGORIES[index % len(CATEGORIES)]
    if kind == 'article':
        prompt = (f'Технический тест модели для газеты 387 News. Напиши связный русский очерк в рубрике «{cat}» '
                  'на 650–850 слов с содержательной завязкой и не менее чем 8 абзацами. '
                  'Не изобретай реальные события, выставки, имена, результаты исследований, цены или даты. '
                  'Материал — ИМИТАЦИЯ журналистского текста, никогда не публикуется. '
                  'Используй общий контекст только как материал для авторского обобщения, без заявлений '
                  'об изучении первоисточников. Верни только JSON с ключами title, teaser, paragraphs. '
                  'Каждый paragraph — {heading: строка, text: связный абзац}. Контекст:\n' + CONTEXT)
        return prompt, ARTICLE_SCHEMA, 12000
    if kind == 'plan':
        sources = [{'id': f'S{x:03}', 'category': CATEGORIES[x % len(CATEGORIES)],
                    'title': f'Тестовая редакционная карточка {x}',
                    'excerpt': CONTEXT[:220], 'recent': False}
                   for x in range(1, 31)]
        prompt = ('Техническая имитация плана номера 387 News: восемь РАЗНЫХ сюжетов, обязательны рубрики '
                  'Семья, Москва и путешествия, Здоровье и движение, минимум два больших очерка. '
                  'Указанные карточки специально вымышленные для нагрузочного теста, не настоящие источники, '
                  'ничего нельзя публиковать. Отвечай JSON объектом articles с полями '
                  'title, category, kind, source_ids, angle, long. Данные: ' + json.dumps(sources, ensure_ascii=False))
        return prompt, PLAN_SCHEMA, 7500
    prompt = ('Технический тест редакторской оценки текста (ничего не публикуется). '
              'Прочти имитацию источника и ответь JSON объектом {ok: bool, reasons: string[]} '
              'о том, может ли он обосновать конкретные факты, даты и цифры. '
              'Если текст не содержит подтверждённых фактов, укажи причины. Текст: ' + CONTEXT[:4000])
    return prompt, AUDIT_SCHEMA, 5000


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def safe_error_message(message: str) -> str:
    message = re.sub(r'AIza[A-Za-z0-9_-]{15,}', '[REDACTED_API_KEY]', message)
    message = re.sub(r'[\r\n\t]+', ' ', message)
    return message[:220]


def decode_200(body: bytes, kind: str) -> dict:
    obj = json.loads(body)
    candidate = (obj.get('candidates') or [{}])[0]
    finish = candidate.get('finishReason', '')
    content = candidate.get('content') or {}
    output = ''.join(part.get('text', '') for part in content.get('parts', [])
                     if isinstance(part, dict) and not part.get('thought'))
    usage = obj.get('usageMetadata') or {}
    result = {'finish_reason': finish, 'output_chars': len(output),
              'output_words': len(re.findall(r'(?u)\b[\w-]+\b', output)),
              'prompt_tokens': usage.get('promptTokenCount', 0),
              'output_tokens': usage.get('candidatesTokenCount', 0),
              'thought_tokens': usage.get('thoughtsTokenCount', 0),
              'total_tokens': usage.get('totalTokenCount', 0), 'json_ok': False,
              'article_chars': 0, 'paragraphs': 0}
    try:
        payload = json.loads(output)
        if not isinstance(payload, dict):
            return result
        if kind == 'article':
            paragraphs = payload.get('paragraphs') or []
            if not isinstance(paragraphs, list):
                return result
            text = ' '.join(p.get('text', '') for p in paragraphs if isinstance(p, dict))
            result['paragraphs'] = len(paragraphs)
            result['article_chars'] = len(text.strip())
            result['json_ok'] = bool(payload.get('title')) and len(paragraphs) >= 7
        elif kind == 'plan':
            result['json_ok'] = isinstance(payload.get('articles'), list)
        else:
            result['json_ok'] = isinstance(payload.get('ok'), bool)
    except (ValueError, TypeError):
        pass
    return result


def one_attempt(key: str, kind: str, slot: int, attempt: int, timeout: int = 150) -> dict:
    prompt, schema, max_output = make_prompt(kind, slot)
    payload = json.dumps({
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': {
            'responseMimeType': 'application/json',
            'responseJsonSchema': schema,
            'maxOutputTokens': max_output,
            'thinkingConfig': {'thinkingLevel': 'low'},
        }}, ensure_ascii=False).encode('utf-8')
    url = f'{API_BASE}/{MODEL}:generateContent'
    req = Request(url, data=payload, method='POST',
                  headers={'x-goog-api-key': key, 'Content-Type': 'application/json'})
    row = {'time_utc': now_utc(), 'model': MODEL, 'kind': kind, 'slot': slot,
           'attempt': attempt, 'http_status': 0, 'latency_s': 0,
           'error_class': '', 'error_message': '', 'response_retry_after': ''}
    start = time.monotonic()
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read(2_000_000)
            row['http_status'] = resp.status
        row.update(decode_200(data, kind))
    except HTTPError as exc:
        row['http_status'] = exc.code
        row['error_class'] = 'HTTPError'
        row['response_retry_after'] = str(exc.headers.get('Retry-After', ''))[:50]
        try:
            info = json.loads(exc.read(4096))
            err = info.get('error') or {}
            row['error_message'] = safe_error_message(str(err.get('message','')))
        except (ValueError, UnicodeError):
            row['error_message'] = ''
    except (URLError, TimeoutError, OSError) as exc:
        row['error_class'] = type(exc).__name__
        row['error_message'] = safe_error_message(str(exc))
    except (ValueError, KeyError, TypeError) as exc:
        row['error_class'] = type(exc).__name__
        row['error_message'] = safe_error_message(str(exc))
    finally:
        row['latency_s'] = round(time.monotonic() - start, 2)
    return row


def p95(numbers: list[float]) -> float:
    if not numbers:
        return 0
    ordered = sorted(numbers)
    return ordered[math.ceil(.95 * len(ordered)) - 1]


def summarize(records: list[dict], started: str, target_minutes: int, complete: bool) -> tuple[dict, str]:
    codes = Counter(str(x.get('http_status',0)) for x in records)
    ok = [x for x in records if x.get('http_status') == 200 and x.get('json_ok')]
    one_per_slot = {}
    for row in records:
        one_per_slot.setdefault(row['slot'], []).append(row)
    completed_slots = sum(any(a.get('http_status') == 200 and a.get('json_ok') for a in attempts)
                          for attempts in one_per_slot.values())
    latencies = [x['latency_s'] for x in records if x.get('http_status') == 200]
    usage_keys = ['prompt_tokens','output_tokens','thought_tokens','total_tokens']
    total_usage = {k: sum(x.get(k,0) if isinstance(x.get(k),int) else 0 for x in records) for k in usage_keys}
    article_ok = [x for x in ok if x.get('kind') == 'article']
    summary = {
        'model': MODEL, 'started_utc': started, 'ended_utc': now_utc(),
        'duration_requested_minutes': target_minutes, 'completed_entire_duration': complete,
        'slots_started': len(one_per_slot), 'slots_succeeded': completed_slots,
        'api_requests_total': len(records), 'successful_valid_responses': len(ok),
        'http_codes': dict(codes), 'median_success_latency_seconds': round(statistics.median(latencies),2) if latencies else 0,
        'p95_success_latency_seconds': p95(latencies), 'token_usage_successes': total_usage,
        'article_samples': len(article_ok),
        'article_samples_at_least_580_chars': sum(x.get('article_chars',0) >=580 for x in article_ok),
        'article_median_body_characters': int(statistics.median([x['article_chars'] for x in article_ok])) if article_ok else 0,
    }
    test_ok = (codes.get('429',0)==0 and completed_slots>=max(3, int(.8*len(one_per_slot)))
               and (not article_ok or summary['article_samples_at_least_580_chars'] == len(article_ok)))
    status = ('ПРЕДВАРИТЕЛЬНО УСТОЙЧИВО' if test_ok and complete else 'НУЖНО ПОВТОРИТЬ ИЛИ СМЕНИТЬ РЕЖИМ')
    text = f'''# 387 News — отчёт длительного теста Gemini

**Результат: {status}.** Это выборочное наблюдение, а не гарантия доступности и не официальные квоты Google.

- Модель: `{MODEL}`
- Начало (UTC): {started}; конец (UTC): {summary['ended_utc']}
- Запланированная продолжительность: {target_minutes} минут; полный интервал: {'да' if complete else 'нет'}
- Плановых операций начато: **{len(one_per_slot)}**; завершено с корректным JSON: **{completed_slots}**
- Запросов к API с учётом повторов: **{len(records)}**
- HTTP-коды: `{json.dumps(dict(codes), ensure_ascii=False)}`
- Время успешных ответов: медиана **{summary['median_success_latency_seconds']} с**, p95 **{summary['p95_success_latency_seconds']} с**
- Токены (ответы HTTP 200): `{json.dumps(total_usage, ensure_ascii=False)}`
- Тестовых статей: **{len(article_ok)}**; достигли 580 символов: **{summary['article_samples_at_least_580_chars']}**
- Медианная длина тела тестовой статьи: **{summary['article_median_body_characters']} символов**

## Как интерпретировать

- **503** — временная недоступность/перегрузка серверов, это **не** измерение вашей квоты.
- **429** — ограничение скорости или квоты; точное ограничение RPM/TPM/RPD нужно сверять в AI Studio → Rate limits.
- Ответ **200** с неполным JSON или малым объёмом — проблема качества/ограничения ответа, а не квоты.
- Частота запросов в тесте специально низкая. Для оценки реальных активных числовых лимитов смотрите интерфейс Google AI Studio.
- Тест не доказывает достоверность статей: в целях измерения используются синтетические исходные данные; готовые тексты не сохраняются.

## Подробности

`attempts.json` — измерения каждого обращения, без API-ключа, исходных текстов и ответов модели. `summary.json` — сводные показатели. Газета и GitHub Pages не изменялись.
'''
    return summary, text


def persist(records, started, duration, complete):
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / 'attempts.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    summary, md = summarize(records, started, duration, complete)
    (BASE / 'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (BASE / 'REPORT.md').write_text(md,encoding='utf-8')
    return summary


def run(duration: int, interval: int, max_calls: int, timeout: int) -> int:
    key = os.getenv('GEMINI_API_KEY','').strip()
    if not key:
        print('ERROR: GEMINI_API_KEY is not configured. No requests sent.',file=sys.stderr)
        return 2
    started = now_utc()
    records = []
    began = time.monotonic()
    deadline = began + duration * 60
    hard_stop = False
    reasons = []
    print(f'Probe started. Model={MODEL}, duration={duration}m, spacing={interval}m, max actual API calls={max_calls}',flush=True)
    try:
        slot = 0
        while time.monotonic() < deadline-60 and len(records) < max_calls:
            planned = began + slot * interval * 60
            if planned >= deadline-60:
                break
            if time.monotonic() < planned:
                time.sleep(min(planned - time.monotonic(), 10))
                continue
            kind = ('plan', 'article', 'article', 'audit')[slot % 4]
            for retry in range(3):
                if len(records) >= max_calls or time.monotonic() >= deadline - 60:
                    break
                row = one_attempt(key, kind, slot, retry + 1, timeout=timeout)
                records.append(row)
                persist(records,started,duration,False)
                print(f"[{datetime.now(MOSCOW):%H:%M:%S} MSK] slot={slot+1} kind={kind} attempt={retry+1} "
                      f"HTTP={row['http_status']} latency={row['latency_s']}s "
                      f"json_ok={row.get('json_ok',False)} tokens={row.get('total_tokens',0)}",flush=True)
                code=row['http_status']
                if code == 429:
                    reasons.append('HTTP 429: quota or rate limit reached; stopping to protect free tier')
                    hard_stop = True
                    break
                if code in (400,401,402,403,404):
                    reasons.append(f'HTTP {code}: configuration, billing or model error; stopping')
                    hard_stop = True
                    break
                if code==200:
                    break
                if code in (408,500,502,503,504,0) and retry < 2:
                    backoff=(60,180)[retry]
                    print(f'Transient error; waiting {backoff}s before retry.',flush=True)
                    time.sleep(min(backoff,max(0,deadline-time.monotonic()-50)))
                    continue
                break
            if hard_stop:
                break
            slot += 1
    except KeyboardInterrupt:
        reasons.append('Interrupted by user')
    finally:
        full = not hard_stop and not reasons and time.monotonic() >= deadline - interval * 60 - 70
        summary = persist(records,started,duration,full)
        if reasons:
            print('Stop reason: ' + '; '.join(reasons),flush=True)
        print('Probe complete: '+json.dumps({k:summary[k] for k in ('slots_started','slots_succeeded','api_requests_total','http_codes')},ensure_ascii=False),flush=True)
        print('Download artifact 387-gemini-probe-report from this workflow run. No site files were changed.',flush=True)
    return 0


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--duration-minutes',type=int,default=240)
    ap.add_argument('--interval-minutes',type=int,default=15)
    ap.add_argument('--max-calls',type=int,default=24)
    ap.add_argument('--timeout-seconds',type=int,default=145)
    args=ap.parse_args()
    if not 30 <= args.duration_minutes <= 300: ap.error('duration 30..300')
    if not 5 <= args.interval_minutes <= 60: ap.error('interval 5..60')
    if not 1 <= args.max_calls <= 35: ap.error('calls 1..35')
    return run(args.duration_minutes,args.interval_minutes,args.max_calls,args.timeout_seconds)

if __name__ == '__main__':
    raise SystemExit(main())
