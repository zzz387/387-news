"""4.3 adapter for the EXISTING 003-R state, workflow, quota and publisher."""
import copy,json,os
from datetime import datetime,timedelta,timezone
from scripts import policy41 as p,editorial43 as e,daily43,editorial41 as legacy,rights41,source41,special_contract41 as sc,generation_runtime as runtime

THEMES={1:'Постановка «Василиса Прекрасная» в ДМТЮА: один подтверждённый культурный аспект.',
 2:'Школа на улице Климашкина: организация пространства или декоративные цветы фасада. Это цветы, не сто оттенков.',
 3:'Один полезный аспект совместной игры с малышом. Не повторяй подборку UNICEF, не обещай 21 занятие. Если описываешь игру, нужны возраст/готовность, действия взрослого и безопасность.',
 4:'Напрудный переулок: подтверждённое изменение городской среды; исторический контекст только при наличии фактов.',
 5:'Один применимый способ уважительного разговора с подростком, без медицинских обещаний.',
 6:'Движение в старшем возрасте: реальное исследование, его дизайн, результаты и ограничения. Не подменять научную работу пресс-релизом.',
 7:'Добавки к кофе: проверенный узкий аспект калорийности или наблюдательных данных. Не повторять неподтверждённые 40%, не рекомендовать сливки для похудения; исследование 2025 года не становится исследованием 2026 года.',
 8:'Отношения после отъезда детей: один полезный аспект. Китайские поперечные данные о пожилых людях не доказывают причинность и не описывают все семьи.'}


def migrate(state):
    if not sc.is_special(state):raise p.Blocked('SPECIAL_CONTRACT_INVALID')
    if state.get('special43_revision')==1:return state
    state['policy41_checkpoint']=copy.deepcopy(state)
    state.update(policy_version='4.3',special43_revision=1,audit_passed=False,selected_ids=[],review_date=datetime.now(p.TZ).date().isoformat())
    for r in state['candidates']:
        old=copy.deepcopy(r.get('rejected_part',{}))
        if old.get('result',{}).get('approve') is False:
            if r.get('article'):r.setdefault('previous_preparations',[]).append({'article':r.pop('article'),'refusal':old})
        # Full previously checked originals, claims, sections, rejected drafts and usage survive.
        evidence=r.get('special_evidence',{})
        support={s['url']:s for s in r.get('supporting_sources',[])}
        support.update({url:row['source'] for url,row in evidence.items() if row.get('source')})
        if r['special_slot']==3:
            alternatives=r.get('evidence_plan',{}).get('fact_base_urls',[])
            primary=next((support[u] for u in alternatives if u in support),None)
            if primary:
                if r.get('source'):support[r['source']['url']]=r['source']
                r['source']=copy.deepcopy(primary);r['url']=primary['url']
        r['supporting_sources']=[s for url,s in support.items() if url!=r['url']]
        r['commission']={'theme':THEMES[r['special_slot']], 'context':'Самостоятельное внеочередное переиздание номера от 26 октября 2026. Старые события не выдавать за сегодняшнюю новость; никакой обязательной длины, глубины или количества разделов.'}
        r.setdefault('progress',{}).setdefault('v43',{'write_attempts':int('article' in r),'review_attempts':{},'history':[]})
        if r.get('status') in ('ready','needs_review','rejected'):r['status']='preparing'
        r.setdefault('checks',{}).pop('final43',None)
        r.setdefault('history',[])
    state['articles']={};state['status']='RETRY_PENDING'
    print('[special43-migration] '+json.dumps({'slots':8,'prior_state_preserved':True,'old_verdicts_not_overridden':True,'quota_preserved':True}),flush=True)
    return state


def repair_review_protocol_v2(state):
    if state.get('special43_review_v2')==1:return
    changed=[]
    for row in state['candidates']:
        progress=row.get('progress',{}).get('v43',{});history=progress.get('history',[])
        last=history[-1] if history else {}
        if row.get('status')=='needs_review':
            print('[special43-review-diagnostic] '+json.dumps({'slot':row['special_slot'],'approve':last.get('approve'),
                'failed_checks':[key for key in e.CHECKS if last.get(key) is not True],'issues_count':len(last.get('issues',[])),
                'unresolved_count':len(last.get('unresolved',[]))}),flush=True)
        if row.get('status')=='needs_review' and row.get('article') and e.positive_semantics(last):
            row['status']='preparing';changed.append(row['special_slot'])
    if changed and state.get('block_code')=='SPECIAL43_TOPICS_NEED_REVIEW':state['status']='RETRY_PENDING';state.pop('block_code',None)
    state['special43_review_v2']=1
    print('[special43-review-protocol] '+json.dumps({'slots':changed,'automatic_approval':False,'drafts_and_counters_preserved':True}),flush=True)


