"""Public release date routing only. No checkpoint, dossier, or credential access."""
from datetime import datetime
import json
import os
from pathlib import Path
try:
    from scripts import news
except ImportError:
    import news

CONFIG = {'date':'2026-10-25','prior_run_id':40209759347,'prior_artifact_id':12605134114}


def pending_date(root, now):
    date = CONFIG['date']
    if datetime.fromisoformat(date).date()<=now.date() and not (root/'issues'/date/'issue.json').is_file():
        return date
    return None


def context(phase, preview, date, event, root=None, now=None):
    root = root or news.ROOT
    now = now or datetime.now(news.TZ)
    pending = pending_date(root,now)
    # Explicit manual requests retain their date/mode. All cron strings are unchanged.
    if event=='push':
        return ('resume' if pending else 'check'),False,CONFIG['date']
    if event=='schedule' and phase in ('write','audit','publish') and pending:
        return 'resume',False,pending
    return phase,preview,date


def main():
    phase,preview,date = context(os.environ['PHASE'],os.environ['PREVIEW']=='true',
                                os.environ.get('TARGET_DATE',''),os.environ['GITHUB_EVENT_NAME'])
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:
        output.write(f'phase={phase}\npreview={str(preview).lower()}\ntarget_date={date}\n')
        recover = phase=='resume' and date==CONFIG['date'] and not preview
        output.write(f'legacy_recovery={str(recover).lower()}\n')
        output.write(f'prior_run_id={CONFIG["prior_run_id"]}\nprior_artifact_id={CONFIG["prior_artifact_id"]}\n')
    print(f'[release-context] phase={phase} preview={preview} target_date={date or "automatic"}',flush=True)

if __name__=='__main__': main()
