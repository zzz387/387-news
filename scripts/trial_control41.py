"""Owner-side wrapper around the existing workflow, not another production system.

Uses an existing authenticated gh session. Never reads or exports GitHub Secrets,
approves a deployment, changes main, or weakens an existing protection rule.
"""
import argparse
import base64
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo
try:
    from scripts import review_viewer41 as viewer
except ImportError: import review_viewer41 as viewer

ENV='387-news-v41-trial'
ENV_PATH=f'repos/{viewer.REPO}/environments/{ENV}'
WORKFLOW_PATH=f'repos/{viewer.REPO}/actions/workflows/daily-v31.yml'


def api(method,path,body=None):
    if method!='GET':
        legal=(method=='PUT' and path==ENV_PATH or method=='POST' and path==ENV_PATH+'/deployment-branch-policies'
               or method=='POST' and path==WORKFLOW_PATH+'/dispatches')
        if not legal: raise ValueError('TRIAL_CONTROL_MUTATION_OUT_OF_SCOPE')
        if path.endswith('/dispatches') and (body.get('ref')!=viewer.BRANCH or body.get('inputs',{}).get('phase') not in ('trial-route','trial','trial-inspect')):
            raise ValueError('TRIAL_CONTROL_DISPATCH_OUT_OF_SCOPE')
    args=['api','--method',method,path]
    if body is not None: args+=['--input','-']
    output=viewer.gh(args,input_json=body)
    return json.loads(output) if output.strip() else None


def ensure_environment(owner_id,call=api):
    try: current=call('GET',ENV_PATH)
    except RuntimeError as exc:
        if 'status=404' not in str(exc): raise
        current=None
    rules=(current or {}).get('protection_rules',[])
    review=next((rule for rule in rules if rule.get('type')=='required_reviewers'),{})
    reviewers=[{'type':r['type'],'id':r['reviewer']['id']} for r in review.get('reviewers',[])]
    if not any(r['type']=='User' and r['id']==owner_id for r in reviewers): reviewers.append({'type':'User','id':owner_id})
    if len(reviewers)>6: raise RuntimeError('TRIAL_ENVIRONMENT_REVIEWER_LIMIT_NEEDS_OWNER')
    policy=(current or {}).get('deployment_branch_policy')
    if policy and policy.get('protected_branches'): raise RuntimeError('TRIAL_ENVIRONMENT_EXISTING_BRANCH_PROTECTION_REQUIRES_OWNER')
    if current is None or not review or reviewers!=[{'type':r['type'],'id':r['reviewer']['id']} for r in review.get('reviewers',[])]:
        body={'reviewers':reviewers,'prevent_self_review':review.get('prevent_self_review',False),
              'wait_timer':next((r.get('wait_timer',0) for r in rules if r.get('type')=='wait_timer'),0),
              'deployment_branch_policy':policy or {'protected_branches':False,'custom_branch_policies':True}}
        call('PUT',ENV_PATH,body)
    verified=call('GET',ENV_PATH)
    actual=next((rule for rule in verified.get('protection_rules',[]) if rule.get('type')=='required_reviewers'),None)
    if not actual or not any(r['type']=='User' and r['reviewer']['id']==owner_id for r in actual.get('reviewers',[])):
        raise RuntimeError('TRIAL_ENVIRONMENT_REVIEWERS_NOT_CONFIRMED')
    if review.get('prevent_self_review') and not actual.get('prevent_self_review'):
        raise RuntimeError('TRIAL_ENVIRONMENT_PROTECTION_CHANGED_UNEXPECTEDLY')
    policy=verified.get('deployment_branch_policy') or {}
    if policy.get('custom_branch_policies'):
        patterns=call('GET',ENV_PATH+'/deployment-branch-policies?per_page=100').get('branch_policies',[])
        if not any(p.get('name')==viewer.BRANCH for p in patterns):
            call('POST',ENV_PATH+'/deployment-branch-policies',{'name':viewer.BRANCH,'type':'branch'})
    return {'required_reviewers':True,'prevent_self_review':actual.get('prevent_self_review',False)}


