#!/usr/bin/env python3
"""387 News 3.0: encrypted incremental drafts, no premature public release.

Free GitHub Actions, no private repository or paid API needed. Draft articles
are AES-256-GCM encrypted before any artifact upload. API credentials and
passphrases are never included in checkpoints or printed to logs.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta
import gzip
import io
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from scripts import news
except ImportError:
    import news

TZ = news.TZ
ROOT = news.ROOT
ARTIFACT_FILE = Path(os.environ.get('RUNNER_TEMP','/tmp')) / 'news-draft.enc'


def validate_key(key_b64: str) -> bytes:
    try:
        key = base64.b64decode(key_b64.strip(), validate=True)
    except Exception as e:
        raise RuntimeError('DRAFT_ENCRYPTION_KEY must be a base64-encoded 32-byte random key') from e
    if len(key) != 32:
        raise RuntimeError('DRAFT_ENCRYPTION_KEY must decode to exactly 32 bytes')
    return key


def cipher(state: dict, key: bytes) -> bytes:
    payload = gzip.compress(json.dumps(state, ensure_ascii=False).encode('utf-8'))
    nonce = secrets.token_bytes(12)
    return b'387N3' + nonce + AESGCM(key).encrypt(nonce, payload, b'387-News-Private-Draft-v3')


def decipher(blob: bytes, key: bytes) -> dict:
    if not blob.startswith(b'387N3') or len(blob) < 40:
        raise RuntimeError('Encrypted checkpoint has an invalid header')
    raw = AESGCM(key).decrypt(blob[5:17], blob[17:], b'387-News-Private-Draft-v3')
    state = json.loads(gzip.decompress(raw))
    if not isinstance(state, dict):
        raise RuntimeError('Invalid checkpoint data')
    return state


def request_json(url: str) -> dict:
    gh = os.environ.get('GH_TOKEN','').strip()
    if not gh:
        raise RuntimeError('GH_TOKEN missing (workflow must grant actions: read)')
    req = Request(url, headers={
        'Authorization':'Bearer '+gh,
        'Accept':'application/vnd.github+json',
        'X-GitHub-Api-Version':'2022-11-28',
        'User-Agent':'387-News-Checkpoint-Reader',
    })
    with urlopen(req,timeout=40) as response:
        return json.loads(response.read())


def fetch_latest_checkpoint(label: str, key: bytes) -> dict | None:
    repo = os.environ.get('GITHUB_REPOSITORY','')
    if not repo or '/' not in repo:
        # Local tests can instead use NEWS_TEST_CHECKPOINT below.
        local = os.environ.get('NEWS_TEST_CHECKPOINT')
        if local and Path(local).is_file():
            return decipher(Path(local).read_bytes(),key)
        return None
    from urllib.parse import quote
    api = f'https://api.github.com/repos/{repo}/actions/artifacts?per_page=100&name={quote(label)}'
    candidates = request_json(api).get('artifacts',[])
    candidates = [x for x in candidates if not x.get('expired') and x.get('name') == label]
    if not candidates:
        return None
    latest = max(candidates, key=lambda x:(x.get('created_at',''), x['id']))
    print(f'[checkpoint] found encrypted draft artifact ID={latest["id"]}',flush=True)
    url = f'https://api.github.com/repos/{repo}/actions/artifacts/{latest["id"]}/zip'
    req = Request(url,headers={
        'Authorization':'Bearer '+os.environ['GH_TOKEN'],
        'Accept':'application/vnd.github+json',
        'User-Agent':'387-News-Checkpoint-Reader'})
    with urlopen(req,timeout=65) as resp:
        data = resp.read(12_000_000)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return decipher(z.read('news-draft.enc'),key)


def save(state: dict, key: bytes):
    ARTIFACT_FILE.write_bytes(cipher(state, key))
    print(f'[checkpoint] AES-256-GCM encrypted; '
          f'{len(state.get("articles",{}))}/8 article drafts', flush=True)


def phase_date(phase: str, now: datetime, manual_date: str | None) -> str:
    if manual_date:
        return datetime.strptime(manual_date, '%Y-%m-%d').date().isoformat()
    if phase == 'plan':
        return (now.date()+timedelta(days=1)).isoformat()
    if phase == 'write' and now.hour >= 11:
        return (now.date()+timedelta(days=1)).isoformat()
    return now.date().isoformat()


def artifact_label(date: str, preview: bool) -> str:
    return f'387news-{"test" if preview else "production"}-{date}'


def build_plan(state: dict | None, date: str):
    if state:
        print('[plan] checkpoint already exists; not regenerating.',flush=True)
        return state
    target = datetime.fromisoformat(date+'T06:00:00').replace(tzinfo=TZ)
    sources = news.gather_sources(datetime.now(TZ))
    # News freshness is measured at PUBLICATION, not when sources are collected.
    for source in sources:
        source['recent'] = (not source.get('evergreen') and
                            news.is_recent(source.get('published', ''), target))
    if len(sources) < 12:
        raise RuntimeError(f'Only {len(sources)} retrieved sources; at least 12 required')
    planned = news.choose_plan(sources, date)
    return {'version':3, 'date':date, 'sources':sources, 'plan':planned,
            'articles':{}, 'stage':'planned', 'audit_passed':False,
            'created_at':datetime.now(TZ).isoformat()}


def write_batch(state: dict, size=2):
    if state.get('audit_passed'):
        print('[write] already audited; no edits allowed',flush=True)
        return state
    if not state.get('plan'):
        raise RuntimeError('Missing story plan; run plan phase first')
    known = {s['id']:s for s in state['sources']}
    pending = [i for i in range(len(state['plan'])) if str(i) not in state['articles']]
    for i in pending[:size]:
        print(f'[write] article {i+1}/8 category={state["plan"][i]["category"]}',flush=True)
        try:
            article = news.write_article(state['plan'][i],known,state['date'])
            article['slug'] = news.slugify(article['title'],i+1)
            state['articles'][str(i)] = article
            print(f'[write] saved {i+1}/8, {article["word_count"]} words',flush=True)
        except Exception as e:
            # Preserve completed items and give later batches a chance to retry.
            print(f'[write] failed slot {i+1}; no public changes: {str(e)[:240]}',file=sys.stderr,flush=True)
    state['stage'] = 'writing'
    return state


def audit(state: dict):
    if state.get('audit_passed'):
        print('[audit] approved previously, no extra model requests',flush=True)
        return state
    plan = state.get('plan',[])
    articles = state.get('articles',{})
    if len(plan) != 8 or len(articles) != 8:
        raise RuntimeError(f'Incomplete issue: {len(articles)}/8. Not approved for publication.')
    ordered = [articles[str(i)] for i in range(8)]
    target_release = datetime.fromisoformat(state['date']+'T06:00:00').replace(tzinfo=TZ)
    lookup = {x['id']:x for x in state['sources']}
    for article in ordered:
        if article['kind'].lower() == 'новость':
            if not any(news.is_recent(lookup[i]['published'],target_release)
                       for i in article['source_ids']):
                raise RuntimeError('News item older than 72h at release; audit blocked')
    count = news.editorial_audit(ordered,state['sources'])
    state['audit_passed'] = True
    state['stage'] = 'audited'
    state['word_count'] = count
    state['audited_at'] = datetime.now(TZ).isoformat()
    print(f'[audit] approved 8 articles, {count} words; source IDs validated',flush=True)
    return state


def render(state: dict, preview: bool):
    if not state.get('audit_passed') or state.get('stage') != 'audited':
        raise RuntimeError('No approved draft; not publishing')
    date = state['date']
    release = datetime.fromisoformat(date+'T06:00:00').replace(tzinfo=TZ)
    now = datetime.now(TZ)
    if not preview and now < release:
        seconds = (release - now).total_seconds()
        if seconds > 25*60:
            raise RuntimeError('Too early to publish; refusing exposure of unreleased issue')
        print(f'[release] private until 06:00 MSK; waiting {int(seconds)} seconds',flush=True)
        time.sleep(seconds)
    issue_dir = ROOT / 'issues' / date
    if issue_dir.exists():
        print('[release] issue already exists in repository; no duplicate',flush=True)
        return False
    if preview:
        # Can test build correctness without writing any public files.
        print(f'[preview] approved issue for {date}; render disabled (encrypted draft only)',flush=True)
        return False
    source_map = {x['id']:x for x in state['sources']}
    ordered = [state['articles'][str(i)] for i in range(8)]
    no = news.get_next_number()
    issue_dir.mkdir(parents=True,exist_ok=False)
    files=[]
    for item in ordered:
        path=issue_dir/'articles'/item['slug']/'index.html'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(news.render_article(release,no,item,source_map),encoding='utf-8')
        files.append(path)
    (issue_dir/'issue.json').write_text(json.dumps({'date':date,'number':no,'articles':ordered},ensure_ascii=False,indent=2),encoding='utf-8')
    paths=[issue_dir/'index.html', ROOT/'index.html', ROOT/'archive/index.html']
    paths[0].write_text(news.render_overview(release,no,ordered,permanent=True),encoding='utf-8')
    paths[1].write_text(news.render_overview(release,no,ordered),encoding='utf-8')
    paths[2].write_text(news.render_archive(),encoding='utf-8')
    (ROOT/'sitemap.xml').write_text(news.sitemap(),encoding='utf-8')
    news.validate_local_links(files+paths)
    print(f'[release] validated site, issue №{no:03d}, date {date}',flush=True)
    return True


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--phase', choices=['plan','write','audit','publish'],required=True)
    p.add_argument('--preview', action='store_true')
    p.add_argument('--target-date', default=None)
    args=p.parse_args()
    key = validate_key(os.environ.get('DRAFT_ENCRYPTION_KEY',''))
    date=phase_date(args.phase,datetime.now(TZ),args.target_date)
    label=artifact_label(date,args.preview)
    print(f'[387 News] phase={args.phase}, target={date}, '
          f'mode={"TEST" if args.preview else "PRODUCTION"}',flush=True)
    state=fetch_latest_checkpoint(label,key)
    if state and (state.get('date')!=date or state.get('version')!=3):
        raise RuntimeError('Bad checkpoint metadata')
    if args.phase=='plan':
        state=build_plan(state,date)
    else:
        if not state:
            raise RuntimeError('Encrypted draft missing; plan stage has not completed')
        if args.phase=='write':state=write_batch(state)
        elif args.phase=='audit':
            # Recover missed articles in the last editing window where possible.
            if len(state.get('articles',{})) < 8:
                state=write_batch(state, size=8-len(state.get('articles',{})))
            state=audit(state)
    if state:
        # The artifact uploader will only see ciphertext, never plaintext.
        save(state,key)
        output=os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output,'a',encoding='utf-8') as f:
                f.write('checkpoint=true\n')
                f.write(f'artifact_name={label}\n')
    if args.phase=='publish':
        ready=render(state,args.preview)
        output=os.environ.get('GITHUB_OUTPUT')
        if output and ready:
            with open(output,'a',encoding='utf-8') as f:f.write('published=true\n')


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        # Never echo secrets, API responses, or unpublished draft contents.
        print('STAGE FAILED; WEBSITE UNCHANGED: '+str(e)[:400],file=sys.stderr,flush=True)
        sys.exit(1)
