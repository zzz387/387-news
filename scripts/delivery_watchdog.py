"""Independent public delivery control: dispatch the SAME production, never Gemini."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
import json,os,time
from scripts import release_queue as queue,release_monitor as monitor,site_checks

WORKFLOW='daily-v31.yml'
ACTIVE={'queued','pending','waiting','in_progress','requested'}
MAX_RECOVERIES=3
POLL_SECONDS=600
RECOVERY_GAP=timedelta(minutes=12)
ARM_SECONDS=5*60*60
DELIVERY_LEAD_SECONDS=6*60
MAX_PREPARATIONS=4


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


def prepare_date(date,now,request=monitor.github,exclude_run_id=0):
    """Bounded wake-up of the existing controller, using the SAME mutex/quota."""
    datetime.strptime(date,'%Y-%m-%d')
    result={'date':date,'dispatched':False}
    rows=productions(request)
    def busy(rows):return any(r['status'] in ACTIVE and r['id']!=exclude_run_id for r in rows)
    if busy(rows):return dict(result,code='PREPARATION_ALREADY_ACTIVE')
    prior=[r for r in rows if r.get('event')=='workflow_dispatch' and r.get('display_title')=='Preparation '+date]
    # Day-ahead attempts must not consume the following night's wake-up budget.
    today=[r for r in prior if queue.moscow(datetime.fromisoformat(r['created_at'].replace('Z','+00:00'))).date()==now.date()]
    if len(today)>=MAX_PREPARATIONS:return dict(result,code='PREPARATION_WAKEUP_LIMIT')
    retry_after=max((datetime.fromisoformat(r['created_at'].replace('Z','+00:00'))+RECOVERY_GAP for r in prior),default=now)
    if now<retry_after:return dict(result,code='PREPARATION_BACKOFF')
    if request('GET',f'actions/workflows/{WORKFLOW}').get('state')!='active':return dict(result,code='PRODUCTION_WORKFLOW_DISABLED')
    if busy(productions(request)):return dict(result,code='PREPARATION_ALREADY_ACTIVE')
    request('POST',f'actions/workflows/{WORKFLOW}/dispatches',{'ref':'main','inputs':{'phase':'resume','preview':'false','target_date':date}})
    return dict(result,dispatched=True,code='PREPARATION_DISPATCHED',attempt=len(today)+1)


def reference_repair_pending(root,date):
    from scripts import mosaic44
    spec=mosaic44.CONFIG.get('repair_reference_art',{});target=spec.get('date','9999-12-31');path=Path(root)/'issues'/target/'release.json'
    if date<target or not path.is_file():return False
    row=json.loads(path.read_text())
    return row.get('number')==spec.get('number') and any(i.get('model')==spec['source_model'] for i in row.get('illustrations',[]))

def library_date(root,date,now,preparation,request=monitor.github,exclude_run_id=0):
    """Museum-only jobs occupy idle windows after bounded daily preparation."""
    from scripts import art_library44 as lib
    result={'date':date,'dispatched':False}
    if preparation.get('code')!='PREPARATION_WAKEUP_LIMIT':return dict(result,code='DAILY_PREPARATION_FIRST')
    if (datetime.fromisoformat(date+'T06:00').replace(tzinfo=queue.news.TZ)+timedelta(days=1)-now).total_seconds()<1800:return dict(result,code='DAILY_RELEASE_FIRST')
    registry=lib.load(root);lib.queue_topups(root,registry);report=lib.library_report(registry)
    if report['complete'] and not report['pending_topups']:return dict(result,code='LIBRARY_COMPLETE')
    if not lib.prefill_genres(registry,now.astimezone(timezone.utc)):return dict(result,code='LIBRARY_SOURCE_BACKOFF')
    rows=productions(request)
    def busy(rows):return any(r['status'] in ACTIVE and r['id']!=exclude_run_id for r in rows)
    if busy(rows):return dict(result,code='PRODUCTION_ACTIVE')
    prior=[r for r in rows if r.get('event')=='workflow_dispatch' and r.get('display_title','').startswith('Library ')]
    today=[r for r in prior if datetime.fromisoformat(r['created_at'].replace('Z','+00:00')).astimezone(timezone.utc).date()==now.astimezone(timezone.utc).date()]
    if len(today)>=4:return dict(result,code='LIBRARY_WAKEUP_LIMIT')
    last=max((datetime.fromisoformat(r['created_at'].replace('Z','+00:00')) for r in prior),default=now-RECOVERY_GAP)
    if now-last<RECOVERY_GAP:return dict(result,code='LIBRARY_BACKOFF')
    if busy(productions(request)):return dict(result,code='PRODUCTION_ACTIVE')
    request('POST',f'actions/workflows/{WORKFLOW}/dispatches',{'ref':'main','inputs':{'phase':'library_prefill','preview':'false','target_date':date}})
    return dict(result,dispatched=True,code='LIBRARY_DISPATCHED')


def backfill_date(root,date,now,preparation,request=monitor.github,exclude_run_id=0,status=None):
    """Two serial free-window continuations/day; daily editing always goes first."""
    result={'date':date,'dispatched':False}
    if preparation.get('code')!='PREPARATION_WAKEUP_LIMIT':return dict(result,code='DAILY_PREPARATION_FIRST')
    if (datetime.fromisoformat(date+'T06:00').replace(tzinfo=queue.news.TZ)+timedelta(days=1)-now).total_seconds()<1800:return dict(result,code='DAILY_RELEASE_FIRST')
    path=Path(root)/'issues'/date/'release.json'
    repair=reference_repair_pending(root,date)
    current_missing=path.is_file() and json.loads(path.read_text()).get('art44',{}).get('missing',0)
    if repair and not current_missing:
        from scripts import mosaic44
        date=mosaic44.CONFIG['repair_reference_art']['date'];path=Path(root)/'issues'/date/'release.json';result['date']=date
    elif current_missing:
        from scripts import mosaic44
        repair=repair and date==mosaic44.CONFIG['repair_reference_art']['date']
    if not path.is_file() or (not json.loads(path.read_text()).get('art44',{}).get('missing',0) and not repair):return dict(result,code='ARTWORK_COMPLETE')
    if (status or {}).get('cloudflare_art',{}).get('cooldown_until',0)>now.timestamp():return dict(result,code='ARTWORK_COOLDOWN')
    def busy(rows):return any(r['status'] in ACTIVE and r['id']!=exclude_run_id for r in rows)
    rows=productions(request)
    if busy(rows):return dict(result,code='PRODUCTION_ACTIVE')
    prior=[r for r in rows if r.get('display_title')=='Artwork '+date and r.get('event')=='workflow_dispatch']
    today=[r for r in prior if datetime.fromisoformat(r['created_at'].replace('Z','+00:00')).astimezone(timezone.utc).date()==now.astimezone(timezone.utc).date()]
    if len(today)>=2:return dict(result,code='ARTWORK_WAKEUP_LIMIT')
    last=max((datetime.fromisoformat(r['created_at'].replace('Z','+00:00')) for r in prior),default=now-RECOVERY_GAP)
    if now-last<RECOVERY_GAP:return dict(result,code='ARTWORK_BACKOFF')
    if busy(productions(request)):return dict(result,code='PRODUCTION_ACTIVE')
    inputs={'phase':'backfill_issue_art','preview':'false','target_date':date}
    if repair:inputs['repair_schnell_images']='true'
    request('POST',f'actions/workflows/{WORKFLOW}/dispatches',{'ref':'main','inputs':inputs})
    return dict(result,dispatched=True,code='ARTWORK_DISPATCHED')


def current(date,check,diagnostic=None):
    try:
        report=check(expected_date=date)
        if diagnostic is not None and isinstance(report,dict):
            editorial=report.get('editorial_standard',{})
            if editorial.get('compliant'):
                diagnostic['editorial_status']=editorial['admission_status']
                diagnostic['editorial_standard']=editorial
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


def run(root,*,clock=queue.moscow,sleep=time.sleep,request=monitor.github,check=site_checks.check_site,poll_seconds=POLL_SECONDS,prepare_early=False):
    now=queue.moscow(clock());date=now.date().isoformat();release=datetime.fromisoformat(date+'T06:00:00').replace(tzinfo=queue.news.TZ)
    result={'date':date,'verified':False,'recovery_dispatched':False,'publication_status':'WAITING_FOR_RELEASE','code':'NOT_DUE','gemini_requests':0}
    if now<release:
        if prepare_early and os.getenv('NEWS_POLICY_VERSION')=='4.4':
            try:result['preparation']=prepare_date(date,now,request)
            except Exception as exc:result['preparation']={'code':'PREPARATION_API_UNCERTAIN','error':type(exc).__name__}
        if (release-now).total_seconds()>ARM_SECONDS:return result
        print('[delivery-watchdog] '+json.dumps(dict(result,code='ARMED_FOR_DELIVERY',release_at=release.isoformat(),delivery_start=(release-timedelta(seconds=DELIVERY_LEAD_SECONDS)).isoformat())),flush=True)
        # Waiting for delivery must not prevent bounded preparation retries when
        # later cron wake-ups are missing. No model, draft or additional mutex.
        last_prepare=now;local_dispatches=int(result.get('preparation',{}).get('dispatched',False))
        def preparation_wait(seconds):
            nonlocal last_prepare,local_dispatches
            sleep(seconds);at=queue.moscow(clock())
            if not prepare_early or os.getenv('NEWS_POLICY_VERSION')!='4.4' or local_dispatches>=MAX_PREPARATIONS or at-last_prepare<RECOVERY_GAP:return
            last_prepare=at
            try:
                wake=prepare_date(date,at,request);result['preparation']=wake
                local_dispatches+=int(wake['dispatched'])
                if wake['code']=='PREPARATION_WAKEUP_LIMIT':local_dispatches=MAX_PREPARATIONS
            except Exception as exc:result['preparation']={'code':'PREPARATION_API_UNCERTAIN','error':type(exc).__name__}
        queue.wait_until_release(date,clock=clock,sleep=preparation_wait,maximum_wait=ARM_SECONDS,lead_seconds=DELIVERY_LEAD_SECONDS)
    deadline=max(queue.moscow(clock()),release)+timedelta(seconds=poll_seconds)
    attempts=0;code='RECOVERY_NOT_VERIFIED';active=False
    while True:
        now=queue.moscow(clock())
        if now.date().isoformat()!=date:code='WATCHDOG_DATE_ROLLED_OVER';break
        if now>=release and current(date,check,result):
            result.update(verified=True,publication_status='PUBLISHED_VERIFIED',delivery_status='PUBLICATION_VERIFIED',code='VERIFIED')
            if prepare_early and os.getenv('NEWS_POLICY_VERSION')=='4.4':
                try:result['preparation']=prepare_date((now.date()+timedelta(days=1)).isoformat(),now,request)
                except Exception as exc:result['preparation']={'code':'PREPARATION_API_UNCERTAIN','error':type(exc).__name__}
            if prepare_early and os.getenv('NEWS_POLICY_VERSION')=='4.4':
                try:result['artwork_recovery']=backfill_date(root,date,now,result.get('preparation',{}),request)
                except Exception as exc:result['artwork_recovery']={'code':'ARTWORK_API_UNCERTAIN','error':type(exc).__name__}
            if prepare_early and os.getenv('NEWS_POLICY_VERSION')=='4.4' and not result.get('artwork_recovery',{}).get('dispatched'):
                try:result['library_recovery']=library_date(root,date,now,result.get('preparation',{}),request)
                except Exception as exc:result['library_recovery']={'code':'LIBRARY_API_UNCERTAIN','error':type(exc).__name__}
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
                    if now>=release and current(date,check,result):continue
                    if any(r['status'] in ACTIVE for r in productions(request)):active=True
                    else:
                        attempts+=1
                        phase='publish' if queue.edition_exists(root,date) or os.getenv('NEWS_POLICY_VERSION')!='4.4' else 'run'
                        request('POST',f'actions/workflows/{WORKFLOW}/dispatches',{'ref':'main','inputs':{'phase':phase,'preview':'false','target_date':date}})
                        result.update(recovery_dispatched=True,publication_status='PUBLISHING',code='RECOVERY_DISPATCHED')
                        print('[delivery-watchdog] '+json.dumps(dict(result,recovery_attempts=attempts)),flush=True)
        except Exception as exc:
            code='WATCHDOG_GITHUB_ERROR';result['api_error']=type(exc).__name__
            if isinstance(exc,HTTPError):result['api_http_status']=exc.code
            break
        if now>=deadline:code='ACTIVE_PRODUCTION_TIMEOUT' if active else 'RECOVERY_NOT_VERIFIED';break
        sleep(min(30,max(0,(deadline-now).total_seconds())))
    result.update(publication_status='PUBLICATION_FAILED',delivery_status='PUBLICATION_FAILED',code=code,recovery_attempts=attempts)
    try:result['incident']=monitor.incident(date,code,False,request,recovery_attempts=min(attempts,MAX_RECOVERIES),public_check_code=result.get('public_check_code'))
    except Exception as exc:result['notification_error']=type(exc).__name__
    return result


def main():
    if (os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REPOSITORY')!='zzz387/387-news' or os.getenv('GITHUB_REF_NAME')!='main'):
        raise RuntimeError('WATCHDOG_PROTECTED_MAIN_REQUIRED')
    if os.getenv('NEWS_AUTOMATION_V31_ENABLED')!='true' or os.getenv('NEWS_RELEASE_APPROVED')!='true':raise RuntimeError('WATCHDOG_PRODUCTION_NOT_ENABLED')
    def delivered(**kwargs):
        report=site_checks.check_site(**kwargs)
        site_checks.check_assets(queue.news.ROOT)
        return report
    result=run(queue.news.ROOT,check=delivered,prepare_early=True)
    print('[delivery-watchdog] '+json.dumps(result),flush=True)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:stream.write('### Independent public delivery\n\n```json\n'+json.dumps(result,indent=2)+'\n```\n')
    if result['publication_status']=='PUBLICATION_FAILED':raise RuntimeError('WATCHDOG_PUBLICATION_FAILED')

if __name__=='__main__':main()


