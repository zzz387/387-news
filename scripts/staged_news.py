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
    from scripts import news, editorial31, publication, audit_policy, audit_repair, pipeline, release_queue, policy41, editorial41, publication41
except ImportError:
    import news
    import editorial31
    import publication
    import audit_policy
    import audit_repair
    import pipeline
    import release_queue
    import policy41
    import editorial41
    import publication41

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


def vetted_count(state):
    return sum(r.get('status')=='ready' for r in state.get('candidates',[])) if state.get('version') in (41,43) else len(state.get('articles',{}))


def save(state: dict, key: bytes):
    ARTIFACT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = ARTIFACT_FILE.with_suffix('.tmp')
    temp.write_bytes(cipher(state, key))
    temp.chmod(0o600)
    temp.replace(ARTIFACT_FILE)
    target=pipeline.article_target(state)  # preserve v31/v41 while using the v43 configuration
    print(f'[checkpoint] AES-256-GCM encrypted; {vetted_count(state)}/{target} vetted article drafts',flush=True)


def phase_date(phase: str, now: datetime, manual_date: str | None) -> str:
    if manual_date:
        return datetime.strptime(manual_date,'%Y-%m-%d').date().isoformat()
    now=release_queue.moscow(now)
    if phase in ('plan','auto'):
        return (now.date()+timedelta(days=1)).isoformat()
    return release_queue.target_date(ROOT,now)


def artifact_label(date: str, preview: bool) -> str:
    label = f'387news31-{"test" if preview else "production"}-{date}'
    if os.getenv('NEWS_V41_TRIAL')=='true':
        if not preview: raise RuntimeError('Trial checkpoints must remain preview-only')
        label=f'387news41-trial-{date}'
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
    target = datetime.fromisoformat(date+'T'+policy41.RELEASE_TIME).replace(tzinfo=TZ)
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
            state['dossiers'][slot] = editorial31.make_dossier(plan, lookup, state['date'], state.setdefault('dossier_builds', {}).setdefault(slot, {}))
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
            state.setdefault('review_failures', {}).pop(slot, None)
            state.setdefault('dossier_builds', {}).pop(slot, None)
            persist_progress()
            print(f'[replace] rejected slot={i+1} assigned a different vetted source-backed story', flush=True)
            break