def repair_dated_context_v1(state):
    """One addressed rewrite of the observed news-date failure, never a local approval."""
    row=next((r for r in state['candidates'] if r['special_slot']==6),None)
    if not row or row.get('special43_dated_context_v1'):return
    progress=row.get('progress',{}).get('v43',{});history=progress.get('history',[])
    last=history[-1] if history else {}
    if (row.get('status')!='needs_review' or not row.get('article') or not e.positive_semantics(last)
            or not e.news_errors(last,row,state)):return
    row['special43_dated_context_v1']={'pending':True,'attempts':0,'reason_codes':e.news_errors(last,row,state)}
    row['status']='preparing';state['status']='RETRY_PENDING';state.pop('block_code',None)
    print('[special43-dated-context] '+json.dumps({'slot':6,'action':'ONE_ADDRESSED_REPAIR','reason_codes':e.news_errors(last,row,state),'all_prior_counters_preserved':True}),flush=True)


class Editor(e.Editor):
    def finish(self,state,r):
        repair=r.get('special43_dated_context_v1',{})
        if repair.get('pending'):
            self.state=state;self.usage_record=r;self.verify_source(r)
            if repair['attempts']>=1:raise p.Blocked('DATED_CONTEXT_REPAIR_EXHAUSTED')
            repair['attempts']+=1;self.persist()
            try:
                article=self.call('Исправь только временную подачу сохранённой самостоятельной медицинской заметки. '
                    'Проверка фактов, безопасности и прав положительна, но подача оперативной новости не имеет подтверждённой свежей даты события. '
                    'Подготовь законченное ретроспективное объяснение проверенного исследования: ясно укажи настоящую дату научной работы, '
                    'дизайн, результаты и ограничения. Не называй его сегодняшней новостью или новым открытием. Не выдумывай дату; '
                    'если дата исследования отсутствует, не приписывай её. Не меняй чисел, выборки и выводов; корреляция не причинность. '
                    'Не добавляй лечебных советов, обещаний и фактов без источников. Сохрани полезный аспект, собственную форму C. '
                    'Никакой обязательной длины, глубины или количества разделов. '
                    'Схема finished/title/teaser/blocks, URL только в служебных источниках. '
                    'Независимая итоговая проверка затем заново оценит, является ли итоговый текст новостью, и все критерии допуска. '
                    '\nДиагностика: '+json.dumps(repair['reason_codes'])+'\nСохранённая статья: '+json.dumps(r['article'],ensure_ascii=False)+
                    '\nПолные проверенные оригиналы: '+json.dumps(self.writing_basis(r),ensure_ascii=False),output_tokens=12000,schema='v43_article')
            except runtime.GenerationPaused:
                repair['attempts']-=1;self.persist();raise
            if article.get('finished') is not True:raise p.Blocked('DATED_CONTEXT_REPAIR_INCOMPLETE')
            normalized=e.normalize(dict(article,category=r['category'],kind=r['kind'],mode=r['mode'],activities=[]))
            r['progress']['v43'].setdefault('previous_articles',[]).append(r['article'])
            r['article']=normalized;r['checks'].pop('final43',None);repair['pending']=False;self.persist()
        return super().finish(state,r)

    def verify_source(self,r):
        # Reuse complete cached companion originals, fetching missing sources only once.
        for url,row in r.get('special_evidence',{}).items():
            if row.get('source'):self.state.setdefault('source_cache',{}).setdefault(url,copy.deepcopy(row['source']))
        if r['special_slot'] in (6,7):
            from scripts import special003r
            if not r.get('source'):r['source']=self.cached_fetch(r['url']);self.persist()
            studies=r.get('special_study_urls') or r.get('evidence_plan',{}).get('studies') or special003r.study_links(r['source'])
            if not studies:raise p.Blocked('SPECIAL_FULL_STUDY_REQUIRED')
            r['special_study_urls']=studies
            if r['special_slot']==6 and r['source']['url'] not in studies:
                old_source=r['source'];paper=self.cached_fetch(studies[0])
                r.setdefault('supporting_sources',[]).append(old_source)
                r.update(source=paper,url=paper['url']);self.persist()
            r['verification_urls']=list(dict.fromkeys(r.get('verification_urls',[])+studies))
        super().verify_source(r)

    def writing_basis(self,r):
        sources=[r['source']]+r.get('supporting_sources',[]);by_id={s['id']:s for s in sources}
        if r['special_slot'] in (6,7):return {'full_originals':self.model_sources(r),'commission':r['commission']}
        allowed_urls=r.get('evidence_plan',{}).get('fact_base_urls') or [s['url'] for s in sources]
        neutral=[]
        for inventory in r.get('progress',{}).get('neutral_inventories',{}).values():
            for row in inventory.get('items',{}).values():
                if row.get('kind') in ('unprotected_fact','attributed_opinion') and row.get('source_id') in by_id and by_id[row['source_id']]['url'] in allowed_urls:
                    neutral.append({k:row.get(k) for k in ('source_id','kind','subject','relation','value','qualifiers')})
        facts=[]
        claims=list(r.get('claims',[]))+[claim for row in r.get('special_evidence',{}).values() for claim in row.get('claims',[])]
        for claim in claims:
            source=by_id.get(claim.get('source_id'))
            if source and source['url'] in allowed_urls and claim.get('quote','').strip() and any(claim['quote'] in b['text'] for b in source['blocks']):
                facts.append({k:claim.get(k) for k in ('source_id','fact','sensitive')})
        metadata=[{k:s.get(k,'') for k in ('id','url','title','publisher','published')} for s in sources]
        if neutral or facts:return {'neutral_facts':neutral,'previously_grounded_facts':facts,'sources':metadata,'commission':r['commission']}
        # New research content was never analysed: use the actual full originals, not snippets.
        return {'full_originals':[s for s in self.model_sources(r) if s['url'] in allowed_urls],'commission':r['commission']}


