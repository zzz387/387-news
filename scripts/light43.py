"""Optional batched light stories: at most two model calls per issue, never a gate."""
import copy,json,re,os
from collections import Counter
from datetime import datetime,timezone
try:from scripts import editorial43 as e,content41,news,policy41 as p,rights41,selection43
except ImportError:import editorial43 as e,content41,news,policy41 as p,rights41,selection43

S={'type':'string'}
news.SCHEMAS['v43_light_write']=content41.schema({'items':{'type':'array','items':content41.schema({'id':S,'source_id':S,'title':S,'text':S})}})
review=copy.deepcopy(news.SCHEMAS['v43_final']);review['properties']['id']=S;review['required'].append('id')
news.SCHEMAS['v43_light_review']=content41.schema({'reviews':{'type':'array','items':review}})


def story_suitable(row):
    """No topical, humorous or positive-news gate. Safety is content-specific."""
    from scripts import light44
    return not light44.dangerous(selection43.story_context(row))


def recent(root):
    from pathlib import Path
    rows=[]
    for path in Path(root).glob('issues/*/release.json'):
        for item in json.loads(path.read_text()).get('light_news',[]):
            rows.append({'title':item['title'],'summary':item.get('text',''),'url':item.get('source',{}).get('url','')})
    return rows

def main_work(state):
    # Accepted long work has priority, including unselected encrypted reserve.
    rows=selection43.ready(state)
    rows += [r for r in state.get('stock43',{}).get('records',[]) if e.eligible(r)]
    return rows

def reserve_accepted_sources(state,rows):
    urls={r['source']['url'] for r in rows};queue=state.setdefault('light43_queue',[])
    for candidate in state['candidates']:
        if candidate['url'] in urls and candidate.get('status') in ('discovered','preparing','retryable_error'):
            candidate['for_light_only']=True
            if candidate['id'] not in queue:queue.append(candidate['id'])


def ready(state,limit=None):
    from scripts import policy44,light44
    if policy44.active(state):return light44.ready(state)
    result=[];mains=main_work(state)
    for row in state.get('light43',{}).get('records',[]):
        if not e.eligible(row):continue
        try:rights41.require(row['source'],'INDEPENDENT_ARTICLE',rights41.decision(row['source'],'INDEPENDENT_ARTICLE'))
        except p.Blocked:continue
        if e.news_errors(row.get('checks',{}).get('final43',{}),row,state):continue
        if any(selection43.duplicate(row,x) for x in mains+result+state.get('_recent_light43',[])):continue
        result.append(row)
    return result if limit is None else result[:limit]


def safe_record(item,source):
    text=item['text'].strip()
    if not text or len(re.split(r'(?<=[.!?])\s+(?=[А-ЯA-Z])',text))>3:raise p.Blocked('LIGHT_FORMAT')
    grant=rights41.decision(source,'INDEPENDENT_ARTICLE');rights41.require(source,'INDEPENDENT_ARTICLE',grant)
    row={'id':item['id'],'url':source['url'],'source':source,'rights':grant,'mode':'INDEPENDENT_ARTICLE','category_hint':'Наука','category':'Наука','status':'preparing','checks':{},'progress':{},'history':[],
         'article':{'title':item['title'],'teaser':'','blocks':[{'kind':'paragraph','text':text}],'mode':'INDEPENDENT_ARTICLE','category':'Наука','kind':'Короткая новость','activities':[]}}
    e.normalize(row['article']);e.structure(row)
    if e.high_risk(row):raise p.Blocked('LIGHT_HIGH_RISK_EXCLUDED')
    return row


def sources_for_batch(state,excluded=()):
    selected=[];mains=main_work(state)
    excluded=set(excluded)|set(state.get('stock43',{}).get('published_urls',[]))
    for row in sorted(state['candidates'],key=lambda r:(r['id'] not in state.get('light43_queue',[]),not r.get('for_light_only',False))):
        src=row.get('source')
        if row.get('status')=='preparing' and row.get('article') and not row.get('for_light_only'):continue
        if not src or src['url'] in excluded or src['url'] in {s['url'] for s in selected}:continue
        if not src.get('full_text_verified') or src.get('metadata_status')!='verified' or not story_suitable(row):continue
        if any(selection43.duplicate(row,r) for r in mains+state.get('_recent_light43',[])):continue
        if rights41.decision(src,'INDEPENDENT_ARTICLE')['status']=='allowed':selected.append(src)
        if len(selected)>=5:break
    return selected


