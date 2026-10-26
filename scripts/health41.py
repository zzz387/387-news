"""Read-only production diagnostics: metadata, public HTTPS and model capabilities only."""
from datetime import datetime,timedelta,timezone
import argparse,json,os
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from scripts import policy41 as p,release_queue,site_checks,generation_runtime


def emit(tag,value):
    print('['+tag+'] '+json.dumps(value,ensure_ascii=False),flush=True)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:
            stream.write('\n### '+tag+'\n\n```json\n'+json.dumps(value,ensure_ascii=False,indent=2)+'\n```\n')


def get(path):
    if os.environ['GITHUB_REPOSITORY']!='zzz387/387-news':raise RuntimeError('REPOSITORY_MISMATCH')
    request=Request('https://api.github.com/repos/zzz387/387-news/'+path,headers={
        'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    with urlopen(request,timeout=30) as response:return json.load(response)


def recent_runs(now,fetch=get):
    cutoff=now.astimezone(timezone.utc)-timedelta(hours=12);rows=[]
    for page in range(1,101):
        batch=fetch('actions/workflows/daily-v31.yml/runs?branch=main&per_page=100&page='+str(page))['workflow_runs']
        for row in batch:
            if datetime.fromisoformat(row['created_at'].replace('Z','+00:00'))>=cutoff:rows.append(row)
        if len(batch)<100 or any(datetime.fromisoformat(row['created_at'].replace('Z','+00:00'))<cutoff for row in batch):return rows
    raise RuntimeError('RUN_PAGINATION_INCOMPLETE')


def checkpoint_date(root,now,artifacts):
    proposed=release_queue.target_date(root,now)
    return release_queue.unfinished_date(root,proposed,artifacts)


def artifact_records(fetch=get):
    rows=[]
    for page in range(1,101):
        batch=fetch('actions/artifacts?per_page=100&page='+str(page))['artifacts'];rows.extend(batch)
        if len(batch)<100:return rows
    raise RuntimeError('ARTIFACT_LIST_INCOMPLETE')


def select(rows,labels):
    matching=[row for row in rows if row['name'] in labels]
    valid=[row for row in matching if not row['expired']]
    if not valid:
        if matching:raise RuntimeError('SAVED_ARTIFACT_EXPIRED')
        return None
    row=max(valid,key=lambda item:(item['created_at'],item['id']))
    if row.get('workflow_run',{}).get('head_branch')!='main':raise RuntimeError('ARTIFACT_ORIGIN_INVALID')
    return row


def metadata(root,now=None,fetch=get):
    now=now or datetime.now(p.TZ);page=fetch('pages')
    emit('pages-api',{'checked_at':now.isoformat(),**{k:page.get(k) for k in ('build_type','cname','https_enforced','status')}})
    if page.get('build_type')!='workflow' or page.get('cname')!='387.su' or page.get('https_enforced') is not True:
        raise RuntimeError('PAGES_DOMAIN_OR_MODE_INVALID')
    workflow=fetch('actions/workflows/daily-v31.yml');runs=recent_runs(now,fetch)
    emit('production-metadata',{'workflow_state':workflow['state'],'hours':12,'runs':[
        {k:r.get(k) for k in ('id','event','status','conclusion','created_at','head_sha')} for r in runs]})
    if workflow['state']!='active':raise RuntimeError('PRODUCTION_WORKFLOW_NOT_ACTIVE')
    text=(Path(root)/'.github/workflows/daily-v31.yml').read_text()
    for required in ('pages: write','id-token: write','name: github-pages','NEWS_MAX_REQUESTS_PER_RUN: "24"',
                     'NEWS_MAX_REQUESTS_PER_DAY: "220"','NEWS_REQUEST_GAP_SECONDS: "6"',"cron: '54 2 * * *'"):
        if required not in text:raise RuntimeError('PRODUCTION_PERMISSION_OR_SCHEDULE_MISSING')
    rows=artifact_records(fetch);date=checkpoint_date(root,now,rows)
    checkpoint=select(rows,{'387news31-production-'+date})
    emit('checkpoint-metadata',{'date':date,'found':bool(checkpoint),'artifact_id':checkpoint['id'] if checkpoint else None,
        'run_id':checkpoint['workflow_run']['id'] if checkpoint else None,'content_downloaded':False})
    day=now.astimezone(timezone.utc).date();today=day.isoformat()
    ledger=select(rows,set(generation_runtime.quota_labels(today)))
    if ledger is None:ledger=select(rows,set(generation_runtime.quota_labels((day-timedelta(days=1)).isoformat())))
    if ledger is None:raise RuntimeError('RECENT_QUOTA_LEDGER_MISSING')
    ledger_day=ledger['name'][len('387news31-quota-'):][:10]
    emit('quota-metadata',{'artifact_id':ledger['id'],'run_id':ledger['workflow_run']['id'],'day':ledger_day,
        'current_utc_day':today,'read_only':True})
    with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
        stream.write('quota_id='+str(ledger['id'])+'\nquota_run='+str(ledger['workflow_run']['id'])+'\nquota_day='+ledger_day+'\n')


def public_health(path,ledger_day,now=None):
    now=now or datetime.now(p.TZ);path=Path(path);before=path.read_bytes();ledger=json.loads(before)
    if ledger.get('day')!=ledger_day or type(ledger.get('requests')) is not int or not 0<=ledger['requests']<=220:
        raise RuntimeError('QUOTA_LEDGER_INVALID')
    emit('quota-read-only',{'day':ledger['day'],'requests_used':ledger['requests'],
        'requests_used_today':ledger['requests'] if ledger['day']==now.astimezone(timezone.utc).date().isoformat() else 0,
        'cooldowns':{m:{'until_moscow':datetime.fromtimestamp(t,p.TZ).isoformat(),'active':t>now.timestamp()} for m,t in ledger.get('cooldowns',{}).items()},
        'model_requests_performed_by_health_job':0,'ledger_modified':False})
    current=site_checks.check_site();current=site_checks.check_site(expected_date=current['issue_date'])
    if path.read_bytes()!=before:raise RuntimeError('READ_ONLY_LEDGER_CHANGED')
    emit('public-https',current)


def model_metadata(open_url=urlopen):
    # No inference, no prompt, no billing/configuration mutation. A GET does not prove inference availability.
    if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REF_NAME')!='main':raise RuntimeError('MODELS_ACTIONS_MAIN_REQUIRED')
    key=os.environ['GEMINI_API_KEY'];rows=[]
    for model in ('gemini-3.5-flash-lite','gemini-3.1-flash-lite'):
        request=Request('https://generativelanguage.googleapis.com/v1beta/models/'+model,
            headers={'x-goog-api-key':key})
        try:
            with open_url(request,timeout=20) as response:data=json.load(response)
            rows.append({'model':model,'http':200,'methods':data.get('supportedGenerationMethods',[]),
                'input_token_limit':data.get('inputTokenLimit'),'output_token_limit':data.get('outputTokenLimit')})
        except HTTPError as exc:rows.append({'model':model,'http':exc.code})
        except Exception as exc:rows.append({'model':model,'error_class':type(exc).__name__})
    emit('gemini-model-metadata',{'models':rows,'inference_requests':0,'inference_availability':'not_proven_by_metadata'})
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['metadata','public','models']);args=parser.parse_args()
    if args.mode=='metadata':metadata(Path(os.getenv('HEALTH_PRODUCTION_ROOT','.')))
    elif args.mode=='public':public_health(os.environ['QUOTA_PATH'],os.environ['QUOTA_DAY'])
    else:model_metadata()

if __name__=='__main__':main()
