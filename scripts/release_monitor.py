"""Public HTTPS delivery checks and one deduplicated GitHub incident per edition."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
try:
    from scripts import news, site_checks, release_queue
except ImportError:
    import news
    import site_checks
    import release_queue

CODES={'NOT_PREPARED','READY_NOT_PUBLISHED','SITE_NOT_CURRENT','EXTERNAL_SERVICE',
       'QUOTA_EXHAUSTED','EDITORIAL_HOLD','DELIVERY_RETRY_LIMIT','SETTINGS_BLOCKED','VERIFIED','WATCHDOG_GITHUB_ERROR','PRODUCTION_WORKFLOW_DISABLED',
       'WATCHDOG_RECOVERY_LIMIT','ACTIVE_PRODUCTION_TIMEOUT','RECOVERY_NOT_VERIFIED','WATCHDOG_DATE_ROLLED_OVER'}


PUBLIC_CHECK_CODES={'PUBLIC_DATE_MISSING','PUBLIC_DATE_MISMATCH','PUBLIC_METADATA_INVALID','PUBLIC_HOME_CHANGED','PUBLIC_OVERVIEW_CHANGED','PUBLIC_MARKDOWN_CHANGED','PUBLIC_ARCHIVE_LINK_MISSING','PUBLIC_LINK_COUNT_MISMATCH','PUBLIC_CONTENT_CHANGED','PUBLIC_COUNT_INVALID','PUBLIC_KIND_MISMATCH','EMPTY_OR_MISLABELLED_RESERVE','HTTP_404','HTTP_403','HTTP_503','HTTP_STATUS_OTHER','HTTPS_TRANSPORT_ERROR','PUBLIC_CHECK_FAILED'}

def github(method,path,payload=None):
    repo=os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
        raise RuntimeError('Invalid repository identity')
    token=os.environ['GH_TOKEN']
    request=Request(f'https://api.github.com/repos/{repo}/{path}',method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json',
                 'User-Agent':'387-News-Release-Monitor'})
    with urlopen(request,timeout=30) as response:
        raw=response.read()
        return json.loads(raw) if raw else None


def incident_attempts(body):
    match=re.search(r'<!-- 387-news-recoveries: (\d+) -->',body or '')
    return min(3,int(match[1])) if match else 0


def find_incident(date,request=github):
    datetime.strptime(date,'%Y-%m-%d')
    marker=f'<!-- 387-news-release:{date} -->'
    existing=None
    for page in range(1,6):
        batch=request('GET',f'issues?state=all&per_page=100&page={page}')
        if not isinstance(batch,list): raise RuntimeError('Invalid incident list')
        existing=next((i for i in batch if not i.get('pull_request') and i.get('user',{}).get('login')=='github-actions[bot]' and marker in (i.get('body') or '')),None)
        if existing or len(batch)<100: break
    else:
        raise RuntimeError('Incident pagination limit; refusing uncertain duplicate')
    return existing


def incident(date,code,healthy,request=github,*,recovery_attempts=None,public_check_code=None):
    datetime.strptime(date,'%Y-%m-%d')
    if code not in CODES:raise ValueError('Unknown public diagnostic code')
    marker=f'<!-- 387-news-release:{date} -->'
    existing=find_incident(date,request)
    attempts=max(incident_attempts((existing or {}).get('body','')),recovery_attempts or 0)
    if type(attempts) is not int or not 0<=attempts<=3:raise ValueError('RECOVERY_COUNT_INVALID')
    if attempts:marker+='\n<!-- 387-news-recoveries: '+str(attempts)+' -->'
    if healthy:
        if existing and existing.get('state')!='closed':
            request('PATCH',f'issues/{existing["number"]}',{'state':'closed',
                'body':marker+f'\n\nRelease {date}: VERIFIED over HTTPS; complete articles match the applicable policy and public overview.\n'})
        return 'resolved' if existing else 'none'
    body=(marker+f'\n\nRelease {date}: **{code}**.\n\n'
          'The controller retains checkpoints and approved articles. Existing wake-up windows retry within API and delivery limits. '
          'Editorial holds and exhausted delivery retry limits need owner diagnosis. No drafts or secrets are included.\n')
    if public_check_code in PUBLIC_CHECK_CODES:body+='\nPublic HTTPS check: **'+public_check_code+'**.\n'
    run_id=os.getenv('GITHUB_RUN_ID','');repo=os.getenv('GITHUB_REPOSITORY','')
    if repo=='zzz387/387-news' and run_id.isdigit():body+='\nActions: https://github.com/'+repo+'/actions/runs/'+run_id+'\n'
    if existing:
        if existing.get('state')!='open' or existing.get('body')!=body:
            request('PATCH',f'issues/{existing["number"]}',{'state':'open','body':body})
        return 'updated'
    request('POST','issues',{'title':f'[387 News] Release incident {date}','body':body})
    return 'created'


def evaluate(root,status,now=None,check_public=site_checks.check_site):
    now=now or datetime.now(news.TZ)
    today=now.date().isoformat()
    if now.hour<6:
        return {'date':today,'code':'NOT_PREPARED','verified':False,'alert':False,'not_due':True,'publication_status':'WAITING_FOR_RELEASE'}
    try:
        check_public(expected_date=today)
        return {'date':today,'code':'VERIFIED','verified':True,'alert':False,'publication_status':'PUBLISHED_VERIFIED'}
    except (HTTPError,URLError,TimeoutError,OSError):
        external=True
    except Exception:
        external=False
    exists=release_queue.edition_exists(root,today)
    code='EXTERNAL_SERVICE' if external else 'SITE_NOT_CURRENT' if exists else 'NOT_PREPARED'
    if status.get('date')==today:
        block=status.get('block_code')
        if block=='DAILY_QUOTA': code='QUOTA_EXHAUSTED'
        elif block in ('API_COOLDOWN','AUDIT_EXTERNAL_ERROR','INFRASTRUCTURE_ERROR'): code='EXTERNAL_SERVICE'
        elif block=='RELEASE_DISABLED': code='SETTINGS_BLOCKED'
        elif block=='DELIVERY_RETRY_LIMIT': code='DELIVERY_RETRY_LIMIT'
        elif status.get('stage')=='BLOCKED': code='EDITORIAL_HOLD'
        elif status.get('audit_passed') and not exists: code='READY_NOT_PUBLISHED'
    # One-hour grace prevents a transient initial deploy from creating an incident.
    alert=now.hour>=7 or code in ('EDITORIAL_HOLD','DELIVERY_RETRY_LIMIT')
    return {'date':today,'code':code,'verified':False,'alert':alert,'publication_status':'PUBLICATION_FAILED'}


def main():
    raw=json.loads(os.getenv('PIPELINE_STATUS','{}') or '{}')
    result=evaluate(news.ROOT,raw)
    output=os.getenv('GITHUB_OUTPUT')
    if output:
        with open(output,'a') as stream:stream.write('verified='+str(result['verified']).lower()+'\npublication_status='+result['publication_status']+'\n')
    if os.getenv('NEWS_POLICY_VERSION')=='4.3':
        try:
            workflow=github('GET','actions/workflows/daily-v31.yml')
            print('[daily-workflow] '+json.dumps({'state':workflow['state'],'path':workflow['path'],'release_target':'06:00 Europe/Moscow'}),flush=True)
        except Exception as exc:print('[daily-workflow] '+json.dumps({'code':'METADATA_UNAVAILABLE','error':type(exc).__name__}),flush=True)
    result['waiting_for_authorized_special_priority']=os.getenv('SPECIAL_PRIORITY_HOLD')=='true' and os.getenv('NEWS_POLICY_VERSION')!='4.3'
    try:
        if result['verified'] or result['alert']:
            result['incident']=incident(result['date'],result['code'],result['verified'])
    except HTTPError as exc:
        result['notification_error']='GitHub HTTP '+str(exc.code)
    except Exception as exc:
        result['notification_error']=type(exc).__name__
    print('[delivery-status] '+json.dumps(result),flush=True)
    summary=os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a') as stream:
            stream.write('### Public delivery\n\n```json\n'+json.dumps(result,indent=2)+'\n```\n')
    if not result['verified'] and not result.get('not_due') and not result['waiting_for_authorized_special_priority']:
        raise RuntimeError('Daily edition is not verified on the public site; incident/retry status recorded')

if __name__=='__main__': main()
