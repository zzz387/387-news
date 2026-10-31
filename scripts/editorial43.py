"""Daily 4.3: bounded preparation, one substantive gate, no issue-size veto."""
import copy,json,re
from datetime import datetime,timedelta
try:
    from scripts import policy41 as p,source41,rights41,content41,editorial41 as old,news
except ImportError:
    import policy41 as p,source41,rights41,content41,editorial41 as old,news

CONFIG=json.loads((p.ROOT/'config/daily43.json').read_text())
VERSION='4.3'
S={'type':'string'}; B={'type':'boolean'}
news.SCHEMAS['v43_article']=content41.schema({'finished':B,'title':S,'teaser':S,
    'blocks':{'type':'array','items':content41.schema({'kind':{'type':'string','enum':['heading','paragraph','item']},'text':S})}})
CHECKS=('facts','safety','rights','independence','title_matches','complete','evidence_sufficient')
news.SCHEMAS['v43_final']=content41.schema({'approve':B,**{name:B for name in CHECKS},
    'is_news':B,'event_date':S,'event_source_id':S,'event_evidence_id':S,'event_quote':S,
    'issues':{'type':'array','items':S},'unresolved':{'type':'array','items':S},
    'claims':{'type':'array','items':content41.schema({'fact':S,'source_id':S,'evidence_id':S,'quote':S})}})


def migrate(state,date):
    if state and state.get('version')==43:return state
    result={'version':43,'policy_version':VERSION,'date':date,'candidates':[],'articles':{},'history':[],
            'stage':'PREPARING','audit_passed':False,'selected_ids':[]}
    if state:
        result['previous_policy_checkpoint']=copy.deepcopy(state)
        for key in ('branch','preview','_quota_snapshot'): 
            if key in state:result[key]=copy.deepcopy(state[key])
        result['candidates']=copy.deepcopy(state.get('candidates',[]))
        for row in result['candidates']:
            row.setdefault('progress',{});row.setdefault('checks',{});row.setdefault('history',[])
            if row.get('status')=='ready':row['status']='preparing'
        result['history'].append({'code':'POLICY43_MIGRATION','previous_state_preserved':True})
    return result


def normalize(article):
    """Exact repeated blocks only; no paraphrasing or removal of distinct facts."""
    blocks=[];seen=set()
    for block in article.get('blocks',[]):
        if not isinstance(block,dict) or not isinstance(block.get('text'),str):raise p.Blocked('ARTICLE_FORMAT')
        text=block['text'].strip()
        if not text:continue
        kind=block.get('kind','paragraph')
        if kind not in ('title','heading','paragraph','item','quote','table'):kind='paragraph'
        key=(kind,text)
        if key in seen:continue
        seen.add(key);blocks.append(dict(block,id='body/'+str(len(blocks)),kind=kind,text=text))
    article['blocks']=blocks
    if not isinstance(article.get('title'),str) or not article['title'].strip() or not blocks:raise p.Blocked('ARTICLE_INCOMPLETE')
    if not any(b['kind'] not in ('heading','title') for b in blocks):raise p.Blocked('ARTICLE_INCOMPLETE')
    article.setdefault('teaser','');article.setdefault('activities',[])
    if not isinstance(article['teaser'],str):raise p.Blocked('ARTICLE_FORMAT')
    if re.search(r'https?://',article['title']+' '+article['teaser']+' '+' '.join(b['text'] for b in blocks)):raise p.Blocked('BODY_LINKS_NOT_READER_CONTENT')
    return article



