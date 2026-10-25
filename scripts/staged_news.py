#!/usr/bin/env python3
"""387 News 3.1: encrypted incremental drafts, no premature public release.

Free GitHub Actions, no private repository or paid API needed. Draft articles
are AES-256-GCM encrypted before any artifact upload. API credentials and
passphrases are never included in checkpoints or printed to logs.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta
import gzip
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    from scripts import news, editorial31
except ImportError:
    import news
    import editorial31

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
    """Load the checkpoint downloaded by the official GitHub artifact action.

    Never open GitHub's redirect-based ZIP endpoint directly: on some runs its
    storage redirect returns HTTP 401 despite a successful artifact listing.
    This function only reads a local ciphertext file; no article text is
    printed or uploaded in plaintext.
    """
    path_str = os.environ.get('NEWS_CHECKPOINT_FILE')
    if path_str:
        path = Path(path_str)
        if path.is_file():
            state = decipher(path.read_bytes(), key)
            print('[checkpoint] encrypted draft downloaded and decrypted',flush=True)
            return state
        if os.environ.get('NEWS_CHECKPOINT_EXPECTED', '').lower() == 'true':
            raise RuntimeError('Checkpoint was found but the downloaded encrypted file is missing')
        return None
    # Local development only. On GitHub always require the official download.
    local = os.environ.get('NEWS_TEST_CHECKPOINT')
    if local and Path(local).is_file():
        return decipher(Path(local).read_bytes(), key)
    if os.environ.get('GITHUB_REPOSITORY'):
        raise RuntimeError('NEWS_CHECKPOINT_FILE was not configured by the workflow')
    return None


def save(state: dict, key: bytes):
    ARTIFACT_FILE.write_bytes(cipher(state, key))
    print(f'[checkpoint] AES-256-GCM encrypted; '
          f'{len(state.get("articles",{}))}/8 vetted article drafts', flush=True)


def phase_date(phase: str, now: datetime, manual_date: str | None) -> str:
    if manual_date:
        return datetime.strptime(manual_date, '%Y-%m-%d').date().isoformat()
    if phase == 'plan':
        return (now.date()+timedelta(days=1)).isoformat()
    if phase == 'write' and now.hour >= 11:
        return (now.date()+timedelta(days=1)).isoformat()
    return now.date().isoformat()


def artifact_label(date: str, preview: bool) -> str:
    return f'387news31-{"test" if preview else "production"}-{date}'


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
    planned, candidates = editorial31.choose_plan(sources, date)
    # An unverifiable "fresh scientific discovery" is excluded and the plan is
    # recomputed from the already vetted candidate pool; all quality and rubric
    # restrictions still apply. No new LLM research request is needed.
    sources, planned = editorial31.select_plan_with_verified_science(
        sources, candidates, initial_plan=planned)
    return {'version':31, 'date':date, 'sources':sources, 'plan':planned,
            'articles':{}, 'dossiers':{}, 'rejections':{}, 'candidates':candidates, 'stage':'planned', 'audit_passed':False,
            'created_at':datetime.now(TZ).isoformat()}


def write_batch(state: dict, size=2):
    """Save only individually verified articles; failed slots can be retried later."""
    if state.get('audit_passed'):
        print('[write] already audited; no edits allowed',flush=True)
        return state
    if not state.get('plan'):
        raise RuntimeError('Missing strong story plan; run plan first')
    known={s['id']:s for s in state['sources']}
    articles=state.setdefault('articles',{})
    dossiers=state.setdefault('dossiers',{})
    rejections=state.setdefault('rejections',{})
    pending=[i for i in range(len(state['plan'])) if str(i) not in articles]
    for i in pending[:size]:
        slot=str(i)
        plan=state['plan'][i]
        print(f'[write] source-grounded article {i+1}/8 category={plan["category"]}',flush=True)
        try:
            if slot not in dossiers:
                dossiers[slot]=editorial31.make_dossier(plan,known,state['date'])
                print(f'[dossier] verified literal quotes: {len(dossiers[slot]["claims"])}',flush=True)
            reason=rejections.get(slot,'')
            article=editorial31.write_from_dossier(plan,dossiers[slot],state['date'],reason)
            editorial31.verify_article(article,plan,dossiers[slot],known)
            article['slug']=news.slugify(article['title'],i+1)
            articles[slot]=article
            rejections.pop(slot,None)
            print(f'[write] VERIFIED and saved {i+1}/8, {article["word_count"]} words',flush=True)
        except Exception as e:
            # FAIL CLOSED: do not count or publish a failed article; retain dossier.
            rejections[slot]=str(e)[:700]
            print(f'[write] SLOT {i+1} REJECTED: {str(e)[:220]}; checkpoint preserved',
                  file=sys.stderr,flush=True)
    state['stage']='writing' if len(articles)<8 else 'ready_for_audit'
    segments = sum(len(d.get('_longform_progress',{}).get('parts',[]))
                   for d in dossiers.values() if isinstance(d,dict))
    print(f'[write] CHECKPOINT STATUS: {len(articles)}/8 verified articles; '
          f'{segments} provisional longform segments held in encrypted draft; '
          'green workflow is not publication approval',flush=True)
    return state


def audit(state:dict):
    if state.get('audit_passed'):
        print('[audit] previously approved — read-only',flush=True)
        return state
    articles=state.get('articles',{})
    if len(articles)!=8:
        raise RuntimeError(f'Incomplete issue: {len(articles)}/8; site unchanged')
    ordered=[articles[str(i)] for i in range(8)]
    lookup={s['id']:s for s in state['sources']}
    release=datetime.fromisoformat(state['date']+'T06:00:00').replace(tzinfo=TZ)
    for a in ordered:
        if a['kind'].lower()=='новость' and not any(news.is_recent(lookup[i]['published'],release)
                                                   for i in a['source_ids']):
            state['audit_note']='News item stale at scheduled release'
            state['stage']='audit_veto'
            print('[AUDIT VETO] stale news — website unchanged',flush=True)
            return state
    try:
        total=editorial31.audit_issue(ordered,state['plan'],lookup)
    except Exception as e:
        state['stage']='audit_veto'
        state['audit_note']=str(e)[:1200]
        # An editorial veto (not a temporary Gemini outage) must be repairable.
        # Keep dossiers & other approved drafts; rewrite just the weakest slot.
        if isinstance(e, ValueError):
            index=min(range(8), key=lambda i: (
                ordered[i]['word_count'] / (editorial31.MIN_LONG if state['plan'][i]['long']
                                           else editorial31.MIN_SHORT),
                state['plan'][i].get('editorial_score', 25)))
            state.setdefault('rejections',{})[str(index)]='Final issue audit: '+str(e)[:500]
            state['articles'].pop(str(index),None)
            print(f'[audit] returned slot {index+1}/8 to revision queue',flush=True)
        print('[AUDIT VETO] '+str(e)[:240]+' — website unchanged',flush=True)
        return state
    state['audit_passed']=True
    state['stage']='audited'
    state['word_count']=total
    state['audited_at']=datetime.now(TZ).isoformat()
    state.pop('audit_note',None)
    print(f'[audit] EDITORIAL PRECHECK approved: 8 articles, {total} words. '
          'External model review is NOT independent verification of truth.',flush=True)
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
    if not preview and os.environ.get('NEWS_RELEASE_APPROVED', '').lower() != 'true':
        raise RuntimeError('Release veto: NEWS_RELEASE_APPROVED must be explicitly enabled')
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
    p.add_argument('--phase', choices=['plan','write','audit','publish','check'],required=True)
    p.add_argument('--preview', action='store_true')
    p.add_argument('--target-date', default=None)
    args=p.parse_args()
    key = validate_key(os.environ.get('DRAFT_ENCRYPTION_KEY',''))
    date=phase_date(args.phase,datetime.now(TZ),args.target_date)
    label=artifact_label(date,args.preview)
    print(f'[387 News] phase={args.phase}, target={date}, '
          f'mode={"TEST" if args.preview else "PRODUCTION"}',flush=True)
    state=fetch_latest_checkpoint(label,key)
    if state and (state.get('date')!=date or state.get('version')!=31):
        raise RuntimeError('Bad checkpoint metadata')
    if args.phase=='check':
        if state is None:
            raise RuntimeError('No saved checkpoint found for this date and preview mode')
        print(f'[checkpoint-test] OK; encrypted draft restored; '
              f'{len(state.get("articles",{}))}/8 articles; '
              f'target={state.get("date")}',flush=True)
        return
    if args.phase=='plan':
        state=build_plan(state,date)
    else:
        if not state:
            raise RuntimeError('Encrypted draft missing; plan stage has not completed')
        if args.phase=='write':state=write_batch(state)
        elif args.phase=='audit':
            # Never generate unreviewed missing articles during the final audit.
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
        if not state or not state.get('audit_passed'):
            raise RuntimeError('Unapproved issue: cannot publish or preview release')
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