def batch_records(saved,state):
    sources=saved.get('sources',[]);diagnostics=[];records=[]
    if not sources:return records,diagnostics
    _,aliases=e.review_wire({'source':sources[0],'supporting_sources':sources[1:]})
    by_alias={alias:src for alias,(src,_) in aliases.items()}
    draft=saved.get('draft',{});items=draft.get('items',[]) if isinstance(draft,dict) else []
    items=items[:5] if isinstance(items,list) else []
    ids=Counter(item.get('id') for item in items if isinstance(item,dict) and isinstance(item.get('id'),str))
    for index,item in enumerate(items):
        codes=[]
        try:
            if not isinstance(item,dict):raise p.Blocked('LIGHT_ITEM_FORMAT')
            item_id=item.get('id')
            if not isinstance(item_id,str) or not item_id.strip() or ids[item_id]!=1:raise p.Blocked('LIGHT_ID_AMBIGUOUS')
            reference=item.get('source_id');src=by_alias.get(reference)
            if src is None:
                matches=[src for src in sources if reference in (src.get('id'),src.get('url'),src.get('canonical'))]
                if len(matches)!=1:raise p.Blocked('LIGHT_SOURCE_UNBOUND')
                src=matches[0]
            row=safe_record(item,src)
            if any(selection43.duplicate(row,r) for r in main_work(state)+records+state.get('_recent_light43',[])):raise p.Blocked('LIGHT_DUPLICATE')
            records.append(row)
        except (KeyError,TypeError,ValueError) as exc:codes=[getattr(exc,'code','LIGHT_ITEM_FORMAT')]
        diagnostics.append({'item':index+1,'codes':codes})
    return records,diagnostics


def apply_batch_review(saved,state):
    records,diagnostics=batch_records(saved,state);sources=saved.get('sources',[])
    if not sources:return []
    _,aliases=e.review_wire({'source':sources[0],'supporting_sources':sources[1:]})
    by_id={};ambiguous=set()
    review=saved.get('review',{});reviews=review.get('reviews',[]) if isinstance(review,dict) else []
    for result in reviews if isinstance(reviews,list) else []:
        if not isinstance(result,dict) or not isinstance(result.get('id'),str):continue
        item_id=result['id']
        if item_id in by_id:ambiguous.add(item_id)
        by_id[item_id]=result
    accepted=[]
    for row in records:
        codes=[];result=by_id.get(row['id'])
        if row['id'] in ambiguous:codes=['LIGHT_REVIEW_ID_AMBIGUOUS']
        elif result is None:codes=['LIGHT_REVIEW_MISSING']
        elif saved.get('review_inputs',{}).get(row['id'])!=e.fingerprint(row):codes=['LIGHT_REVIEW_INPUT_CHANGED']
        else:
            try:
                verdict,errors=e.bind_review(result,row,aliases,e.fingerprint(row));codes+=errors
                codes+=['CHECK_'+k.upper() for k in e.CHECKS if verdict.get(k) is not True]
                if verdict.get('approve') is not True:codes.append('LIGHT_REVIEW_VETO')
                if verdict.get('issues')!=[] or verdict.get('unresolved')!=[]:codes.append('LIGHT_UNRESOLVED')
                codes+=e.news_errors(verdict,row,state)
                if any(c.get('source_id')!=row['source']['id'] or not any(c.get('quote','') in b['text'] for b in row['source']['blocks']) for c in verdict.get('claims',[])):codes.append('LIGHT_PRIMARY_WITNESS_MISMATCH')
                if not codes:
                    row['light_kind']='news' if verdict['is_news'] else 'historical_fact' if re.search(r'(?i)истор|древн|history|ancient',row['article']['title']) else 'unusual_fact'
                    row['checks']['final43']=dict(verdict,approved=True);row['ready_checked_at']=datetime.now(p.TZ).isoformat();row['status']='ready';accepted.append(row)
            except (KeyError,TypeError,ValueError):codes.append('LIGHT_REVIEW_FORMAT')
        index=next(i for i,item in enumerate(saved['draft']['items'][:5]) if item.get('id')==row['id'])
        diagnostics[index]['codes']=sorted(set(codes))
    saved['diagnostics']=diagnostics
    return accepted


