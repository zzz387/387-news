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
 'v41_analysis':schema({'claims':{'type':'array','items':schema({'id':S,'source_id':S,'quote':S,'evidence_id':S,'fact':S,'sensitive':B})},
                       'requirements':{'type':'array','items':S},'topic_key':S,'event_date':S,'event_date_quote':S,'event_evidence_id':S,
                       'category':{'type':'string','enum':list(policy.CATEGORIES)},'kind':S,'worth_publishing':B,'reader_value':S,
                       'covered_ids':{'type':'array','items':S}}),
 'v41_outline':schema({'title':S,'teaser':S,'category':S,'kind':S,'sections':{'type':'array','items':schema({'id':S,'heading':S,'purpose':S,'fact_ids':{'type':'array','items':S},'requirement_ids':{'type':'array','items':S},'activity_count':{'type':'integer','minimum':0}})}}),
 'v41_section':schema({'id':S,'finished':B,'blocks':{'type':'array','items':schema({'kind':{'type':'string','enum':['title','heading','paragraph','item','quote','table']},'text':S})},
     'activities':{'type':'array','items':schema({'id':S,'title':S,'age':S,'materials':{'type':'array','items':S},
        'steps':{'type':'array','items':S},'benefit':S,'safety':S})},'covered_requirements':{'type':'array','items':S},'covered_requirement_ids':{'type':'array','items':S}}),
 'v41_practical':schema({'id':S,'title':S,'age':S,'materials':{'type':'array','items':S},
                           'steps':{'type':'array','items':S},'benefit':S,'safety':S}),
 'v41_review':schema({'approve':B,'issues':{'type':'array','items':S},'unresolved':{'type':'array','items':S},
                     'covered_ids':{'type':'array','items':S}}),
})

# Required in real model responses; legacy accepted checkpoints retain their original covered IDs.
news.SCHEMAS['v41_review']['properties']['affected_ids']={'type':'array','items':S}
news.SCHEMAS['v41_review']['required'].append('affected_ids')


def evidence_units(group):
    """Exact source spans, selected by short IDs; no model-generated quotation text."""
    units=[]
    for piece in group:
        for raw in re.split(r'(?<=[.!?。！？])\s+|\n+',piece['text']):
            text=raw.strip()
            if text:units.append({'id':'q'+str(len(units)+1),'piece_id':piece['id'],'text':text})
    return units


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


def operation_groups(pieces,boundary=None,limit=None):
    """Pack complete short pieces into a technical request; retain every id/offset.

    Three-piece operations keep the legacy single-piece protocol for restored
    small jobs. No content is shortened and no editorial length rule is applied.
    """
    if len(pieces)<=3: return [[piece] for piece in pieces]
    groups=[]; current=[]; size=0; key=None
    for piece in pieces:
        next_key=boundary(piece) if boundary else None
        if current and (size+len(piece['text'])>(limit or policy.CONFIG['technical']['operation_characters']) or next_key!=key):
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
            if any(block.get(k)!=original.get(k) for k in ('heading_level','list_kind','list_group','list_index','list_depth')):
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


def validate_section(result,section,record,requirements):
    if (not isinstance(result,dict) or result.get('id')!=section['id'] or result.get('finished') is not True
            or not isinstance(result.get('blocks'),list) or not result['blocks']
            or not isinstance(result.get('activities'),list)):
        raise policy.Blocked('SECTION_INCOMPLETE')
    covered=list(result.get('covered_requirements',[]))
    selected=result.get('covered_requirement_ids',[])
    if not isinstance(selected,list) or not set(selected)<=set(requirements):raise policy.Blocked('SECTION_REQUIREMENT_REFERENCE_INVALID')
    if selected:covered=[requirements[key] for key in selected]
    if not set(covered)<=set(requirements.values()):raise policy.Blocked('SECTION_REQUIREMENT_REFERENCE_INVALID')
    result['covered_requirements']=covered
    if section.get('requirement_ids') and not set(section['requirement_ids'])<=set(selected):
        raise policy.Blocked('SECTION_REQUIRED_COVERAGE_MISSING',json.dumps({'required_ids':section['requirement_ids'],'covered_ids':selected,'missing_ids':sorted(set(section['requirement_ids'])-set(selected))},ensure_ascii=False))
    if 'activity_count' in section and len(result['activities'])!=section['activity_count']:
        raise policy.Blocked('SECTION_ACTIVITY_COUNT_MISMATCH',json.dumps({'required_activities':section['activity_count'],'received_activities':len(result['activities'])}))
    # Validate a section without imposing the whole article's promised activity count.
    source=dict(record['source'],title='')
    semantic_structure({'title':'Самостоятельный раздел','mode':'INDEPENDENT_ARTICLE',
                        'blocks':result['blocks'],'activities':result['activities']},source)
    prior=[item for key,value in record['progress'].get('sections',{}).items() if key!=section['id'] for item in value.get('activities',[])]
    signatures={normalized(item['title']) for item in prior}
    instructions={normalized(' '.join(item['steps'])) for item in prior}
    for item in result['activities']:
        if normalized(item['title']) in signatures or normalized(' '.join(item['steps'])) in instructions:
            raise policy.Blocked('REPEATED_ACTIVITY_CONTENT')
        signatures.add(normalized(item['title']));instructions.add(normalized(' '.join(item['steps'])))
    return result


