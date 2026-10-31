"""Optional batched light stories: at most two model calls per issue, never a gate."""
import copy,json,re
from datetime import datetime,timezone
try:from scripts import editorial43 as e,content41,news,policy41 as p,rights41,selection43
except ImportError:import editorial43 as e,content41,news,policy41 as p,rights41,selection43

S={'type':'string'}
news.SCHEMAS['v43_light_write']=content41.schema({'items':{'type':'array','items':content41.schema({'id':S,'source_id':S,'title':S,'text':S})}})
review=copy.deepcopy(news.SCHEMAS['v43_final']);review['properties']['id']=S;review['required'].append('id')
news.SCHEMAS['v43_light_review']=content41.schema({'reviews':{'type':'array','items':review}})


def ready(state):
    result=[];mains=selection43.ready(state)
    for row in state.get('light43',{}).get('records',[]):
        if not e.eligible(row):continue
        try:rights41.require(row['source'],'INDEPENDENT_ARTICLE',rights41.decision(row['source'],'INDEPENDENT_ARTICLE'))
        except p.Blocked:continue
        if any(selection43.duplicate(row,x) for x in mains+result):continue
        result.append(row)
    return result[:5]


def safe_record(item,source):
    text=item['text'].strip()
    if not text or len(re.split(r'(?<=[.!?])\s+(?=[А-ЯA-Z])',text))>3:raise p.Blocked('LIGHT_FORMAT')
    grant=rights41.decision(source,'INDEPENDENT_ARTICLE');rights41.require(source,'INDEPENDENT_ARTICLE',grant)
    row={'id':item['id'],'url':source['url'],'source':source,'rights':grant,'mode':'INDEPENDENT_ARTICLE','category_hint':'Наука','category':'Наука','status':'preparing','checks':{},'progress':{},'history':[],
         'article':{'title':item['title'],'teaser':'','blocks':[{'kind':'paragraph','text':text}],'mode':'INDEPENDENT_ARTICLE','category':'Наука','kind':'Короткая новость','activities':[]}}
    e.normalize(row['article']);e.structure(row)
    if e.high_risk(row):raise p.Blocked('LIGHT_HIGH_RISK_EXCLUDED')
    return row


def prepare(state,persist=lambda:None,editor=None):
    saved=state.setdefault('light43',{'write_attempts':0,'review_attempts':0,'records':[]})
    if saved.get('complete') or saved.get('review_attempts',0)>=1:return
    budget=news.runtime.ACTIVE_BUDGET
    remaining=2-saved.get('http_requests',0);needed=1 if saved.get('draft') else 2
    if remaining<=0 or not budget or not budget.can_request() or budget.used+needed>budget.run_limit:return
    used_today=budget.ledger.get('requests',0) if budget.ledger.get('day')==datetime.now(timezone.utc).date().isoformat() else 0
    if used_today+needed>budget.day_limit-24:return
    editor=editor or e.Editor(persist=persist);editor.state=state
    original_limit=budget.run_limit;start_used=budget.used
    budget.run_limit=min(original_limit,budget.used+remaining)
    try:
        if not saved.get('draft'):
            if saved.get('write_attempts',0)>=1:return
            sources=[]
            for row in state['candidates']:
                src=row.get('source')
                if not row.get('light_suitable') or not src or e.high_risk(row):continue
                if re.search(r'(?i)войн|болезн|убит|трагед|disaster|cancer|death|illness',src['title']):continue
                if any(selection43.duplicate(row,r) for r in selection43.ready(state)):continue
                grant=rights41.decision(src,'INDEPENDENT_ARTICLE')
                if grant['status']=='allowed' and src['url'] not in {s['url'] for s in sources}:sources.append(src)
                if len(sources)>=5:break
            if not sources:return
            saved['sources']=sources
            dummy={'source':sources[0],'supporting_sources':sources[1:]};wire,aliases=e.review_wire(dummy)
            prompt='Рубрика «НЕ ВСЁ ТАК СЕРЬЁЗНО». Подготовь до пяти коротких добрых, удивительных фактов: заголовок и1–3 предложения. Юмор только из реальной истории, без насмешек над людьми, трагедиями или болезнями. Собственные формулировки и композиция C, никаких вымышленных фактов и скрытого перевода. Можно меньше пяти или пустой список. Только факты полных оригиналов, не аннотации. Не выдавай старое за сегодняшнее. Для каждого id и source_id=sN. Не повторяй основные сюжеты: '+json.dumps(selection43.prompt_context(state),ensure_ascii=False)+'\nПолные источники: '+json.dumps(wire,ensure_ascii=False)
            if len(prompt)>e.Editor.context_characters:return
            before=budget.used;saved['write_attempts']+=1;persist()
            try:saved['draft']=editor.call(prompt,output_tokens=4000,schema='v43_light_write')
            except news.runtime.GenerationPaused:
                if budget.used==before:saved['write_attempts']-=1
                persist();return
            persist()
        sources=saved['sources'];dummy={'source':sources[0],'supporting_sources':sources[1:]};wire,aliases=e.review_wire(dummy)
        by_alias={alias:src for alias,(src,_) in aliases.items()};records=[]
        for item in saved['draft'].get('items',[])[:5]:
            try:
                row=safe_record(item,by_alias[item['source_id']])
                if any(selection43.duplicate(row,r) for r in selection43.ready(state)+records):continue
                records.append(row)
            except (KeyError,TypeError,ValueError):continue
        if not records:saved['complete']=True;persist();return
        before=budget.used;saved['review_attempts']+=1;persist()
        report=editor.call('Одна независимая проверка коротких заметок политики4.3. Для каждого id оцени все семь критериев v43_final, включая факты, безопасность, права C и самостоятельность формулировок/подбора, соответствие заголовка. Никаких фиктивных фактов, насмешек над бедой, опасных советов и ложной свежести. Каждый существенный факт в claims с дословной цитатой и sN/qN; сама ссылка не подтверждает смысл. Для оперативной новости нужна подтверждённая актуальная дата события; для исторического факта не выдавай его за сегодняшнее событие. Плохие заметки отклони отдельно, не блокируй остальные.\nЗаметки: '+json.dumps([{'id':r['id'],'article':r['article']} for r in records],ensure_ascii=False)+'\nПолные источники: '+json.dumps(wire,ensure_ascii=False),output_tokens=8000,schema='v43_light_review')
        by_id={x['id']:x for x in report.get('reviews',[]) if isinstance(x,dict) and 'id' in x}
        for row in records:
            verdict,errors=e.bind_review(by_id.get(row['id'],{}),row,aliases,e.fingerprint(row))
            if errors or not e.positive_semantics(verdict) or e.news_errors(verdict,row,state):continue
            if any(c.get('source_id')!=row['source']['id'] or not any(c.get('quote','') in b['text'] for b in row['source']['blocks']) for c in verdict.get('claims',[])):continue
            row['checks']['final43']=dict(verdict,approved=True);row['status']='ready';saved['records'].append(row)
        saved['complete']=True;persist()
    except news.runtime.GenerationPaused:
        if budget.used==before:saved['review_attempts']-=1
        persist()
    except Exception as exc:
        saved['code']=getattr(exc,'code',type(exc).__name__);persist()
        print('[light43] '+json.dumps({'code':saved['code'],'optional':True}),flush=True)
    finally:
        saved['http_requests']=saved.get('http_requests',0)+(budget.used-start_used)
        budget.run_limit=original_limit
        persist()