def structure(record):
    article=record['article'];source=record['source'];mode=record['mode']
    if not article.get('title') or not article.get('blocks'):raise p.Blocked('ARTICLE_INCOMPLETE')
    if mode in ('ORIGINAL_REPUBLICATION','FULL_TRANSLATION'):
        blocks=article['blocks'];original=source['blocks']
        if [b.get('source_block_id') for b in blocks]!=[b['id'] for b in original]:raise p.Blocked('SOURCE_COVERAGE_INCOMPLETE')
        if any(not b.get('text','').strip() or any(b.get(k)!=o.get(k) for k in ('kind','heading_level','list_kind','list_group','list_index','list_depth')) for b,o in zip(blocks,original)):raise p.Blocked('SOURCE_STRUCTURE_CHANGED')
        if mode=='ORIGINAL_REPUBLICATION' and (article['title']!=source['title'] or [b['text'] for b in blocks]!=[b['text'] for b in original]):raise p.Blocked('ORIGINAL_CHANGED')
    else:
        if any(b.get('source_block_id') for b in article['blocks']):raise p.Blocked('COPIED_SOURCE_LAYOUT')
        own=content41.normalized(' '.join(b['text'] for b in article['blocks']))
        if any(own==content41.normalized(' '.join(b['text'] for b in s['blocks'])) for s in [source]+record.get('supporting_sources',[])):raise p.Blocked('DISGUISED_COPY')
    return True


def fingerprint(record):
    return p.digest({'article':record['article'],'sources':[{key:s.get(key) for key in ('url','content_hash','published','metadata_status')} for s in [record['source']]+record.get('supporting_sources',[])],
        'rights':record['rights']})



def high_risk(record):
    article=record.get('article',{})
    text=' '.join(str(value) for value in [record.get('source',{}).get('title',''),article.get('title',''),article.get('teaser','')]+[b.get('text','') for b in article.get('blocks',[])])
    return (record.get('category') in ('Семья','Здоровье и движение','Экономика и бизнес') or
            record.get('category_hint') in ('Семья','Здоровье и движение','Экономика и бизнес') or
            bool(re.search(r'(?i)медицин|лечени|дозиров|малыш|ребен|ребён|детям|здоров|юридич|инвестиц|лекарств|таблет|препарат|беремен|доз[ауые]|child|toddler|infant|medical|treatment',text)))


def safety_sources_valid(record):
    if not high_risk(record):return True
    sources=[record.get('source',{})]+record.get('supporting_sources',[])
    return (all(s.get('full_text_verified') and s.get('metadata_status')=='verified' for s in sources)
            and len({old.publisher_identity(s['url']) for s in sources})>=2
            and any(old.host_matches(s['url'],old.TRUSTED) for s in sources))

def eligible(record):
    if not safety_sources_valid(record):return False
    if record.get('status')!='ready' or not record.get('article') or not record.get('source'):return False
    try:structure(record)
    except (p.Blocked,KeyError,TypeError):return False
    gate=record.get('checks',{}).get('final43',{})
    try:return gate.get('approved') is True and gate.get('input_hash')==fingerprint(record) and all(gate.get(name) is True for name in CHECKS)
    except (KeyError,TypeError):return False


def select_ready(state):
    result=[];seen=set()
    for r in state['candidates']:
        if not eligible(r):continue
        try:
            rights41.require(r['source'],r['article']['mode'],r['rights'])
            current=rights41.decision(r['source'],r['article']['mode'])
            rights41.require(r['source'],r['article']['mode'],current)
        except p.Blocked:continue
        key=p.digest(r['article'])
        if key not in seen:result.append(r);seen.add(key)
    return result


def review_wire(record):
    sources=[record['source']]+record.get('supporting_sources',[]);wire=[];aliases={}
    for i,source in enumerate(sources,1):
        sid='s'+str(i);blocks=[];refs={}
        for j,block in enumerate(source['blocks'],1):
            bid='q'+str(j);blocks.append(dict(block,id=bid));refs[bid]=block
        aliases[sid]=(source,refs)
        wire.append({**{key:source.get(key,'') for key in ('url','title','publisher','author','published','language','publication_type','doi')},'id':sid,'blocks':blocks})
    return wire,aliases


