"""Executable v4.1 editorial engine. All work/checks remain in the encrypted state."""
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse
try:
    from scripts import policy41 as policy, source41, rights41, content41 as content, news
except ImportError:
    import policy41 as policy
    import source41
    import rights41
    import content41 as content
    import news

TRUSTED={
    'who.int','cdc.gov','nih.gov','ncbi.nlm.nih.gov','cochrane.org','unicef.org',
    'publication.pravo.gov.ru','consultant.ru','cbr.ru','mos.ru','nasa.gov','esa.int',
}


def host_matches(url,domains):
    host=(urlparse(url).hostname or '').lower().removeprefix('www.')
    return any(host==domain or host.endswith('.'+domain) for domain in domains)


def publisher_identity(url):
    host=(urlparse(url).hostname or '').lower().removeprefix('www.')
    roots=set(TRUSTED)|set(rights41.source_profiles()['institutions'])
    matches=[domain for domain in roots if host==domain or host.endswith('.'+domain)]
    return min(matches,key=lambda d:len(d.split('.'))) if matches else host


def new_state(date):
    return {'version':41,'policy_version':policy.VERSION,'date':date,'articles':{},'dossiers':{},
            'plan':[],'candidates':[],'sources':[],'history':[],'audit_passed':False,'stage':'planning'}


def migrate(state,date):
    if state is None: return new_state(date)
    if state.get('version')==41 and state.get('policy_version')==policy.VERSION: return state
    migrated=new_state(date)
    migrated['legacy_v31']=copy.deepcopy(state)
    for key in ('_quota_snapshot','branch','preview'): 
        if key in state: migrated[key]=copy.deepcopy(state[key])
    migrated['history'].append({'stage':'migration','decision':'needs_review','code':'V31_REVALIDATION_REQUIRED'})
    return migrated


ANALYSIS_REPAIR_REVISION='literal-quotes-bounded-v1'
ANALYSIS_RETRY_CODES={'CLAIM_NOT_IN_ORIGINAL','SOURCE_ANALYSIS_INCOMPLETE','EVENT_DATE_UNVERIFIED'}


def restore_analysis_repairs(state):
    if state.get('analysis_repair_revision')==ANALYSIS_REPAIR_REVISION:return
    for record in state.get('candidates',[]):
        last=(record.get('history') or [{}])[-1]
        if record.get('status')=='rejected' and last.get('code') in ANALYSIS_RETRY_CODES:
            record['status']='preparing'
            record.setdefault('progress',{})['_prior_analysis_failures']=1
    state['analysis_repair_revision']=ANALYSIS_REPAIR_REVISION


def event(state,record,stage,decision,code='',detail=''):
    entry={'at':datetime.now(policy.TZ).isoformat(),'stage':stage,'decision':decision,'code':code}
    if detail: entry['detail']=detail
    record.setdefault('history',[]).append(entry)
    print(f'[editorial41] stage={stage} decision={decision} code={code or "OK"}',flush=True)


def discover(state):
    if state.get('discovered'): return
    urls=[]
    if os.getenv('NEWS_V41_TRIAL')=='true':
        if os.getenv('GITHUB_ACTIONS')!='true': raise policy.Blocked('TRIAL_ACTIONS_REQUIRED')
        configured=json.loads((policy.ROOT/'config/trial-sources.json').read_text())
        for item in configured['candidates']:
            if item.get('trial_eligible'):
                state['candidates'].append(dict(item,id=policy.digest(item['url']),status='discovered',checks={},progress={}))
        state['discovered']=True
        return
    configured=policy.ROOT/'config/candidates.json'
    if configured.is_file(): urls.extend(json.loads(configured.read_text()).get('candidates',[]))
    # RSS descriptions are discovery hints only. They never become source evidence.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for items in pool.map(news.read_feed,news.FEEDS.items()):
            urls.extend({'url':item['url'],'category_hint':item.get('feed','')} for item in items)
    for category,items in news.EVERGREEN.items():
        urls.extend({'url':url,'category_hint':category} for _,url in items)
    existing={c['url'] for c in state['candidates']}
    for item in urls:
        if item['url'] in existing: continue
        existing.add(item['url'])
        state['candidates'].append(dict(item,id=policy.digest(item['url']),status='discovered',checks={},progress={}))
    state['discovered']=True


def article_hash(article,source,rights):
    return policy.digest({'content':content.content_hash(article),'source':{k:source.get(k) for k in ('content_hash','url','title','author','published','event_date','language')},'rights':rights})


def valid_gate(record,name,fingerprint):
    gate=record.get('checks',{}).get(name,{})
    return gate.get('approved') is True and gate.get('input_hash')==fingerprint