def write_batch(state: dict, size=2):
    """Fair revision queue; keep accepted parts and candidates awaiting review."""
    if state.get('audit_passed'):
        return state
    if not state.get('plan'):
        raise RuntimeError('Missing strong story plan; run plan first')
    audit_repair.process_repairs(state,persist_progress)
    if state.get('audit_blocked') or state.get('audit_repairs'):
        return state
    if not state.get('dossier_repair_v2'):
        # Older code requested 7–13 facts but demanded eight for a feature.
        # Recheck those prematurely rejected extractions once with the bounded extractor.
        for slot, reason in list(state.setdefault('rejected', {}).items()):
            if reason.startswith('Insufficient exact source evidence') and 'after 3 extractions' not in reason:
                state['rejected'].pop(slot)
        state['dossier_repair_v2'] = True
    replace_rejected_stories(state)
    known = {s['id']:s for s in state['sources']}
    articles = state.setdefault('articles', {})
    dossiers = state.setdefault('dossiers', {})
    rejections = state.setdefault('rejections', {})
    rejected = state.setdefault('rejected', {})
    revisions = state.setdefault('revisions', {})
    reviews = state.setdefault('review_failures', {})
    cursor = state.get('write_cursor', 0) % len(state['plan'])
    pending = [(cursor+j) % len(state['plan']) for j in range(len(state['plan']))]
    pending = [i for i in pending if str(i) not in articles and str(i) not in rejected]
    for i in pending[:size]:
        slot = str(i)
        plan = state['plan'][i]
        # Rotate even when quota pauses this slot, so other stories get a turn.
        state['write_cursor'] = (i+1) % len(state['plan'])
        under_review = False
        try:
            if slot not in dossiers:
                dossiers[slot] = editorial31.make_dossier(plan, known, state['date'], state.setdefault('dossier_builds', {}).setdefault(slot, {}))
                persist_progress()
            dossier = dossiers[slot]
            candidate = dossier.get('_draft_candidate')
            if candidate is None:
                candidate = editorial31.write_from_dossier(plan, dossier, state['date'], rejections.get(slot, ''))
                dossier['_draft_candidate'] = candidate
                persist_progress()
            try:
                under_review = True
                editorial31.verify_article(candidate, plan, dossier, known)
            except ValueError:
                # Only an editorial veto invalidates prose, never an outage.
                dossier.pop('_draft_candidate', None)
                for name in ('_longform_progress', '_shortform_progress'):
                    if name in dossier:
                        dossier[name]['rebuild_required'] = True
                reviews[slot] = reviews.get(slot, 0) + 1
                if reviews[slot] >= 3:
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
            if isinstance(exc, ValueError) and not under_review:
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
    if state.get('audit_blocked') or state.get('audit_repairs'):
        print('[audit] pending attributed repair or bounded hold; no audit API request',flush=True)
        return state
    digest = audit_policy.fingerprint(state)
    if (digest in state.get('audit_failed_fingerprints',{})
            or state.get('audit_rounds',0)>=audit_policy.MAX_AUDITS):
        state['audit_blocked'] = 'Unchanged rejected issue or audit round limit; no automatic retry'
        persist_progress()
        print('[audit] unchanged rejected input or audit limit; accepted articles retained',flush=True)
        return state
    order = state.get('article_order',list(range(8)))
    if sorted(order)!=list(range(8)):
        raise RuntimeError('Invalid issue composition order')
    ordered=[articles[str(i)] for i in order]
    plans=[state['plan'][i] for i in order]
    lookup={s['id']:s for s in state['sources']}
    release=datetime.fromisoformat(state['date']+'T06:00:00').replace(tzinfo=TZ)
    review_index = None
    try:
        for i, a in zip(order,ordered):
            if a['kind'].lower()=='новость' and not any(news.is_recent(lookup[s]['published'],release)
                                                        for s in a['source_ids']):
                raise audit_policy.AuditRejected([audit_policy.issue('stale_news',scope='article',
                    article_ids=[i+1],repair_ids=[i+1],action='replace_story',
                    reason='News item stale at scheduled release',instruction='Select a different verified fresh story')])
            if a.get('_review_scope') != 'title_teaser_body_v1':
                review_index = i
                editorial31.verify_article(a,state['plan'][i],state['dossiers'][str(i)],lookup)
                a['_review_scope'] = 'title_teaser_body_v1'
                persist_progress()
                review_index = None
        total=editorial31.audit_issue(ordered,plans,lookup,article_ids=[i+1 for i in order])
    except RUNTIME.GenerationPaused:
        raise
    except ValueError as exc:
        state['audit_rounds'] = state.get('audit_rounds',0)+1
        if isinstance(exc,audit_policy.AuditRejected):
            findings = exc.issues
        elif review_index is not None:
            findings = [audit_policy.issue('unsupported_claim',scope='article',
                article_ids=[review_index+1],repair_ids=[review_index+1],action='revise_article',
                reason=str(exc),instruction=str(exc))]
        else:
            findings = [audit_policy.issue('unattributed',reason=str(exc))]
        audit_repair.record_veto(state,findings,persist_progress)
        return state
    except Exception as exc:
        state['stage']='audit_veto'
        state['audit_note']='Operational audit failure: '+type(exc).__name__
        persist_progress()
        print(f'[audit] operational error={type(exc).__name__}; no article invalidated',flush=True)
        return state
    state['audit_rounds'] = state.get('audit_rounds',0)+1
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
    release = datetime.fromisoformat(date+'T'+policy41.RELEASE_TIME+':00').replace(tzinfo=TZ)
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
    if state.get('version')==41:
        if not preview:
            editorial41.verify_publication_sources(state,persist=PERSIST or (lambda:None))
        return publication41.build(state,ROOT,preview)
    if not preview and not issue_dir.exists():
        raise RuntimeError('V41_REVALIDATION_REQUIRED: historical approval cannot publish a new issue')
    if issue_dir.exists():
        if preview:
            return False
        saved = json.loads((issue_dir / 'issue.json').read_text(encoding='utf-8'))
        expected = publication.public_issue(state, saved['number'])
        if publication.content_digest(saved) != publication.content_digest(expected):
            raise RuntimeError('Existing archive differs from approved issue; refusing overwrite')
        news.validate_local_links(list(issue_dir.rglob('*.html')) + [ROOT/'index.html', ROOT/'archive/index.html'])
        print('[release] approved issue already committed; safe deployment retry, archive unchanged', flush=True)
        return True
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
    if state.get('version')==41: return publication41.build(state,root,False)
    date = state['date']
    issue_dir = root / 'issues' / date
    source_map = {x['id']:x for x in state['sources']}
    ordered = [state['articles'][str(i)] for i in state.get('article_order',range(8))]
    no = news.get_next_number()
    issue_dir.mkdir(parents=True,exist_ok=False)
    files=[]
    for item in ordered:
        path=issue_dir/'articles'/item['slug']/'index.html'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(news.render_article(release,no,item,source_map),encoding='utf-8')
        files.append(path)
    public = publication.public_issue(state, no)
    (issue_dir/'issue.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
    (issue_dir/'issue.md').write_text(publication.markdown(public),encoding='utf-8')
    paths=[issue_dir/'index.html', root/'index.html', root/'archive/index.html']
    paths[0].write_text(news.render_overview(release,no,ordered,permanent=True),encoding='utf-8')
    paths[1].write_text(news.render_overview(release,no,ordered),encoding='utf-8')
    paths[2].write_text(news.render_archive(),encoding='utf-8')
    (root/'sitemap.xml').write_text(news.sitemap(),encoding='utf-8')
    news.validate_local_links(files+paths)
    print(f'[build] validated site, issue №{no:03d}, date {date}',flush=True)
    return True


def recover_special_quota(ledger, key):
    """Actions-only decryption: recover accounting only, never special editorial state."""
    location=os.getenv('NEWS_SPECIAL_QUOTA_FILE')
    expected=os.getenv('NEWS_SPECIAL_QUOTA_EXPECTED')=='true'
    if not location:
        if expected: raise RuntimeError('Missing special quota backup path')
        return
    path=Path(location)
    if not path.is_file():
        if expected: raise RuntimeError('Expected special quota backup download missing')
        return
    if os.getenv('GITHUB_ACTIONS')!='true':raise RuntimeError('Special quota recovery requires Actions')
    backup=decipher(path.read_bytes(),key)
    if (backup.get('version')!=41 or backup.get('branch')!='main' or backup.get('preview') is not False
            or backup.get('special_edition',{}).get('id')!='003-R'):
        raise RuntimeError('Invalid special quota backup provenance')
    RUNTIME.merge_snapshot(ledger,backup.get('_quota_snapshot',{}))


def main():
    global PERSIST
    p = argparse.ArgumentParser()
    p.add_argument('--phase', choices=['auto','plan','research','write','audit','publish','check','resume','run','inspect'], required=True)
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
    if state and (state.get('date') != date or state.get('version') not in (31,41,43)
                  or state.get('branch', branch) != branch
                  or state.get('preview', args.preview) != args.preview):
        raise RuntimeError('Bad checkpoint metadata')
    target_count=pipeline.article_target(state or {})
    if state:
        state.pop('pause_reason', None)
        count = sum(len(d.get(k, {}).get('parts', [])) for d in state.get('dossiers', {}).values() for k in ('_longform_progress', '_shortform_progress'))
        print(f'[resume] {vetted_count(state)}/{target_count} verified articles; {count} accepted segments; '
              f'{len(state.get("dossiers", {}))} saved dossiers', flush=True)
    try:from scripts import daily43,editorial43
    except ImportError:import daily43,editorial43
    use43=os.getenv('NEWS_POLICY_VERSION')=='4.3' and daily43.enabled()
    if args.phase not in ('check','inspect') and not release_queue.edition_exists(ROOT,date):
        state=editorial43.migrate(state,date) if use43 else editorial41.migrate(state,date)
    if args.phase in ('check','inspect'):
        if state is None:
            raise RuntimeError('No saved checkpoint found for this date and preview mode')
        segments = sum(len(d.get(k, {}).get('parts', [])) for d in state.get('dossiers', {}).values() for k in ('_longform_progress', '_shortform_progress'))
        print(f'[checkpoint-test] restored {vetted_count(state)}/{target_count} articles, {segments} segments', flush=True)
        if args.phase=='inspect':
            action='publish_when_due' if state.get('audit_passed') else 'audit' if vetted_count(state)>=pipeline.article_target(state) else 'continue_saved_writing'
            pipeline.status(state,'APPROVED' if state.get('audit_passed') else 'READY_FOR_AUDIT' if vetted_count(state)>=pipeline.article_target(state) else 'RETRY_PENDING',action)
            pipeline.emit_report(state,state.get('_quota_snapshot',{}),os.getenv('GITHUB_OUTPUT'))
        return
    quota_path = Path(os.getenv('NEWS_QUOTA_FILE', str(ARTIFACT_FILE.parent / 'quota.json')))
    if os.getenv('NEWS_QUOTA_EXPECTED') == 'true' and not quota_path.is_file():
        raise RuntimeError('Expected quota ledger download missing; refusing API calls')
    ledger = json.loads(quota_path.read_text()) if quota_path.is_file() else {}
    RUNTIME.merge_snapshot(ledger,(state or {}).get('_quota_snapshot', {}))
    recover_special_quota(ledger,key)
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

    if state is None and args.phase in ('run','resume','write','audit','auto','plan'):
        state=editorial43.migrate(None,date) if use43 else editorial41.new_state(date)

    PERSIST = RUNTIME.CHECKPOINT = persist
    RUNTIME.ACTIVE_BUDGET = RUNTIME.RequestBudget(ledger, persist)
    previous_handler = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(RUNTIME.GenerationPaused('Runner stopped; checkpoint retained')))
    try:
        persist()  # arm always() upload BEFORE any generation
        if state is None:
            raise RuntimeError('Encrypted draft missing; run plan first')
        ready=False
        if state.get('version')==43:
            ready=daily43.advance(state,date,args.preview,sys.modules[__name__],persist)
        elif state.get('version')==41:
            ready=pipeline.advance(state,date,args.preview,sys.modules[__name__],persist)
        elif args.phase=='plan':
            pipeline.status(state,'PLANNING','research')
            build_plan(state,date)
        elif args.phase=='research':
            pipeline.status(state,'RESEARCHING','write')
            if not state.get('plan'): build_plan(state,date)
            research_batch(state)
        elif args.phase in ('run','resume','write','audit','auto'):
            ready=pipeline.advance(state,date,args.preview,sys.modules[__name__],persist)
        elif args.phase=='publish':
            ready=render(state,args.preview)
            pipeline.status(state,'PUBLISHING' if ready else 'APPROVED','commit_and_deploy' if ready else 'preview_complete')
        if output and ready:
            with open(output,'a',encoding='utf-8') as stream:
                stream.write(f'published=true\nissue_date={state["date"]}\n')
    except RUNTIME.GenerationPaused as exc:
        print(f'[paused] {exc}', flush=True)
        if state:
            state['pause_reason']=str(exc)
            pipeline.pause(state,ready=vetted_count(state)>=pipeline.article_target(state) and not state.get('audit_passed'))
            if any(marker in str(exc) for marker in ('429','503','cooldown')):
                pipeline.status(state,'RETRY_PENDING','resume_after_cooldown','API_COOLDOWN')
    except policy41.Blocked as exc:
        if state:
            pipeline.status(state,'BLOCKED','review_editorial_diagnosis',exc.code)
            print(f'[editorial41] stage=release decision=blocked code={exc.code}',flush=True)
    except Exception:
        if state: pipeline.status(state,'RETRY_PENDING','retry_saved_stage','INFRASTRUCTURE_ERROR')
        raise
    finally:
        persist()
        if state: pipeline.emit_report(state,ledger,output)
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
        print('STAGE FAILED; WEBSITE UNCHANGED: '+type(e).__name__+'; private diagnostics retained',file=sys.stderr,flush=True)
        sys.exit(1)
