"""003-R production, isolated ciphertext and shared quota; owner-authorized one-shot special priority."""
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
        plan=sc.evidence_plan(slot)
        state['candidates'].append({'id':'003-R-'+str(slot['slot']),'special_slot':slot['slot'],
            'url':plan['primary'],'original_urls':slot['original_urls'],'category_hint':slot['category'],
            'verification_urls':plan['support'],'evidence_plan':copy.deepcopy(plan),
            'unused_original_urls':[url for url in slot['original_urls'] if url not in [plan['primary']]+plan['support']],'status':'discovered','checks':{},'progress':{},
            'commission':{'original_topic':slot.get('replacement_topic',slot['original_title']),'category':slot['category'],
                'requirements':slot['requirements'],'kind':'Внеочередное переиздание: события 26 октября не выдавать за новые; контекст только по подтверждённым источникам. Неиспользованные исходные URL не считаются проверенными. Научная статья, использованная вместо исходной, должна быть явно отличима от исходного исследования.'}})
    return state


PREVIOUS_DEFINITION_HASH='5921ed0c3b6f8750294f2336f71f290f4f5e104df7d932a123781086b3eaac98'
PREVIOUS_BASIS_HASH='2ea5e5239ee5937d5922e2f3eac9f05f5db27ab63999b77ea8f187d8289873d8'


def refresh_definition(state):
    identity=state.get('special_edition',{})
    if identity=={'id':sc.ID,'definition_hash':p.digest(sc.definition())}:return state
    if identity.get('id')!=sc.ID or identity.get('definition_hash') not in (PREVIOUS_DEFINITION_HASH,PREVIOUS_BASIS_HASH):raise RuntimeError('SPECIAL_STATE_PROVENANCE_INVALID')
    replacement=new_state();old={r['special_slot']:r for r in state['candidates']}
    changed=[]
    for index,fresh in enumerate(replacement['candidates']):
        previous=old[fresh['special_slot']]
        previous_plan=previous.get('evidence_plan') or {'primary':previous['url'],'support':list(dict.fromkeys(previous['original_urls'][1:]+previous['verification_urls'])),'studies':[],'mode':None}
        if previous_plan==fresh['evidence_plan']:
            previous.update(evidence_plan=fresh['evidence_plan'],unused_original_urls=fresh['unused_original_urls'])
            replacement['candidates'][index]=previous
        else:
            state.setdefault('prior_source_plans',[]).append(copy.deepcopy(previous))
            fresh['history']=copy.deepcopy(previous.get('history',[]))
            fresh['model_usage']=copy.deepcopy(previous.get('model_usage',{}))
            for key in ('article_repair_count','repair_count','section_attempts','analysis_repairs','coverage_repairs'):
                if key in previous.get('progress',{}):fresh['progress'][key]=copy.deepcopy(previous['progress'][key])
            state.get('articles',{}).pop(previous['id'],None);state.get('dossiers',{}).pop(previous['id'],None)
            changed.append(previous['special_slot'])
    state['candidates']=replacement['candidates'];state['special_edition']=replacement['special_edition']
    if changed:
        state['audit_passed']=False;state.pop('issue_approval_hash',None);state['selected_ids']=[]
        priority=state.get('production_priority',{})
        if priority.get('reason')=='SPECIAL_TOPIC_NEEDS_REVIEW':
            priority.setdefault('repair_history',[]).append({'reason':priority['reason'],'new_evidence_slots':changed})
            priority['status']='ACTIVE';priority.pop('reason',None)
    print('[special-source-migration] '+json.dumps({'changed_slots':changed,'quota_preserved':True,'unrelated_progress_preserved':True}))
    return state


def admit(root,daily,ledger,now=None,priority=False):
    now=(now or datetime.now(p.TZ)).astimezone(p.TZ)
    if priority:
        current_day=now.astimezone(timezone.utc).date().isoformat()
        if ledger.get('day','')>current_day:return False,'FUTURE_SHARED_LEDGER'
        if any(until>now.timestamp() for until in ledger.get('cooldowns',{}).values()):return False,'GEMINI_COOLDOWN'
        if ledger.get('day')==current_day and ledger.get('requests',220)>=220:return False,'DAILY_QUOTA'
        return True,'SPECIAL_FIRST_OWNER_AUTHORIZED'
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