class Editor:
    def __init__(self,call=None,fetch=None,grants=None,images=None,persist=lambda:None):
        model=call or news.gemini
        def checked_call(prompt,**kwargs):
            # API context is a transport constraint, never a reason to shorten an article.
            if len(prompt)>policy.CONFIG['technical']['context_characters']:
                raise policy.Blocked('OPERATION_CONTEXT_NEEDS_REVIEW','No input was clipped or sent; reduce the scope of this operation')
            usage=getattr(self,'usage_record',None)
            stage=(getattr(self,'active_stage',None) if kwargs.get('schema') in ('v41_review','v41_issue') else None) or kwargs.get('schema','unknown')
            counter=None
            if usage is not None:
                counter=usage.setdefault('model_usage',{}).setdefault(stage,{'operations':0,'http_requests':0,'completed':0,'failures':0})
                counter['operations']+=1; self.persist()
            budget=news.runtime.ACTIVE_BUDGET
            previous_counter=budget.usage_counter if budget else None
            if budget: budget.usage_counter=counter
            try:
                result=model(prompt,**kwargs)
                if counter is not None: counter['completed']+=1
                return result
            except BaseException:
                if counter is not None: counter['failures']+=1
                raise
            finally:
                try:
                    if counter is not None: self.persist()
                finally:
                    if budget: budget.usage_counter=previous_counter
        self.call=checked_call; self.fetch=fetch or source41.fetch
        cfg=rights41.configuration()
        self.grants=cfg['grants'] if grants is None else grants
        self.image_grants=cfg['images'] if images is None else images
        self.persist=persist
    def cached_fetch(self,url):
        state=getattr(self,'state',None)
        if state is None: return self.fetch(url)
        cache=state.setdefault('source_cache',{})
        if url not in cache: cache[url]=self.fetch(url); self.persist()
        return copy.deepcopy(cache[url])
    def analyse(self,record):
        source=record['source']; progress=record['progress'].setdefault('analysis',{})
        pieces=content.chunks(source['blocks'])
        cache_key=policy.digest({'source':source['content_hash'],'url':source['url'],
            'metadata':[source.get(k) for k in ('author','published','language')],'analysis_revision':'facts-v2'})
        shared=getattr(self,'state',{}).setdefault('analysis_cache',{}).setdefault(cache_key,{})
        for piece in pieces:
            if piece['id'] not in progress and piece['id'] in shared:
                progress[piece['id']]=copy.deepcopy(shared[piece['id']])
        pending=[piece for piece in pieces if piece['id'] not in progress]
        repairs=record['progress'].setdefault('analysis_repairs',{})
        for group in content.operation_groups(pending):
            group_id=policy.digest([part['id'] for part in group])
            attempt=repairs.setdefault(group_id,{'failures':record['progress'].pop('_prior_analysis_failures',0),'code':''})
            while True:
                if attempt['failures']>=policy.CONFIG['technical']['content_attempts']:
                    raise policy.Blocked(attempt['code'] or 'SOURCE_ANALYSIS_INCOMPLETE')
                prompt=('Изучи полный оригинал по последовательным частям. Эта часть: '+json.dumps(content.operation_payload(group),ensure_ascii=False)+
                '\nМетаданные: '+json.dumps({k:source[k] for k in ('id','url','title','author','published','language')},ensure_ascii=False)+
                '\nИзвлеки проверяемые факты, точные дословные quote из одной конкретной части, требования к полноте и дату события (пусто, если неизвестна). '
                'Не придумывай. source_id должен совпадать с исходником. sensitive=true для спорных/медицинских/опасных утверждений. '
                'Для самостоятельного текста выделяй нейтральные проверяемые факты и общие знания. Авторские примеры, подборка и формулировки не являются свободным сырьём для рерайта. '
                'covered_ids — точные id ВСЕХ частей pieces (или единственной части). topic_key — фактический сюжет, не заголовок.')
                if attempt['code']:
                    prompt+='\nПредыдущая попытка отклонена: '+attempt['code']+(
                        '. Исправь именно диагностированную ошибку. quote — непрерывная дословная строка из одной '
                        'конкретной части, без парафраза, исправлений и склеивания. source_id — точный id оригинала; '
                        'covered_ids — все id переданных частей. Не выдумывай подтверждение. Если факт нельзя '
                        'подтвердить точной цитатой, не включай его в claims. Дату не указывай без дословного свидетельства.')
                result=self.call(prompt,output_tokens=8000,schema='v41_analysis')
                try:
                    if set(result.get('covered_ids',[]))!={part['id'] for part in group}: raise policy.Blocked('SOURCE_ANALYSIS_INCOMPLETE')
                    if result.get('event_date') and (not result.get('event_date_quote') or not any(result['event_date_quote'] in part['text'] for part in group)):
                        raise policy.Blocked('EVENT_DATE_UNVERIFIED')
                    assigned={part['id']:[] for part in group}
                    for claim in result['claims']:
                        matches=[part for part in group if claim.get('quote','').strip() and claim['quote'] in part['text']]
                        if claim['source_id']!=source['id'] or not matches: raise policy.Blocked('CLAIM_NOT_IN_ORIGINAL')
                        owner=matches[0]['id']; claim=dict(claim,id=owner+'/'+claim['id']); assigned[owner].append(claim)
                except policy.Blocked as exc:
                    attempt['failures']+=1; attempt['code']=exc.code
                    event(getattr(self,'state',{}),record,'source_analysis','retry_pending',exc.code)
                    self.persist()
                    if attempt['failures']>=policy.CONFIG['technical']['content_attempts']: raise
                    continue
                break
            for piece in group:
                progress[piece['id']]=dict(result,claims=assigned[piece['id']],covered_ids=[piece['id']])
                shared[piece['id']]=copy.deepcopy(progress[piece['id']])
            self.persist()
        if not any(r.get('worth_publishing') is True for r in progress.values()): raise policy.Blocked('NO_EDITORIAL_VALUE')
        categories=[r['category'] for r in progress.values()]
        record['category']=max(policy.CATEGORIES,key=lambda category:(categories.count(category),
            category==record.get('category_hint'),-policy.CATEGORIES.index(category)))
        record['kind']=next(iter(progress.values()))['kind']
        record['claims']=[claim for result in progress.values() for claim in result['claims']]
        record['requirements']=list(dict.fromkeys(r for result in progress.values() for r in result['requirements']))
        record['topic_key']=' | '.join(dict.fromkeys(result['topic_key'] for result in progress.values()))
        dates=[r['event_date'] for r in progress.values() if r['event_date']]
        if dates and len(set(dates))==1: source['event_date']=dates[0]
    def source_verified(self,state,record):
        source=record.get('source')
        if source is None:
            source=self.cached_fetch(record['url']); record['source']=source; self.persist()
        if not source.get('full_text_verified') or source.get('extraction_status')!='complete':
            raise policy.Blocked('FULL_ORIGINAL_REQUIRED')
        mode,rights=rights41.select_mode(source,self.grants)
        if mode in ('ORIGINAL_REPUBLICATION','FULL_TRANSLATION') and any(re.search(r'https?://|www\.',block['text']) for block in source['blocks']):
            # Preserve the complete original, rather than silently deleting its visible URLs.
            # The reader policy requires a single source block, so choose an independent work.
            alternative=rights41.decision(source,'INDEPENDENT_ARTICLE',self.grants)
            if alternative.get('status')!='allowed': raise policy.Blocked('ORIGINAL_READER_FORMAT_CONFLICT')
            mode,rights='INDEPENDENT_ARTICLE',alternative
        rights41.require(source,mode,rights)
        if record.get('mode') and record['mode']!=mode:
            record.setdefault('previous_preparations',[]).append({'article':record.pop('article',None),'progress':record['progress'],'checks':record['checks']})
            record['progress']={}; record['checks']={}
        record.update(mode=mode,rights=rights)
        # No source photograph is selected automatically. Every selected image has a separate grant.
        record['image_inventory']=[{'url':image['url'],'decision':rights41.image_decision(image,self.image_grants)} for image in source.get('images',[])]
        for image in record.get('images',[]):
            if rights41.image_decision(image,self.image_grants)['status']!='allowed': raise policy.Blocked('IMAGE_RIGHTS_UNKNOWN')
        self.analyse(record)
        if record['kind'].casefold()=='новость':
            try:
                if not source.get('published'): raise ValueError('news publication date missing')
                event_date=datetime.fromisoformat(source['event_date'])
                event_date=event_date.replace(tzinfo=policy.TZ) if event_date.tzinfo is None else event_date.astimezone(policy.TZ)
                release=datetime.fromisoformat(state['date']+'T'+policy.RELEASE_TIME).replace(tzinfo=policy.TZ)
                if not timedelta(0)<=release-event_date<=timedelta(hours=policy.CONFIG['news_event_hours']): raise ValueError('stale event')
            except (ValueError,TypeError): raise policy.Blocked('NEWS_EVENT_FRESHNESS_UNVERIFIED')
        record['checks']['source_verified']={'approved':True,'input_hash':policy.digest({'source':source['content_hash'],'rights':rights,'images':record.get('images',[])})}
        event(state,record,'source_verified','approved'); self.persist()
    def prepare(self,state,record):
        source=record['source']; mode=record['mode']; rights41.require(source,mode,record['rights'])
        progress=record['progress']
        if record.get('article'): return record['article']
        if mode=='ORIGINAL_REPUBLICATION':
            blocks=[dict(b,source_block_id=b['id']) for b in source['blocks']]
            article={'title':source['title'],'teaser':'','blocks':blocks,'activities':[]}
        elif mode=='FULL_TRANSLATION':
            blocks=content.complete_translation(source,progress,self.call,self.persist)
            article={'title':next(b['text'] for b in blocks if b['kind']=='title'),'teaser':'','blocks':blocks,'activities':[]}
        else:
            if not record['claims']: raise policy.Blocked('INDEPENDENT_FACT_BASE_EMPTY')
            if 'outline' not in progress:
                progress['outline']=self.call('Создай самостоятельную статью непосредственно по-русски. '
                    'Не перевод и не рерайт. Самостоятельные композиция, примеры и подбор. '
                    'Только проверенные факты: '+json.dumps([{k:v for k,v in fact.items() if k!='quote'} for fact in record['claims']],ensure_ascii=False)+
                    '\nПолезные вопросы: '+json.dumps(record['requirements'],ensure_ascii=False)+
                    '\nКатегории: '+json.dumps(policy.CATEGORIES,ensure_ascii=False)+
                    '\nВсе 20 приоритетов очерков: '+json.dumps(policy.CONFIG['priority_topics'],ensure_ascii=False)+
                    '\n2–3 глубоких очерка — предпочтение, не квота объёма. Никаких норм длины. '
                    'Если тема обещает '+str(content.promised_activities(source['title']) or 'конкретные')+
                    ' занятий, запланируй применимые самостоятельные инструкции и безопасность. '
                    'Верни title,teaser,category,kind,sections[id,heading,purpose,fact_ids].',output_tokens=6000,schema='v41_outline')
                self.persist()
            outline=progress['outline']
            if outline.get('category') not in policy.CATEGORIES or not outline.get('sections'): raise policy.Blocked('OUTLINE_INVALID')
            ids=[s['id'] for s in outline['sections']]
            if len(ids)!=len(set(ids)): raise policy.Blocked('OUTLINE_SECTION_DUPLICATE')
            facts={c['id']:c for c in record['claims']}
            for section in outline['sections']:
                if not section.get('fact_ids') or not set(section['fact_ids'])<=set(facts): raise policy.Blocked('OUTLINE_FACT_REFERENCE_INVALID')
                done=progress.setdefault('sections',{})
                if section['id'] in done: continue
                failures=progress.setdefault('section_attempts',{})
                while failures.get(section['id'],0)<policy.CONFIG['technical']['content_attempts']:
                    result=self.call('Напиши законченный самостоятельный раздел по-русски, без лимита длины и без воды. '
                        'Не называй источники, не вставляй URLs или редакционные комментарии. '
                        'Не копируй охраняемую форму и подборку первоисточника. '
                        'План раздела: '+json.dumps(section,ensure_ascii=False)+
                        '\nФакты: '+json.dumps([facts[i] for i in section['fact_ids']],ensure_ascii=False)+
                        '\nВопросы всей статьи: '+json.dumps(record['requirements'],ensure_ascii=False)+
                        '\ncovered_requirements — только дословные вопросы из этого списка, реально раскрытые данным разделом. Не повторяй чужие разделы ради покрытия.'
                        '\nВ практических activities нужны: уникальный id,title,age/предпосылки,materials,steps,benefit,safety. '
                        'Верни id,finished,blocks[kind,text],activities,covered_requirements. '
                        'finished=true только если все задачи раздела раскрыты. Предыдущая диагностика: '+str(progress.get('section_error','')),
                        output_tokens=16000,schema='v41_section')
                    if (result.get('id')==section['id'] and result.get('finished') is True
                            and result.get('blocks') and all(b.get('text','').strip() for b in result['blocks'])):
                        done[section['id']]=result; self.persist(); break
                    failures[section['id']]=failures.get(section['id'],0)+1
                    progress['section_error']='Incomplete section; supply complete content, not a summary'
                    self.persist()
                if section['id'] not in done: raise policy.Blocked('SECTION_ATTEMPTS_EXHAUSTED')
            article={'title':outline['title'],'teaser':outline['teaser'],'blocks':[], 'activities':[]}
            for section in outline['sections']:
                result=progress['sections'][section['id']]
                if section['heading']: article['blocks'].append({'id':section['id']+'/heading','kind':'heading','text':section['heading']})
                article['blocks'].extend(dict(b,id=f'{section["id"]}/{i}') for i,b in enumerate(result['blocks']))
                article['activities'].extend(dict(item,section_id=section['id']) for item in result['activities'])
            covered={question for section in progress['sections'].values() for question in section.get('covered_requirements',[])}
            if not set(record['requirements'])<=covered: raise policy.Blocked('TOPIC_REQUIREMENTS_NOT_COVERED')
            record['category']=outline['category']; record['kind']=outline['kind']
        article.update(mode=mode,source_id=source['id'],policy_version=policy.VERSION,
                       category=record.get('category') or (record.get('category_hint') if record.get('category_hint') in policy.CATEGORIES else 'Наука'),
                       kind=record.get('kind','статья'),images=copy.deepcopy(record.get('images',[])),
                       primary_source={k:source[k] for k in ('url','title','publisher','author','published')},
                       attribution=record['rights'].get('attribution',{}))
        # Practical analysis must be explicit for A/B too; names without instructions cannot pass.
        if mode!='INDEPENDENT_ARTICLE' and content.promised_activities(article['title']):
            article['activities']=copy.deepcopy(record.get('verified_activities',[]))
        content.semantic_structure(article,source,practical=mode=='INDEPENDENT_ARTICLE')
        record['article']=article
        record['checks']['content_prepared']={'approved':True,'input_hash':article_hash(article,source,record['rights'])}
        event(state,record,'content_prepared','approved'); self.persist()
        return article
    def practical_manifest(self,record):
        article=record['article']; source=record['source']
        expected=content.promised_activities(article['title']) or content.promised_activities(source['title'])
        if expected is None or len(article.get('_activity_evidence',[]))==expected: return
        groups=[]
        for block in source['blocks']:
            if block['kind'] in ('heading','item'):
                groups.append([block])
            elif groups and block['kind']!='title': groups[-1].append(block)
        numbered=[g for g in groups if re.match(r'^\s*\d+[.)\s]',g[0]['text'])]
        selected=numbered if len(numbered)==expected else groups
        if len(selected)!=expected: raise policy.Blocked('PRACTICAL_SECTION_COVERAGE_UNKNOWN')
        progress=record['progress'].setdefault('practical_manifest',{})
        for group in selected:
            identity=group[0]['id']
            if identity in progress: continue
            if len(group)==1 and group[0]['kind']=='heading': raise policy.Blocked('ACTIVITY_NAMES_WITHOUT_INSTRUCTIONS')
            result=self.call('Извлеки только реально содержащуюся в полном оригинале инструкцию. '
                'Не добавляй недостающую информацию. steps — ДОСЛОВНЫЕ исходные цитаты действий, '
                'а не названия игры. Возраст/предпосылки, материалы, смысл и безопасность — '
                'по тексту; отсутствие необходимых сведений отмечай в проверке, не выдумывай. '
                'id='+identity+'. Полный раздел: '+json.dumps(group,ensure_ascii=False),
                output_tokens=8000,schema='v41_practical')
            text=' '.join(b['text'] for b in group)
            if result.get('id')!=identity or not result.get('steps') or any(step not in text for step in result['steps']):
                raise policy.Blocked('PRACTICAL_EVIDENCE_NOT_IN_SOURCE')
            progress[identity]=result; self.persist()
        article['_activity_evidence']=[progress[g[0]['id']] for g in selected]
        content.semantic_structure(article,source)

    def review(self,state,record,stage):
        self.active_stage=stage
        article=record['article']; source=record['source']; fp=article_hash(article,source,record['rights'])
        if valid_gate(record,stage,fp): return
        record.pop('rejected_part',None)
        if stage=='completeness_checked' and record['mode']!='INDEPENDENT_ARTICLE': self.practical_manifest(record)
        content.semantic_structure(article,source,practical=record['mode']=='INDEPENDENT_ARTICLE' or stage!='fact_checked')
        sensitive=(article['category']=='Здоровье и движение' or bool(article.get('activities')) or any(c['sensitive'] for c in record['claims']))
        supporting=record.setdefault('supporting_sources',[])
        if stage=='fact_checked' and sensitive:
            if not supporting:
                for url in record.get('verification_urls',[]):
                    supporting.append(self.cached_fetch(url)); self.persist()
            domains={publisher_identity(s['url']) for s in [source]+supporting if s.get('full_text_verified')}
            allowed=({'who.int','cdc.gov','nih.gov','ncbi.nlm.nih.gov','cochrane.org'} if article['category']=='Здоровье и движение' else TRUSTED)
            authoritative=[s for s in [source]+supporting if host_matches(s['url'],allowed)]
            if len(domains)<2 or not authoritative: raise policy.Blocked('INDEPENDENT_SAFETY_EVIDENCE_REQUIRED')
        support_facts=[]
        if stage=='fact_checked' and supporting:
            for additional in supporting:
                analysis=record['progress'].setdefault('support_analysis',{}).setdefault(additional['id'],{})
                reference_record={'source':additional,'progress':analysis}
                self.analyse(reference_record)
                support_facts.extend({'source_url':additional['url'],**claim} for claim in reference_record['claims'])
        parts=content.chunks(article['blocks'])
        if record['mode']=='FULL_TRANSLATION':
            # Review every accepted translation operation against its exact full source part,
            # even when the translation expands beyond the source's character boundaries.
            parts=[{'id':piece['id'],'block_id':piece['block_id'],'kind':piece['kind'],
                    'text':record['progress']['translated'][piece['id']], 'source_piece':piece}
                   for piece in content.chunks(source['blocks'])]
        for item in article.get('activities',[]):
            parts.extend(dict(part,section_id=item.get('section_id')) for part in content.chunks([{'id':'activity/'+item['id'],'kind':'paragraph','text':json.dumps(item,ensure_ascii=False)}]))
        progress=record['progress'].setdefault('reviews',{}).setdefault(stage,{})
        if progress.get('input_hash')!=fp: progress.clear(); progress.update(input_hash=fp,parts={})
        pending=[part for part in parts if part['id'] not in progress['parts']]
        for group in content.operation_groups(pending,limit=policy.CONFIG['technical']['review_operation_characters']):
            part=group[0]; part_index=parts.index(part)
            references=[]
            if record['mode'] in ('ORIGINAL_REPUBLICATION','FULL_TRANSLATION'):
                for member in group:
                    reference=member.get('source_piece') or next((b for b in content.chunks(source['blocks']) if b['id']==member['id']),None)
                    references.extend([reference] if reference else record['claims'])
            else:
                references=record['claims']
            instructions={
              'fact_checked':'Отдельный фактчекинг: имена, даты события, числа, цитаты, научные/медицинские/правовые сведения, безопасность. Непроверяемое существенное утверждение — unresolved, а не approve. Ошибку чужого оригинала не исправлять молча.',
              'completeness_checked':'Проверь смысловую полноту: все обещания заголовка, инструкции, примеры, числа, оговорки и выводы. Для A/B сравни полный оригинал с данной частью, не допускай сокращение. Если существенный смысл зависит от отсутствующей иллюстрации/таблицы, unresolved; не считай лицензию текста разрешением на каждую картинку. Для C оцени полноту самостоятельной темы и применимость действий, а не копирование чужой композиции.',
              'editorial_checked':'Отдельная литературная проверка, включая самостоятельность режима C: сравни исходную подборку и расположение идей с новым текстом. Лёгкий рерайт/перевод/копирование авторской подборки запрещены, даже при иных словах. Если самостоятельность не установлена — unresolved. Законченность мысли, ясный живой русский язык, связность, отсутствие воды, дублей, канцелярита и метатекста. Практические действия действительно выполнимы. Никаких нормативов длины.',
            }[stage]
            result=self.call(instructions+'\nЗаголовок: '+article['title']+'\nЧасть: '+json.dumps(content.operation_payload(group),ensure_ascii=False)+
                '\nПроверенные сведения/оригинал: '+json.dumps(references,ensure_ascii=False)+
                '\nНезависимые проверенные цитаты: '+json.dumps(support_facts,ensure_ascii=False)+
                '\nИсходная композиция (для выявления скрытого рерайта): '+json.dumps([b for b in source['blocks'] if b['kind'] in ('title','heading','item')] if record['mode']=='INDEPENDENT_ARTICLE' else [],ensure_ascii=False)+
                '\nОбязательные вопросы: '+json.dumps(record['requirements'],ensure_ascii=False)+
                '\nСоседние части для проверки связности: '+json.dumps(parts[max(0,part_index-1):part_index]+parts[part_index+1:part_index+2],ensure_ascii=False)+
                '\nПроверяй локальные факты/полноту именно этой части; другие вопросы могут быть раскрыты в других разделах. Не требуй всей статьи внутри одной технической части.'+
                '\nПри отказе affected_ids — только точные id частей с доказанной проблемой; при общей проблеме без адресного основания оставь пустой список. Не выбирай случайный раздел.'+
                '\nВерни approve,issues,unresolved,covered_ids=[точные id ВСЕХ проверенных pieces или одной части].',output_tokens=5000,schema='v41_review')
            try: content.approved_review(result,[member['id'] for member in group])
            except policy.Blocked:
                affected=result.get('affected_ids',[]) if isinstance(result,dict) else []
                scoped=[member for member in group if member['id'] in affected]
                scopes={member.get('section_id') or member['block_id'].split('/')[0] for member in scoped}
                block_id=(next(iter(scopes))+'/repair') if len(scopes)==1 and set(affected)<={m['id'] for m in group} else ''
                record['rejected_part']={'stage':stage,'block_id':block_id,'result':result}
                self.persist()
                raise
            for member in group: progress['parts'][member['id']]=result
            self.persist()
        if stage=='editorial_checked' and record['mode']=='INDEPENDENT_ARTICLE' and progress.get('independence_hash')!=fp:
            result=self.call('Проверка самостоятельности режима C. Отдельно проверь композицию, формулировки, '
                'подбор примеров и объяснения. Использование общих неохраняемых фактов допустимо без разрешения автора. '
                'Но перевод, синонимический рерайт или сохранение охраняемой подборки не превращают произведение в самостоятельное. '
                'Сомнения — unresolved. Для темы21 занятия нужен собственный набор и организация применимых действий, '
                'а не перевод той же подборки. covered_ids=[composition,wording,examples,explanations]. '
                '\nПолный оригинал: '+json.dumps(source['blocks'],ensure_ascii=False)+
                '\nСамостоятельная статья: '+json.dumps({'title':article['title'],'blocks':article['blocks'],'activities':article.get('activities',[])},ensure_ascii=False),
                output_tokens=5000,schema='v41_review')
            try: content.approved_review(result,['composition','wording','examples','explanations'])
            except policy.Blocked:
                record['rejected_part']={'stage':stage,'block_id':'','result':result}; self.persist()
                raise
            progress['independence_hash']=fp; progress['independence_result']=result; self.persist()
        record['checks'][stage]={'approved':True,'input_hash':fp,'checked_at':datetime.now(policy.TZ).isoformat()}
        self.active_stage=None
        event(state,record,stage,'approved'); self.persist()
    def finish(self,state,record):
        self.state=state
        self.usage_record=record; self.active_stage=None
        if record.get('source') and record.get('mode'):
            current=rights41.decision(record['source'],record['mode'],self.grants)
            if current.get('status')!='allowed' or current!=record.get('rights'): record['checks'].pop('source_verified',None)
        if not record['checks'].get('source_verified',{}).get('approved'): self.source_verified(state,record)
        while True:
            self.prepare(state,record)
            try:
                for stage in ('fact_checked','completeness_checked','editorial_checked'): self.review(state,record,stage)
                break
            except policy.Blocked as exc:
                rejected=record.get('rejected_part',{})
                progress=record['progress']
                section_id=next((s['id'] for s in progress.get('outline',{}).get('sections',[])
                                 if rejected.get('block_id','').startswith(s['id']+'/')),None)
                if (exc.code!='REVIEW_REJECTED' or record['mode']!='INDEPENDENT_ARTICLE' or not section_id
                        or progress.get('repair_count',0)>=policy.CONFIG['technical']['repair_attempts']): raise
                progress['repair_count']=progress.get('repair_count',0)+1
                progress.setdefault('repair_history',[]).append(copy.deepcopy(rejected))
                progress['section_error']=json.dumps(rejected,ensure_ascii=False)
                progress['sections'].pop(section_id,None)
                # Preserve all other accepted sections and their generation attempts.
                progress.get('section_attempts',{}).pop(section_id,None)
                record.pop('article',None)
                for name in policy.STAGES:
                    if name!='source_verified': record['checks'].pop(name,None)
                event(state,record,'repair','retry','ATTRIBUTED_SECTION_REPAIR')
                self.persist()
        article=record['article']; fp=article_hash(article,record['source'],record['rights'])
        for name in ('content_prepared','fact_checked','completeness_checked','editorial_checked'):
            if not valid_gate(record,name,fp): raise policy.Blocked('STALE_REVIEW')
        rights41.require(record['source'],article['mode'],record['rights'])
        content.semantic_structure(article,record['source'])
        record['checks']['ready_to_publish']={'approved':True,'input_hash':fp}
        record['status']='ready'
        event(state,record,'ready_to_publish','approved'); self.persist()
        return article


