"""Small source-grounded briefs. One batched request, no article audit or topic gate."""
import copy,json,re,os
from datetime import datetime
from scripts import policy41 as p,news,content41,rights41,editorial43 as e,selection43 as sel,policy44
S={'type':'string'}
news.SCHEMAS['v44_briefs']=content41.schema({'items':{'type':'array','items':content41.schema({'id':S,'source_id':S,'title':S,'text':S,'time_kind':{'type':'string','enum':['news','historical_fact','unusual_fact']},'event_date':S,'evidence':{'type':'array','items':content41.schema({'block_id':S,'quote':S})}})}})

def fingerprint(row):return p.digest({'article':row['article'],'source_hash':row['source']['content_hash'],'rights':row['rights']})

def dangerous(text):
    return bool(re.search(r'(?i)(?:(?:принимайте|дайте|введите).{0,50}(?:лекарств|препарат|таблет|доз|инъекц)|лечите.{0,30}(?:болезн|заболеван)|inject.{0,20}(?:drug|dose)|take.{0,15}dose|как изготовить.{0,15}(?:бомб|яд))',text))

def eligible(row):
    gate=row.get('checks',{}).get('brief44',{})
    try:return row.get('status') in ('ready','reserve_ready') and gate.get('approved') is True and gate.get('input_hash')==fingerprint(row) and not dangerous(row['article']['title']+' '+row['article']['blocks'][0]['text'])
    except (KeyError,TypeError):return False

def duplicate(a,b):
    """Same concrete source/event, not the main article's narrow-topic families."""
    source_a=a.get('source',{});source_b=b.get('source',{})
    if (a.get('url') or source_a.get('url')) and (a.get('url') or source_a.get('url'))==(b.get('url') or source_b.get('url')):return True
    for key in ('doi','event_id'):
        if source_a.get(key) and source_a.get(key)==source_b.get(key):return True
    if sel.normalized(sel.title(a))==sel.normalized(sel.title(b)):return True
    left=sel.tokens(' '.join(policy44.texts(a)));right=sel.tokens(' '.join(policy44.texts(b)))
    return len(left&right)>=10 and len(left&right)/max(1,len(left|right))>=.93


def ready(state):
    from scripts import light43
    result=[];published=set(state.get('stock43',{}).get('published_urls',[]));mains=sel.ready(state)
    for row in state.get('light43',{}).get('records',[]):
        if not (eligible(row) or e.eligible(row)):continue
        if row['source']['url'] in published:continue
        try:rights41.require(row['source'],'INDEPENDENT_ARTICLE',rights41.decision(row['source'],'INDEPENDENT_ARTICLE'))
        except p.Blocked:continue
        if any(duplicate(row,r) for r in mains+result+state.get('_recent_light43',[])):continue
        result.append(row)
    return result

