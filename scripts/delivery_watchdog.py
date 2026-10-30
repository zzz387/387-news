"""Independent public delivery control: dispatch the SAME production, never Gemini."""
from datetime import datetime,timedelta
from pathlib import Path
from urllib.error import HTTPError,URLError
import json,os,time
from scripts import release_queue as queue,release_monitor as monitor,site_checks

WORKFLOW='daily-v31.yml'
ACTIVE={'queued','pending','waiting','in_progress','requested'}
MAX_RECOVERIES=3
POLL_SECONDS=600
RECOVERY_GAP=timedelta(minutes=12)
ARM_SECONDS=90*60


def productions(request):
    rows=[]
    for page in range(1,101):
        value=request('GET',f'actions/workflows/{WORKFLOW}/runs?branch=main&per_page=100&page={page}')
        batch=value.get('workflow_runs') if isinstance(value,dict) else None
        if not isinstance(batch,list):raise RuntimeError('PRODUCTION_LIST_INVALID')
        if any(not isinstance(r,dict) or not isinstance(r.get('id'),int) or 'status' not in r for r in batch):raise RuntimeError('PRODUCTION_LIST_INVALID')
        rows.extend(r for r in batch if r.get('head_branch')=='main' and r.get('event') in ('push','schedule','workflow_dispatch'))
        if len(batch)<100:return rows
    raise RuntimeError('PRODUCTION_LIST_INCOMPLETE')


def recoveries(rows,date):
    return [r for r in rows if r.get('event')=='workflow_dispatch' and r.get('display_title')=='Delivery '+date]


def observed_attempts(rows,date):return len({r['id'] for r in recoveries(rows,date)})


def current(date,check,diagnostic=None):
    try:
        check(expected_date=date)
        if diagnostic is not None:diagnostic.pop('public_check_code',None)
        return True
    except HTTPError as exc:code='HTTP_'+str(exc.code) if exc.code in (403,404,503) else 'HTTP_STATUS_OTHER'
    except (URLError,TimeoutError,OSError):code='HTTPS_TRANSPORT_ERROR'
    except Exception as exc:code=str(exc) if str(exc) in monitor.PUBLIC_CHECK_CODES else 'PUBLIC_CHECK_FAILED'
    if diagnostic is not None:diagnostic['public_check_code']=code
    return False


def durable_attempts(date,request):
    issue=monitor.find_incident(date,request)
    return monitor.incident_attempts((issue or {}).get('body',''))


def run(root,*,clock=queue.moscow,sleep=time.sleep,request=monitor.github,check=site_checks.check_site,poll_seconds=POLL_SECONDS):
    now=queue.moscow(clock());date=now.date().isoformat();release=datetime.fromisoformat(date+'T06:00:00').replace(tzinfo=queue.news.TZ)
    result={'date':date,'verified':False,'recovery_dispatched':False,'publication_status':'WAITING_FOR_RELEASE','code':'NOT_DUE','gemini_requests':0}
    if now<release:
        if (release-now).total_seconds()>ARM_SECONDS:return result
        print('[delivery-watchdog] '+json.dumps(dict(result,code='ARMED_UNTIL_0600',release_at=release.isoformat())),flush=True)
        # Separate watcher lock: generation can continue while this appointment waits.
        queue.wait_until_release(date,clock=clock,sleep=sleep,maximum_wait=ARM_SECONDS)
    deadline=queue.moscow(clock())+timedelta(seconds=poll_seconds)
    attempts=0;code='RECOVERY_NOT_VERIFIED';active=False
    while True:
        now=queue.moscow(clock())
        if now.date().isoformat()!=date:code='WATCHDOG_DATE_ROLLED_OVER';break
        if current(date,check,result):
            result.update(verified=True,publication_status='PUBLISHED_VERIFIED',code='VERIFIED')
            try:result['incident']=monitor.incident(date,'VERIFIED',True,request)
            except Exception as exc:result['notification_error']=type(exc).__name__
            return result
        try:
            rows=productions(request);active=any(r['status'] in ACTIVE for r in rows)
            attempts=max(attempts,observed_attempts(rows,date),durable_attempts(date,request))
            if not active and not result['recovery_dispatched']:
                workflow=request('GET',f'actions/workflows/{WORKFLOW}')
                if workflow.get('state')!='active':code='PRODUCTION_WORKFLOW_DISABLED';break
                if attempts>=MAX_RECOVERIES:code='WATCHDOG_RECOVERY_LIMIT';break
                prior=recoveries(rows,date)
                retry_after=max((datetime.fromisoformat(r['created_at'].replace('Z','+00:00'))+RECOVERY_GAP for r in prior),default=now)
                if now>=retry_after:
                    # Recheck the site and active producers immediately before the one POST.
                    if current(date,check,result):continue
                    if any(r['status'] in ACTIVE for r in productions(request)):active=True
                    else:
                        attempts+=1
                        request('POST',f'actions/workflows/{WORKFLOW}/dispatches',{'ref':'main','inputs':{'phase':'run','preview':'false','target_date':date}})
                        result.update(recovery_dispatched=True,publication_status='PUBLISHING',code='RECOVERY_DISPATCHED')
                        print('[delivery-watchdog] '+json.dumps(dict(result,recovery_attempts=attempts)),flush=True)
        except Exception as exc:
            code='WATCHDOG_GITHUB_ERROR';result['api_error']=type(exc).__name__
            if isinstance(exc,HTTPError):result['api_http_status']=exc.code
            break
        if now>=deadline:code='ACTIVE_PRODUCTION_TIMEOUT' if active else 'RECOVERY_NOT_VERIFIED';break
        sleep(min(30,max(0,(deadline-now).total_seconds())))
    result.update(publication_status='PUBLICATION_FAILED',code=code,recovery_attempts=attempts)
    try:result['incident']=monitor.incident(date,code,False,request,recovery_attempts=min(attempts,MAX_RECOVERIES),public_check_code=result.get('public_check_code'))
    except Exception as exc:result['notification_error']=type(exc).__name__
    return result


def main():
    if (os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REPOSITORY')!='zzz387/387-news' or os.getenv('GITHUB_REF_NAME')!='main'):
        raise RuntimeError('WATCHDOG_PROTECTED_MAIN_REQUIRED')
    if os.getenv('NEWS_AUTOMATION_V31_ENABLED')!='true' or os.getenv('NEWS_RELEASE_APPROVED')!='true':raise RuntimeError('WATCHDOG_PRODUCTION_NOT_ENABLED')
    result=run(queue.news.ROOT)
    print('[delivery-watchdog] '+json.dumps(result),flush=True)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:stream.write('### Independent public delivery\n\n```json\n'+json.dumps(result,indent=2)+'\n```\n')
    if result['publication_status']=='PUBLICATION_FAILED':raise RuntimeError('WATCHDOG_PUBLICATION_FAILED')

if __name__=='__main__':main()