def duplicate(article,record,others):
    def shingles(text):
        tokens=content.normalized(text).split()
        return set(zip(*(tokens[i:] for i in range(8))))
    text=content.body(article); tokens=shingles(text)
    for prior in others:
        if prior.get('source_url')==record['source']['canonical']: return True
        if prior.get('topic_key') and content.normalized(prior['topic_key'])==content.normalized(record['topic_key']): return True
        old=shingles(prior.get('text',''))
        if tokens and old and len(tokens&old)/min(len(tokens),len(old))>.65: return True
    return False


def archive_entries(root):
    """Read published text, including legacy archives, without modifying it."""
    result=[]
    for path in Path(root).glob('issues/*/articles/*/index.html'):
        from html.parser import HTMLParser
        class Reader(HTMLParser):
            def __init__(self): super().__init__(); self.text=[]; self.links=[]
            def handle_data(self,text): self.text.append(text)
            def handle_starttag(self,tag,attrs):
                a=dict(attrs)
                if tag=='a' and a.get('href','').startswith('https://'): self.links.append(a['href'])
        reader=Reader(); reader.feed(path.read_text(encoding='utf-8'))
        result.append({'text':' '.join(reader.text),'source_url':next((u for u in reader.links if not u.startswith('https://387.su/')),''),'path':str(path)})
    return result


