"""Route each wake-up using Moscow time and current public delivery state."""
from datetime import datetime, timedelta
import os
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
    return path.is_file() and 'data-policy-version="4.1"' in path.read_text(encoding='utf-8')


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


def main():
    phase,preview,date = context(os.environ.get('PHASE','run'),os.environ.get('PREVIEW','false')=='true',
                                os.environ.get('TARGET_DATE',''),os.environ['GITHUB_EVENT_NAME'],
                                check_public=site_checks.check_site)
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:
        output.write(f'phase={phase}\npreview={str(preview).lower()}\ntarget_date={date}\n')
    print(f'[release-context] phase={phase} preview={preview} target_date={date}',flush=True)

if __name__=='__main__': main()
