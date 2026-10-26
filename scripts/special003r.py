"""003-R production, isolated ciphertext and shared quota; daily production first."""
import argparse
import copy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import re
import signal
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote,urlparse,urljoin
try:
    from scripts import special_contract41 as sc,special_publication41 as publication,policy41 as p
    from scripts import editorial41 as e,rights41,source41,staged_news as stage,news,quota41,release_queue,site_checks
except ImportError:
    import special_contract41 as sc
    import special_publication41 as publication
    import policy41 as p
    import editorial41 as e
    import rights41,source41,staged_news as stage,news,quota41,release_queue,site_checks

LABEL='387news41-special-003-r'


def new_state():
    state=e.new_state(datetime.now(p.TZ).date().isoformat())
    state['special_edition']={'id':sc.ID,'definition_hash':p.digest(sc.definition())}
    state.update(branch='main',preview=False,discovered=True)
    for slot in sc.definition()['slots']:
        state['candidates'].append({'id':'003-R-'+str(slot['slot']),'special_slot':slot['slot'],
            'url':slot['url'],'original_urls':slot['original_urls'],'category_hint':slot['category'],
            'verification_urls':slot['verification_urls'],'status':'discovered','checks':{},'progress':{},
            'commission':{'original_topic':slot['original_title'],'category':slot['category'],
                'requirements':slot['requirements'],'kind':'Внеочередное переиздание; события26октября не выдавать за новые; контекст только по подтверждённым источникам.'}})
    return state


def admit(root,daily,ledger,now=None):
    now=(now or datetime.now(p.TZ)).astimezone(p.TZ)
    if not 12<=now.hour<22:return False,'OUTSIDE_SPARE_DAYTIME_WINDOW'
    today=now.date().isoformat();upcoming=(now.date()+timedelta(days=1)).isoformat()
    if not release_queue.edition_exists(root,today):return False,'CURRENT_DAILY_NOT_PUBLISHED'
    if (not daily or daily.get('version')!=41 or daily.get('date')!=upcoming or daily.get('branch')!='main'
            or daily.get('preview') is not False or not daily.get('audit_passed')):return False,'DAILY_NOT_READY'
    try:e.validate_issue(daily)
    except (p.Blocked,KeyError,TypeError):return False,'DAILY_APPROVAL_NOT_VALID'
    if ledger.get('day')!=now.astimezone(timezone.utc).date().isoformat() or type(ledger.get('requests')) is not int:
        return False,'CURRENT_SHARED_LEDGER_REQUIRED'
    if ledger['requests']<0 or 220-ledger['requests']<sc.definition()['minimum_spare_requests']:
        return False,'NO_SPARE_QUOTA_WITH_DAILY_RESERVE'
    if any(until>now.timestamp() for until in ledger.get('cooldowns',{}).values()):return False,'GEMINI_COOLDOWN'
    try:from scripts import pipeline
    except ImportError:import pipeline
    if (datetime.fromisoformat(pipeline.next_wake(now))-now).total_seconds()<720:return False,'DAILY_WINDOW_TOO_CLOSE'
    return True,'DAILY_APPROVED_AND_SPARE_QUOTA'


def remaining_run_limit(daily_used,ledger):
    if type(daily_used) is not int or not 0<=daily_used<=24:raise RuntimeError('DAILY_RUN_ACCOUNTING_INVALID')
    return max(0,min(24-daily_used,220-ledger.get('requests',220)-sc.definition()['daily_reserve_requests']))


def study_links(source):
    result=[]
    for block in source['blocks']:
        for url in block.get('links',[]):
            host=(urlparse(url).hostname or '').lower()
            if host in ('doi.org','pubmed.ncbi.nlm.nih.gov','pmc.ncbi.nlm.nih.gov') and url.startswith('https://') and url not in result:
                result.append(url)
    if not result and (urlparse(source['url']).hostname or '').endswith('sciencedaily.com'):
        # Journal references may sit outside the article's prose region. Read the already
        # robots-verified public original, never a search snippet or an abstract fallback.
        from html.parser import HTMLParser
        class References(HTMLParser):
            def handle_starttag(self,tag,attrs):
                href=dict(attrs).get('href','')
                url=urljoin(source['url'],href);host=(urlparse(url).hostname or '').lower()
                if tag=='a' and host in ('doi.org','pubmed.ncbi.nlm.nih.gov','pmc.ncbi.nlm.nih.gov') and url not in result:
                    result.append(url)
        parser=References();parser.feed(source41.transport(source['url']))
    return result[:4]  # bounded discovery, never a substitute for full study verification