def select_ready(state,archive=()):
    ready=[c for c in state['candidates'] if c.get('status')=='ready']
    selected=[]
    def add(record):
        other=[{'text':content.body(c['article']),'source_url':c['source']['canonical'],'topic_key':c['topic_key']} for c in selected]
        if duplicate(record['article'],record,list(archive)+other): return False
        selected.append(record); return True
    for category in policy.CONFIG['required_categories']:
        for record in ready:
            if record['article']['category']==category and record not in selected and add(record): break
    if not policy.REQUIRED.issubset({c['article']['category'] for c in selected}): return []
    while len(selected)<policy.ARTICLE_COUNT:
        available=[c for c in ready if c not in selected]
        available.sort(key=lambda c:(sum(s['article']['category']==c['article']['category'] for s in selected),
                                     c['article'].get('kind')!='очерк'))
        if not any(add(c) for c in available): return []
    return selected


ISSUE_CODES=('FACT_ERROR','INCOMPLETE','UNSAFE','DUPLICATE','BALANCE','COMPOSITION','LANGUAGE','RIGHTS','OTHER')
news.SCHEMAS['v41_issue']=content.schema({'approve':content.B,'covered_ids':{'type':'array','items':content.S},
    'issues':{'type':'array','items':content.schema({'code':{'type':'string','enum':list(ISSUE_CODES)},'reason':content.S,
        'article_ids':{'type':'array','items':{'type':'integer'}},
        'repair_ids':{'type':'array','items':{'type':'integer'}},
        'action':{'type':'string','enum':['replace_story','hold']}})}})