def diagnose_saved(state):
    """Safe counts/codes only. Old missing verdicts cannot be reconstructed."""
    saved=state.get('light43',{});records,normalization=batch_records(saved,state)
    if saved.get('review'):apply_batch_review(saved,state)
    reasons=Counter(code for item in saved.get('diagnostics',normalization) for code in item['codes'])
    reviewed=[r for r in saved.get('records',[]) if r.get('status') in ('ready','reserve_ready') and e.eligible(dict(r,status='ready'))]
    summary={'stored_records':len(saved.get('records',[])),'reviewed_records':len(reviewed),'main_conflicts':sum(any(selection43.duplicate(r,m) for m in main_work(state)) for r in reviewed),'sources':len(saved.get('sources',[])),'written':len(saved.get('draft',{}).get('items',[]) or []) if isinstance(saved.get('draft',{}),dict) else 0,
        'normalized':len(records),'normalization_rejected':sum(bool(d['codes']) for d in normalization),
        'accepted':len(ready(state)),'rejection_codes':dict(reasons),
        'review_retained':bool(saved.get('review')),'legacy_review_unavailable':bool(saved.get('review_attempts') and not saved.get('review')),
        'batches':1+len(saved.get('batches',[])) if saved else 0,'http_requests':saved.get('http_requests',0)}
    saved['summary']=summary
    print('[light43-diagnostic] '+json.dumps(summary),flush=True)
    return summary


