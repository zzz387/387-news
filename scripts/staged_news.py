#!/usr/bin/env python3
"""387 News 3.1: encrypted incremental drafts, no premature public release.

Free GitHub Actions, no private repository or paid API needed. Draft articles
are AES-256-GCM encrypted before any artifact upload. API credentials and
passphrases are never included in checkpoints or printed to logs.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import signal
import shutil
import tempfile
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
RUNTIME = news.runtime
PERSIST = None

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
    ARTIFACT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = ARTIFACT_FILE.with_suffix('.tmp')
    temp.write_bytes(cipher(state, key))
    temp.chmod(0o600)
    temp.replace(ARTIFACT_FILE)
    print(f'[checkpoint] AES-256-GCM encrypted; '
          f'{len(state.get("articles",{}))}/8 vetted article drafts', flush=True)


def phase_date(phase: str, now: datetime, manual_date: str | None) -> str:
    if manual_date:
        return datetime.strptime(manual_date, '%Y-%m-%d').date().isoformat()
    if phase in ('plan', 'auto'):
        return (now.date()+timedelta(days=1)).isoformat()
    if phase in ('write', 'research') and now.hour >= 11:
        return (now.date()+timedelta(days=1)).isoformat()
    return now.date().isoformat()


def artifact_label(date: str, preview: bool) -> str:
    label = f'387news31-{"test" if preview else "production"}-{date}'
    branch = os.getenv('GITHUB_REF_NAME', 'main')
    if branch != 'main':
        label += '-' + hashlib.sha256(branch.encode()).hexdigest()[:12]
    return label


def build_plan(state: dict | None, date: str):
    if state and state.get('plan'):
        print('[plan] checkpoint already exists; not regenerating.',flush=True)
        return state
    if state is None:
        state = {'version':31, 'date':date, 'articles':{}, 'dossiers':{},
                 'rejections':{}, 'stage':'planning', 'audit_passed':False,
                 'created_at':datetime.now(TZ).isoformat()}
    target = datetime.fromisoformat(date+'T06:00:00').replace(tzinfo=TZ)
    if not state.get('sources'):
        state['sources'] = news.gather_sources(datetime.now(TZ))
        persist_progress()
    sources = state['sources']
    # News freshness is measured at PUBLICATION, not when sources are collected.
    for source in sources:
        source['recent'] = (not source.get('evergreen') and
                            news.is_recent(source.get('published', ''), target))
    if len(sources) < 12:
        raise RuntimeError(f'Only {len(sources)} retrieved sources; at least 12 required')
    planned, candidates = editorial31.choose_plan(sources, date, progress=state)
    # An unverifiable "fresh scientific discovery" is excluded and the plan is
    # recomputed from the already vetted candidate pool; all quality and rubric
    # restrictions still apply. No new LLM research request is needed.
    sources, planned = editorial31.select_plan_with_verified_science(
        sources, candidates, initial_plan=planned)
    state.update(sources=sources, plan=planned, candidates=candidates, stage='planned')
    return state


def persist_progress():
    if PERSIST:
        PERSIST()


def research_batch(state, size=8):
    lookup = {s['id']:s for s in state['sources']}
    for i, plan in enumerate(state['plan']):
        slot = str(i)
        if slot in state.setdefault('dossiers', {}) or slot in state.setdefault('rejected', {}):
            continue
        try:
            state['dossiers'][slot] = editorial31.make_dossier(plan, lookup, state['date'])
        except RUNTIME.GenerationPaused:
            raise
        except RUNTIME.EvidenceRejected as exc:
            state['rejected'][slot] = str(exc)[:600]
        finally:
            persist_progress()
        size -= 1
        if size <= 0:
            break
    state['stage'] = 'researched'
    return state


def replace_rejected_stories(state):
    """Replace only failed slots, preserving every other commission and draft."""
    rejected = state.setdefault('rejected', {})
    archived = state.setdefault('rejected_stories', [])
    lookup = {s['id']:s for s in state['sources']}
    for slot in list(rejected):
        if slot in state.get('articles', {}):
            continue
        i = int(slot)
        old = state['plan'][i]
        attempts = sum(entry['slot'] == slot for entry in archived)
        if attempts >= 3:
            continue
        forbidden = [p['title'] for p in state['plan']] + [x['plan']['title'] for x in archived]
        other = [p for j,p in enumerate(state['plan']) if j != i]
        usage = {}
        for plan in other:
            for sid in plan['source_ids']:
                usage[sid] = usage.get(sid, 0) + 1
        candidates = sorted(state.get('candidates', []), key=lambda c: c['category'] != old['category'])
        for c in candidates:
            categories = [p['category'] for p in other] + [c['category']]
            if (not editorial31.LIFE.issubset(set(categories))
                    or sum(cat in editorial31.LIFE for cat in categories) < 4
                    or any(categories.count(cat) > (3 if cat in editorial31.LIFE else 2) for cat in set(categories))
                    or editorial31.candidate_score(c) < 19
                    or any(editorial31.meaningfully_same(c['title'], t) for t in forbidden)):
                continue
            ids = c.get('source_ids') or []
            if not 1 <= len(ids) <= 3 or not all(sid in lookup and usage.get(sid, 0) < 2 for sid in ids):
                continue
            if not any(editorial31._reference_quality(lookup[sid]) for sid in ids):
                continue
            if old['long'] and not editorial31._longform_evidence(c, lookup)[0]:
                continue
            if c.get('kind', '').lower() == 'новость' and not any(lookup[sid].get('recent') and not lookup[sid].get('evergreen') for sid in ids):
                continue
            replacement = {'title':c['title'], 'category':c['category'], 'kind':c['kind'],
                           'source_ids':list(ids), 'long':bool(old['long']),
                           'editorial_score':editorial31.candidate_score(c),
                           'angle':c.get('hook', ''), 'hook':c.get('hook', ''),
                           'long_topic_id':editorial31.normalized_topic_id(c)}
            try:
                editorial31.enrich_originals(state['sources'], [replacement])
            except RuntimeError:
                continue
            # The preserved commissions plus replacement must still obey source reuse.
            if any(usage.get(sid, 0) >= 2 for sid in replacement['source_ids']):
                continue
            archived.append({'slot':slot, 'plan':old, 'reason':rejected[slot],
                             'dossier':state.setdefault('dossiers', {}).pop(slot, None)})
            state['plan'][i] = replacement
            rejected.pop(slot)
            state.setdefault('rejections', {}).pop(slot, None)
            state.setdefault('revisions', {}).pop(slot, None)
            persist_progress()
            print(f'[replace] rejected slot={i+1} assigned a different vetted source-backed story', flush=True)
            break


def write_batch(state: dict, size=2):
    """Fair revision queue; keep accepted parts and candidates awaiting review."""
    if state.get('audit_passed'):
        return state
    if not state.get('plan'):
        raise RuntimeError('Missing strong story plan; run plan first')
    replace_rejected_stories(state)
    known = {s['id']:s for s in state['sources']}
    articles = state.setdefault('articles', {})
    dossiers = state.setdefault('dossiers', {})
    rejections = state.setdefault('rejections', {})
    rejected = state.setdefault('rejected', {})
    revisions = state.setdefault('revisions', {})
    cursor = state.get('write_cursor', 0) % len(state['plan'])
    pending = [(cursor+j) % len(state['plan']) for j in range(len(state['plan']))]
    pending = [i for i in pending if str(i) not in articles and str(i) not in rejected]
    for i in pending[:size]:
        slot = str(i)
        plan = state['plan'][i]
        # Rotate even when quota pauses this slot, so other stories get a turn.
        state['write_cursor'] = (i+1) % len(state['plan'])
        try:
            if slot not in dossiers:
                dossiers[slot] = editorial31.make_dossier(plan, known, state['date'])
                persist_progress()
            dossier = dossiers[slot]
            candidate = dossier.get('_draft_candidate')
            if candidate is None:
                candidate = editorial31.write_from_dossier(plan, dossier, state['date'], rejections.get(slot, ''))
                dossier['_draft_candidate'] = candidate
                persist_progress()
            try:
                editorial31.verify_article(candidate, plan, dossier, known)
            except ValueError:
                # Only an editorial veto invalidates prose, never an outage.
                dossier.pop('_draft_candidate', None)
                for name in ('_longform_progress', '_shortform_progress'):
                    if name in dossier:
                        dossier[name]['rebuild_required'] = True
                revisions[slot] = revisions.get(slot, 0) + 1
                if revisions[slot] >= 3:
                    raise RUNTIME.EvidenceRejected('Three editorial reviews rejected this story')
                raise
            candidate['slug'] = news.slugify(candidate['title'], i+1)
            articles[slot] = candidate
            dossier.pop('_draft_candidate', None)
            rejections.pop(slot, None)
            print(f'[write] VERIFIED slot={i+1}/8 words={candidate["word_count"]}', flush=True)
        except RUNTIME.GenerationPaused:
            raise
        except RUNTIME.EvidenceRejected as exc:
            rejected[slot] = str(exc)[:600]
            rejections[slot] = str(exc)[:600]
            print(f'[write] slot={i+1} rejected: insufficient evidence or supported prose', flush=True)
        except Exception as exc:
            rejections[slot] = str(exc)[:700]
            # Bound short article repair too; transport errors do not condemn sources.
            if isinstance(exc, ValueError) and not plan.get('long'):
                revisions[slot] = revisions.get(slot, 0) + 1
                if revisions[slot] >= 9:
                    rejected[slot] = 'Repeated editorial/structural rejection; manual source review required'
            print(f'[write] slot={i+1} deferred ({type(exc).__name__}); progress preserved', flush=True)
        finally:
            persist_progress()
    state['stage'] = 'writing' if len(articles) < 8 else 'ready_for_audit'
    segments = sum(len(d.get(k, {}).get('parts', [])) for d in dossiers.values() for k in ('_longform_progress', '_shortform_progress'))
    print(f'[write] CHECKPOINT STATUS: {len(articles)}/8 verified articles; {segments} accepted segments; '
          f'{len(rejected)} rejected stories; publication remains gated', flush=True)
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
            dossier = state.get('dossiers', {}).get(str(index), {})
            dossier.pop('_draft_candidate', None)
            for name in ('_longform_progress', '_shortform_progress'):
                if name in dossier:
                    dossier[name]['rebuild_required'] = True
            revisions = state.setdefault('revisions', {})
            revisions[str(index)] = revisions.get(str(index), 0) + 1
            if revisions[str(index)] >= 3:
                state.setdefault('rejected', {})[str(index)] = 'Repeated issue audit veto'
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
    if not preview and os.environ.get('GITHUB_REF_NAME', 'main') != 'main':
        raise RuntimeError('Release veto: only main may publish')
    if not preview and os.environ.get('NEWS_RELEASE_APPROVED', '').lower() != 'true':
        raise RuntimeError('Release veto: NEWS_RELEASE_APPROVED must be explicitly enabled')
    issue_dir = ROOT / 'issues' / date
    if issue_dir.exists():
        print('[release] issue already exists in repository; no duplicate',flush=True)
        return False
    if preview:
        # Build and validate in a temporary private directory, never in Pages files.
        with tempfile.TemporaryDirectory(prefix='387news-preview-') as directory:
            root = Path(directory)
            for name in ('assets', 'archive', 'issues'):
                if (ROOT / name).is_dir():
                    shutil.copytree(ROOT / name, root / name)
            _assemble(state, release, root)
        print('[preview] full HTML build and local links validated; private files removed', flush=True)
        return False
    return _assemble(state, release, ROOT)


def _assemble(state, release, root):
    previous_root = news.ROOT
    news.ROOT = root
    try:
        return _assemble_files(state, release, root)
    finally:
        news.ROOT = previous_root


def _assemble_files(state, release, root):
    date = state['date']
    issue_dir = root / 'issues' / date
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
    paths=[issue_dir/'index.html', root/'index.html', root/'archive/index.html']
    paths[0].write_text(news.render_overview(release,no,ordered,permanent=True),encoding='utf-8')
    paths[1].write_text(news.render_overview(release,no,ordered),encoding='utf-8')
    paths[2].write_text(news.render_archive(),encoding='utf-8')
    (root/'sitemap.xml').write_text(news.sitemap(),encoding='utf-8')
    news.validate_local_links(files+paths)
    print(f'[release] validated site, issue №{no:03d}, date {date}',flush=True)
    return True


def main():
    global PERSIST
    p = argparse.ArgumentParser()
    p.add_argument('--phase', choices=['auto','plan','research','write','audit','publish','check'], required=True)
    p.add_argument('--preview', action='store_true')
    p.add_argument('--target-date', default=None)
    args = p.parse_args()
    if args.phase == 'auto' and not args.preview:
        raise RuntimeError('auto is a preview-only integration phase')
    key = validate_key(os.environ.get('DRAFT_ENCRYPTION_KEY', ''))
    date = phase_date(args.phase, datetime.now(TZ), args.target_date)
    label = artifact_label(date, args.preview)
    state = fetch_latest_checkpoint(label, key)
    branch = os.getenv('GITHUB_REF_NAME', 'main')
    if state and (state.get('date') != date or state.get('version') != 31
                  or state.get('branch', branch) != branch
                  or state.get('preview', args.preview) != args.preview):
        raise RuntimeError('Bad checkpoint metadata')
    if state:
        state.pop('pause_reason', None)
        count = sum(len(d.get(k, {}).get('parts', [])) for d in state.get('dossiers', {}).values() for k in ('_longform_progress', '_shortform_progress'))
        print(f'[resume] {len(state.get("articles", {}))}/8 verified articles; {count} accepted segments; '
              f'{len(state.get("dossiers", {}))} saved dossiers', flush=True)
    if args.phase == 'check':
        if state is None:
            raise RuntimeError('No saved checkpoint found for this date and preview mode')
        segments = sum(len(d.get(k, {}).get('parts', [])) for d in state.get('dossiers', {}).values() for k in ('_longform_progress', '_shortform_progress'))
        print(f'[checkpoint-test] restored {len(state.get("articles", {}))}/8 articles, {segments} segments', flush=True)
        return
    quota_path = Path(os.getenv('NEWS_QUOTA_FILE', str(ARTIFACT_FILE.parent / 'quota.json')))
    if os.getenv('NEWS_QUOTA_EXPECTED') == 'true' and not quota_path.is_file():
        raise RuntimeError('Expected quota ledger download missing; refusing API calls')
    ledger = json.loads(quota_path.read_text()) if quota_path.is_file() else {}
    snapshot = (state or {}).get('_quota_snapshot', {})
    if snapshot.get('day') == ledger.get('day'):
        ledger['requests'] = max(ledger.get('requests', 0), snapshot.get('requests', 0))
    elif snapshot.get('day', '') > ledger.get('day', ''):
        ledger = snapshot.copy()
    output = os.getenv('GITHUB_OUTPUT')

    def persist():
        quota_path.parent.mkdir(parents=True, exist_ok=True)
        temp = quota_path.with_suffix('.tmp')
        temp.write_text(json.dumps(ledger), encoding='utf-8')
        temp.replace(quota_path)
        if state:
            state.update(branch=branch, preview=args.preview, _quota_snapshot=json.loads(json.dumps(ledger)))
            save(state, key)
        if output:
            with open(output, 'a', encoding='utf-8') as f:
                f.write(f'quota=true\nquota_name={quota_label()}\n')
                if state:
                    f.write(f'checkpoint=true\nartifact_name={label}\n')

    PERSIST = RUNTIME.CHECKPOINT = persist
    RUNTIME.ACTIVE_BUDGET = RUNTIME.RequestBudget(ledger, persist)
    previous_handler = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(RUNTIME.GenerationPaused('Runner stopped; checkpoint retained')))
    try:
        persist()  # arm always() upload BEFORE any generation
        if (args.phase in ('plan', 'auto') or (state and args.phase in ('research', 'write'))) and (not state or not state.get('plan')):
            if state is None:
                state = {'version':31, 'date':date, 'articles':{}, 'dossiers':{},
                         'rejections':{}, 'stage':'planning', 'audit_passed':False}
            state = build_plan(state, date)
            persist()
        elif state is None:
            raise RuntimeError('Encrypted draft missing; run plan first')
        if args.phase == 'research':
            research_batch(state)
        elif args.phase in ('write', 'auto'):
            write_batch(state, size=8)
            if args.phase == 'auto' and len(state.get('articles', {})) == 8:
                audit(state)
                if state.get('audit_passed'):
                    render(state, True)
        elif args.phase == 'audit':
            audit(state)
        elif args.phase == 'publish':
            if not state.get('audit_passed'):
                raise RuntimeError('Unapproved issue: cannot publish or preview release')
            ready = render(state, args.preview)
            if output and ready:
                with open(output, 'a', encoding='utf-8') as f:
                    f.write('published=true\n')
    except RUNTIME.GenerationPaused as exc:
        print(f'[paused] {exc}', flush=True)
        if state:
            state['pause_reason'] = str(exc)
    finally:
        persist()
        RUNTIME.ACTIVE_BUDGET = RUNTIME.CHECKPOINT = PERSIST = None
        signal.signal(signal.SIGTERM, previous_handler)


def quota_label():
    # Shared across issue dates and preview/production; concurrency serializes writers.
    return '387news31-quota-' + datetime.now(timezone.utc).date().isoformat()


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        # Never echo secrets, API responses, or unpublished draft contents.
        print('STAGE FAILED; WEBSITE UNCHANGED: '+str(e)[:400],file=sys.stderr,flush=True)
        sys.exit(1)