def validate_issue(state):
    ids=state.get('selected_ids',[])
    if len(ids)!=policy.ARTICLE_COUNT or len(set(ids))!=policy.ARTICLE_COUNT: raise policy.Blocked('TWELVE_READY_ARTICLES_REQUIRED')
    records={r['id']:r for r in state['candidates']}
    for identity in ids:
        record=records[identity]
        if record.get('status')!='ready': raise policy.Blocked('ARTICLE_NOT_READY')
        article=record['article']; source=record['source']
        rights41.require(source,article['mode'],record['rights'])
        current_rights=rights41.decision(source,article['mode'])
        if current_rights.get('status')!='allowed' or current_rights!=record['rights']:
            raise policy.Blocked('RIGHTS_REVIEW_STALE')
        content.semantic_structure(article,source)
        fp=article_hash(article,source,record['rights'])
        if not all(valid_gate(record,name,fp) for name in policy.STAGES if name!='source_verified'):
            raise policy.Blocked('ARTICLE_GATE_MISSING_OR_STALE')
        source_fp=policy.digest({'source':source['content_hash'],'rights':record['rights'],'images':record.get('images',[])})
        if not valid_gate(record,'source_verified',source_fp): raise policy.Blocked('SOURCE_GATE_STALE')
    if not policy.REQUIRED.issubset({records[i]['article']['category'] for i in ids}): raise policy.Blocked('REQUIRED_CATEGORY_MISSING')
    signature=policy.digest([article_hash(records[i]['article'],records[i]['source'],records[i]['rights']) for i in ids])
    if state.get('issue_approval_hash')!=signature or not state.get('audit_passed'): raise policy.Blocked('ISSUE_NOT_APPROVED')
    return True


