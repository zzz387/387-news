"""Small daily controller using existing encryption, quota, mutex and Pages delivery."""
import copy,json,os
from datetime import datetime,timedelta
from pathlib import Path
try:
    from scripts import policy41 as p,editorial43 as e,publication43,news,pipeline,source41,rights41,editorial41
except ImportError:
    import policy41 as p,editorial43 as e,publication43,news,pipeline,source41,rights41,editorial41


def enabled():return e.CONFIG.get('enabled') is True


def reserve_catalog():
    return json.loads((p.ROOT/'config/fallback-sources43.json').read_text())['sources']


def reserve_rows(state,now,fetch=None,refresh=False):
    """Only public bibliographic metadata. Cached checks are explicitly dated, not news."""
    rows=[];refresh_attempts=0
    catalog=reserve_catalog()
    cache=state.setdefault('source_digest_cache',{})
    if fetch is None:
        from scripts.public_sources41 import Session
        fetch=Session().fetch
    for entry in catalog:
        row=copy.deepcopy(cache.get(entry['url'],entry))
        try:
            checked=datetime.fromisoformat(row['checked_at']);age=now-checked.astimezone(p.TZ)
            if refresh:raise ValueError('refresh')
            if not timedelta(0)<=age<=timedelta(days=e.CONFIG['reserve_max_age_days']):raise ValueError('expired')
            source41.safe_url(row['url'])
            if not all(row.get(k) for k in ('title','publisher','content_hash')):raise ValueError('metadata')
        except (ValueError,KeyError,TypeError):
            if refresh_attempts>=8:break
            refresh_attempts+=1
            try:
                source=fetch(entry['url'])
                if rights41.decision(source,'INDEPENDENT_ARTICLE')['status']!='allowed':continue
                row={k:source.get(k,'') for k in ('url','title','publisher','published','content_hash')}
                row['checked_at']=source['access_checked_at'];cache[row['url']]=copy.deepcopy(row)
            except Exception as exc:
                print('[reserve43] '+json.dumps({'code':getattr(exc,'code',type(exc).__name__),'usable':False}),flush=True);continue
        rows.append(row)
        if len(rows)>=8:break  # digest display size, never a minimum article count
    return rows


def discover(state):
    known={r['url'] for r in state['candidates']}
    for item in json.loads((p.ROOT/'config/candidates.json').read_text()).get('candidates',[]):
        if item['url'] not in known:
            state['candidates'].append(dict(item,id=p.digest(item['url']),status='discovered',checks={},progress={},history=[]));known.add(item['url'])


def advance(state,date,preview,ops,persist=lambda:None,now=None,check_public=None,editor=None):
    clock=(lambda:now) if now is not None else pipeline.now_moscow
    current=clock();root=Path(ops.ROOT)
    if date<current.date().isoformat() and not (root/'issues'/date/'index.html').is_file():
        pipeline.status(state,'DEFERRED','preserve_old_checkpoint','SUPERSEDED_UNFINISHED_DATE');persist();return False
    if (root/'issues'/date/'index.html').is_file():
        ready=pipeline.published_delivery(state,date,ops,preview,current,check_public or pipeline.site_checks.check_site);persist();return ready
    release=datetime.fromisoformat(date+'T06:00').replace(tzinfo=p.TZ)
    budget=news.runtime.ACTIVE_BUDGET
    # Delivery has first claim on every due window; never wait for more model work.
    if current<release:
        discover(state);persist();injected_editor=editor is not None;editor=editor or e.Editor(persist=persist)
        prior={r.get('source_url') for r in editorial41.archive_entries(root)}
        for record in state['candidates']:
            if len(e.select_ready(state))>=e.CONFIG['article_target']:break
            if clock()>=release or not budget or not budget.can_request():break
            if not os.getenv('GEMINI_API_KEY') and not injected_editor:break
            if record.get('status') not in ('discovered','preparing','retryable_error'):continue
            if record['url'] in prior:record['status']='deferred';persist();continue
            record['status']='preparing';persist()
            try:editor.finish(state,record)
            except news.runtime.GenerationPaused:
                record['status']='preparing';persist();break
            except Exception as exc:
                failures=record['progress'].get('v43_external_failures',0)+1
                record['progress']['v43_external_failures']=failures
                record['history'].append({'code':getattr(exc,'code',type(exc).__name__),'stage':'v43_final'})
                record['status']='deferred' if isinstance(exc,p.Blocked) or failures>=2 else 'retryable_error'
                print('[candidate43] '+json.dumps({'id':record['id'],'status':record['status'],'code':getattr(exc,'code',type(exc).__name__)}),flush=True)
            persist()
    selected=e.select_ready(state);state['selected_ids']=[r['id'] for r in selected]
    state['articles']={r['id']:r['article'] for r in selected}
    reserve=[] if selected else reserve_rows(state,clock())
    state['issue_kind']='articles' if selected else 'source_digest'
    state['reserve_count']=len(reserve)
    state['public_article_count']=len(selected);persist()
    if not selected and not reserve:
        pipeline.status(state,'BLOCKED','refresh_verified_reserve','NO_SAFE_RESERVE');persist();return False
    if clock()<release and not preview:
        pipeline.status(state,'APPROVED','publish_when_due');state['audit_passed']=True;persist();return False
    if preview:
        publication43.build(state,root,reserve,preview=True)
        pipeline.status(state,'APPROVED','preview_complete');persist();return False
    state['audit_passed']=True
    if not pipeline.reserve_delivery(state,clock()):persist();return False
    publication43.build(state,root,reserve)
    pipeline.status(state,'PUBLISHING','commit_and_deploy');persist();return True


def check_reserve():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--check-reserve',action='store_true',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    rows=reserve_rows({},datetime.now(p.TZ),refresh=True)
    if not rows:raise RuntimeError('NO_CHECKED_PUBLIC_RESERVE')
    report={'policy_version':'4.3','gemini_requests':0,'sources':rows,'checked_at':datetime.now(p.TZ).isoformat()}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('[reserve43-public-check] '+json.dumps(report,ensure_ascii=False))


if __name__=='__main__':check_reserve()