def bind_witness(source_id,evidence_id,quote,sources,aliases):
    if not isinstance(quote,str) or not quote.strip():return None
    source=None;block=None
    if source_id in aliases:
        source,refs=aliases[source_id];block=refs.get(evidence_id)
    else:
        source=next((s for s in sources if s['id']==source_id),None)
        if source:block=next((b for b in source['blocks'] if b['id']==evidence_id),None)
    def exact(block):
        if quote in block['text']:return quote
        pattern=r'\s+'.join(re.escape(piece) for piece in quote.split())
        match=re.search(pattern,block['text']) if pattern else None
        return match.group(0) if match else None
    if block:
        literal=exact(block)
        if literal:return source['id'],block['id'],literal
    # A unique literal location can repair a malformed ID; it never proves the claim's meaning.
    matches=[]
    for candidate in ([source] if source else sources):
        for piece in candidate['blocks']:
            literal=exact(piece)
            if literal:matches.append((candidate['id'],piece['id'],literal))
    return matches[0] if len(matches)==1 else None


def positive_semantics(result):
    return (result.get('approve') is True and all(result.get(k) is True for k in CHECKS)
            and result.get('issues')==[] and result.get('unresolved')==[])


def bind_review(result,record,aliases,fp):
    result=copy.deepcopy(result);sources=[record['source']]+record.get('supporting_sources',[]);errors=[]
    result['input_hash']=fp  # bound by the synchronous call, never echoed/attested by the model
    if not result.get('claims'):errors.append('CLAIMS_MISSING')
    for claim in result.get('claims',[]):
        found=bind_witness(claim.get('source_id'),claim.get('evidence_id'),claim.get('quote'),sources,aliases)
        if not found or not isinstance(claim.get('fact'),str) or not claim['fact'].strip():errors.append('WITNESS_NOT_BOUND');continue
        claim.update(source_id=found[0],evidence_id=found[1],quote=found[2])
    if result.get('is_news') is True:
        found=bind_witness(result.get('event_source_id'),result.get('event_evidence_id'),result.get('event_quote'),sources,aliases)
        if found:result.update(event_source_id=found[0],event_evidence_id=found[1],event_quote=found[2])
    return result,sorted(set(errors))


def news_errors(result,record,state):
    if type(result.get('is_news')) is not bool:return ['NEWS_CLASSIFICATION_MISSING']
    if not result['is_news']:return []
    errors=[]
    try:
        date=datetime.fromisoformat(result['event_date']);date=date.replace(tzinfo=p.TZ) if date.tzinfo is None else date.astimezone(p.TZ)
        release=datetime.fromisoformat(state.get('review_date',state['date'])+'T06:00').replace(tzinfo=p.TZ)
        if release-date<timedelta(0):errors.append('NEWS_EVENT_IN_FUTURE')
        elif release-date>timedelta(hours=72):errors.append('NEWS_EVENT_TOO_OLD')
        sources=[record['source']]+record.get('supporting_sources',[])
        source=next((s for s in sources if s['id']==result['event_source_id']),{})
        literal=next((b['text'] for b in source.get('blocks',[]) if b['id']==result['event_evidence_id']),'')
        if not result.get('event_quote') or result['event_quote'] not in literal:errors.append('NEWS_EVENT_WITNESS_MISSING')
        elif not content41.witnessed_event_date(result['event_date'],result['event_quote']):errors.append('NEWS_EVENT_DATE_NOT_IN_WITNESS')
        if not source.get('published'):errors.append('NEWS_PUBLICATION_DATE_MISSING')
    except (ValueError,KeyError,TypeError):errors.append('NEWS_EVENT_FIELDS_INVALID')
    return errors