def verify_publication_sources(state,fetch=None,persist=lambda:None):
    """Recheck live originals without replacing approved text or consulting Gemini."""
    fetch=fetch or source41.fetch
    records={r['id']:r for r in state['candidates']}
    for identity in state['selected_ids']:
        record=records[identity]; original=record['source']
        try: current=fetch(original['url'])
        except Exception as exc:
            record['status']='needs_review'; state['audit_passed']=False
            event(state,record,'release_source','needs_review','SOURCE_RELEASE_UNAVAILABLE',type(exc).__name__)
            persist()
            raise policy.Blocked('SOURCE_RELEASE_UNAVAILABLE',type(exc).__name__) from exc
        keys=('content_hash','title','author','published','language','declared_license')
        if (not current.get('full_text_verified') or current.get('metadata_status')!='verified'
                or any(current.get(k)!=original.get(k) for k in keys)):
            record['status']='needs_review'; state['audit_passed']=False
            event(state,record,'release_source','needs_review','SOURCE_CHANGED_AFTER_REVIEW')
            persist()
            raise policy.Blocked('SOURCE_CHANGED_AFTER_REVIEW')
        record['release_source_checked_at']=datetime.now(policy.TZ).isoformat(); persist()
    return True


def approve_selection(state,selected,editor):
    editor.usage_record=state; editor.active_stage='issue_audit'
    signature=policy.digest([article_hash(r['article'],r['source'],r['rights']) for r in selected])
    if state.get('issue_approval_hash')==signature and state.get('audit_passed'): return True
    if signature in state.get('issue_rejections',{}): raise policy.Blocked('UNCHANGED_ISSUE_REJECTED')
    if state.get('issue_attempts',0)>=4: raise policy.Blocked('ISSUE_REPAIR_LIMIT')
    records=[{'article_id':i+1,'id':r['id'],'title':r['article']['title'],'category':r['article']['category'],
              'kind':r['article']['kind'],'reader_value':[a.get('reader_value','') for a in r['progress']['analysis'].values()],
              'topic':r['topic_key']} for i,r in enumerate(selected)]
    result=editor.call('Финальная композиция 387 News v4.1: ровно '+str(policy.ARTICLE_COUNT)+
        ' законченных проверенных статей; обязательные рубрики '+json.dumps(list(policy.REQUIRED),ensure_ascii=False)+
        '. Примерно половина про жизнь — ориентир, не механическая квота. '
        'Предпочтительны 2–3 глубоких очерка (человеческий и интеллектуальный), без требования длины. '
        'Никакого вытеснения остальных направлений одной тематикой и повторов сюжета/угла. '
        'Каждый текст уже отдельно проверен. При отказе укажи только конкретно затронутые article_ids '
        'и минимальные repair_ids из этого множества, action=replace_story или hold без repair_ids. '
        'Не выбирай статью по объёму. covered_ids — все id кандидатов. Номер: '+json.dumps(records,ensure_ascii=False),
        output_tokens=6000,schema='v41_issue')
    state['issue_attempts']=state.get('issue_attempts',0)+1
    if set(result.get('covered_ids',[]))!={r['id'] for r in selected}: raise policy.Blocked('ISSUE_REVIEW_INCOMPLETE')
    if result.get('approve') is not True or result.get('issues'):
        findings=result.get('issues') or []
        state.setdefault('issue_rejections',{})[signature]=result
        targets=set()
        for finding in findings:
            affected=finding.get('article_ids'); fixes=finding.get('repair_ids')
            safe_code=finding.get('code') if finding.get('code') in ISSUE_CODES else 'OTHER'
            safe_ids=[i for i in affected if type(i) is int and 1<=i<=policy.ARTICLE_COUNT] if isinstance(affected,list) else []
            print(f'[editorial41] stage=issue_editorial decision=rejected code={safe_code} article_ids={safe_ids}',flush=True)
            if (finding.get('action')!='replace_story' or not isinstance(affected,list) or not isinstance(fixes,list)
                    or not fixes or not set(fixes)<=set(affected)
                    or any(type(i) is not int or not 1<=i<=policy.ARTICLE_COUNT for i in affected+fixes)):
                raise policy.Blocked('ISSUE_EDITORIAL_HOLD',json.dumps(result,ensure_ascii=False))
            targets.update(fixes)
        if not targets: raise policy.Blocked('ISSUE_EDITORIAL_HOLD',json.dumps(result,ensure_ascii=False))
        for target in targets:
            selected[target-1]['status']='rejected'
            event(state,selected[target-1],'issue_editorial','rejected','ATTRIBUTED_ISSUE_VETO',json.dumps(result,ensure_ascii=False))
        editor.persist()
        return False
    state['selected_ids']=[r['id'] for r in selected]
    state['articles']={r['id']:r['article'] for r in selected}
    state['plan']=[{'candidate_id':r['id'],'title':r['article']['title'],'category':r['article']['category'],'kind':r['article']['kind']} for r in selected]
    state.update(audit_passed=True,issue_approval_hash=signature,stage='audited')
    editor.persist(); validate_issue(state)
    return True


