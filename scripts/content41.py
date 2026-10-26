"""Semantic content contracts and complete, resumable model operations."""
from difflib import SequenceMatcher
import json
import re
try:
    from scripts import policy41 as policy, news
except ImportError:
    import policy41 as policy
    import news

S={'type':'string'}; B={'type':'boolean'}

def schema(properties): return {'type':'object','properties':properties,'required':list(properties)}

news.SCHEMAS.update({
 'v41_translation':schema({'finished':B,'segments':{'type':'array','items':schema({'id':S,'text':S})}}),
 'v41_analysis':schema({'claims':{'type':'array','items':schema({'id':S,'source_id':S,'quote':S,'fact':S,'sensitive':B})},
                       'requirements':{'type':'array','items':S},'topic_key':S,'event_date':S,'event_date_quote':S,
                       'category':{'type':'string','enum':list(policy.CATEGORIES)},'kind':S,'worth_publishing':B,'reader_value':S,
                       'covered_ids':{'type':'array','items':S}}),
 'v41_outline':schema({'title':S,'teaser':S,'category':S,'kind':S,'sections':{'type':'array','items':schema({'id':S,'heading':S,'purpose':S,'fact_ids':{'type':'array','items':S}})}}),
 'v41_section':schema({'id':S,'finished':B,'blocks':{'type':'array','items':schema({'kind':S,'text':S})},
     'activities':{'type':'array','items':schema({'id':S,'title':S,'age':S,'materials':{'type':'array','items':S},
        'steps':{'type':'array','items':S},'benefit':S,'safety':S})},'covered_requirements':{'type':'array','items':S}}),
 'v41_practical':schema({'id':S,'title':S,'age':S,'materials':{'type':'array','items':S},
                           'steps':{'type':'array','items':S},'benefit':S,'safety':S}),
 'v41_review':schema({'approve':B,'issues':{'type':'array','items':S},'unresolved':{'type':'array','items':S},
                     'covered_ids':{'type':'array','items':S}}),
})


def chunks(blocks):
    """Technical operation size only; all offsets and all blocks are retained."""
    limit=policy.CONFIG['technical']['operation_characters']; result=[]
    for block in blocks:
        text=block['text']
        if not text.strip(): raise policy.Blocked('EMPTY_SOURCE_BLOCK')
        for start in range(0,len(text),limit):
            end=min(len(text),start+limit)
            result.append({'id':f'{block["id"]}:{start}:{end}','block_id':block['id'],
                           'kind':block['kind'],'start':start,'end':end,'text':text[start:end]})
    return result


def operation_groups(pieces,boundary=None):
    """Pack complete short pieces into a technical request; retain every id/offset.

    Three-piece operations keep the legacy single-piece protocol for restored
    small jobs. No content is shortened and no editorial length rule is applied.
    """
    if len(pieces)<=3: return [[piece] for piece in pieces]
    groups=[]; current=[]; size=0; key=None
    for piece in pieces:
        next_key=boundary(piece) if boundary else None
        if current and (size+len(piece['text'])>policy.CONFIG['technical']['operation_characters'] or next_key!=key):
            groups.append(current); current=[]; size=0
        current.append(piece); size+=len(piece['text']); key=next_key
    if current: groups.append(current)
    return groups


def operation_payload(group):
    return group[0] if len(group)==1 else {'id':'batch/'+policy.digest([p['id'] for p in group]),'pieces':group}


def complete_translation(source,progress,call=news.gemini,persist=lambda:None):
    if progress.get('translation_source_hash') not in (None,source['content_hash']):
        raise policy.Blocked('TRANSLATION_SOURCE_CHANGED')
    progress['translation_source_hash']=source['content_hash']
    pieces=chunks(source['blocks'])
    expected=[p['id'] for p in pieces]
    accepted=progress.setdefault('translated',{})
    pending=[piece for piece in pieces if piece['id'] not in accepted]
    for group in operation_groups(pending):
        identity=policy.digest([p['id'] for p in group]); failures=progress.setdefault('translation_attempts',{})
        for _ in range(policy.CONFIG['technical']['content_attempts']):
            if failures.get(identity,0)>=policy.CONFIG['technical']['content_attempts']:
                raise policy.Blocked('TRANSLATION_ATTEMPTS_EXHAUSTED')
            result=call('Полный точный перевод на русский. Ничего не сокращай и не добавляй: '
                'сохрани все инструкции, примеры, цифры и оговорки. Техническая часть исходника: '+
                json.dumps(operation_payload(group),ensure_ascii=False)+'. Верни finished=true и segments=[{id:точный id каждой части,text:полный перевод}]. '
                'В batch верни ВСЕ pieces, отдельный segment для каждого исходного id. '
                'Если не завершено, finished=false. Предыдущая ошибка: '+str(progress.get('translation_error','')),
                output_tokens=12000,schema='v41_translation')
            segments=result.get('segments',[]) if isinstance(result,dict) else []
            if (isinstance(result,dict) and result.get('finished') is True and isinstance(segments,list)
                    and len(segments)==len(group) and all(isinstance(x,dict) and isinstance(x.get('text'),str) and x['text'].strip() for x in segments)
                    and {x.get('id') for x in segments}=={p['id'] for p in group}):
                accepted.update({x['id']:x['text'] for x in segments}); persist(); break
            failures[identity]=failures.get(identity,0)+1
            progress['translation_error']='Incomplete response or missing/incorrect segment id; continue full content, never summarize'
            persist()
        if any(p['id'] not in accepted for p in group): raise policy.Blocked('TRANSLATION_INCOMPLETE')
    if set(accepted)!=set(expected): raise policy.Blocked('TRANSLATION_PART_SET_MISMATCH')
    blocks=[]
    for block in source['blocks']:
        translated=''.join(accepted[p['id']] for p in pieces if p['block_id']==block['id'])
        blocks.append(dict(block,text=translated,source_block_id=block['id']))
    return blocks