def admit(root,daily,ledger,now=None):
    now=now or datetime.now(p.TZ);today=now.date().isoformat();day=now.astimezone(timezone.utc).date().isoformat()
    from scripts import release_queue
    if not release_queue.edition_exists(root,today):return False,'CURRENT_DAILY_NOT_PUBLISHED'
    if not daily or daily.get('version')!=43 or daily.get('branch')!='main' or daily.get('preview') is not False:return False,'DAILY43_STATE_REQUIRED'
    if not daily43.reserve_rows({},now):return False,'DAILY_RESERVE_UNAVAILABLE'
    if ledger.get('day')!=day or type(ledger.get('requests')) is not int:return False,'CURRENT_SHARED_LEDGER_REQUIRED'
    if 220-ledger['requests']<=sc.definition()['daily_reserve_requests']:return False,'DAILY_QUOTA_RESERVED'
    if any(until>now.timestamp() for until in ledger.get('cooldowns',{}).values()):return False,'GEMINI_COOLDOWN'
    return True,'CURRENT_DAILY_AND_RESERVE_PROTECTED'


def validate_ready(state):
    if not sc.is_special(state):raise p.Blocked('SPECIAL_CONTRACT_INVALID')
    rows=sorted(e.select_ready(state),key=lambda r:r.get('special_slot',0))
    if [r.get('special_slot') for r in rows]!=list(range(1,9)):raise p.Blocked('SPECIAL_EIGHT_TOPICS_REQUIRED')
    for r in rows:
        slot=sc.definition()['slots'][r['special_slot']-1];plan=sc.evidence_plan(slot)
        allowed={plan['primary'],*plan['support'],*r.get('special_study_urls',[])}
        if r['url'] not in allowed or r['source']['url']!=r['url'] or r.get('original_urls')!=slot['original_urls'] or r['article']['category']!=slot['category']:raise p.Blocked('SPECIAL_TOPIC_OR_SOURCE_CHANGED')
        if r['special_slot']==2:
            from scripts.special003r import unsupported_palette
            if unsupported_palette(' '.join(b['text'] for b in r['article']['blocks'])):raise p.Blocked('UNSUPPORTED_HUNDRED_SHADES')
        if r['special_slot'] in (6,7):
            found={s['url'] for s in [r['source']]+r.get('supporting_sources',[]) if s.get('full_text_verified')}
            if not r.get('special_study_urls') or not set(r['special_study_urls'])<=found:raise p.Blocked('SPECIAL_FULL_STUDY_REQUIRED')
    state['selected_ids']=[r['id'] for r in rows];state['audit_passed']=True
    return rows