def advance(state,date,preview,ops,persist,now=None,check_public=None,editor=None):
    try:
        from scripts import pipeline, publication41
    except ImportError:
        import pipeline
        import publication41
    clock=pipeline.now_moscow if now is None else lambda:now
    current=clock()
    # Existing immutable public archives take the no-generation delivery path.
    if (ops.ROOT/'issues'/date/'index.html').is_file():
        return pipeline.published_delivery(state,date,ops,preview,current,check_public or pipeline.site_checks.check_site)
    editor=editor or Editor(persist=persist)
    restore_analysis_repairs(state); persist()
    rights_signature=policy.digest({'grants':editor.grants,'images':editor.image_grants,'source_profiles':rights41.source_profiles()})
    if state.get('rights_config_hash')!=rights_signature:
        for record in state['candidates']:
            last=(record.get('history') or [{}])[-1].get('code','')
            if record.get('status')=='needs_review' and 'RIGHTS' in last:
                record['status']='discovered'; record.get('checks',{}).pop('source_verified',None)
            if record.get('status')=='ready':
                current_rights=rights41.decision(record['source'],record['mode'],editor.grants)
                if current_rights!=record['rights']:
                    record['status']='preparing'; record['checks'].pop('source_verified',None)
                    state['audit_passed']=False
        state['rights_config_hash']=rights_signature; persist()
    release=datetime.fromisoformat(date+'T'+policy.RELEASE_TIME).replace(tzinfo=policy.TZ)
    if state.get('audit_passed'):
        try: validate_issue(state)
        except policy.Blocked as exc:
            pipeline.status(state,'BLOCKED','review_stale_approval',exc.code); persist(); return False
    else:
        discover(state); persist()
        archive=archive_entries(ops.ROOT)
        for _ in range(policy.CONFIG['technical']['run_steps']):
            selected=select_ready(state,archive)
            ready_count=sum(c.get('status')=='ready' for c in state['candidates'])
            # Prepared reserves are preferred; a complete approved issue need not wait for extras after release.
            if selected and (ready_count>=policy.ARTICLE_COUNT+policy.CONFIG['reserve_articles'] or clock()>=release or not pipeline.capacity()):
                if not pipeline.capacity():
                    pipeline.pause(state,ready=True); persist(); return False
                pipeline.status(state,'AUDIT_IN_PROGRESS','review_issue_composition'); persist()
                try:
                    if approve_selection(state,selected,editor): break
                except policy.Blocked as exc:
                    state.setdefault('history',[]).append({'stage':'issue_editorial','code':exc.code,'detail':exc.detail})
                    pipeline.status(state,'BLOCKED','review_issue_diagnosis',exc.code); persist(); return False
            if not pipeline.capacity(): pipeline.pause(state,ready=bool(selected)); persist(); return False
            pending=[c for c in state['candidates'] if c.get('status') in ('discovered','preparing','retryable_error')]
            if not pending:
                if selected:
                    try:
                        if approve_selection(state,selected,editor): break
                    except policy.Blocked as exc:
                        state.setdefault('history',[]).append({'stage':'issue_editorial','code':exc.code,'detail':exc.detail})
                        pipeline.status(state,'BLOCKED','review_issue_diagnosis',exc.code); persist(); return False
                pipeline.status(state,'BLOCKED','review_candidates_and_rights','NO_TWELVE_READY_ARTICLES'); persist(); return False
            all_records=state['candidates']; start=state.get('candidate_cursor',0)%len(all_records)
            index=next((start+i)%len(all_records) for i in range(len(all_records)) if all_records[(start+i)%len(all_records)] in pending)
            record=all_records[index]; state['candidate_cursor']=(index+1)%len(all_records)
            record['status']='preparing'; persist()
            pipeline.status(state,'RESEARCHING' if not record['checks'].get('source_verified') else 'WRITING','prepare_verified_reserves')
            try:
                editor.finish(state,record)
                state['dossiers'][record['id']]={'claims':record['claims'],'checks':record['checks']}
                state['articles'][record['id']]=record['article']
            except news.runtime.GenerationPaused:
                record['status']='preparing'; persist(); raise
            except policy.Blocked as exc:
                record['status']='needs_review' if 'RIGHTS' in exc.code or 'SOURCE_NEEDS' in exc.code else 'rejected'
                event(state,record,'gate',record['status'],exc.code,exc.detail)
            except Exception as exc:
                record['status']='retryable_error'
                record['source_attempts']=record.get('source_attempts',0)+1
                if record['source_attempts']>=policy.CONFIG['technical']['source_attempts']: record['status']='needs_review'
                event(state,record,'transport',record['status'],'EXTERNAL_SOURCE_ERROR',type(exc).__name__)
                persist(); return False
            persist()
        if not state.get('audit_passed'):
            pipeline.status(state,'RETRY_PENDING','continue_candidates','RUN_STEP_LIMIT'); persist(); return False
    pipeline.status(state,'APPROVED','prepare_html'); persist()
    if state.get('v41_preview_hash')!=state['issue_approval_hash']:
        publication41.build(state,ops.ROOT,preview=True)
        state['v41_preview_hash']=state['issue_approval_hash']; persist()
    current=clock()
    if preview: return False
    if current<release:
        budget=news.runtime.ACTIVE_BUDGET
        if (release-current).total_seconds()>600 or budget and budget.remaining_seconds()<(release-current).total_seconds()+90:
            pipeline.status(state,'WAITING_FOR_RELEASE_TIME','publish_at_release'); persist(); return False
    if not pipeline.reserve_delivery(state,max(current,release)): persist(); return False
    persist()
    return ops.render(state,False)
