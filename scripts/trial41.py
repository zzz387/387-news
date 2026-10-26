"""Explicitly approved Actions-only Gemini trial. No commit, Pages or plaintext upload."""
import argparse
import base64
from datetime import datetime,timedelta
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile
from urllib.request import Request,urlopen
import zipfile
try:
    from scripts import policy41 as p, editorial41, publication41, staged_news as stage, quota41, browser41,review_crypto41,trial_admission41,site_checks
except ImportError:
    import policy41 as p
    import editorial41
    import publication41
    import staged_news as stage
    import quota41
    import browser41
    import review_crypto41
    import trial_admission41
    import site_checks

CONFIRMATION='RUN_V41_TRIAL_WITH_GEMINI'
ENVIRONMENT='387-news-v41-trial'
MAGIC=b'387T41'; AAD=b'387-News-v41-Trial-Review-v1'


def guard(env=os.environ,inspect=False):
    if (env.get('GITHUB_ACTIONS')!='true' or env.get('GITHUB_EVENT_NAME')!='workflow_dispatch'
            or env.get('GITHUB_REF_NAME')!='codex/editorial-policy-v41'
            or env.get('GITHUB_ACTOR','').casefold()!=env.get('GITHUB_REPOSITORY_OWNER','').casefold()
            or not env.get('GITHUB_ACTOR')): raise RuntimeError('TRIAL_OWNER_ACTIONS_DISPATCH_REQUIRED')
    expected=env.get('TRIAL_APPROVED_SHA','')
    if not re.fullmatch('[0-9a-f]{40}',expected) or expected!=env.get('GITHUB_SHA'):
        raise RuntimeError('TRIAL_REVIEWED_COMMIT_REQUIRED')
    if not inspect and env.get('TRIAL_CONFIRMATION')!=CONFIRMATION:
        raise RuntimeError('TRIAL_SEPARATE_GEMINI_PERMISSION_REQUIRED')
    if env.get('TRIAL_PREVIEW')!='true': raise RuntimeError('TRIAL_PREVIEW_REQUIRED')