def remaining_run_limit(daily_used,ledger,priority=False):
    if type(daily_used) is not int or not 0<=daily_used<=24:raise RuntimeError('DAILY_RUN_ACCOUNTING_INVALID')
    used=ledger.get('requests',0) if not priority or ledger.get('day')==datetime.now(timezone.utc).date().isoformat() else 0
    return max(0,min(24-daily_used,220-used-(0 if priority else sc.definition()['daily_reserve_requests'])))


def study_links(source):
    result=[]
    for block in source['blocks']:
        for url in block.get('links',[]):
            host=(urlparse(url).hostname or '').lower()
            if host in ('doi.org','dx.doi.org','pubmed.ncbi.nlm.nih.gov','pmc.ncbi.nlm.nih.gov') and urlparse(url).scheme in ('http','https'):
                if host.endswith('doi.org') and not re.match(r'^/10\.\d{4,9}/',urlparse(url).path):continue
                url=urlparse(url)._replace(scheme='https',netloc='doi.org' if host.endswith('doi.org') else host).geturl()
                if url not in result:result.append(url)
    if not result and (urlparse(source['url']).hostname or '').endswith('sciencedaily.com'):
        # Journal references may sit outside the article's prose region. Read the already
        # robots-verified public original, never a search snippet or an abstract fallback.
        from html.parser import HTMLParser
        class References(HTMLParser):
            def handle_starttag(self,tag,attrs):
                href=dict(attrs).get('href','')
                url=urljoin(source['url'],href);host=(urlparse(url).hostname or '').lower()
                if tag=='a' and host in ('doi.org','dx.doi.org','pubmed.ncbi.nlm.nih.gov','pmc.ncbi.nlm.nih.gov') and urlparse(url).scheme in ('http','https'):
                    if host.endswith('doi.org') and not re.match(r'^/10\.\d{4,9}/',urlparse(url).path):return
                    url=urlparse(url)._replace(scheme='https',netloc='doi.org' if host.endswith('doi.org') else host).geturl()
                    if url not in result:result.append(url)
        parser=References();parser.feed(source41.transport(source['url']))
    return result[:4]  # bounded discovery, never a substitute for full study verification