def advance(state,editor,root,persist):
    editor.state=state
    for r in state['candidates']:
        if e.eligible(r):continue
        if r.get('status') not in ('preparing','discovered','retryable_error'):continue
        try:editor.finish(state,r);state['articles'][r['id']]=r['article'];persist()
        except runtime.GenerationPaused:persist();raise
        except Exception as exc:
            count=r.get('special43_failures',0)+1;r['special43_failures']=count
            r.setdefault('history',[]).append({'stage':'special43','code':getattr(exc,'code',type(exc).__name__)})
            r['status']='needs_review' if isinstance(exc,p.Blocked) or count>=2 else 'retryable_error'
            print('[special43-refusal] '+json.dumps({'slot':r['special_slot'],'code':getattr(exc,'code',type(exc).__name__),'status':r['status']}),flush=True);persist()
    if len(e.select_ready(state))==8:validate_ready(state);persist();return True
    if not any(r['status'] in ('preparing','discovered','retryable_error') for r in state['candidates']):state.update(status='BLOCKED',block_code='SPECIAL43_TOPICS_NEED_REVIEW')
    return False



def material_source(source):
    return {**{k:source.get(k) for k in ('url','title','author','published','declared_license','language','metadata_status')},
        'blocks':[{k:block.get(k) for k in ('kind','text','heading_level','list_kind','list_index','list_depth')} for block in source['blocks']]}


def verify_sources(state,persist):
    for r in validate_ready(state):
        for source in [r['source']]+r.get('supporting_sources',[]):
            current=source41.fetch(source['url'])
            changed=[k for k in ('content_hash','title','published','declared_license') if current.get(k)!=source.get(k)]
            if changed==['content_hash'] and r['mode']=='INDEPENDENT_ARTICLE' and material_source(current)==material_source(source):
                grant=rights41.decision(current,'INDEPENDENT_ARTICLE')
                rights41.require(current,'INDEPENDENT_ARTICLE',grant)
                r.setdefault('current_source_checks',{})[source['url']]={'content_hash':current['content_hash'],'material_unchanged':True,'checked_at':datetime.now(timezone.utc).isoformat()}
                persist()
                print('[special43-source-change] '+json.dumps({'slot':r['special_slot'],'code':'NONEDITORIAL_TRANSPORT_ONLY'}),flush=True)
                continue
            if changed:
                print('[special43-source-change] '+json.dumps({'slot':r['special_slot'],'url':source['url'],'fields':changed,'same_text':[b['text'] for b in source['blocks']]==[b['text'] for b in current['blocks']]}),flush=True)
                r.setdefault('previous_preparations',[]).append({'article':r.pop('article'),'source':r['source']})
                r['source']=current if source['url']==r['url'] else r['source']
                r['supporting_sources']=[current if item['url']==source['url'] else item for item in r.get('supporting_sources',[])]
                state.setdefault('source_cache',{})[source['url']]=current
                r.setdefault('previous_source_inventories',[]).append(r['progress'].pop('neutral_inventories',{}))
                r['status']='preparing';r['checks'].pop('final43',None);state['audit_passed']=False;persist()
                raise p.Blocked('SPECIAL43_SOURCE_CHANGED_REVIEW_REQUIRED')


def emit(state,used=0):
    if used:state['special43_runs']=state.get('special43_runs',0)+1
    if state.get('special43_runs',0)>=32 and state.get('status')!='PUBLISHED':state.update(status='BLOCKED',block_code='SPECIAL43_RUN_LIMIT')
    cont=not state.get('publication_verified') and state.get('status')!='BLOCKED' and (any(r['status'] in ('preparing','discovered','retryable_error') for r in state['candidates']) or state.get('audit_passed'))
    value={'articles':sum(e.eligible(r) for r in state['candidates']),'slots':[{'slot':r['special_slot'],'status':r['status']} for r in state['candidates']],
           'run_used':used,'requests_used':state.get('_quota_snapshot',{}).get('requests'),'continue_special':cont,'daily_hold':False,'status':state.get('status')}
    print('[special43-status] '+json.dumps(value),flush=True)
    with open(os.environ['GITHUB_OUTPUT'],'a') as stream:stream.write('hold_daily=false\nrun_used='+str(used)+'\ncontinue_special='+str(cont).lower()+'\n')
