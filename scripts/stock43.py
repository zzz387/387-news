"""Editorial inventory inside the existing Actions AES-GCM checkpoint mechanism.

No plaintext artifact, new key, database, model client or independent generator.
"""
import copy,json
from datetime import datetime,timedelta
from pathlib import Path
from scripts import editorial43 as e,selection43 as sel,policy41 as p,rights41,editorial41

LABEL='387news43-editorial-stock'

def empty():return {'version':1,'records':[],'light':[],'backlog':[],'published_urls':[]}

def ensure(state):return state.setdefault('stock43',empty())

def source_urls(row):return {u for u in (row.get('url'),row.get('source',{}).get('url'),row.get('source',{}).get('canonical')) if u}

def identity(row):return p.digest({'url':row.get('url'),'article':row.get('article',{})})

def merge(state,incoming):
    stock=ensure(state)
    if not incoming:return stock
    if incoming.get('version')!=1:raise RuntimeError('STOCK_VERSION_INVALID')
    newer=incoming.get('updated_at','')>stock.get('updated_at','')
    state['_stock_backup_newer43']=newer
    if newer:stock['updated_at']=incoming['updated_at']
    stock['published_urls']=sorted(set(stock.get('published_urls',[]))|set(incoming.get('published_urls',[])))
    for key in ('records','light','backlog'):
        record_key=(lambda r:r['url']) if key=='backlog' else identity
        rows={record_key(r):r for r in incoming.get(key,[])}
        for row in stock.get(key,[]):
            k=record_key(row)
            if k not in rows:rows[k]=row
            elif key=='backlog' and not newer:rows[k]=row
            elif key!='backlog':
                incoming_row=rows[k]
                incoming_row['stock_published']=bool(incoming_row.get('stock_published') or row.get('stock_published'))
                if not incoming_row.get('stock_reserved_for') and row.get('stock_reserved_for'):incoming_row['stock_reserved_for']=row['stock_reserved_for']
        stock[key]=list(rows.values())
    return stock

def published(root):
    urls={r.get('source_url') for r in editorial41.archive_entries(Path(root))}
    for path in Path(root).glob('issues/*/release.json'):
        data=json.loads(path.read_text())
        urls.update(r.get('source',{}).get('url') for r in data.get('light_news',[]))
    return urls-{None,''}

def reconcile(state,root):
    stock=ensure(state);stock['published_urls']=sorted(set(stock['published_urls'])|published(root))
    for key in ('records','light','backlog'):
        for row in stock[key]:
            if source_urls(row)&set(stock['published_urls']):
                row['stock_published']=True
                stock['published_urls']=sorted(set(stock['published_urls'])|source_urls(row))
            reserved=row.get('stock_reserved_for')
            if reserved and (Path(root)/'issues'/reserved/'index.html').exists() and not row.get('stock_published'):row.pop('stock_reserved_for',None)
    return stock

def reusable(row,date,used=()):
    if row.get('stock_published') or source_urls(row)&set(used):return False
    from scripts import light44
    brief=light44.eligible(row)
    if not brief and (not e.eligible(row) or row.get('checks',{}).get('final43',{}).get('is_news') is not False):return False
    if brief and row.get('light_kind')=='news':return False
    # Clinical/legal/childcare advice is not silently carried into another day.
    # Such work stays in its original checkpoint until fresh normal safety review.
    if e.high_risk(row):return False
    try:
        checked=datetime.fromisoformat(row['ready_checked_at']);checked=checked.replace(tzinfo=p.TZ) if checked.tzinfo is None else checked
        at=datetime.fromisoformat(date+'T06:00').replace(tzinfo=p.TZ)
        if not -timedelta(days=1)<=at-checked<=timedelta(days=e.CONFIG['reserve_max_age_days']):return False
        rights41.require(row['source'],row['article']['mode'],rights41.decision(row['source'],row['article']['mode']))
    except (KeyError,ValueError,p.Blocked):return False
    return True