def accept(item,source):
    title=item['title'].strip();text=item['text'].strip()
    if not title or not text or len(re.split(r'(?<=[.!?])\s+(?=[А-ЯA-Z])',text))>3:raise p.Blocked('BRIEF_FORMAT')
    if dangerous(title+' '+text):raise p.Blocked('BRIEF_UNSAFE')
    if not source.get('full_text_verified') or source.get('metadata_status')!='verified':raise p.Blocked('BRIEF_SOURCE_UNVERIFIED')
    source41_url=__import__('scripts.source41',fromlist=['safe_url']);source41_url.safe_url(source['url'])
    grant=rights41.decision(source,'INDEPENDENT_ARTICLE');rights41.require(source,'INDEPENDENT_ARTICLE',grant)
    witnesses=[]
    for proof in item.get('evidence',[]):
        quote=proof.get('quote','');block=next((b for b in source['blocks'] if b['id']==proof.get('block_id')),None)
        if not block or not quote.strip() or quote not in block['text']:raise p.Blocked('BRIEF_FACT_NOT_BOUND')
        witnesses.append(quote)
    if not witnesses:raise p.Blocked('BRIEF_FACT_NOT_BOUND')
    evidence=' '.join(witnesses)
    if set(re.findall(r'\d+(?:[.,]\d+)?',title+' '+text))-set(re.findall(r'\d+(?:[.,]\d+)?',evidence)):raise p.Blocked('BRIEF_NUMBER_UNSUPPORTED')
    own=content41.normalized(text)
    source_expression=content41.normalized(' '.join(b['text'] for b in source['blocks']))
    words=own.split()
    if any(len(' '.join(words[i:i+14]))>=80 and ' '.join(words[i:i+14]) in source_expression for i in range(max(0,len(words)-13))):raise p.Blocked('BRIEF_COPIED_EXPRESSION')
    if any(own==content41.normalized(b['text']) for b in source['blocks']):raise p.Blocked('BRIEF_COPIED_TEXT')
    kind=item.get('time_kind')
    if kind not in ('news','historical_fact','unusual_fact'):raise p.Blocked('BRIEF_TIME_KIND')
    if kind!='news' and re.search(r'(?i)сегодня|вчера|на этой неделе|только что|today|yesterday',title+' '+text):raise p.Blocked('BRIEF_FALSE_RECENCY')
    if kind=='news':
        date=item.get('event_date','')
        if not date or not any(content41.witnessed_event_date(date,q) for q in witnesses):raise p.Blocked('BRIEF_EVENT_DATE_UNSUPPORTED')
        # A verified old event is honestly labelled, never artificially made current.
        stamp=datetime.fromisoformat(date);stamp=stamp.replace(tzinfo=p.TZ) if stamp.tzinfo is None else stamp
        if stamp>datetime.now(p.TZ):raise p.Blocked('BRIEF_EVENT_IN_FUTURE')
        if (datetime.now(p.TZ)-stamp).days>3:
            if re.search(r'(?i)сегодня|вчера|на этой неделе|только что|today|yesterday',title+' '+text):raise p.Blocked('BRIEF_FALSE_RECENCY')
            kind='historical_fact'
    row={'id':p.digest({'source':source['url'],'title':title}),'url':source['url'],'source':source,'mode':'INDEPENDENT_ARTICLE','rights':grant,'status':'ready','progress':{},'history':[],
         'article':{'title':title,'teaser':'','category':'Короткие истории','kind':'Короткая история','mode':'INDEPENDENT_ARTICLE','blocks':[{'kind':'paragraph','text':text}],'activities':[]},
         'light_kind':kind,'ready_checked_at':datetime.now(p.TZ).isoformat(),'checks':{}}
    row['checks']['brief44']={'approved':True,'input_hash':fingerprint(row),'evidence':copy.deepcopy(item['evidence']),'event_date':item.get('event_date',''),'basis':'single_batched_source_check'}
    return row