def witnessed_event_date(value,quote):
    """Require the declared calendar date in the literal witness, not metadata."""
    from datetime import datetime
    try:date=datetime.fromisoformat(value.replace('Z','+00:00')).date()
    except (ValueError,TypeError,AttributeError):return False
    text=quote.casefold()
    if date.isoformat() in text:return True
    numeric=rf'(?<!\d)0?{date.day}[./]0?{date.month}[./]{date.year}(?!\d)'
    if re.search(numeric,text):return True
    months=[('января','january'),('февраля','february'),('марта','march'),('апреля','april'),
            ('мая','may'),('июня','june'),('июля','july'),('августа','august'),
            ('сентября','september'),('октября','october'),('ноября','november'),('декабря','december')]
    for month in months[date.month-1]:
        if re.search(rf'(?<!\d)0?{date.day}\s+{month}\s*,?\s*{date.year}(?!\d)',text):return True
        if re.search(rf'\b{month}\s+0?{date.day}\s*,?\s*{date.year}(?!\d)',text):return True
    return False


def review_wire(group):
    aliases={'p'+str(i+1):part['id'] for i,part in enumerate(group)}
    payload=[dict(part,id=alias) for alias,part in zip(aliases,group)]
    return operation_payload(payload),aliases


def restore_review_ids(result,aliases):
    result=dict(result)
    for field in ('covered_ids','affected_ids'):
        values=result.get(field,[])
        if not isinstance(values,list):raise policy.Blocked('REVIEW_PROTOCOL_INVALID')
        if len(values)!=len(set(values)):raise policy.Blocked('REVIEW_PROTOCOL_INVALID')
        if set(values)<=set(aliases):result[field]=[aliases[value] for value in values]
        elif not set(values)<=set(aliases.values()):raise policy.Blocked('REVIEW_PROTOCOL_INVALID')
    if set(result.get('covered_ids',[]))!=set(aliases.values()):raise policy.Blocked('REVIEW_PROTOCOL_INVALID')
    return result


def validate_outline(outline,record):
    sections=outline.get('sections',[])
    if not sections or outline.get('category') not in policy.CATEGORIES:raise policy.Blocked('OUTLINE_INVALID')
    if len({s['id'] for s in sections})!=len(sections):raise policy.Blocked('OUTLINE_SECTION_DUPLICATE')
    facts={c['id'] for c in record['claims']}
    refs={'r'+str(i+1):text for i,text in enumerate(record['requirements'])}
    reverse={text:key for key,text in refs.items()}
    for section in sections:
        if not section.get('fact_ids') or not set(section['fact_ids'])<=facts:raise policy.Blocked('OUTLINE_FACT_REFERENCE_INVALID')
        if 'requirement_ids' in section:
            section['requirement_ids']=[reverse.get(value,value) for value in section['requirement_ids']]
            if not set(section['requirement_ids'])<=set(refs):raise policy.Blocked('OUTLINE_REQUIREMENT_REFERENCE_INVALID')
    modern=any('requirement_ids' in s for s in sections)
    if modern and set(refs)-{key for section in sections for key in section.get('requirement_ids',[])}:
        raise policy.Blocked('OUTLINE_REQUIREMENT_COVERAGE_MISSING')
    expected=promised_activities(record.get('commission',{}).get('original_topic','')) or promised_activities(record['source']['title'])
    if modern and expected is not None and (any(type(s.get('activity_count')) is not int or s['activity_count']<0 for s in sections)
            or sum(s['activity_count'] for s in sections)!=expected):raise policy.Blocked('OUTLINE_ACTIVITY_ALLOCATION_INVALID')
    return True
