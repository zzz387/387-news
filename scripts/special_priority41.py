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
    elif any(r.get('status')=='needs_review' for r in state['candidates']):reason='SPECIAL_TOPIC_NEEDS_REVIEW'
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