def prepare(state,persist=lambda:None,editor=None):
    from scripts import policy44,light44
    if policy44.active(state):return light44.prepare(state,persist)
    saved=state.setdefault('light43',{'write_attempts':0,'review_attempts':0,'records':[]})
    for key,value in (('write_attempts',0),('review_attempts',0),('records',[]),('http_requests',0)):saved.setdefault(key,value)
    reserve_accepted_sources(state,ready(state))
    # Nested transport counters survive a crash before the call's finally block.
    saved['http_requests']=max(saved['http_requests'],sum(v.get('http_requests',0) for v in saved.get('model_usage',{}).values()))
    if saved.get('review') and not saved.get('complete'):
        recovered=apply_batch_review(saved,state);existing={r['id'] for r in saved['records']}
        saved['records'] += [r for r in recovered if r['id'] not in existing]
        saved['complete']=True;saved['code']='LIGHT_ACCEPTED' if recovered else 'LIGHT_ALL_REJECTED';reserve_accepted_sources(state,recovered);persist()
    window=os.getenv('GITHUB_RUN_ID','local-window')+':'+os.getenv('GITHUB_RUN_ATTEMPT','1')
    batch_http=saved['http_requests']-saved.get('batch_http_start',0)
    failed_write=(not saved.get('draft') and saved['write_attempts']-saved.get('batch_write_start',0)>=1 and batch_http>0)
    finished=saved.get('complete') or bool(saved.get('review')) or batch_http>=2 or failed_write
    if finished:
        diagnose_saved(state)
        if ready(state) or saved.get('batches') or saved.get('attempt_window')==window:return
        excluded={s['url'] for s in saved.get('sources',[])}
        sources=sources_for_batch(state,excluded)
        if not sources:return
        # Exactly one replacement batch, in another production window. Original
        # sources, counters, draft, review and diagnoses remain in the checkpoint.
        previous={k:copy.deepcopy(v) for k,v in saved.items() if k not in ('records','batches','model_usage')}
        saved.setdefault('batches',[]).append(previous)
        for key in ('draft','review','review_inputs','complete','code','diagnostics'):saved.pop(key,None)
        saved.pop('attempt_window',None)
        saved.update(sources=sources,batch_http_start=saved['http_requests'],batch_write_start=saved['write_attempts'],batch_review_start=saved['review_attempts'])
        persist()
    budget=news.runtime.ACTIVE_BUDGET
    remaining=2-(saved['http_requests']-saved.get('batch_http_start',0));needed=1 if saved.get('draft') else 2
    keep=max(4,2*max(0,e.CONFIG['minimum_articles']-len(selection43.composition(state))))
    if not budget or remaining<needed or not budget.can_request() or budget.remaining_requests()<needed+keep:return
    used_today=budget.ledger.get('requests',0) if budget.ledger.get('day')==datetime.now(timezone.utc).date().isoformat() else 0
    if used_today+needed>budget.day_limit-24:return
    editor=editor or e.Editor(persist=persist);editor.state=state;editor.usage_record=saved
    original_limit=budget.run_limit;start_used=budget.used;start_requests=saved['http_requests']
    budget.run_limit=min(original_limit,budget.used+remaining)
    saved.setdefault('attempt_window',window)
    try:
        if not saved.get('draft'):
            if saved['write_attempts']-saved.get('batch_write_start',0)>=1 and saved['http_requests']-saved.get('batch_http_start',0)>0:return
            sources=saved.get('sources') or sources_for_batch(state)
            if not sources:saved['code']='LIGHT_NO_VERIFIED_SOURCES';return
            saved['sources']=sources
            wire,_=e.review_wire({'source':sources[0],'supporting_sources':sources[1:]})
            prompt='Рубрика «НЕ ВСЁ ТАК СЕРЬЁЗНО»: до пяти независимых коротких добрых, удивительных фактов. Заголовок и1–3 предложения. Без политики, трагедий, болезней, насмешек, выдумок и скрытого перевода. Можно меньше пяти или пустой список. Только факты полных оригиналов. Старое не выдавай за сегодняшнее. Для каждой заметки уникальный id и source_id строго sN из списка источников. Один источник на заметку; каждый факт должен подтверждаться именно им. Не повторяй основные сюжеты: '+json.dumps(selection43.prompt_context(state),ensure_ascii=False)+'\nПолные источники: '+json.dumps(wire,ensure_ascii=False)
            if saved['write_attempts']==saved.get('batch_write_start',0):saved['write_attempts']+=1
            persist();saved['draft']=editor.call(prompt,output_tokens=4000,schema='v43_light_write');persist()
        records,normalization=batch_records(saved,state);saved['diagnostics']=normalization
        if not records:saved['complete']=True;saved['code']='LIGHT_NORMALIZATION_REJECTED';return
        if not saved.get('review'):
            if saved['review_attempts']-saved.get('batch_review_start',0)>=1 and saved['http_requests']-saved.get('batch_http_start',0)>=2:return
            sources=saved['sources'];wire,_=e.review_wire({'source':sources[0],'supporting_sources':sources[1:]})
            saved['review_inputs']={r['id']:e.fingerprint(r) for r in records}
            if saved['review_attempts']==saved.get('batch_review_start',0):saved['review_attempts']+=1
            persist()
            saved['review']=editor.call('Одна независимая пакетная проверка коротких заметок политики4.3. Для каждого id из заметок оцени все семь критериев v43_final: факты, безопасность, права, самостоятельность, заголовок и законченность. Проверяй смысл каждого факта и дословную цитату. Для claims source_id=sN и evidence_id=qN строго из полного оригинала. Каждый факт заметки подтверждается её единственным source_id. Верни is_news=true только если это оперативная новость, тогда подтверди дату события дословной цитатой. Для исторического/неоперативного факта is_news=false, поля event_* пустые: отсутствие сегодняшней даты не ошибка. Не отклоняй фактическую историю из-за отсутствия глубины, юмора или большого объёма. Отклоняй заметки отдельно: ошибка одной не отменяет остальные. approve=true только если семь критериев true, issues/unresolved пустые.\nЗаметки: '+json.dumps([{'id':r['id'],'source_id':next('s'+str(i+1) for i,s in enumerate(sources) if s['id']==r['source']['id']),'article':r['article']} for r in records],ensure_ascii=False)+'\nПолные источники: '+json.dumps(wire,ensure_ascii=False),output_tokens=8000,schema='v43_light_review');persist()
        accepted=apply_batch_review(saved,state)
        existing={r['id'] for r in saved['records']}
        saved['records'] += [r for r in accepted if r['id'] not in existing]
        reserve_accepted_sources(state,accepted)
        saved['complete']=True;saved['code']='LIGHT_ACCEPTED' if accepted else 'LIGHT_ALL_REJECTED'
    except news.runtime.GenerationPaused as exc:
        saved['code']='GEMINI_HTTP_503' if '503' in str(exc) else 'GEMINI_HTTP_429' if '429' in str(exc) else 'LIGHT_PREPARATION_PAUSED'
    except Exception as exc:
        saved['code']=getattr(exc,'code',type(exc).__name__)
        print('[light43] '+json.dumps({'code':saved['code'],'optional':True}),flush=True)
    finally:
        saved['http_requests']=max(saved['http_requests'],start_requests+budget.used-start_used)
        budget.run_limit=original_limit
        diagnose_saved(state);persist()


def diagnose_checkpoint(path):
    """Read-only production diagnosis. Never export the decrypted state or verdict."""
    from scripts import staged_news
    from pathlib import Path
    if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REF_NAME')!='main':raise RuntimeError('PROTECTED_DIAGNOSIS_ONLY')
    key=staged_news.validate_key(os.environ['DRAFT_ENCRYPTION_KEY'])
    state=staged_news.decipher(Path(path).read_bytes(),key)
    print('[light43-checkpoint-date] '+json.dumps({'date':state['date']}),flush=True)
    diagnose_saved(state)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--diagnose-checkpoint',required=True);args=parser.parse_args()
    diagnose_checkpoint(args.diagnose_checkpoint)