def available(state,date,key='records',include_reserved=False):
    stock=ensure(state);used=set(stock['published_urls'])
    rows=[r for r in stock[key] if reusable(r,date,used) and (not r.get('stock_reserved_for') or include_reserved and r['stock_reserved_for']==date)]
    from scripts import policy44,light44
    if key=='light' and policy44.active(state):
        result=[]
        for row in rows:
            if not any(light44.duplicate(row,other) for other in result):result.append(row)
        return result
    return sel.unique_ready(rows)

def bank(state,row,now,key='records'):
    stock=ensure(state)
    if not reusable(row,state['date'],stock['published_urls']):return False
    rows=stock[key]
    from scripts import policy44,light44
    compare=light44.duplicate if key=='light' and policy44.active(state) else sel.duplicate
    if any(identity(row)==identity(r) or compare(row,r) for r in rows if not r.get('stock_published')):return False
    cap=e.CONFIG.get('article_stock_target',20) if key=='records' else e.CONFIG.get('light_stock_target',15)
    if len(available(state,state['date'],key))>=cap:
        needed={g for g,n in policy44.counts(available(state,state['date'])).items() if n<2}
        if not (key=='records' and policy44.active(state) and policy44.subject(row) in needed):return False
    saved=copy.deepcopy(row);saved['stock_saved_at']=now.isoformat();saved['stock_published']=False
    rows.append(saved);row['status']='reserve_ready'
    return True

def balance(state,root,now):
    """Keep accepted surplus in the same encrypted inventory, never discard it."""
    selected=sel.composition(state)
    for row in sel.ready(state):
        if row not in selected:
            existing=next((r for r in ensure(state)['records'] if identity(r)==identity(row)),None)
            if existing is not None and existing.get('stock_reserved_for')==state['date'] and not existing.get('stock_published'):
                existing.pop('stock_reserved_for');row['status']='reserve_ready'
            else:bank(state,row,now)
    return selected


def draw(state,root,now,target=None):
    reconcile(state,root);target=target or e.CONFIG['article_target'];known={r['url'] for r in state['candidates']}
    history=sel.recent(root,state['date']);selected=sel.composition(state)
    pending=list(available(state,state['date'],include_reserved=True))
    from scripts import policy44
    while pending and (policy44.active(state) or len(selected)<target):
        proxies=[dict(r,status='discovered') for r in pending]
        plan=sel.order(dict(state,candidates=selected+proxies),history,limit=1)
        if not plan:break
        row=next(r for r in pending if identity(r)==identity(plan[0]));pending.remove(row)
        if policy44.active(state) and row.get('stock_prepared_for')==state['date'] and len(selected)>=e.CONFIG['minimum_articles'] and all(n>=2 for n in policy44.counts(selected).values()):continue
        previous=next((r for r in state['candidates'] if r['url']==row['url']),None)
        if previous is not None and previous.get('status')!='reserve_ready':continue
        if any(sel.duplicate(row,r) for r in selected+history):continue
        row['stock_reserved_for']=state['date']
        if previous is not None:
            previous['status']='ready';previous['stock_origin']=identity(row);selected.append(previous)
        else:
            saved=copy.deepcopy(row);saved['stock_origin']=identity(row);saved['status']='ready'
            state['candidates'].append(saved);selected.append(saved);known.add(row['url'])
    if policy44.active(state):policy44.migrate(state)
    return len(selected)

def draw_light(state,root):
    from scripts import light43
    reconcile(state,root);saved=state.setdefault('light43',{'records':[]});rows=saved.setdefault('records',[])
    related=sel.ready(state)+light43.ready(state)+sel.recent(root,state['date'])
    from scripts import policy44
    target=e.CONFIG.get('light_target',12) if policy44.active(state) else 3
    from scripts import light44
    for row in available(state,state['date'],'light',include_reserved=True):
        # A separately commissioned stock batch stays for the following edition.
        # It may rescue THIS issue only if its eight-note minimum becomes short.
        if policy44.active(state) and row.get('stock_prepared_for')==state['date'] and len(light43.ready(state))>=e.CONFIG.get('light_minimum',8):continue
        if not policy44.active(state) and len(light43.ready(state))>=target:break
        if any((light44.duplicate if policy44.active(state) else sel.duplicate)(row,r) for r in related):continue
        row['stock_reserved_for']=state['date']
        copied=copy.deepcopy(row);copied['status']='ready';copied['stock_origin']=identity(row);rows.append(copied);related.append(copied)

