"""One owner-authorized priority, stored inside the existing special checkpoint."""
from datetime import datetime,timedelta
import json,os
from scripts import policy41 as p,special_contract41 as sc


def config():
    value=json.loads((p.ROOT/'config/production-priority.json').read_text())
    if (value.get('edition')!=sc.ID or value.get('id')!='003-R-first-2026-10-27'
            or type(value.get('enabled')) is not bool
            or value.get('maximum_active_hours')!=72 or value.get('maximum_productive_runs')!=64
            or value.get('maximum_stalled_runs')!=4):raise RuntimeError('SPECIAL_PRIORITY_CONFIG_INVALID')
    return value


def reconcile(state,now=None):
    cfg=config();now=now or datetime.now(p.TZ)
    if not cfg['enabled']:return False,'PRIORITY_DISABLED'
    priority=state.setdefault('production_priority',{'id':cfg['id'],'started_at':now.isoformat(),
        'status':'ACTIVE','productive_runs':0,'stalled_runs':0})
    if priority.get('id')!=cfg['id']:raise RuntimeError('SPECIAL_PRIORITY_ID_MISMATCH')
    if state.get('publication_verified'):
        priority.update(status='COMPLETED',reason='SPECIAL_HTTPS_VERIFIED');return False,priority['reason']
    if priority['status']!='ACTIVE':return False,priority.get('reason','SPECIAL_PRIORITY_TERMINAL')
    reason=None
    if now-datetime.fromisoformat(priority['started_at'])>=timedelta(hours=cfg['maximum_active_hours']):reason='SPECIAL_PRIORITY_TIME_LIMIT'
    elif priority['productive_runs']>=cfg['maximum_productive_runs']:reason='SPECIAL_PRIORITY_RUN_LIMIT'
    elif priority['stalled_runs']>=cfg['maximum_stalled_runs']:reason='SPECIAL_PRIORITY_STALLED'
    elif any(r.get('status')=='needs_review' for r in state['candidates']) and not any(r.get('status') in ('discovered','preparing','retryable_error') for r in state['candidates']):reason='SPECIAL_TOPIC_NEEDS_REVIEW'
    elif state.get('status')=='BLOCKED':reason=state.get('block_code','SPECIAL_BLOCKED')
    if reason:
        priority.update(status='BLOCKED',reason=reason)
        return False,reason
    return True,'SPECIAL_FIRST_OWNER_AUTHORIZED'


def fingerprint(state):
    return p.digest([{'id':r['id'],'status':r['status'],'checks':r.get('checks',{}),
        'analysis':r.get('progress',{}).get('analysis',{}),'sections':r.get('progress',{}).get('sections',{}),
        'translated':r.get('progress',{}).get('translated',{}),'evidence':r.get('special_evidence',{}),
        'support':{url:item.get('progress',{}).get('analysis',{}) for url,item in r.get('progress',{}).get('special_support',{}).items()}}
        for r in state['candidates']]+[state.get('audit_passed')])


def finish_run(state,before,used):
    priority=state.get('production_priority')
    if priority and priority['status']=='ACTIVE' and used:
        priority['productive_runs']+=1
        priority['stalled_runs']=priority['stalled_runs']+1 if fingerprint(state)==before else 0


def emit(state,used=0):
    hold,reason=reconcile(state)
    value={'id':sc.ID,'priority':state.get('production_priority',{}).get('status','DISABLED'),'hold_daily':hold,'reason':reason,
        'articles':sum(r.get('status')=='ready' for r in state['candidates']),
        'slots':[{'slot':r['special_slot'],'status':r['status'],
                  'sections':len(r.get('progress',{}).get('sections',{})),
                  'code':(r.get('history') or [{}])[-1].get('code')} for r in state['candidates']],
        'run_used':used,'publication_verified':bool(state.get('publication_verified'))}
    print('[special-priority] '+json.dumps(value),flush=True)
    with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
        stream.write('hold_daily='+str(hold).lower()+'\nrun_used='+str(used)+'\n')
    return value


def repair_real_run_v2(state):
    """Address only failures demonstrated in run 40454216057; no accounting resets."""
    if state.get('special_real_repair_revision')==2:return
    changed=[]
    for record in state['candidates']:
        code=(record.get('history') or [{}])[-1].get('code')
        if record.get('status')=='needs_review' and code in ('EVENT_DATE_UNVERIFIED','REVIEW_REJECTED'):
            record['status']='preparing';changed.append(record['special_slot'])
            record['commission']['kind']='Явно обозначенная неоперативная статья переиздания. Не выдавать старое событие за новую новость. Все даты и факты внутри текста требуют независимой проверки.'
    priority=state.get('production_priority',{})
    if changed and priority.get('reason')=='SPECIAL_TOPIC_NEEDS_REVIEW' and not any(r.get('status')=='needs_review' for r in state['candidates']):
        priority.setdefault('repair_history',[]).append({'revision':2,'previous_status':priority['status'],'reason':priority['reason'],'slots':changed})
        priority['status']='ACTIVE';priority.pop('reason',None)
    state['special_real_repair_revision']=2
    print('[special-repair-migration] '+json.dumps({'revision':2,'slots':changed,'quota_and_attempts_preserved':True}),flush=True)