def prepare(state,persist=lambda:None):
    from scripts import light43
    saved=state.setdefault('light43',{'records':[]});saved.setdefault('records',[])
    batch=saved.setdefault('v44',{'completed':[],'refusals':[],'http_requests':0})
    if batch.get('response') is not None and not batch.get('response_applied'):
        apply_response(state,persist);return
    budget=news.runtime.ACTIVE_BUDGET
    if not budget or not budget.can_request():return
    window=os.getenv('GITHUB_RUN_ID','local')+':'+os.getenv('GITHUB_RUN_ATTEMPT','1')
    if batch.get('window')==window:return
    from scripts import stock43
    if len(ready(state))>=e.CONFIG.get('light_target',12) and len(stock43.available(state,state['date'],'light'))>=e.CONFIG.get('light_stock_target',40):return
    excluded=set(state.get('stock43',{}).get('published_urls',[]))|{r['source']['url'] for r in saved['records']}|{r['url'] for r in batch['refusals']}
    mains=light43.main_work(state);sources=[];publishers={}
    needed={g for g,n in policy44.counts(sel.ready(state)).items() if n<2}
    candidates=sorted(state['candidates'],key=lambda r:(not r.get('for_light_only'),r.get('publisher_id','')))
    # Round-robin publisher preference, never a topical quota.
    pending=[r for r in candidates if policy44.subject(r) not in needed and not (r.get('article') and r.get('status')=='preparing' and not r.get('for_light_only')) and r.get('source',{}).get('full_text_verified') and r.get('source',{}).get('metadata_status')=='verified' and r['source']['url'] not in excluded and not any(sel.duplicate(r,m) for m in mains)]
    while pending and len(sources)<12:  # transport batch size, NEVER a publication maximum
        row=min(pending,key=lambda r:publishers.get(r.get('publisher_id') or r['source'].get('publisher'),0));pending.remove(row);src=row['source']
        if src['url'] in {s['url'] for s in sources}:continue
        if rights41.decision(src,'INDEPENDENT_ARTICLE')['status']!='allowed':continue
        if sources and sum(len(json.dumps(s,ensure_ascii=False)) for s in sources)+len(json.dumps(src,ensure_ascii=False))>90000:continue
        sources.append(src);key=row.get('publisher_id') or src.get('publisher');publishers[key]=publishers.get(key,0)+1
    if not sources:return
    # Atomic resume: a completed response is retained before deterministic admission.
    batch.pop('response',None);batch['response_applied']=False
    batch['window']=window;batch['sources']=sources;batch['attempts']=batch.get('attempts',0)+1;persist()
    wire,_=e.review_wire({'source':sources[0],'supporting_sources':sources[1:]})
    old_limit=budget.run_limit;start=budget.used;budget.run_limit=min(old_limit,budget.used+1)
    try:
        prompt='Подготовь короткую газетную подборку на русском: стремись к8–12 разным сообщениям из этих источников, можно меньше при нехватке фактов. Темы любые, не требуется юмор, доброта, глубина или полный пересказ. Для каждого: короткий собственный заголовок,1–3 собственных предложения, source_id, time_kind news/historical_fact/unusual_fact, event_date (только подтверждённая дата события для news), evidence с block_id и точной непустой цитатой. Сверь каждое утверждение с оригиналом: не выдумывай факты, числа, имена и обстоятельства, не искажай смысл. Собственная композиция и формулировки; не копируй заголовки/аннотации. Исторические факты не выдавай за сегодняшнюю новость. Никаких опасных инструкций, лечения или незаконных советов. Это краткие сообщения, не большие статьи; отдельный литературный аудит не нужен.\n'+json.dumps(wire,ensure_ascii=False)
        response=news.gemini(prompt,output_tokens=12000,schema='v44_briefs');batch['response']=response;persist()
    except news.runtime.GenerationPaused as exc:
        batch['code']='BRIEF_API_PAUSED';persist();return
    except Exception as exc:
        batch['code']=getattr(exc,'code',type(exc).__name__);persist();return
    finally:batch['http_requests']+=budget.used-start;budget.run_limit=old_limit;persist()
    apply_response(state,persist)

def apply_response(state,persist=lambda:None):
    from scripts import light43
    saved=state['light43'];batch=saved['v44'];sources=batch['sources'];response=batch['response'];window=batch['window']
    mains=sel.ready(state)
    by_id={s['id']:s for s in sources};accepted=[]
    _,aliases=e.review_wire({'source':sources[0],'supporting_sources':sources[1:]})
    for item in response.get('items',[]):
        if not isinstance(item,dict):
            batch['refusals'].append({'url':'','code':'BRIEF_FORMAT'});continue
        try:
            item=copy.deepcopy(item)
            if item.get('source_id') in aliases:
                src,refs=aliases[item['source_id']];item['source_id']=src['id']
                for proof in item.get('evidence',[]):
                    found=e.bind_witness(src['id'],proof.get('block_id'),proof.get('quote'),[src],{})
                    # qN is a transport alias, restored to its original block ID.
                    original=refs.get(proof.get('block_id'))
                    if original:proof['block_id']=original['id']
                    elif found:proof.update(block_id=found[1],quote=found[2])
            src=by_id[item['source_id']];row=accept(item,src)
            if any(duplicate(row,x) for x in mains+ready(state)+accepted+state.get('_recent_light43',[])):raise p.Blocked('BRIEF_DUPLICATE')
            accepted.append(row)
        except (KeyError,TypeError,ValueError,AttributeError) as exc:batch['refusals'].append({'url':by_id.get(item.get('source_id'),{}).get('url',''),'code':getattr(exc,'code','BRIEF_FORMAT')})
    batch['response_applied']=True
    saved['records']+=accepted;batch['completed'].append({'window':window,'accepted':len(accepted),'attempts':batch['attempts']});light43.reserve_accepted_sources(state,accepted);persist()
    print('[brief44] '+json.dumps({'accepted':len(accepted),'ready':len(ready(state)),'refusal_codes':dict(__import__('collections').Counter(r['code'] for r in batch['refusals'])),'http_requests':batch['http_requests']}),flush=True)