def probe():
    config=sc.definition();urls=list(dict.fromkeys(u for slot in config['slots'] for u in slot['original_urls']))
    def inspect(url):
        try:
            source=source41.fetch(url);mode,decision=rights41.select_mode(source)
            rights41.require(source,mode,decision)
            return {'url':url,'status':'eligible','mode':mode,'rights':decision['status'],
                'verification':decision.get('verification'),'content_hash':source['content_hash'],
                'metadata_status':source['metadata_status'],'study_urls':study_links(source)}
        except Exception as exc:
            row={'url':url,'status':'blocked','code':getattr(exc,'code',None) if isinstance(exc,p.Blocked) else type(exc).__name__}
            if 'source' in locals():
                try:
                    row['metadata']={key:source.get(key) for key in ('title','canonical','language','author','published','publisher','metadata_gaps','metadata_status','extraction_method')}
                    row['study_urls']=study_links(source)
                    if source.get('metadata_status')!='verified':
                        try:from scripts import source_dom41 as dom
                        except ImportError:import source_dom41 as dom
                        document=dom.Document();document.feed(source41.transport(url));document.close()
                        meta=dom.metadata(document)
                        row['public_metadata_candidates']={key:value for key,value in meta.items()
                            if any(part in key.lower() for part in ('language','lang','locale','date','author','creator','modified','pubdate'))
                            and isinstance(value,str)}
                except Exception as diagnostic:row['diagnostic_error']=type(diagnostic).__name__
            return row
    with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(inspect,urls))
    by_url={r['url']:r for r in rows}
    report={'id':sc.ID,'gemini_requests':0,'checked_at':datetime.now(p.TZ).isoformat(),'sources':rows,
        'articles':[{'slot':s['slot'],'topic':s['original_title'],'original_urls':s['original_urls'],
                     'status':'sources_ready' if all(by_url[u]['status']=='eligible' for u in s['original_urls']) else 'source_hold',
                     'generation':'not_started'} for s in config['slots']]}
    print('[special-sources] '+json.dumps(report,ensure_ascii=False))
    Path(os.environ.get('SPECIAL_SOURCE_REPORT','/tmp/special-source-report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


class Editor(e.Editor):
    def source_verified(self,state,record):
        # Resolve full originals, rights and studies before spending a single model request.
        if not record.get('source'):record['source']=self.cached_fetch(record['url']);self.persist()
        mode,decision=rights41.select_mode(record['source']);rights41.require(record['source'],mode,decision)
        medical=record['category_hint']=='Здоровье и движение'
        studies=study_links(record['source']) if medical else []
        if medical and not studies:raise p.Blocked('SPECIAL_FULL_STUDY_REQUIRED')
        extra=list(dict.fromkeys(record['original_urls'][1:]+record['verification_urls']+studies))
        for url in extra:
            original=self.cached_fetch(url)
            rights41.require(original,'INDEPENDENT_ARTICLE',rights41.decision(original,'INDEPENDENT_ARTICLE'))
        super().source_verified(state,record)
        record['requirements']=list(dict.fromkeys(record['requirements']+record['commission']['requirements']))
        evidence=record.setdefault('special_evidence',{})
        for url in extra:
            if url not in evidence:
                source=self.cached_fetch(url)
                decision=rights41.decision(source,'INDEPENDENT_ARTICLE');rights41.require(source,'INDEPENDENT_ARTICLE',decision)
                item={'source':source,'progress':{}}
                self.analyse(item)
                evidence[url]={'source':source,'claims':item['claims']};self.persist()
        record['supporting_sources']=[item['source'] for item in evidence.values()]
        if record['mode']=='INDEPENDENT_ARTICLE':
            primary=list(record['claims']);ids={x['id'] for x in primary}
            record['claims']=primary+[c for item in evidence.values() for c in item['claims'] if c['id'] not in ids]
        record['special_study_urls']=studies
        record['checks']['source_verified']['special_evidence_complete']=True
        self.persist()
    def finish(self,state,record):
        # An interrupted supplementary analysis must finish before the normal accepted source gate is reused.
        if record.get('checks',{}).get('source_verified',{}).get('approved') and not record['checks']['source_verified'].get('special_evidence_complete'):
            self.source_verified(state,record)
        result=super().finish(state,record)
        if result['category']!=record['category_hint']:raise p.Blocked('SPECIAL_TOPIC_CATEGORY_CHANGED')
        if record['special_slot']==3 and len(result.get('activities',[]))!=21:raise p.Blocked('SPECIAL_21_COMPLETE_ACTIVITIES_REQUIRED')
        return result


def verify_sources(state,persist):
    e.verify_publication_sources(state,persist=persist)
    for record in state['candidates']:
        if record.get('article',{}).get('kind','').casefold()=='новость':
            event=record['source'].get('event_date')
            try:
                event=datetime.fromisoformat(event);event=event.replace(tzinfo=p.TZ) if event.tzinfo is None else event.astimezone(p.TZ)
                if not timedelta(0)<=datetime.now(p.TZ)-event<=timedelta(hours=p.CONFIG['news_event_hours']):raise ValueError()
            except (ValueError,TypeError):raise p.Blocked('SPECIAL_NEWS_NO_LONGER_CURRENT')
        for original in record.get('supporting_sources',[]):
            current=source41.fetch(original['url'])
            if any(current.get(k)!=original.get(k) for k in ('content_hash','title','author','published','declared_license')):
                raise p.Blocked('SPECIAL_SUPPORT_CHANGED_AFTER_REVIEW')


def advance(state,editor,root,persist):
    if not sc.is_special(state):raise p.Blocked('SPECIAL_CONTRACT_REQUIRED')
    editor.state=state
    archive=[item for item in e.archive_entries(root)
             if not Path(item['path']).resolve().is_relative_to((Path(root)/'issues'/sc.ORIGINAL).resolve())
             and not Path(item['path']).resolve().is_relative_to((Path(root)/'issues'/sc.SLUG).resolve())]
    for _ in range(p.CONFIG['technical']['run_steps']):
        ready=[r for r in state['candidates'] if r['status']=='ready']
        if len(ready)==8:
            if any(e.duplicate(r['article'],r,archive+[{'text':e.content.body(x['article']),
                    'source_url':x['source']['canonical'],'topic_key':x['topic_key']} for x in ready if x is not r]) for r in ready):
                raise p.Blocked('SPECIAL_DUPLICATE_WITH_UNRELATED_ARCHIVE')
            ready.sort(key=lambda r:r['special_slot'])
            if e.approve_selection(state,ready,editor):return True
            # An issue-specific repair keeps the same commissioned topic and originals.
            for r in ready:
                if r['status']!='rejected':continue
                if r.get('special_issue_repairs',0)>=2:raise p.Blocked('SPECIAL_ISSUE_REPAIR_LIMIT')
                r['special_issue_repairs']=r.get('special_issue_repairs',0)+1
                r.setdefault('previous_preparations',[]).append({'article':r.pop('article',None),'progress':copy.deepcopy(r['progress'])})
                r['progress']={};r['checks']={};r['status']='discovered'
            persist();continue
        pending=[r for r in state['candidates'] if r['status'] in ('discovered','preparing','retryable_error')]
        if not pending:raise p.Blocked('SPECIAL_EIGHT_FIXED_TOPICS_NOT_READY')
        record=pending[0];record['status']='preparing';persist();editor.usage_record=record
        try:
            editor.finish(state,record);state['articles'][record['id']]=record['article'];persist()
        except news.runtime.GenerationPaused:raise
        except p.Blocked as exc:
            record['status']='needs_review';e.event(state,record,'special_gate','needs_review',exc.code);persist()
        except Exception as exc:
            record['source_attempts']=record.get('source_attempts',0)+1
            record['status']='needs_review' if record['source_attempts']>=3 else 'retryable_error'
            e.event(state,record,'special_source',record['status'],'EXTERNAL_SOURCE_ERROR',type(exc).__name__);persist();return False
    return False


def select_artifacts():
    now=datetime.now(p.TZ);day=now.astimezone(timezone.utc).date().isoformat();upcoming=(now.date()+timedelta(days=1)).isoformat()
    labels={'special':LABEL,'daily':'387news31-production-'+upcoming,'quota':'387news31-quota-'+day}
    output={}
    for kind,label in labels.items():
        records=[]
        for page in range(1,101):
            batch=stage.request_json('https://api.github.com/repos/zzz387/387-news/actions/artifacts?per_page=100&name='+quote(label)+'&page='+str(page))['artifacts']
            records.extend(r for r in batch if r['name']==label)
            if len(batch)<100:break
        else:raise RuntimeError('SPECIAL_ARTIFACT_LIST_INCOMPLETE')
        valid=[r for r in records if not r['expired']]
        if records and not valid:raise RuntimeError('SPECIAL_RESTORE_EXPIRED')
        if valid:
            item=max(valid,key=lambda r:(r['created_at'],r['id']));run=item.get('workflow_run',{})
            if run.get('head_branch')!='main' or type(run.get('id')) is not int:raise RuntimeError('SPECIAL_ARTIFACT_ORIGIN_INVALID')
            output.update({kind+'_found':'true',kind+'_id':str(item['id']),kind+'_run':str(run['id'])})
        else:output[kind+'_found']='false'
    with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
        for key,value in output.items():stream.write(key+'='+value+'\n')


def recover_delivery(state,persist,check=None):
    check=check or publication.check_public
    try:
        result=check();state['publication_verified']=True;persist()
        print('[special-status] '+json.dumps(result));return False
    except Exception:
        if state.get('delivery_attempts',0)>=5:
            print('[special-status] BLOCKED code=SPECIAL_DELIVERY_RETRY_LIMIT');return False
        state['delivery_attempts']=state.get('delivery_attempts',0)+1;persist()
        return True


def run():
    if (os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REF_NAME')!='main' or
        os.getenv('GITHUB_REPOSITORY')!='zzz387/387-news' or os.getenv('NEWS_SPECIAL_EDITION')!=sc.ID):
        raise RuntimeError('SPECIAL_PROTECTED_ACTIONS_MAIN_REQUIRED')
    root=p.ROOT;sc.check_original(root)
    key=stage.validate_key(os.environ['DRAFT_ENCRYPTION_KEY'])
    files={kind:Path(os.environ[kind.upper()+'_CHECKPOINT_FILE']) for kind in ('special','daily','quota')}
    for kind,path in files.items():
        if os.getenv(kind.upper()+'_EXPECTED')=='true' and not path.is_file():raise RuntimeError('SPECIAL_OFFICIAL_RESTORE_MISSING')
    state=stage.decipher(files['special'].read_bytes(),key) if files['special'].is_file() else new_state()
    if not sc.is_special(state) or state.get('branch')!='main' or state.get('preview') is not False:raise RuntimeError('SPECIAL_STATE_PROVENANCE_INVALID')
    ledger=json.loads(files['quota'].read_text()) if files['quota'].is_file() else {}
    daily=stage.decipher(files['daily'].read_bytes(),key) if files['daily'].is_file() else None
    budget=None
    prior_snapshot=copy.deepcopy(state.get('_quota_snapshot',{}))
    stale_shared=(prior_snapshot.get('day','')>ledger.get('day','') or
        prior_snapshot.get('day')==ledger.get('day') and prior_snapshot.get('requests',0)>ledger.get('requests',0))
    def persist():
        if not stale_shared:state['_quota_snapshot']=copy.deepcopy(ledger)
        file=Path(os.environ['RUNNER_TEMP'])/'special-003-r.enc';temp=file.with_suffix('.tmp')
        temp.write_bytes(stage.cipher(state,key));temp.chmod(0o600);temp.replace(file)
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('checkpoint=true\n')
        if budget is not None:
            path=files['quota'];path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(ledger));temp.replace(path)
            with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('quota=true\nquota_name='+stage.quota_label()+'\n')
    if (root/'issues'/sc.SLUG/'index.html').is_file() and os.getenv('SPECIAL_INITIALIZE_ONLY')!='true':
        publication.validate(root)
        if recover_delivery(state,persist):
            try:from scripts import production_preflight41
            except ImportError:import production_preflight41
            production_preflight41.require_pages()
            with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('ready=true\n')
        return
    admitted,reason=admit(root,daily,ledger)
    daily_used=int(os.getenv('NEWS_DAILY_RUN_USED','24'))
    if remaining_run_limit(daily_used,ledger)==0:admitted,reason=False,'DAILY_USED_RUN_BUDGET'
    if stale_shared:admitted,reason=False,'SPECIAL_SHARED_LEDGER_STALE'
    if os.getenv('SPECIAL_INITIALIZE_ONLY')=='true':admitted,reason=False,'INITIALIZED_ONLY_NO_GEMINI'
    if admitted:
        runs=stage.request_json('https://api.github.com/repos/zzz387/387-news/actions/workflows/daily-v31.yml/runs?branch=main&per_page=30')['workflow_runs']
        if any(str(r['id'])!=os.environ['GITHUB_RUN_ID'] and r['status'] in ('queued','pending','waiting','in_progress') for r in runs):
            admitted,reason=False,'ANOTHER_DAILY_RUN_WAITING'
    if admitted:
        try:site_checks.check_site(expected_date=datetime.now(p.TZ).date().isoformat())
        except Exception:admitted,reason=False,'CURRENT_DAILY_HTTPS_UNVERIFIED'
    persist()
    if not admitted:
        print('[special-status] '+json.dumps({'id':sc.ID,'stage':'DEFERRED','reason':reason,'articles':sum(r['status']=='ready' for r in state['candidates']),'gemini_requests':0}));return
    # Independent state, identical global request budget/cooldown; never mutate the daily file.
    budget=news.runtime.RequestBudget(ledger,persist,run_limit=remaining_run_limit(daily_used,ledger))
    news.runtime.ACTIVE_BUDGET=budget;news.runtime.CHECKPOINT=persist
    previous=signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(news.runtime.GenerationPaused('Special runner stopped')))
    try:
        persist();ready=advance(state,Editor(persist=persist),root,persist)
        if ready:
            verify_sources(state,persist)
            try:from scripts import browser41,production_preflight41
            except ImportError:import browser41,production_preflight41
            production_preflight41.require_pages()
            state['published_at']=datetime.now(p.TZ).isoformat()
            publication.build(state,root)
            with __import__('tempfile').TemporaryDirectory(prefix='387-special-browser-') as output:
                report=browser41.check(root,sc.SLUG,output,expected_count=8,overview_path='/issues/'+sc.SLUG+'/')
            print('[special-browser] '+json.dumps(report))
            with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('ready=true\n')
    except news.runtime.GenerationPaused:
        state['status']='RETRY_PENDING';print('[special-status] RETRY_PENDING; checkpoint and shared quota retained')
    except p.Blocked as exc:
        state['status']='BLOCKED';state['block_code']=exc.code;print('[special-status] BLOCKED code='+exc.code)
    finally:
        persist();print('[special-metrics] '+json.dumps({'id':sc.ID,'articles':sum(r['status']=='ready' for r in state['candidates']),
            'requests_used':ledger.get('requests'),'run_used':budget.used,'workflow_run_used':daily_used+budget.used,'stages':quota41.actual_usage(state)}))
        news.runtime.ACTIVE_BUDGET=news.runtime.CHECKPOINT=None;signal.signal(signal.SIGTERM,previous)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--probe',action='store_true');parser.add_argument('--locate',action='store_true');parser.add_argument('--verify-public',action='store_true')
    args=parser.parse_args()
    if args.probe:probe()
    elif args.locate:select_artifacts()
    elif args.verify_public:print('[special-status] '+json.dumps(publication.check_public()))
    else:run()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('[special-status] FAILED code='+ (exc.code if isinstance(exc,p.Blocked) else type(exc).__name__))
        raise SystemExit(1)