def protected_environment(get=None):
    if get is None:
        def get():
            url='https://api.github.com/repos/'+os.environ['GITHUB_REPOSITORY']+'/environments/'+ENVIRONMENT
            request=Request(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
                'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
            with urlopen(request,timeout=25) as response: return json.load(response)
    try: environment=get()
    except Exception as exc: raise RuntimeError('TRIAL_ENVIRONMENT_PROTECTION_UNVERIFIED') from None
    if not any(rule.get('type')=='required_reviewers' and rule.get('reviewers') for rule in environment.get('protection_rules',[])):
        raise RuntimeError('TRIAL_ENVIRONMENT_REVIEWER_REQUIRED')


def seal(data,key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce=secrets.token_bytes(12)
    return MAGIC+nonce+AESGCM(key).encrypt(nonce,data,AAD)


def unseal(blob,key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(MAGIC): raise ValueError('Invalid trial review bundle')
    return AESGCM(key).decrypt(blob[6:18],blob[18:],AAD)


def export(state,root,destination,browser=browser41.check):
    editorial41.validate_issue(state)
    selected=[r for r in state['candidates'] if r['id'] in state['selected_ids']]
    unicef=next((r for r in selected if r.get('test_id')=='unicef-21'),None)
    if (not unicef or unicef['url']!='https://www.unicef.org/parenting/child-care/21-learning-activities-babies-and-toddlers'
            or unicef['mode']!='INDEPENDENT_ARTICLE' or len(unicef['article'].get('activities',[]))!=21):
        raise p.Blocked('TRIAL_UNICEF_21_INCOMPLETE')
    if not any(r['mode']=='FULL_TRANSLATION' for r in selected): raise p.Blocked('TRIAL_LICENSED_TRANSLATION_REQUIRED')
    destination=Path(destination)
    if destination.resolve().is_relative_to(p.ROOT.resolve()): raise p.Blocked('TRIAL_EXPORT_MUST_BE_OUTSIDE_REPOSITORY')
    destination.mkdir(parents=True,exist_ok=True)
    for path in (Path(root)/'assets').rglob('*'):
        if path.is_symlink() or path.name.startswith('.') or path.suffix.lower() in ('.enc','.pem','.key','.env'):
            raise p.Blocked('TRIAL_UNSAFE_PUBLIC_ASSET')
    shutil.copytree(Path(root)/'assets',destination/'assets')
    (destination/'issues').mkdir(); (destination/'archive').mkdir()
    publication41.build(state,destination,preview=False)  # private temporary tree only
    report={'policy_version':p.VERSION,'article_count':len(selected),'gemini_usage':quota41.actual_usage(state),
            'source_urls':[r['url'] for r in selected],'checks':'all_required_gates_passed',
            'human_editorial_review':'pending; automatic gates do not prove literary quality',
            'articles':[{'title':r['article']['title'],'category':r['article']['category'],
                         'mode':r['mode'],'source_url':r['url'],'automatic_gates':{
                         name:bool(r['checks'].get(name,{}).get('approved')) for name in p.STAGES}}
                        for r in selected]}
    report['browser']=browser(destination,state['date'],destination/'screenshots')
    (destination/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--preflight',action='store_true'); parser.add_argument('--inspect',action='store_true')
    parser.add_argument('--route-only',action='store_true')
    args=parser.parse_args(); guard(inspect=args.inspect or args.route_only)
    if args.route_only:
        print('[trial-route] owner workflow_dispatch, branch, exact SHA and preview verified; no Secrets or Gemini used')
        return
    protected_environment()
    recipient=os.getenv('TRIAL_REVIEW_PUBLIC_KEY','').strip()
    if recipient: review_crypto41.public_key(recipient)
    date=os.environ['TARGET_DATE']; moment=datetime.strptime(date,'%Y-%m-%d').date()
    if args.preflight: print('[trial] protected owner approval and pinned commit verified'); return
    if moment<=datetime.now(p.TZ).date() and not Path(os.environ['NEWS_CHECKPOINT_FILE']).is_file():
        raise RuntimeError('TRIAL_NEW_RUN_REQUIRES_FUTURE_DATE')
    key=stage.validate_key(os.environ['DRAFT_ENCRYPTION_KEY'])
    if not args.inspect:
        production=None
        if os.getenv('NEWS_PRODUCTION_CHECKPOINT_EXPECTED')=='true':
            production=stage.decipher(Path(os.environ['NEWS_PRODUCTION_CHECKPOINT_FILE']).read_bytes(),key)
        ledger_path=Path(os.environ['NEWS_QUOTA_FILE'])
        if os.getenv('NEWS_QUOTA_EXPECTED')=='true' and not ledger_path.is_file(): raise RuntimeError('SHARED_LEDGER_RESTORE_FAILED')
        ledger=json.loads(ledger_path.read_text()) if ledger_path.is_file() else {}
        admitted,reason=trial_admission41.assess(p.ROOT,production,ledger)
        if admitted:
            try: site_checks.check_site(expected_date=datetime.now(p.TZ).date().isoformat())
            except Exception: admitted,reason=False,'CURRENT_PRODUCTION_HTTPS_UNVERIFIED'
        if not admitted:
            print('[trial-admission] deferred code='+reason+'; Gemini requests=0')
            with open(os.environ['GITHUB_OUTPUT'],'a') as output: output.write('trial_deferred='+reason+'\n')
            return
    # Always force preview. The normal official restoration, budget and persistence paths remain authoritative.
    if not args.inspect:
        previous=sys.argv
        previous_root=stage.ROOT; previous_news=stage.news.ROOT
        with tempfile.TemporaryDirectory(prefix='387-trial-worktree-') as temp:
            working=Path(temp)
            shutil.copytree(p.ROOT/'assets',working/'assets')
            (working/'issues').mkdir(); (working/'archive').mkdir()
            for issue in (p.ROOT/'issues').iterdir():
                if issue.is_dir() and issue.name!=date: shutil.copytree(issue,working/'issues'/issue.name)
            try:
                stage.ROOT=stage.news.ROOT=working
                sys.argv=['staged_news','--phase','run','--preview','--target-date',date]
                stage.main()
            finally:
                sys.argv=previous; stage.ROOT=previous_root; stage.news.ROOT=previous_news
    file=stage.ARTIFACT_FILE if stage.ARTIFACT_FILE.is_file() else Path(os.environ['NEWS_CHECKPOINT_FILE'])
    state=stage.decipher(file.read_bytes(),key)
    if state.get('date')!=date or state.get('preview') is not True or state.get('branch')!='codex/editorial-policy-v41':
        raise RuntimeError('TRIAL_CHECKPOINT_PROVENANCE_INVALID')
    if not state.get('audit_passed'):
        print('[trial] incomplete; encrypted checkpoint retained; resume with the same date after quota/cooldown')
        return
    def retain():
        stage.save(state,key)
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('checkpoint=true\nartifact_name='+stage.artifact_label(date,True)+'\n')
    # Recheck originals after all writing/reviews; loss/change replaces only the affected candidate.
    editorial41.verify_publication_sources(state,persist=retain)
    with tempfile.TemporaryDirectory(prefix='387-private-trial-') as temp:
        report=export(state,p.ROOT,Path(temp)/'site')
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in (Path(temp)/'site').rglob('*'):
                if path.is_file(): archive.write(path,path.relative_to(Path(temp)/'site'))
        destination=Path(os.environ['RUNNER_TEMP'])/'trial-review.enc'
        destination.write_bytes(seal(buffer.getvalue(),key)); destination.chmod(0o600)
        if recipient:
            owner_file=Path(os.environ['RUNNER_TEMP'])/'owner-review.enc'
            owner_file.write_bytes(review_crypto41.seal(buffer.getvalue(),recipient,date,os.environ['GITHUB_SHA'])); owner_file.chmod(0o600)
            with open(os.environ['GITHUB_OUTPUT'],'a') as output: output.write('owner_review_ready=true\n')
        print('[trial] complete: 12 reviewed articles, desktop/mobile checks; encrypted review bundle retained; no publication')
        print('[trial-metrics] '+json.dumps(report['gemini_usage']))
        with open(os.environ['GITHUB_OUTPUT'],'a') as output: output.write('trial_complete=true\n')


if __name__=='__main__': main()