def new_run(phase,date,sha,recipient,call=api,wait=time.sleep):
    query=WORKFLOW_PATH+'/runs?event=workflow_dispatch&branch=codex%2Feditorial-policy-v41&per_page=100'
    before={r['id'] for r in call('GET',query).get('workflow_runs',[])}
    body={'ref':viewer.BRANCH,'inputs':{'phase':phase,'preview':'true','target_date':date,
        'trial_approved_sha':sha,'trial_confirmation':'RUN_V41_TRIAL_WITH_GEMINI' if phase=='trial' else '',
        'trial_review_public_key':recipient}}
    call('POST',WORKFLOW_PATH+'/dispatches',body)
    for _ in range(30):
        found=[r for r in call('GET',query).get('workflow_runs',[]) if r['id'] not in before and r.get('head_sha')==sha
               and r.get('event')=='workflow_dispatch' and (r.get('actor') or {}).get('login','').casefold()=='zzz387']
        if len(found)==1: return found[0]
        if len(found)>1: raise RuntimeError('TRIAL_DISPATCH_AMBIGUOUS_RUN: inspect Actions; do not repeat blindly')
        wait(2)
    raise RuntimeError('TRIAL_DISPATCH_RUN_NOT_YET_VISIBLE: inspect Actions before retrying')


def verify_route(run,call=api,wait=time.sleep):
    run_id=run['id']
    for _ in range(60):
        status=call('GET',f'repos/{viewer.REPO}/actions/runs/{run_id}')
        if status.get('status')=='completed':
            jobs=call('GET',f'repos/{viewer.REPO}/actions/runs/{run_id}/jobs').get('jobs',[])
            if (status.get('conclusion')=='success' and any(j.get('name')=='trial-route' and j.get('conclusion')=='success' for j in jobs)
                    and all(j.get('conclusion')=='skipped' for j in jobs if j.get('name') in ('trial','prepare','deploy','monitor'))):
                return True
            raise RuntimeError('TRIAL_BRANCH_DISPATCH_ROUTE_NOT_CONFIRMED')
        wait(2)
    raise RuntimeError('TRIAL_ROUTE_STILL_QUEUED: no Gemini dispatch performed')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['start','resume','inspect','open'])
    parser.add_argument('--key-dir',type=Path); parser.add_argument('--date')
    args=parser.parse_args(); directory=Path(args.key_dir or viewer.key_directory()); session_file=directory/'session.json'
    if args.command=='open':
        session=json.loads(session_file.read_text())
        import sys
        sys.argv=['review_viewer41','--run',str(session['run_id']),'--expected-sha',session['sha'],
                  '--date',session['date'],'--key-dir',str(directory)]
        viewer.main(); return
    identity=api('GET','user')
    if identity.get('login','').casefold()!='zzz387': raise RuntimeError('TRIAL_OWNER_GH_SESSION_REQUIRED')
    pr=api('GET',f'repos/{viewer.REPO}/pulls/7')
    if pr.get('state')!='open' or pr['head']['ref']!=viewer.BRANCH or pr['base']['ref']!='main':
        raise RuntimeError('TRIAL_PR_PROVENANCE_INVALID')
    sha=pr['head']['sha']
    if not re.fullmatch('[0-9a-f]{40}',sha): raise RuntimeError('TRIAL_HEAD_SHA_INVALID')
    today=datetime.now(ZoneInfo('Europe/Moscow')).date()
    session=json.loads(session_file.read_text()) if session_file.exists() else None
    if args.command in ('resume','inspect'):
        if not session: raise RuntimeError('TRIAL_SAVED_SESSION_REQUIRED')
        date=session['date']
    else:
        date=args.date or (today+timedelta(days=1)).isoformat()
        if datetime.strptime(date,'%Y-%m-%d').date()<=today: raise RuntimeError('TRIAL_FIRST_DATE_MUST_BE_FUTURE_IN_MOSCOW')
    # Fetch the actual branch workflow. A subsequent route run, rather than this text check,
    # proves GitHub accepts the branch's dispatch inputs before the real trial is dispatched.
    workflow=api('GET',f'repos/{viewer.REPO}/contents/{viewer.WORKFLOW}?ref={sha}')
    text=base64.b64decode(workflow['content']).decode()
    if 'trial-route' not in text or 'trial_review_public_key' not in text: raise RuntimeError('TRIAL_BRANCH_WORKFLOW_INPUTS_MISSING')
    _,recipient=viewer.owner_key(directory)
    route=new_run('trial-route',date,sha,recipient)
    verify_route(route)
    protection=ensure_environment(identity['id'])
    run=new_run('trial-inspect' if args.command=='inspect' else 'trial',date,sha,recipient)
    session={'date':date,'sha':sha,'route_run_id':route['id'],'run_id':run['id'],'required_reviewers':protection['required_reviewers']}
    session_file.write_text(json.dumps(session,indent=2))
    if __import__('os').name=='posix': session_file.chmod(0o600)
    print('Создан защищённый trial: '+run['html_url'])
    print('На странице run: Review deployments → 387-news-v41-trial → Approve and deploy. Ничего не обходите и не нажимайте Bypass.')
    print('После trial_complete: python -m scripts.trial_control41 open')


if __name__=='__main__': main()