def bank_light(state,now):
    from scripts import light43
    from scripts import policy44
    if policy44.active(state):return  # New batches choose issue/stock BEFORE generation.
    keep=3
    for row in light43.ready(state,limit=None)[keep:]:bank(state,row,now,'light')

def sync_backlog(state):
    stock=ensure(state);used=set(stock['published_urls'])
    old={r['url']:r for r in stock['backlog'] if r.get('url') not in used}
    now=datetime.now(p.TZ).isoformat()
    old.update({r['url']:dict(copy.deepcopy(r),stock_issue_date=state['date']) for r in state['candidates'] if r.get('url') not in used})
    stock['updated_at']=now
    stock['backlog']=list(old.values())

def restore_backlog(state,root):
    stock=reconcile(state,root);known={r['url'] for r in state['candidates']}
    for row in stock['backlog']:
        if row['url'] in stock['published_urls']:continue
        existing=next((r for r in state['candidates'] if r['url']==row['url']),None)
        if row.get('status')=='ready':
            # Recover a successful same-issue review if the issue Artifact upload
            # failed but the newer encrypted inventory upload succeeded.
            if row.get('stock_issue_date')==state['date'] and e.eligible(row) and not e.news_errors(row['checks']['final43'],row,state):
                if existing is None:
                    state['candidates'].append(copy.deepcopy(row));known.add(row['url'])
                elif state.get('_stock_backup_newer43') and not e.eligible(existing):
                    existing.clear();existing.update(copy.deepcopy(row))
            elif existing is None and reusable(row,state['date'],stock['published_urls']):
                bank(state,row,datetime.now(p.TZ))
            continue
        if existing is not None:
            if state.get('_stock_backup_newer43') and row.get('stock_issue_date')==state['date'] and not e.eligible(existing) and row.get('status') in ('preparing','retryable_error'):
                existing.clear();existing.update(copy.deepcopy(row))
            continue
        if row.get('stock_issue_date')!=state['date'] and e.high_risk(row):continue
        if row.get('status') not in ('discovered','preparing','retryable_error'):continue
        saved=copy.deepcopy(row)
        if saved.get('checks',{}).get('final43',{}).get('approved'):continue
        state['candidates'].append(saved);known.add(row['url'])
    state.pop('_stock_backup_newer43',None)


def report(state):
    stock=ensure(state);date=state['date']
    prospects=[r for r in state['candidates'] if r.get('status') in ('discovered','preparing','retryable_error') and not r.get('for_light_only') and r.get('url') not in stock['published_urls'] and r.get('source',{}).get('full_text_verified') and r.get('source',{}).get('metadata_status')=='verified']
    from scripts import priorities43
    stock_groups={g:sum(priorities43.classify(r)['group']==g for r in available(state,date)) for g in ('A','C')}
    required=__import__('scripts.policy44',fromlist=['counts']).counts(available(state,date))
    return {'required_topics':required,'family_articles':stock_groups['A'],'health_sport_articles':stock_groups['C'],'prospective_candidates':len(prospects),'candidate_goal':e.CONFIG.get('candidate_stock_target',32),'ready_articles':len(available(state,date)),'ready_light':len(available(state,date,'light')),
            'stored_articles':len(stock['records']),'stored_light':len(stock['light']),
            'backlog':len(stock['backlog']),'article_goal':e.CONFIG.get('article_stock_target',20),
            'light_goal':e.CONFIG.get('light_stock_target',15)}
