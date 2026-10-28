"""One bounded dispatch of the SAME production controller after saved progress."""
from datetime import datetime,timezone
import json,os
from urllib.request import Request,urlopen
from scripts import staged_news as stage


def decision(ledger,runs,run_id,now=None):
    now=now or datetime.now(timezone.utc)
    if (ledger.get('day')!=now.date().isoformat() or type(ledger.get('requests')) is not int
            or not 0<ledger['requests']<220):return False,'WAIT_FOR_QUOTA_WINDOW'
    if any(until>now.timestamp() for until in ledger.get('cooldowns',{}).values()):return False,'WAIT_FOR_COOLDOWN'
    if any(str(r['id'])!=str(run_id) and r['status'] in ('queued','pending','waiting','in_progress','requested') for r in runs):
        return False,'EXISTING_PRODUCTION_WILL_CONTINUE'
    return True,'SAVED_PROGRESS_AND_FREE_QUOTA'


def main():
    if os.getenv("NEWS_POLICY_VERSION")=="4.3":
        print("[special-continuation] PAUSED_POLICY43");return
    if (os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('GITHUB_REF_NAME')!='main'
            or os.environ.get('GITHUB_REPOSITORY')!='zzz387/387-news'
            or os.environ.get('SPECIAL_HOLD_DAILY')!='true' or not 1<=int(os.environ.get('SPECIAL_RUN_USED','0'))<=24):
        raise RuntimeError('SPECIAL_CONTINUATION_GUARD')
    # Counts-only ledger, restored by the official action; no Gemini key or decryption key here.
    ledger=json.load(open(os.environ['QUOTA_CHECKPOINT_FILE']))
    now=datetime.now(timezone.utc)
    if ledger.get('day') not in (now.date().isoformat(),):
        print('[special-continuation] WAIT_FOR_QUOTA_WINDOW');return
    runs=stage.request_json('https://api.github.com/repos/zzz387/387-news/actions/workflows/daily-v31.yml/runs?branch=main&per_page=100')['workflow_runs']
    allowed,reason=decision(ledger,runs,os.environ['GITHUB_RUN_ID'],now)
    print('[special-continuation] '+reason,flush=True)
    if not allowed:return
    payload={'ref':'main','inputs':{'phase':'run','preview':'false'}}
    request=Request('https://api.github.com/repos/zzz387/387-news/actions/workflows/daily-v31.yml/dispatches',
        method='POST',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
        'Accept':'application/vnd.github+json','Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
    with urlopen(request,timeout=30) as response:
        if response.status!=204:raise RuntimeError('SPECIAL_DISPATCH_NOT_ACCEPTED')
    print('[special-continuation] ONE_DISPATCH_ACCEPTED; same root mutex, unchanged request limits',flush=True)

if __name__=='__main__':main()