def repair_protocol_v3(state):
    if state.get('special_protocol_repair_revision')==3:return
    changed=[]
    for record in state['candidates']:
        from scripts import content41 as content
        rejection=record.get('rejected_part',{});rejected=rejection.get('result',{})
        if record.get('status')=='needs_review' and (record.get('history') or [{}])[-1].get('code')=='REVIEW_REJECTED' and rejection.get('scope')!='article_independence':
            article=record.get('article')
            if article:
                parts=content.chunks(article['blocks'])
                for item in article.get('activities',[]):
                    parts.extend(content.chunks([{'id':'activity/'+item['id'],'kind':'paragraph','text':json.dumps(item,ensure_ascii=False)}]))
                completed=record['progress'].get('reviews',{}).get(rejection.get('stage'),{}).get('parts',{})
                pending=[part for part in parts if part['id'] not in completed]
                groups=content.operation_groups(pending,limit=p.CONFIG['technical']['review_operation_characters'])
                ids=rejected.get('covered_ids',[])
                mismatch=bool(groups) and (not isinstance(ids,list) or len(ids)!=len(set(ids)) or set(ids)!={part['id'] for part in groups[0]})
                print('[special-refusal-diagnostic] '+json.dumps({'slot':record['special_slot'],'approve':rejected.get('approve'),
                    'issues_count':len(rejected.get('issues',[])),'unresolved_count':len(rejected.get('unresolved',[])),
                    'protocol_mismatch':mismatch}),flush=True)
                if mismatch:
                    record['status']='preparing';changed.append(record['special_slot'])
    priority=state.get('production_priority',{})
    if changed and priority.get('reason')=='SPECIAL_TOPIC_NEEDS_REVIEW' and not any(r.get('status')=='needs_review' for r in state['candidates']):
        priority.setdefault('repair_history',[]).append({'revision':3,'reason':priority['reason'],'slots':changed})
        priority['status']='ACTIVE';priority.pop('reason',None)
    state['special_protocol_repair_revision']=3
    print('[special-protocol-migration] '+json.dumps({'revision':3,'slots':changed,'counters_preserved':True}),flush=True)


def repair_independence_protocol_v4(state):
    if state.get('independence_protocol_revision')==4:return
    changed=[];recovered=[]
    expected={'composition','wording','examples','explanations'}
    for record in state['candidates']:
        rejection=record.get('rejected_part',{});result=rejection.get('result',{})
        if rejection.get('scope')=='article_independence':
            formal=(result.get('approve') is True and not result.get('issues') and not result.get('unresolved') and set(result.get('covered_ids',[]))!=expected)
            print('[independence-refusal-diagnostic] '+json.dumps({'slot':record['special_slot'],
                'approve':result.get('approve') is True,'issues_count':len(result.get('issues',[])),
                'unresolved_count':len(result.get('unresolved',[])),'coverage_complete':set(result.get('covered_ids',[]))==expected,
                'formal_only':formal}),flush=True)
            if record.get('status')=='needs_review' and formal:
                if recover_complete_independence(state,record):recovered.append(record['special_slot'])
                else:record['status']='preparing'
                changed.append(record['special_slot'])
    priority=state.get('production_priority',{})
    if changed and priority.get('reason')=='SPECIAL_TOPIC_NEEDS_REVIEW':
        priority.setdefault('repair_history',[]).append({'revision':4,'formal_recheck_slots':changed})
        priority['status']='ACTIVE';priority.pop('reason',None)
        if state.get('block_code')=='SPECIAL_EIGHT_FIXED_TOPICS_NOT_READY':
            state['status']='RETRY_PENDING';state.pop('block_code',None)
    state['independence_protocol_revision']=4
    print('[independence-protocol-migration] '+json.dumps({'revision':4,'slots':changed,'locally_recovered':recovered,'articles_and_counters_preserved':True}),flush=True)


def recover_complete_independence(state,record):
    """Replay a complete, real positive audit; never infer a missing approval/check."""
    from scripts import editorial41 as e,content41 as c,rights41
    from scripts.special003r import unsupported_palette
    result=c.legacy_independence_response(record.get('rejected_part',{}).get('result',{}))
    if result is None or state.get('all_sources_independence_revision')!=1 or not record.get('article'):return False
    article=record['article'];source=record['source'];fp=e.article_hash(article,source,record['rights'])
    if any(not e.valid_gate(record,name,fp) for name in ('content_prepared','fact_checked','completeness_checked')):return False
    source_gate=record.get('checks',{}).get('source_verified',{})
    expected=p.digest({'source':source['content_hash'],'rights':record['rights'],'images':record.get('images',[])})
    if not source_gate.get('approved') or source_gate.get('input_hash')!=expected or not source_gate.get('special_evidence_complete'):return False
    review=record['progress'].get('reviews',{}).get('editorial_checked',{})
    if review.get('input_hash')!=fp:return False
    if any(not block.get('id') for block in article['blocks']):return False
    parts=c.chunks(article['blocks'])
    for item in article.get('activities',[]):parts.extend(c.chunks([{'id':'activity/'+item['id'],'kind':'paragraph','text':json.dumps(item,ensure_ascii=False)}]))
    for part in parts:
        verdict=review.get('parts',{}).get(part['id'],{})
        if verdict.get('approve') is not True or verdict.get('issues') or verdict.get('unresolved') or part['id'] not in verdict.get('covered_ids',[]):return False
    if article['category']!=record['category_hint'] or (record['special_slot']==2 and unsupported_palette(c.body(article))):return False
    try:
        rights41.require(source,article['mode'],record['rights']);c.semantic_structure(article,source)
        c.approved_review(result,list(c.INDEPENDENCE_FIELDS))
    except p.Blocked:return False
    review.update(independence_hash=fp,independence_result=result,independence_scope='all_commissioned_sources_v1')
    for name in ('editorial_checked','ready_to_publish'):
        record['checks'][name]={'approved':True,'input_hash':fp,'revalidated_from':'complete_positive_legacy_audit'}
    record['status']='ready';state['articles'][record['id']]=article
    e.event(state,record,'independence_protocol','approved','COMPLETE_POSITIVE_AUDIT_REVALIDATED')
    return True
