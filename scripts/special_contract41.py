"""Narrow owner-authorized 003-R contract. Daily editions always retain twelve."""
import json
from pathlib import Path
try:
    from scripts import policy41 as p
except ImportError:import policy41 as p

ID='003-R'; SLUG='2026-10-26-v41'; ORIGINAL='2026-10-26'


def definition():
    value=json.loads((p.ROOT/'config/special-003-r.json').read_text())
    if (value['id']!=ID or value['slug']!=SLUG or value['original_date']!=ORIGINAL or value['article_count']!=8
            or [s['slot'] for s in value['slots']]!=list(range(1,9))):raise p.Blocked('SPECIAL_DEFINITION_INVALID')
    return value


def is_special(state):
    if 'special_edition' not in state:return False
    expected={'id':ID,'definition_hash':p.digest(definition())}
    if state['special_edition']!=expected:raise p.Blocked('SPECIAL_CONTRACT_INVALID')
    return True


def count(state):return 8 if is_special(state) else p.ARTICLE_COUNT


def evidence_plan(slot):
    return slot.get('evidence_plan') or {'primary':slot['url'],
        'support':list(dict.fromkeys(slot['original_urls'][1:]+slot['verification_urls'])),
        'studies':[],'mode':None}


def validate_slots(state):
    if not is_special(state):return
    config=definition();records={r['id']:r for r in state['candidates']}
    selected=[records[x] for x in state['selected_ids']]
    if sorted(r.get('special_slot',0) for r in selected)!=list(range(1,9)):raise p.Blocked('SPECIAL_EIGHT_TOPICS_REQUIRED')
    for r in selected:
        expected=config['slots'][r['special_slot']-1]
        if state.get('header_review_revision')==2:
            from scripts import content41
            if any(r['checks'].get(name,{}).get('review_scope')!=content41.READER_REVIEW_SCOPE for name in ('fact_checked','completeness_checked','editorial_checked')):raise p.Blocked('SPECIAL_READER_HEADER_REVIEW_REQUIRED')
            if r['article']['mode']=='INDEPENDENT_ARTICLE' and r.get('progress',{}).get('reviews',{}).get('editorial_checked',{}).get('independence_scope')!=content41.INDEPENDENCE_REVIEW_SCOPE:raise p.Blocked('SPECIAL_READER_HEADER_INDEPENDENCE_REQUIRED')

        if state.get('all_sources_independence_revision')==1 and r['article']['mode']=='INDEPENDENT_ARTICLE' and r.get('progress',{}).get('reviews',{}).get('editorial_checked',{}).get('independence_scope') not in ('all_commissioned_sources_v1','all_sources_title_teaser_body_v2'):raise p.Blocked('SPECIAL_ALL_SOURCE_INDEPENDENCE_REQUIRED')
        plan=evidence_plan(expected)
        if (r['url']!=plan['primary'] or r['source']['url']!=plan['primary'] or
                r.get('original_urls')!=expected['original_urls'] or r['article']['category']!=expected['category']):
            raise p.Blocked('SPECIAL_TOPIC_OR_SOURCE_CHANGED')
        evidence={item['url']:item for item in r.get('supporting_sources',[])}
        if not r['checks'].get('source_verified',{}).get('special_evidence_complete') or not set(plan['support'])<=set(evidence):
            raise p.Blocked('SPECIAL_ORIGINAL_COMPANIONS_REQUIRED')
        if plan.get('mode') and r['article']['mode']!=plan['mode']:raise p.Blocked('SPECIAL_INDEPENDENT_ALTERNATIVE_REQUIRED')
        if plan.get('fact_base_urls'):
            allowed={evidence[url].get('id') for url in plan['fact_base_urls']}
            if None in allowed:raise p.Blocked('SPECIAL_NEUTRAL_FACT_BASE_INCOMPLETE')
            if not r['claims'] or any(claim['source_id'] not in allowed for claim in r['claims']):raise p.Blocked('SPECIAL_WRITER_FACT_BASE_CHANGED')
        if expected['category']=='Здоровье и движение':
            studies=r.get('special_study_urls',[])
            evidence[r['source']['url']]=r['source']
            if not studies or (plan['studies'] and set(studies)!=set(plan['studies'])) or any(url not in evidence or not evidence[url].get('full_text_verified') for url in studies):
                raise p.Blocked('SPECIAL_FULL_STUDY_REQUIRED')
    unicef=next(r for r in selected if r['special_slot']==3)
    if len(unicef['article'].get('activities',[]))!=21:raise p.Blocked('SPECIAL_21_COMPLETE_ACTIVITIES_REQUIRED')


def check_original(root):
    manifest=json.loads((Path(root)/'issues'/ORIGINAL/'issue.json').read_text())
    if p.digest(manifest)!=definition()['original_manifest_hash']:raise p.Blocked('SPECIAL_ORIGINAL_MANIFEST_CHANGED')
    return manifest
