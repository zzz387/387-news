"""Route each wake-up using Moscow time and current public delivery state."""
from datetime import datetime, timedelta
import os
import re
from pathlib import Path
try:
    from scripts import news, site_checks, policy41
except ImportError:
    import news
    import site_checks
    import policy41


def moscow(now=None):
    now = now or datetime.now(news.TZ)
    return now.replace(tzinfo=news.TZ) if now.tzinfo is None else now.astimezone(news.TZ)


def edition_exists(root,date):
    root=Path(root)
    if (root/'issues'/date/'issue.json').is_file(): return True  # immutable legacy edition
    path=root/'issues'/date/'index.html'
    return path.is_file() and any('data-policy-version="'+v+'"' in path.read_text(encoding='utf-8') for v in ('4.1','4.3'))


def pending_date(root, now):
    today = moscow(now).date().isoformat()
    return today if not edition_exists(root,today) else None


def target_date(root, now=None, check_public=None):
    now = moscow(now)
    today = now.date().isoformat()
    if pending_date(root,now):
        return today
    # A committed edition with stale Pages remains today's recovery task.
    if now.strftime('%H:%M')>=policy41.RELEASE_TIME and check_public is not None:
        try:
            check_public(expected_date=today)
        except Exception:
            print('[release-context] today committed but HTTPS delivery unverified; recover deployment',flush=True)
            return today
    return (now.date()+timedelta(days=1)).isoformat() if now.hour>=12 else today


def context(phase, preview, date, event, root=None, now=None, check_public=None):
    root = root or news.ROOT
    now = moscow(now)
    if date:
        datetime.strptime(date,'%Y-%m-%d')
    if event in ('push','schedule'):
        return 'run',False,target_date(root,now,check_public)
    if date:
        return phase,preview,date
    if phase in ('plan','auto'):
        return phase,preview,(now.date()+timedelta(days=1)).isoformat()
    return phase,preview,target_date(root,now,check_public if not preview else None)


def unfinished_date(root, proposed, records):
    """Artifact metadata only. Resume oldest unpublished date without moving backwards.

    Payloads, decryption keys and ledgers remain in the official Actions restore path.
    Expired matching artifacts are deliberately retained here: locator must fail closed.
    """
    root=Path(root)
    published=[p.name for p in (root/'issues').iterdir()
               if re.fullmatch(r'\d{4}-\d{2}-\d{2}',p.name) and edition_exists(root,p.name)] if (root/'issues').is_dir() else []
    latest=max(published,default='')
    pending=[]
    for record in records:
        match=re.fullmatch(r'387news31-production-(\d{4}-\d{2}-\d{2})',record.get('name',''))
        if not match: continue
        date=match[1]; datetime.strptime(date,'%Y-%m-%d')
        if latest<date<=proposed and not edition_exists(root,date):
            if (record.get('workflow_run') or {}).get('head_branch')!='main':
                raise RuntimeError('PRODUCTION_CHECKPOINT_ORIGIN_UNVERIFIED')
            pending.append(date)
    return min(pending,default=proposed)


def production_artifacts():
    try: from scripts import staged_news
    except ImportError: import staged_news
    repo=os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo): raise RuntimeError('INVALID_REPOSITORY')
    result=[]
    for page in range(1,101):
        batch=staged_news.request_json(f'https://api.github.com/repos/{repo}/actions/artifacts?per_page=100&page={page}').get('artifacts')
        if not isinstance(batch,list): raise RuntimeError('PRODUCTION_ARTIFACT_LIST_INVALID')
        result.extend(batch)
        if len(batch)<100: return result
    raise RuntimeError('PRODUCTION_ARTIFACT_PAGINATION_LIMIT')


def main():
    phase,preview,date = context(os.environ.get('PHASE','run'),os.environ.get('PREVIEW','false')=='true',
                                os.environ.get('TARGET_DATE',''),os.environ['GITHUB_EVENT_NAME'],
                                check_public=site_checks.check_site)
    if (not preview and phase in ('run','resume') and not os.environ.get('TARGET_DATE','').strip()
            and os.environ.get('GITHUB_REF_NAME')=='main'):
        if os.getenv('NEWS_POLICY_VERSION')=='4.3':
            # Keep old ciphertext artifacts under their original dates; don't relabel as today.
            print('[release-context] policy43 serves current date; older checkpoints retained under original labels')
        else:date=unfinished_date(news.ROOT,date,production_artifacts())
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:
        output.write(f'phase={phase}\npreview={str(preview).lower()}\ntarget_date={date}\n')
    print(f'[release-context] phase={phase} preview={preview} target_date={date}',flush=True)

if __name__=='__main__': main()