class Editor(old.Editor):
    context_characters=int(CONFIG.get('context_characters',120000))
    def model_sources(self,record):
        # Complete originals and structural blocks, without unrelated image/transport inventories.
        return [{**{key:source.get(key,'') for key in ('id','url','title','publisher','author','published','language','publication_type','doi')},
                 'blocks':source['blocks']} for source in [record['source']]+record.get('supporting_sources',[])]

    def issue_context(self,state,record):
        try:from scripts import selection43
        except ImportError:import selection43
        return dict(selection43.prompt_context(state),source_kind=record.get('source_kind','unclassified'),publication_type=record.get('source',{}).get('publication_type','unclassified'),rule='Не выдавай пресс-релиз, обзор или журналистскую статью за первичное исследование. Не повторяй уже выбранный факт/событие/рекомендацию; можно раскрыть другой конкретный сюжет. Стиль заголовка — мягкое пожелание, не литературный запрет.')

    def writing_basis(self,record):
        return self.model_sources(record)

    def verify_source(self,record):
        if not record.get('source'):record['source']=self.cached_fetch(record['url']);self.persist()
        source=record['source']
        if not source.get('full_text_verified') or source.get('extraction_status')!='complete' or source.get('metadata_status')!='verified':raise p.Blocked('FULL_VERIFIED_SOURCE_REQUIRED')
        # Retain a completed/partially translated mode. New ordinary candidates
        # default to a narrow C work instead of an unsolicited lengthy translation.
        mode=record.get('article',{}).get('mode') or record.get('mode') or 'INDEPENDENT_ARTICLE'
        grant=rights41.decision(source,mode,self.grants)
        if grant.get('status')!='allowed':mode,grant=rights41.select_mode(source,self.grants)
        if mode!='INDEPENDENT_ARTICLE' and any(re.search(r'https?://|www\.',b['text']) for b in source['blocks']):
            mode='INDEPENDENT_ARTICLE';grant=rights41.decision(source,mode,self.grants)
        rights41.require(source,mode,grant)
        if record.get('article') and record['article'].get('mode')!=mode:
            record.setdefault('previous_mode_preparations',[]).append(record.pop('article'));self.persist()
        record.update(mode=mode,rights=grant,category=record.get('category_hint') or record.get('category') or 'История и культура',kind='Самостоятельная заметка' if mode=='INDEPENDENT_ARTICLE' else 'Перевод' if mode=='FULL_TRANSLATION' else 'Оригинал')
        sensitive=high_risk(record)
        record['high_risk']=sensitive
        if sensitive:
            extra=record.setdefault('supporting_sources',[]);known={s['url'] for s in extra}
            for url in record.get('verification_urls',[]):
                if url!=source['url'] and url not in known:
                    other=self.cached_fetch(url)
                    if not other.get('full_text_verified') or other.get('metadata_status')!='verified':raise p.Blocked('SAFETY_EVIDENCE_INCOMPLETE')
                    if rights41.decision(other,'INDEPENDENT_ARTICLE',self.grants)['status']!='allowed':raise p.Blocked('SAFETY_EVIDENCE_RIGHTS')
                    extra.append(other);known.add(url);self.persist()
            sources=[source]+extra
            if len({old.publisher_identity(s['url']) for s in sources})<2 or not any(old.host_matches(s['url'],old.TRUSTED) for s in sources):raise p.Blocked('INDEPENDENT_SAFETY_EVIDENCE_REQUIRED')
        record['checks']['source43']={'approved':True};self.persist()

    def finish(self,state,record):
        self.state=state;self.usage_record=record
        self.verify_source(record)
        progress=record['progress'].setdefault('v43',{'write_attempts':int('article' in record),'review_attempts':{},'history':[]})
        while True:
            if 'article' not in record:
                if progress['write_attempts']>=1+CONFIG['repair_attempts']:raise p.Blocked('CANDIDATE_ATTEMPTS_EXHAUSTED')
                if record['mode']=='INDEPENDENT_ARTICLE':
                    progress['write_attempts']+=1;self.persist()
                    try:
                        result=self.call('Подготовь законченную самостоятельную русскую заметку по одному полезному узкому аспекту проверенного материала. '
                            'Редакционная политика 4.3: нет минимума длины, глубины, разделов, примеров или пересказа всего источника. '
                            'Собственные формулировки, композиция и объяснения; не поверхностный рерайт и не скрытый перевод. '
                            'Не заимствуй авторские примеры и подборки. Не обещай 21 занятие только потому, что такое число есть в чужом заголовке. '
                            'Заголовок — естественный, выразительный и точный, в культуре качественного журнала. Чередуй конструкции, не копируй чужой заголовок и не создавай кликбейт. Слово «Как» допустимо, но стремись к2–3 таким началам на12 материалов; стилистика не причина отказа и не требует отдельного запроса. '
                            'Заголовок должен соответствовать фактически раскрытому аспекту. Не давай рискованные советы без доказательной базы; '
                            'не придумывай цифры и даты, различай дату публикации и события, корреляцию и причинность. '
                            'Для медицинских исследований укажи дизайн и ограничения, не подменяй исследование пресс-релизом. '
                            'finished=true только для законченной заметки. URL только в служебном блоке источника, не в тексте. '
                            '\nПолные материалы: '+json.dumps(self.writing_basis(record),ensure_ascii=False)+
                            '\nРедакторский контекст текущего номера: '+json.dumps(self.issue_context(state,record),ensure_ascii=False)+'\nПредыдущий отказ: '+json.dumps(progress.get('feedback',{}),ensure_ascii=False),output_tokens=12000,schema='v43_article')
                    except news.runtime.GenerationPaused:
                        progress['write_attempts']-=1;self.persist();raise
                    if result.get('finished') is not True:
                        progress['history'].append({'code':'INCOMPLETE_RESPONSE'});self.persist();continue
                    record['article']=dict(result,category=record['category'],kind=record['kind'],mode=record['mode'],activities=[])
                else:
                    source=record['source']
                    blocks=([dict(b,source_block_id=b['id']) for b in source['blocks']] if record['mode']=='ORIGINAL_REPUBLICATION'
                            else content41.complete_translation(source,record['progress'],self.call,self.persist))
                    record['article']={'title':next((b['text'] for b in blocks if b['kind']=='title'),source['title']),
                        'teaser':'','blocks':blocks,'activities':[],'mode':record['mode'],'category':record['category'],'kind':record['kind']}
                self.persist()
            article=record['article']
            if record['mode']=='INDEPENDENT_ARTICLE':normalize(article)
            structure(record)
            # Generated advice can introduce risk absent from the source title/category.
            self.verify_source(record)
            article.setdefault('mode',record['mode']);article.setdefault('category',record['category']);article.setdefault('kind',record['kind'])
            fp=fingerprint(record)
            if eligible(record):return
            reviews=progress['review_attempts'];review_key='wire2:'+fp;count=reviews.get(review_key,0)
            if count>=1+CONFIG['repair_attempts']:raise p.Blocked('FINAL_REVIEW_ATTEMPTS_EXHAUSTED')
            sources=[record['source']]+record.get('supporting_sources',[])
            evidence={s['id']:{b['id']:b['text'] for b in s['blocks']} for s in sources}
            wire,aliases=review_wire(record)
            reviews[review_key]=count+1;self.persist()
            try:
                result=self.call('Одна независимая итоговая содержательная проверка политики 4.3. '
                    'Проверь ВСЮ статью, включая заголовок/анонс: существенные факты, безопасность, законность режима, '
                    'самостоятельность C (формулировки, композиция, примеры), законченность и соответствие заголовка. '
                    'Не требуй глубины, объёма, всех тем источника, количества примеров/занятий или литературного совершенства. '
                    'A/B должны действительно воспроизводить полный оригинал/перевод по установленным правам. '
                    'Для медицинских, детских и правовых советов требуются компетентные независимые подтверждения; '
                    'неподтверждённый совет, недоказанная дата события или вывод исследования означают отказ. '
                    'В is_news укажи, сообщает ли статья оперативное событие как актуальную новость. Не маскируй новость под evergreen. '
                    'Не путай дату публикации с датой события. Для новости event_date ISO, event_source_id, event_evidence_id и '
                    'event_quote должны прямо подтверждать дату события; для неоперативного материала эти четыре поля пусты. '
                    'Каждый существенный проверяемый факт перечисли в claims: fact,source_id,evidence_id (id блока источника), '
                    'quote (непустая непрерывная дословная цитата этого блока). source_id — короткий sN из источников, evidence_id — короткий qN этого источника. Сам id не доказывает смысл. '
                    'В evidence_sufficient отметь достаточность независимой базы, для советов и исследований особенно строго. '
                    'approve=true только когда все семь критериев true, issues и unresolved пусты. '
                    'Идентификатор запроса (заполняется программой, не возвращай его): '+fp+'\nПредыдущая диагностика протокола: '+json.dumps(progress.get('review_protocol_feedback',{}),ensure_ascii=False)+'\nРежим и права: '+json.dumps(record['rights'],ensure_ascii=False)+
                    '\nДругие материалы и тип источника: '+json.dumps(self.issue_context(state,record),ensure_ascii=False)+'\nКонтекст переиздания (если есть): '+json.dumps(record.get('commission',{}),ensure_ascii=False)+'\nПовышенная проверка: '+str(record['high_risk'])+'\nСтатья: '+json.dumps(article,ensure_ascii=False)+
                    '\nПолные оригиналы и подтверждения: '+json.dumps(wire,ensure_ascii=False),output_tokens=8000,schema='v43_final')
            except news.runtime.GenerationPaused:
                reviews[review_key]=count;self.persist();raise
            if fingerprint(record)!=fp:raise p.Blocked('REVIEW_INPUT_CHANGED')
            result,protocol_errors=bind_review(result,record,aliases,fp)
            good=(not protocol_errors and result.get('input_hash')==fp and result.get('approve') is True and all(result.get(k) is True for k in CHECKS)
                  and result.get('issues')==[] and result.get('unresolved')==[] and bool(result.get('claims')))
            validation_errors=news_errors(result,record,state)
            if validation_errors:good=False
            for claim in result.get('claims',[]):
                literal=evidence.get(claim.get('source_id'),{}).get(claim.get('evidence_id'),'')
                if not claim.get('quote','').strip() or claim['quote'] not in literal or not claim.get('fact','').strip():good=False
            result['validation_errors']=validation_errors
            progress['history'].append(copy.deepcopy(result));self.persist()
            if good:
                record['checks']['final43']=dict(result,approved=True);record['status']='ready';self.persist();return
            progress['feedback']=copy.deepcopy(result)
            print('[editorial43] '+json.dumps({'code':'FINAL_REJECTED','candidate':record['id'],'attempt':count+1,'approve':result.get('approve'),'failed_checks':[key for key in CHECKS if result.get(key) is not True],'issues_count':len(result.get('issues',[])),'unresolved_count':len(result.get('unresolved',[])),'protocol_errors':protocol_errors,'validation_errors':validation_errors}),flush=True)
            if positive_semantics(result) and (protocol_errors or validation_errors):
                progress['review_protocol_feedback']={'codes':protocol_errors+validation_errors,'instruction':'Уточни проверку без изменения статьи: sN и qN, дословная цитата. Для дат отличай публикацию от события и текущую новость от неоперативного объяснения; контекст переиздания сам по себе не отменяет актуальность реальной новости. Если факт/дата не подтверждаются или текст выдаёт старое за новое, отклони; не выдумывай свидетельство и не меняй дату.'}
                self.persist();continue
            if record['mode']!='INDEPENDENT_ARTICLE' or progress['write_attempts']>=1+CONFIG['repair_attempts']:raise p.Blocked('FINAL_REJECTED')
            progress.setdefault('previous_articles',[]).append(record.pop('article'));self.persist()