def normalized(text): return ' '.join(re.findall(r'\w+',text.casefold()))


def body(article):
    parts=[article['title'],article.get('teaser','')]+[b['text'] for b in article.get('blocks',[])]
    for item in article.get('activities',[]):
        parts.extend([item['title'],item['age'],*item['materials'],*item['steps'],item['benefit'],item['safety']])
    return '\n'.join(parts)


def promised_activities(title):
    match=re.search(r'\b(\d+)\s+(?:игр\w*|занят\w*|упражнен\w*|(?:learning\s+)?activities|games)\b',title,re.I)
    return int(match.group(1)) if match else None


def semantic_structure(article,source,practical=True):
    if not article.get('title','').strip() or not article.get('blocks'):
        raise policy.Blocked('ARTICLE_INCOMPLETE')
    blocks=article['blocks']
    if any(not isinstance(b.get('text'),str) or not b['text'].strip() or b.get('kind') not in ('title','heading','paragraph','item','quote','table') for b in blocks):
        raise policy.Blocked('ARTICLE_BLOCK_INVALID')
    texts=[normalized(b['text']) for b in blocks if b['kind'] not in ('heading','title')]
    if len(texts)!=len(set(texts)): raise policy.Blocked('REPEATED_CONTENT')
    if re.search(r'https?://|www\.|\[[^]]+\]\([^)]*\)',body(article),re.I):
        raise policy.Blocked('INTERNAL_LINK_IN_BODY')
    if re.search(r'(?i)(как (?:искусственный интеллект|языковая модель)|в источнике рассказывается|проверено по \d+ ссылкам|system prompt)',body(article)):
        raise policy.Blocked('EDITORIAL_META_IN_BODY')
    mode=article['mode']
    if mode in ('ORIGINAL_REPUBLICATION','FULL_TRANSLATION'):
        if ([b.get('source_block_id') for b in blocks]!=[b['id'] for b in source['blocks']]
                or [b['kind'] for b in blocks]!=[b['kind'] for b in source['blocks']]):
            raise policy.Blocked('SOURCE_COVERAGE_INCOMPLETE')
        if mode=='ORIGINAL_REPUBLICATION' and [b['text'] for b in blocks]!=[b['text'] for b in source['blocks']]:
            raise policy.Blocked('ORIGINAL_CHANGED')
        for block,original in zip(blocks,source['blocks']):
            if any(block.get(k)!=original.get(k) for k in ('heading_level','list_kind','list_group','list_index')):
                raise policy.Blocked('SOURCE_STRUCTURE_CHANGED')
    else:
        if any(b.get('source_block_id') for b in blocks): raise policy.Blocked('COPIED_SOURCE_LAYOUT')
        # A different title alone cannot turn copied expression/selection into an independent article.
        original=normalized(' '.join(b['text'] for b in source['blocks']))
        own=normalized(' '.join(b['text'] for b in blocks))
        shingles=lambda text:set(zip(*(text.split()[i:] for i in range(8))))
        a,b=shingles(original),shingles(own)
        if own==original or a and b and len(a&b)/len(b)>.30: raise policy.Blocked('DISGUISED_COPY')
        headings=[normalized(b['text']) for b in blocks if b['kind'] in ('heading','item')]
        source_headings=[normalized(b['text']) for b in source['blocks'] if b['kind'] in ('heading','item')]
        if headings and source_headings and len(set(headings)&set(source_headings))/len(set(headings))>.60:
            raise policy.Blocked('COPIED_SELECTION_OR_STRUCTURE')
    expected=promised_activities(article['title'])
    if article['mode']=='INDEPENDENT_ARTICLE': expected=expected or promised_activities(source['title'])
    items=article.get('activities',[]) if mode=='INDEPENDENT_ARTICLE' else article.get('_activity_evidence',[])
    if practical and expected is not None and len(items)!=expected: raise policy.Blocked('PROMISED_ACTIVITIES_MISSING')
    ids=[]
    for item in items:
        if (not all(isinstance(item.get(k),str) and item[k].strip() for k in ('id','title','age','benefit','safety'))
                or not isinstance(item.get('materials'),list) or not item['materials']
                or not isinstance(item.get('steps'),list) or not item['steps']
                or any(not isinstance(s,str) or not s.strip() for s in item['steps']+item['materials'])):
            raise policy.Blocked('PRACTICAL_INSTRUCTION_INCOMPLETE')
        if any(normalized(step)==normalized(item['title']) for step in item['steps']):
            raise policy.Blocked('ACTIVITY_NAME_IS_NOT_INSTRUCTION')
        ids.append(item['id'])
    if len(ids)!=len(set(ids)): raise policy.Blocked('DUPLICATED_ACTIVITY')
    return True


def content_hash(article):
    return policy.digest({k:article.get(k) for k in ('title','teaser','blocks','activities','mode','source_id','category','kind','primary_source','attribution','images')})


def approved_review(result,expected_ids):
    if (not isinstance(result,dict) or result.get('approve') is not True or result.get('issues')
            or result.get('unresolved') or not isinstance(result.get('covered_ids'),list)
            or set(result['covered_ids'])!=set(expected_ids)):
        raise policy.Blocked('REVIEW_REJECTED',json.dumps(result,ensure_ascii=False))
