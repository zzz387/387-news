"""State-driven daily production. A cron is a wake-up, never a stage command."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
try:
    from scripts import audit_policy, editorial31 as editorial, news, site_checks, policy41
except ImportError:
    import audit_policy
    import editorial31 as editorial
    import news
    import site_checks
    import policy41

WAKE_TIMES=('00:17','01:17','03:17','04:17','05:17','05:54','06:17','06:37','06:54',
            '07:15','07:30','08:15','12:17','14:17','16:17','18:17','20:17','22:17')
MAX_DELIVERY_ATTEMPTS=3


def now_moscow():
    return datetime.now(news.TZ)


def next_wake(now):
    candidates=[]
    for offset in (0,1):
        day=now.date()+timedelta(days=offset)
        for clock in WAKE_TIMES:
            value=datetime.fromisoformat(f'{day}T{clock}:00').replace(tzinfo=news.TZ)
            if value>now: candidates.append(value)
    return min(candidates).isoformat()


def status(state, name, action, reason=None):
    state.update(pipeline_status=name,next_action=action)
    if reason: state['block_code']=reason
    else: state.pop('block_code',None)


def capacity():
    budget=news.runtime.ACTIVE_BUDGET
    return budget is None or budget.can_request()


def pause(state, ready=False):
    budget=news.runtime.ACTIVE_BUDGET
    code='TIME_OR_RUN_BUDGET'
    if budget and budget.ledger.get('day')==datetime.now(timezone.utc).date().isoformat() and budget.ledger.get('requests',0)>=budget.day_limit:
        code='DAILY_QUOTA'
    status(state,'READY_FOR_AUDIT' if ready else 'RETRY_PENDING','resume_after_budget',code)


def validate_ready(state, require_review=False):
    if state.get('version')==41:
        try: from scripts import editorial41
        except ImportError: import editorial41
        return editorial41.validate_issue(state)
    """Unchanged form/factual provenance gates, without an API request."""
    if len(state.get('plan',[]))!=8 or set(state.get('articles',{}))!={str(i) for i in range(8)}:
        raise ValueError('Incomplete issue')
    categories=[a['category'] for a in state['articles'].values()]
    if not editorial.LIFE.issubset(set(categories)) or sum(c in editorial.LIFE for c in categories)<4:
        raise ValueError('Mandatory rubric balance')
    lookup={s['id']:s for s in state['sources']}
    total=0
    for i,plan in enumerate(state['plan']):
        article=state['articles'][str(i)]
        total+=editorial.article_form(article,plan)
        if (article['category']!=plan['category'] or article['kind']!=plan['kind']
                or article['source_ids']!=plan['source_ids'] or article.get('long')!=bool(plan['long'])):
            raise ValueError('Reviewed commission mismatch')
        if require_review and article.get('_review_scope')!='title_teaser_body_v1':
            raise ValueError('Missing full factual review')
        claims=state.get('dossiers',{}).get(str(i),{}).get('claims',[])
        if len(claims)<(8 if plan['long'] else 5):
            raise ValueError('Incomplete evidence dossier')
        for claim in claims:
            sid=claim['source_id']
            if (sid not in article['source_ids'] or sid not in lookup or not claim.get('quote','').strip()
                    or editorial.normalized(claim['quote']) not in editorial.normalized(lookup[sid].get('evidence',''))):
                raise ValueError('Source quotation mismatch')
    if not 2<=sum(bool(p['long']) for p in state['plan'])<=3 or total<editorial.TARGET_TOTAL:
        raise ValueError('Issue volume gate')
    return total


def published_delivery(state, date, ops, preview, now, check_public):
    metadata=site_checks.validate_local_release(ops.ROOT,date)
    state['public_article_count']=metadata.get('article_count',metadata.get('count',len(metadata.get('articles',[]))))
    if preview:
        status(state,'APPROVED','preview_archive_validated')
        return False
    try:
        check_public(expected_date=date)
    except Exception:
        return reserve_delivery(state,now)
    status(state,'PUBLISHED','none')
    state['delivery_verified_at']=now.isoformat()
    return False


def reserve_delivery(state, now):
    if os.getenv('GITHUB_REF_NAME','main')!='main' or os.getenv('NEWS_RELEASE_APPROVED','').lower()!='true':
        status(state,'BLOCKED','enable_release','RELEASE_DISABLED')
        return False
    if state.get('delivery_attempts',0)>=MAX_DELIVERY_ATTEMPTS:
        status(state,'BLOCKED','inspect_pages_incident','DELIVERY_RETRY_LIMIT')
        return False
    retry=state.get('delivery_retry_after')
    if retry and now<datetime.fromisoformat(retry):
        status(state,'RETRY_PENDING','retry_delivery','DELIVERY_COOLDOWN')
        return False
    # Reserve before commit/deploy; interruptions must not create infinite retries.
    state['delivery_attempts']=state.get('delivery_attempts',0)+1
    state['delivery_retry_after']=(now+timedelta(minutes=10)).isoformat()
    status(state,'PUBLISHING','commit_and_deploy')
    return True


def advance(state, date, preview, ops, persist=lambda:None, now=None, check_public=None):
    if state.get('version')==41:
        try: from scripts import editorial41
        except ImportError: import editorial41
        return editorial41.advance(state,date,preview,ops,persist,now,check_public)
    clock=now_moscow if now is None else lambda: now
    now=clock()
    check_public=check_public or site_checks.check_site
    release=datetime.fromisoformat(date+'T06:00:00').replace(tzinfo=news.TZ)
    if (ops.ROOT/'issues'/date/'issue.json').is_file():
        ready=published_delivery(state,date,ops,preview,now,check_public)
        persist()
        return ready
    for _ in range(10):
        now=clock()  # Generation may cross 06:00; use completion time, not start time.
        if state.get('audit_blocked'):
            status(state,'BLOCKED','review_editorial_diagnosis','EDITORIAL_HOLD'); break
        if state.get('audit_passed'):
            try:
                validate_ready(state,require_review=True)
            except (ValueError,KeyError,TypeError):
                status(state,'BLOCKED','review_checkpoint_integrity','EVIDENCE_INTEGRITY'); break
            signature=audit_policy.fingerprint(state)
            if state.get('validated_html_signature')!=signature:
                ops.render(state,True)  # ephemeral private HTML; no public early files
                state['validated_html_signature']=signature
                persist()
            now=clock()
            if preview:
                status(state,'APPROVED','preview_complete'); break
            if now<release:
                remaining=(release-now).total_seconds()
                budget=news.runtime.ACTIVE_BUDGET
                can_wait=remaining<=600 and (budget is None or budget.remaining_seconds()>remaining+90)
                if not can_wait:
                    status(state,'WAITING_FOR_RELEASE_TIME','publish_at_release'); break
                # The existing render gate waits; no public file exists before 06:00.
            if os.getenv('GITHUB_REF_NAME','main')!='main' or os.getenv('NEWS_RELEASE_APPROVED','').lower()!='true':
                status(state,'BLOCKED','enable_release','RELEASE_DISABLED'); break
            if not reserve_delivery(state,max(now,release)): break
            persist()
            ready=ops.render(state,False)
            persist()
            return ready
        if not state.get('plan'):
            if not capacity(): pause(state); break
            status(state,'PLANNING','research')
            ops.build_plan(state,date); persist(); continue
        missing=[str(i) for i in range(8) if str(i) not in state.get('dossiers',{})
                 and str(i) not in state.get('rejected',{})]
        if missing:
            if not capacity(): pause(state); break
            status(state,'RESEARCHING','write')
            ops.research_batch(state,size=2); persist(); continue
        if len(state.get('articles',{}))<8 or state.get('audit_repairs'):
            if not capacity(): pause(state); break
            before=audit_policy.fingerprint(state)
            status(state,'AUDIT_REPAIR' if state.get('audit_repairs') else 'WRITING','audit_when_complete')
            ops.write_batch(state,size=2); persist()
            if state.get('audit_blocked'): continue
            if len(state.get('articles',{}))<8 or state.get('audit_repairs'):
                if audit_policy.fingerprint(state)==before:
                    status(state,'RETRY_PENDING','continue_saved_writing','INCOMPLETE_WRITING'); break
                continue
        status(state,'READY_FOR_AUDIT','audit'); persist()
        try:
            validate_ready(state)
        except (ValueError,KeyError,TypeError):
            status(state,'BLOCKED','review_checkpoint_integrity','EVIDENCE_INTEGRITY'); break
        if not capacity(): pause(state,ready=True); break
        status(state,'AUDIT_IN_PROGRESS','inspect_audit_result'); persist()
        ops.audit(state); persist()
        if not state.get('audit_passed') and not state.get('audit_repairs') and not state.get('audit_blocked'):
            status(state,'RETRY_PENDING','retry_audit','AUDIT_EXTERNAL_ERROR'); break
    else:
        status(state,'RETRY_PENDING','continue_saved_progress','RUN_STEP_LIMIT')
    persist()
    return False


def article_target(state):
    if state.get('version')==43:
        try:from scripts import editorial43
        except ImportError:import editorial43
        return editorial43.CONFIG['article_target']
    return policy41.ARTICLE_COUNT if state.get('version')==41 else 8


def report(state,ledger,now=None):
    now=now or now_moscow()
    segments=sum(len(d.get(k,{}).get('parts',[])) for d in state.get('dossiers',{}).values()
                 for k in ('_longform_progress','_shortform_progress'))
    if state.get('version')==41:
        segments=sum(len(r.get('progress',{}).get('translated',{}))+len(r.get('progress',{}).get('sections',{})) for r in state.get('candidates',[]))
    retry=next_wake(now)
    if state.get('block_code')=='DAILY_QUOTA':
        tomorrow_utc=datetime.combine(datetime.now(timezone.utc).date()+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)
        retry=next_wake(tomorrow_utc.astimezone(news.TZ))
    ready_count=sum(r.get('status')=='ready' for r in state.get('candidates',[])) if state.get('version') in (41,43) else len(state.get('articles',{}))
    return dict(date=state['date'],policy_version=state.get('policy_version','3.2'),
                issue_kind=state.get('issue_kind','articles'),reserve_links=state.get('reserve_count',0),
                article_target=article_target(state),articles=max(ready_count,state.get('public_article_count',0)),
                segments=segments,dossiers=len(state.get('dossiers',{})),audit_passed=bool(state.get('audit_passed')),
                quota_day=ledger.get('day'),requests_used=ledger.get('requests',0),
                requests_used_today=ledger.get('requests',0) if ledger.get('day')==datetime.now(timezone.utc).date().isoformat() else 0,
                day_limit=news.runtime.ACTIVE_BUDGET.day_limit if news.runtime.ACTIVE_BUDGET else int(os.getenv('NEWS_MAX_REQUESTS_PER_DAY','220')),
                run_used=news.runtime.ACTIVE_BUDGET.used if news.runtime.ACTIVE_BUDGET else 0,
                stage=state.get('pipeline_status','RETRY_PENDING'),next_action=state.get('next_action','resume'),
                next_attempt=retry,release_at=state['date']+'T'+policy41.RELEASE_TIME+':00+03:00',
                publication_verified=state.get('pipeline_status')=='PUBLISHED',
                block_code=state.get('block_code'),delivery_attempts=state.get('delivery_attempts',0))


def emit_report(state,ledger,output=None):
    value=report(state,ledger)
    encoded=json.dumps(value,ensure_ascii=False)
    print('[pipeline-status] '+encoded,flush=True)
    if output:
        with open(output,'a') as stream:
            stream.write('pipeline_status='+encoded+'\n')
    summary=os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a') as stream:
            stream.write('### Editorial pipeline\n\n```json\n'+json.dumps(value,ensure_ascii=False,indent=2)+'\n```\n')
            stream.write('\nA successful checkpoint stage is not proof of publication. HTTPS monitoring reports delivery separately.\n')
    return value