def probe():
    config=sc.definition();urls=list(dict.fromkeys(u for slot in config['slots'] for u in slot['original_urls']+[sc.evidence_plan(slot)['primary']]+sc.evidence_plan(slot)['support']+sc.evidence_plan(slot)['studies']))
    from scripts.public_sources41 import Session
    public_session=Session();fetch=public_session.fetch
    def inspect(url):
        try:
            source=fetch(url);mode,decision=rights41.select_mode(source)
            rights41.require(source,mode,decision)
            return {'url':url,'status':'eligible','mode':mode,'rights':decision['status'],
                'verification':decision.get('verification'),'content_hash':source['content_hash'],
                'metadata_status':source['metadata_status'],'study_urls':study_links(source)}
        except Exception as exc:
            row={'url':url,'status':'blocked','code':getattr(exc,'code',None) if isinstance(exc,p.Blocked) else type(exc).__name__}
            if row['code']=='SOURCE_EXTRACTION_PARTIAL' and urlparse(url).hostname=='vm.ru':
                from scripts import source_dom41 as dom
                html=public_session.cache.get(url)
                if isinstance(html,str):
                    document=dom.Document();document.feed(html);document.close()
                    regions,method=dom.choose_region(document)
                    row['public_dom']={'method':method,'regions':len(regions),'nodes':[
                        {'tag':node.tag,'class':node.attrs.get('class','')[:180],'id':node.attrs.get('id','')[:100],
                         'itemprop':node.attrs.get('itemprop',''),'closed':node.closed,'characters':len(node.text()),
                         'headings':sum(child.tag in ('h1','h2','h3') for child in node.all())}
                        for node in document.root.all() if node.tag in ('article','main') or
                        re.search(r'article|content|text-body',node.attrs.get('class',''),re.I)][:120]}

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
    research_urls=list(dict.fromkeys(u for slot in config['slots'] if slot['category']=='Здоровье и движение'
        for u in (sc.evidence_plan(slot)['studies'] or by_url[sc.evidence_plan(slot)['primary']].get('study_urls',[]))))
    with ThreadPoolExecutor(max_workers=3) as pool:research=list(pool.map(inspect,research_urls))
    research_by_url={r['url']:r for r in research}
    def slot_status(slot):
        plan=sc.evidence_plan(slot)
        if not all(by_url[u]['status']=='eligible' for u in [plan['primary']]+plan['support']):return 'source_hold'
        if slot['category']=='Здоровье и движение':
            studies=plan['studies'] or by_url[plan['primary']].get('study_urls',[])
            if not studies or not all(research_by_url[u]['status']=='eligible' for u in studies):return 'medical_evidence_hold'
        return 'sources_ready'
    report={'id':sc.ID,'gemini_requests':0,'checked_at':datetime.now(p.TZ).isoformat(),'sources':rows,'research_sources':research,
        'articles':[{'slot':s['slot'],'topic':s['original_title'],'original_urls':s['original_urls'],
                     'status':slot_status(s),'active_primary':sc.evidence_plan(s)['primary'],
                     'unused_original_urls':[u for u in s['original_urls'] if u not in [sc.evidence_plan(s)['primary']]+sc.evidence_plan(s)['support']],
                     'generation':'not_started'} for s in config['slots']]}
    print('[special-sources] '+json.dumps(report,ensure_ascii=False))
    Path(os.environ.get('SPECIAL_SOURCE_REPORT','/tmp/special-source-report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report





def merge_claims(*groups):
    result=[];seen=set()
    for group in groups:
        for claim in group:
            key=p.digest(claim)
            if key not in seen:result.append(copy.deepcopy(claim));seen.add(key)
    return result

def neutral_fact_base(plan,evidence):
    if not set(plan['fact_base_urls'])<=set(evidence):raise p.Blocked('SPECIAL_NEUTRAL_FACT_BASE_INCOMPLETE')
    return merge_claims(*[evidence[url]['claims'] for url in plan['fact_base_urls']])

def unsupported_palette(text):
    return bool(re.search(r'(?i)(?:100|сотн\w*|ста|сто)\s+(?:[\w-]+\s+){0,2}(?:оттен\w*|расцвет\w*|цветов\w*\s+(?:решен\w*|вариант\w*))',text))

class Editor(e.Editor):
    def source_verified(self,state,record):
        # Resolve full originals, rights and studies before spending a single model request.
        if not record.get('source'):record['source']=self.cached_fetch(record['url']);self.persist()
        mode,decision=rights41.select_mode(record['source']);rights41.require(record['source'],mode,decision)
        medical=record['category_hint']=='Здоровье и движение'
        plan=record['evidence_plan']
        studies=(plan['studies'] or study_links(record['source'])) if medical else []
        if medical and not studies:raise p.Blocked('SPECIAL_FULL_STUDY_REQUIRED')
        extra=list(dict.fromkeys(plan['support']+studies))
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
                item=record['progress'].setdefault('special_support',{}).setdefault(url,{'source':source,'progress':{}})
                self.analyse(item)
                evidence[url]={'source':source,'claims':item['claims']};self.persist()
        record['supporting_sources']=[item['source'] for item in evidence.values()]
        if record['mode']=='INDEPENDENT_ARTICLE':
            record['claims']=merge_claims(record['claims'],*[item['claims'] for item in evidence.values()])
        if plan.get('fact_base_urls'):
            record['primary_analysis_claims']=copy.deepcopy(record['claims'])
            record['claims']=neutral_fact_base(plan,evidence)
            record['requirements']=list(plan['writer_requirements'])
        if record['special_slot']==2:
            rejected=[claim for claim in record['claims'] if unsupported_palette(claim['fact'])]
            if rejected:
                record.setdefault('excluded_ambiguous_claims',[]).extend(copy.deepcopy(rejected))
                record['claims']=[claim for claim in record['claims'] if claim not in rejected]
                print('[special-fact-diagnostic] '+json.dumps({'slot':2,'code':'UNSUPPORTED_HUNDRED_SHADES','excluded':len(rejected)}))
        record['public_reference_urls']=list(dict.fromkeys(plan.get('public_citation_urls',[])+studies))
        record['special_study_urls']=studies
        record['checks']['source_verified']['special_evidence_complete']=True
        self.persist()
    def finish(self,state,record):
        # An interrupted supplementary analysis must finish before the normal accepted source gate is reused.
        if record.get('checks',{}).get('source_verified',{}).get('approved') and not record['checks']['source_verified'].get('special_evidence_complete'):
            self.source_verified(state,record)
        result=super().finish(state,record)
        if result['category']!=record['category_hint']:raise p.Blocked('SPECIAL_TOPIC_CATEGORY_CHANGED')
        if record['special_slot']==2 and unsupported_palette(e.content.body(result)):raise p.Blocked('UNSUPPORTED_HUNDRED_SHADES')
        if record['special_slot']==3 and len(result.get('activities',[]))!=21:raise p.Blocked('SPECIAL_21_COMPLETE_ACTIVITIES_REQUIRED')
        return result


def verify_sources(state,persist):
    e.verify_publication_sources(state,persist=persist)
    for record in state['candidates']:
        if record.get('article',{}).get('kind','').casefold()=='новость':
            event=record['source'].get('event_date')
            try:
                if not record['source'].get('published'):raise ValueError()
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
            transient=exc.code in {'SOURCE_EXTRACTION_PARTIAL','ROBOTS_UNVERIFIED','SOURCE_UNAVAILABLE'} and not record['checks'].get('source_verified',{}).get('special_evidence_complete')
            if transient:record['source_attempts']=record.get('source_attempts',0)+1
            record['status']='retryable_error' if transient and record['source_attempts']<3 else 'needs_review'
            e.event(state,record,'special_gate',record['status'],exc.code);persist()
            if transient:return False
        except Exception as exc:
            record['source_attempts']=record.get('source_attempts',0)+1
            record['status']='needs_review' if record['source_attempts']>=3 else 'retryable_error'
            e.event(state,record,'special_source',record['status'],'EXTERNAL_SOURCE_ERROR',type(exc).__name__);persist();return False
    return False


def select_artifacts():
    now=datetime.now(p.TZ);day=now.astimezone(timezone.utc).date().isoformat();upcoming=(now.date()+timedelta(days=1)).isoformat()
    date=release_queue.unfinished_date(p.ROOT,release_queue.target_date(p.ROOT,now),release_queue.production_artifacts())
    labels={'special':LABEL,'daily':'387news31-production-'+date,'quota':'387news31-quota-'+day}
    output={}
    for kind,label in labels.items():
        records=[]
        for candidate_label in ((news.runtime.quota_labels(day)+news.runtime.quota_labels((now.astimezone(timezone.utc).date()-timedelta(days=1)).isoformat())) if kind=='quota' else (label,)):
            for page in range(1,101):
                batch=stage.request_json('https://api.github.com/repos/zzz387/387-news/actions/artifacts?per_page=100&name='+quote(candidate_label)+'&page='+str(page))['artifacts']
                records.extend(r for r in batch if r['name']==candidate_label)
                if len(batch)<100:break
            else:raise RuntimeError('SPECIAL_ARTIFACT_LIST_INCOMPLETE')
        valid=[r for r in records if not r['expired']]
        if records and not valid:raise RuntimeError('SPECIAL_RESTORE_EXPIRED')
        if valid:
            item=max(valid,key=lambda r:((r['name'][len('387news31-quota-'):][:10] if kind=='quota' else ''),r['created_at'],r['id']));run=item.get('workflow_run',{})
            if run.get('head_branch')!='main' or type(run.get('id')) is not int:raise RuntimeError('SPECIAL_ARTIFACT_ORIGIN_INVALID')
            output.update({kind+'_found':'true',kind+'_id':str(item['id']),kind+'_run':str(run['id'])})
        else:output[kind+'_found']='false'
    with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
        for key,value in output.items():stream.write(key+'='+value+'\n')


def recover_delivery(state,persist,check=None):
    check=check or publication.check_public
    try:
        result=check();state['publication_verified']=True;state['status']='PUBLISHED';state['publication_verified_at']=datetime.now(p.TZ).isoformat();persist()
        print('[special-status] '+json.dumps(result));return False
    except Exception:
        if state.get('delivery_attempts',0)>=5:
            state.update(status='BLOCKED',block_code='SPECIAL_DELIVERY_RETRY_LIMIT');persist()
            print('[special-status] BLOCKED code=SPECIAL_DELIVERY_RETRY_LIMIT');return False
        state['delivery_attempts']=state.get('delivery_attempts',0)+1;persist()
        return True


def run():
    try:from scripts import daily43
    except ImportError:import daily43
    if os.getenv("NEWS_POLICY_VERSION")=="4.3" and daily43.enabled() and daily43.e.CONFIG.get("special_paused"):
        print("[special-status] PAUSED_POLICY43; existing ciphertext and quota unchanged");return
    if (os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REF_NAME')!='main' or
        os.getenv('GITHUB_REPOSITORY')!='zzz387/387-news' or os.getenv('NEWS_SPECIAL_EDITION')!=sc.ID):
        raise RuntimeError('SPECIAL_PROTECTED_ACTIONS_MAIN_REQUIRED')
    use43=os.getenv('NEWS_POLICY_VERSION')=='4.3'
    if use43:from scripts import special43
    root=p.ROOT;sc.check_original(root)
    key=stage.validate_key(os.environ['DRAFT_ENCRYPTION_KEY'])
    files={kind:Path(os.environ[kind.upper()+'_CHECKPOINT_FILE']) for kind in ('special','daily','quota')}
    for kind,path in files.items():
        if os.getenv(kind.upper()+'_EXPECTED')=='true' and not path.is_file():raise RuntimeError('SPECIAL_OFFICIAL_RESTORE_MISSING')
    if use43 and not files['special'].is_file():raise RuntimeError('SPECIAL43_EXISTING_CHECKPOINT_REQUIRED')
    state=refresh_definition(stage.decipher(files['special'].read_bytes(),key)) if files['special'].is_file() else new_state()
    if use43:
        state=special43.migrate(state)
        state['review_date']=datetime.now(p.TZ).date().isoformat()
    if not sc.is_special(state) or state.get('branch')!='main' or state.get('preview') is not False:raise RuntimeError('SPECIAL_STATE_PROVENANCE_INVALID')
    ledger=json.loads(files['quota'].read_text()) if files['quota'].is_file() else {}
    daily_bytes=files['daily'].read_bytes() if files['daily'].is_file() else None
    daily=stage.decipher(daily_bytes,key) if daily_bytes is not None else None
    print('[special-restore] '+json.dumps({'restored':files['special'].is_file(),'articles':sum(r.get('status')=='ready' for r in state['candidates']),
        'sections':sum(len(r.get('progress',{}).get('sections',{})) for r in state['candidates']),
        'priority_restored':bool(state.get('production_priority')),'daily_date':daily.get('date') if daily else None,
        'daily_articles':sum(r.get('status')=='ready' for r in daily.get('candidates',[])) if daily else None}))
    if state.get('all_sources_independence_revision')!=1:
        rechecks=[]
        for record in state['candidates']:
            if record.get('status')=='ready' and record.get('mode')=='INDEPENDENT_ARTICLE':
                record['status']='preparing';record['checks'].pop('editorial_checked',None);record['checks'].pop('ready_to_publish',None)
                rechecks.append(record['special_slot'])
        state['all_sources_independence_revision']=1
        print('[special-independence-scope] '+json.dumps({'recheck_slots':rechecks,'accepted_text_preserved':True}))
    e.restore_preparation_repairs(state)
    priority_first=os.getenv('SPECIAL_PRIORITY_FIRST')=='true' and not use43
    if priority_first:
        from scripts import special_priority41 as priority_queue
        priority_queue.enable_header_review_v2(state)
        priority_queue.repair_real_run_v2(state)
        priority_queue.repair_protocol_v3(state)
        priority_queue.repair_independence_protocol_v4(state)
        priority_queue.enable_neutral_writer_v1(state)
        news.runtime.merge_snapshot(ledger,state.get('_quota_snapshot',{}))
        if daily:news.runtime.merge_snapshot(ledger,daily.get('_quota_snapshot',{}))
        priority_active,priority_reason=priority_queue.reconcile(state)
    if use43:
        news.runtime.merge_snapshot(ledger,state.get('_quota_snapshot',{}))
        if daily:news.runtime.merge_snapshot(ledger,daily.get('_quota_snapshot',{}))
    budget=None
    prior_snapshot=copy.deepcopy(state.get('_quota_snapshot',{}))
    stale_shared=(prior_snapshot.get('day','')>ledger.get('day','') or
        prior_snapshot.get('day')==ledger.get('day') and prior_snapshot.get('requests',0)>ledger.get('requests',0))
    def persist():
        if daily_bytes is not None and files['daily'].read_bytes()!=daily_bytes:raise RuntimeError('DAILY_CHECKPOINT_CHANGED_DURING_SPECIAL')
        if not stale_shared:state['_quota_snapshot']=copy.deepcopy(ledger)
        file=Path(os.environ['RUNNER_TEMP'])/'special-003-r.enc';temp=file.with_suffix('.tmp')
        temp.write_bytes(stage.cipher(state,key));temp.chmod(0o600);temp.replace(file)
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('checkpoint=true\n')
        if budget is not None:
            path=files['quota'];path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(ledger));temp.replace(path)
            with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('quota=true\nquota_name='+stage.quota_label()+'-special-003-r\n')
    if (root/'issues'/sc.SLUG/'index.html').is_file() and os.getenv('SPECIAL_INITIALIZE_ONLY')!='true':
        publication.validate(root)
        if recover_delivery(state,persist):
            try:from scripts import production_preflight41
            except ImportError:import production_preflight41
            production_preflight41.require_pages()
            with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('ready=true\n')
        if priority_first:priority_queue.emit(state);persist()
        if use43:special43.emit(state);persist()
        return
    admitted,reason=special43.admit(root,daily,ledger) if use43 else admit(root,daily,ledger,priority=priority_first)
    daily_used=int(os.getenv('NEWS_DAILY_RUN_USED','24'))
    if priority_first and not priority_active:admitted,reason=False,priority_reason
    if remaining_run_limit(daily_used,ledger,priority=priority_first)==0:
        reason='DAILY_QUOTA' if ledger.get('day')==datetime.now(timezone.utc).date().isoformat() and ledger.get('requests',0)>=220 else 'DAILY_USED_RUN_BUDGET'
        admitted=False
    if stale_shared:admitted,reason=False,'SPECIAL_SHARED_LEDGER_STALE'
    if os.getenv('SPECIAL_INITIALIZE_ONLY')=='true':admitted,reason=False,'INITIALIZED_ONLY_NO_GEMINI'
    if admitted and not priority_first:
        runs=stage.request_json('https://api.github.com/repos/zzz387/387-news/actions/workflows/daily-v31.yml/runs?branch=main&per_page=30')['workflow_runs']
        if any(str(r['id'])!=os.environ['GITHUB_RUN_ID'] and r['status'] in ('queued','pending','waiting','in_progress') for r in runs):
            admitted,reason=False,'ANOTHER_DAILY_RUN_WAITING'
    if admitted and not priority_first:
        try:site_checks.check_site(expected_date=datetime.now(p.TZ).date().isoformat())
        except Exception:admitted,reason=False,'CURRENT_DAILY_HTTPS_UNVERIFIED'
    persist()
    if not admitted:
        print('[special-status] '+json.dumps({'id':sc.ID,'stage':'DEFERRED','reason':reason,'articles':sum(r['status']=='ready' for r in state['candidates']),'gemini_requests':0}))
        if priority_first:priority_queue.emit(state);persist()
        if use43:special43.emit(state);persist()
        return
    # Independent state, identical global request budget/cooldown; never mutate the daily file.
    budget=news.runtime.RequestBudget(ledger,persist,run_limit=remaining_run_limit(daily_used,ledger,priority=priority_first))
    news.runtime.ACTIVE_BUDGET=budget;news.runtime.CHECKPOINT=persist
    previous=signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(news.runtime.GenerationPaused('Special runner stopped')))
    before=priority_queue.fingerprint(state) if priority_first else None
    try:
        persist();ready=(special43.advance(state,special43.Editor(persist=persist),root,persist) if use43 else advance(state,Editor(persist=persist),root,persist))
        if ready:
            special43.verify_sources(state,persist) if use43 else verify_sources(state,persist)
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
        state['status']='RETRY_PENDING' if use43 and exc.code=='SPECIAL43_SOURCE_CHANGED_REVIEW_REQUIRED' else 'BLOCKED'
        state['block_code']=exc.code;print('[special-status] '+state['status']+' code='+exc.code)
    finally:
        if priority_first:
            priority_queue.finish_run(state,before,budget.used);priority_queue.emit(state,budget.used)
        if use43:special43.emit(state,budget.used)
        persist();print('[special-metrics] '+json.dumps({'id':sc.ID,'articles':sum(r['status']=='ready' for r in state['candidates']),
            'requests_used':ledger.get('requests'),'run_used':budget.used,'workflow_run_used':daily_used+budget.used,'stages':quota41.actual_usage(state),'daily_checkpoint_unchanged':daily_bytes is None or files['daily'].read_bytes()==daily_bytes}))
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
