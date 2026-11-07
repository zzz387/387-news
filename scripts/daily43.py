"""Small daily controller using existing encryption, quota, mutex and Pages delivery."""
import copy,json,os,time
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
            state['candidates'].append(dict(item,id=p.digest(item['url']),status='discovered',checks={},progress={},history=[],discovered_at=datetime.now(p.TZ).isoformat()));known.add(item['url'])


def preparation_order(state,limit=None,exclude_ids=()):
    try:from scripts import selection43
    except ImportError:import selection43
    return selection43.order(state,state.get('_recent43',[]),limit=limit,exclude_ids=exclude_ids)


def advance(state,date,preview,ops,persist=lambda:None,now=None,check_public=None,editor=None,delivery_only=False):
    try:from scripts import selection43,catalog43,light43,priorities43
    except ImportError:import selection43,catalog43,light43,priorities43
    from scripts import stock43
    clock=(lambda:now) if now is not None else pipeline.now_moscow
    save=persist
    def persist():
        state['publication_status']=pipeline.delivery_state(state,clock());save()
    current=clock();root=Path(ops.ROOT)
    if any(path.name>date for path in (root/'issues').glob('*') if path.is_dir() and len(path.name)==10) and not (root/'issues'/date/'index.html').is_file():
        pipeline.status(state,'DEFERRED','preserve_old_checkpoint','SUPERSEDED_UNFINISHED_DATE');persist();return False
    if (root/'issues'/date/'index.html').is_file():
        ready=pipeline.published_delivery(state,date,ops,preview,current,check_public or pipeline.site_checks.check_site);persist();return ready
    release=datetime.fromisoformat(date+'T06:00').replace(tzinfo=p.TZ)
    budget=news.runtime.ACTIVE_BUDGET
    minimum=e.CONFIG['minimum_articles']
    stock43.restore_backlog(state,root)
    stock43.balance(state,root,current)
    stock43.draw(state,root,current)
    state['_recent_light43']=light43.recent(root)
    stock43.draw_light(state,root)
    due=current>=release-timedelta(minutes=10)
    short=len(selection43.composition(state))<minimum
    if short:
        state['audit_passed']=False
        pipeline.status(state,'PREPARING','continue_until_minimum','MINIMUM_ARTICLES_NOT_MET')
    # Delivery has first claim on every due window; never wait for more model work.
    if not delivery_only and (not due or short):
        if budget and not due:budget.deadline=min(budget.deadline,time.monotonic()+max(0,(release-clock()).total_seconds()-600))
        state['_recent43']=selection43.recent(root,date)
        priorities43.apply_rules(state,clock())
        discover(state)
        if os.getenv('NEWS_CATALOG_REFRESH')=='true' and (short or clock()<release-timedelta(minutes=25)):
            try:catalog43.refresh(state,clock(),shortage=short)
            except Exception as exc:print('[catalog43] '+json.dumps({'code':type(exc).__name__,'optional':True}),flush=True)
        priorities43.apply_rules(state,clock())
        priorities43.reconsider_evidence(state)
        persist();injected_editor=editor is not None;editor=editor or e.Editor(persist=persist)
        prior={r.get('source_url') for r in editorial41.archive_entries(root)}|set(stock43.ensure(state)['published_urls'])
        def prepare_light():
            if os.getenv('NEWS_LIGHT_NEWS_ENABLED')!='true' or clock()>=release-timedelta(minutes=10) or not budget:return
            keep=max(4,2*max(0,minimum-len(selection43.composition(state))))
            if budget.remaining_requests()>=keep+2:
                light43.prepare(state,persist)
                stock43.bank_light(state,clock())
        prepare_light()
        attempted_ids=set();extra_searches=0
        while True:
            stock43.balance(state,root,clock())
            banking=len(selection43.composition(state))>=e.CONFIG['article_target']
            main_groups={g:sum(priorities43.classify(r)['group']==g for r in selection43.composition(state)) for g in ('A','C')}
            coverage_pending=[r for r in state['candidates'] if r.get('status') in ('discovered','preparing','retryable_error') and main_groups.get(priorities43.classify(r)['group'],2)<2 and not r.get('for_light_only')]
            coverage_needed=banking and bool(coverage_pending)
            plan_state=state
            if coverage_needed:
                # Missing personal streams take the preparation window before
                # unrelated unfinished stock, even when that stock is full.
                plan_state=dict(state,candidates=selection43.composition(state)+coverage_pending)
            elif banking:
                # Inventory needs its own topic balance, not the already full
                # edition's nine personal places followed by optional science.
                pending=[r for r in state['candidates'] if r.get('status') in ('discovered','preparing','retryable_error') and not e.high_risk(r)]
                plan_state=dict(state,candidates=stock43.available(state,date)+pending,_stock_preparation43=True)
            record=next(iter(preparation_order(plan_state,limit=1,exclude_ids=attempted_ids)),None)
            if record is None:
                needs_supply=(len(selection43.composition(state))<e.CONFIG['article_target'] or len(stock43.available(state,date))<e.CONFIG.get('article_stock_target',20))
                if needs_supply and extra_searches<2 and os.getenv('NEWS_CATALOG_REFRESH')=='true' and budget and budget.can_request():
                    extra_searches+=1
                    try:catalog43.refresh(state,clock(),shortage=True)
                    except Exception as exc:print('[catalog43] '+json.dumps({'code':type(exc).__name__,'optional':True}),flush=True)
                    priorities43.apply_rules(state,clock());priorities43.reconsider_evidence(state);persist();continue
                break
            attempted_ids.add(record['id'])
            count=len(selection43.composition(state))
            banking=count>=e.CONFIG['article_target'] and main_groups.get(priorities43.classify(record)['group'],2)>=2
            if due and count>=minimum:break
            if banking and len(stock43.available(state,date))>=e.CONFIG.get('article_stock_target',20):break
            if (not due and clock()>=release-timedelta(minutes=10)) or not budget or not budget.can_request():break
            if not os.getenv('GEMINI_API_KEY') and not injected_editor:break
            if record.get('status') not in ('discovered','preparing','retryable_error'):continue
            if record['url'] in prior:record['status']='deferred';persist();continue
            if any(selection43.duplicate(record,r) for r in selection43.composition(state)+(stock43.available(state,date) if banking else [])):
                record['status']='topic_duplicate';record['history'].append({'code':'STORY_DUPLICATE_BEFORE_WRITING'});persist();continue
            print('[candidate-priority43] '+json.dumps({'id':record['id'],'group':priorities43.classify(record)['group'],'coverage_needed':coverage_needed,'operation':'review' if record.get('article') else 'write','risk_codes':e.risk_codes(record)}),flush=True)
            record['status']='preparing';persist()
            try:
                if isinstance(editor,e.Editor):
                    editor.state=state;editor.usage_record=record;priorities43.attach_evidence(record,state);editor.verify_source(record)
                    if banking and e.high_risk(record):
                        record['status']='discovered';persist();continue
                    if any(selection43.duplicate(record,r) for r in selection43.composition(state)+(stock43.available(state,date) if banking else [])):
                        record['status']='topic_duplicate';record['history'].append({'code':'STORY_DUPLICATE_AFTER_SOURCE'});persist();continue
                editor.finish(state,record)
                if banking:stock43.bank(state,record,clock())
                peers=[r for r in e.select_ready(state) if r is not record and selection43.duplicate(record,r)]
                if peers and not any(h.get('code')=='STORY_DUPLICATE_AFTER_WRITING' for h in record['history']):
                    record['history'].append({'code':'STORY_DUPLICATE_AFTER_WRITING','peer_ids':[r['id'] for r in peers]})
            except news.runtime.GenerationPaused:
                record['status']='preparing';persist();break
            except Exception as exc:
                failures=record['progress'].get('v43_external_failures',0)+1
                record['progress']['v43_external_failures']=failures
                record['history'].append({'code':getattr(exc,'code',type(exc).__name__),'stage':'v43_final'})
                record['status']='deferred' if isinstance(exc,p.Blocked) or failures>=2 else 'retryable_error'
                print('[candidate43] '+json.dumps({'id':record['id'],'status':record['status'],'code':getattr(exc,'code',type(exc).__name__)}),flush=True)
            persist()
        prepare_light()
    stock43.draw(state,root,clock())
    stock43.balance(state,root,clock())
    selected=selection43.composition(state)
    state['title_style43']=selection43.title_report(selected)
    state['selection43']={'selected':[r['id'] for r in selected],'excluded_duplicate_ids':[r['id'] for r in e.select_ready(state) if any(selection43.duplicate(r,chosen) for chosen in selected) and r not in selected]}
    try:
        state['editorial_report43']=priorities43.report(state,selected,selection43.recent(root,date))
        report=state['editorial_report43']
        print('[topic-coverage43] '+json.dumps({k:report[k] for k in ('prepared_main_articles','core_groups','missing_core_groups','excluded_duplicate_stories')}) ,flush=True)
    except Exception as exc:print('[editorial-report43] '+json.dumps({'code':type(exc).__name__,'optional':True}),flush=True)
    state['selected_ids']=[r['id'] for r in selected]
    state['articles']={r['id']:r['article'] for r in selected}
    stock43.sync_backlog(state)
    state['stock_report43']=stock43.report(state)
    print('[editorial-stock43] '+json.dumps(state['stock_report43']),flush=True)
    if len(selected)<minimum:
        state['audit_passed']=False;state['issue_kind']='preparing';state['reserve_count']=0;state['public_article_count']=0
        pipeline.status(state,'PREPARING','continue_until_minimum','MINIMUM_ARTICLES_NOT_MET');persist();return False
    reserve=[] if selected else reserve_rows(state,clock())
    state['issue_kind']='articles' if selected else 'source_digest'
    state['reserve_count']=len(reserve)
    state['public_article_count']=len(selected);persist()
    if not selected and not reserve:
        pipeline.status(state,'BLOCKED','refresh_verified_reserve','NO_SAFE_RESERVE');persist();return False
    if clock()<release-timedelta(minutes=10) and not preview:
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


def deliver(state,date,preview,ops,persist=lambda:None,now=None,check_public=None):
    """Restore/validate/assemble existing work only. No discovery, writing or Gemini."""
    return advance(state,date,preview,ops,persist,now,check_public,delivery_only=True)
