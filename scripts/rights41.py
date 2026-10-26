"""Documented rights decisions, independent of a model's confidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
try:
    from scripts import policy41 as policy
except ImportError:
    import policy41 as policy

OPEN_LICENSES={
    'https://creativecommons.org/licenses/by/3.0/':{'name':'CC BY 3.0','attribution':True},
    'https://creativecommons.org/licenses/by/4.0/':{'name':'CC BY 4.0','attribution':True},
    'https://creativecommons.org/publicdomain/zero/1.0/':{'name':'CC0 1.0','attribution':False},
}


def configuration(path=None):
    return json.loads(Path(path or policy.ROOT/'config/rights.json').read_text(encoding='utf-8'))


def source_profiles():
    return json.loads((policy.ROOT/'config/source-profiles.json').read_text())


def documented(record):
    valid=(isinstance(record,dict) and record.get('status') in ('allowed','forbidden','unknown')
            and bool(record.get('evidence_url')) and bool(record.get('checked_by'))
            and bool(record.get('checked_at')) and bool(record.get('basis'))
            and record.get('verification')=='human_documented')
    if not valid: return False
    try:
        datetime.fromisoformat(record['checked_at'])
        from urllib.parse import urlparse
        url=urlparse(record['evidence_url'])
        return url.scheme=='https' and bool(url.hostname) and not url.username and not url.password
    except (TypeError,ValueError): return False


def decision(source,mode,records=None):
    if mode not in policy.MODES: raise policy.Blocked('RIGHTS_MODE_INVALID')
    records=records if records is not None else configuration()['grants']
    from urllib.parse import urlparse
    host=urlparse(source['url']).hostname or ''
    ai_restricted=bool(source.get('ai_use_restricted')) or any(
        profile.get('ai_use_restricted') and (host==domain or host.endswith('.'+domain))
        for domain,profile in source_profiles()['institutions'].items())
    for grant in records:
        if grant.get('url')!=source['url'] or grant.get('content_hash')!=source['content_hash']: continue
        item=(grant.get('uses') or {}).get(mode)
        if documented(item):
            if ai_restricted and item.get('ai_processing_permitted') is not True: continue
            return dict(item,source_hash=source['content_hash'],mode=mode,verification='documented_grant',needs_review=item['status']=='unknown')
    if ai_restricted:
        return {'status':'unknown','mode':mode,'source_hash':source['content_hash'],
                'needs_review':True,'reason_code':'SOURCE_AI_TERMS_REVIEW_REQUIRED'}
    if mode=='INDEPENDENT_ARTICLE':
        # Permission to copy a work is distinct from lawful use of unprotected facts.
        # This decision grants no right to translate, paraphrase or copy its selection.
        doubtful=any(source.get(key) for key in ('rights_review_required','access_restricted',
            'confidential','database_extraction_restricted','legal_dispute'))
        permitted=(source.get('full_text_verified') is True and
                   source.get('metadata_status')=='verified' and not doubtful)
        return {'status':'allowed' if permitted else 'unknown','mode':mode,
                'source_hash':source['content_hash'],'verification':'unprotected_facts_rule_v2',
                'evidence_url':source['url'],'basis':'Unprotected facts and ideas only; no licence to the source expression',
                'checked_by':'deterministic-facts-use-v2','checked_at':source['access_checked_at'],
                'conditions':['facts_only','independent_expression','independent_selection'],
                'needs_review':not permitted}
    license_url=(source.get('declared_license') or '').replace('http://creativecommons.org/','https://creativecommons.org/')
    if license_url in OPEN_LICENSES and source.get('full_text_verified'):
        if not source.get('author') and not source.get('institutional_source'):
            return {'status':'unknown','mode':mode,'needs_review':True}
        return {'status':'allowed','mode':mode,'source_hash':source['content_hash'],
                'evidence_url':license_url,'basis':OPEN_LICENSES[license_url]['name'],
                'checked_by':'declared-page-license-v1','checked_at':source['access_checked_at'],
                'attribution':{'author':source.get('author') or source['publisher'],'license':OPEN_LICENSES[license_url]['name'],'license_url':license_url},
                'verification':'declared_page_license','needs_review':False}
    return {'status':'unknown','mode':mode,'source_hash':source['content_hash'],'needs_review':True}


def select_mode(source,records=None):
    if source.get('metadata_status')!='verified' or not source.get('full_text_verified'):
        raise policy.Blocked('SOURCE_NEEDS_REVIEW')
    preferred='ORIGINAL_REPUBLICATION' if source['language']=='ru' else 'FULL_TRANSLATION'
    for mode in (preferred,'INDEPENDENT_ARTICLE'):
        result=decision(source,mode,records)
        if result['status']=='allowed': return mode,result
    raise policy.Blocked('RIGHTS_NEEDS_REVIEW')


def image_decision(image,records=None):
    records=records if records is not None else configuration()['images']
    for record in records:
        if record.get('url')==image.get('url') and record.get('sha256')==image.get('sha256') and documented(record):
            return dict(record,needs_review=record['status']=='unknown')
    return {'status':'unknown','needs_review':True}


def require(source,mode,rights):
    conditions=set(rights.get('conditions',[]))
    if conditions-{'attribution','license_notice','indicate_translation','no_modifications',
                   'facts_only','independent_expression','independent_selection'}:
        raise policy.Blocked('LICENSE_CONDITIONS_UNSUPPORTED')
    if conditions & {'facts_only','independent_expression','independent_selection'} and mode!='INDEPENDENT_ARTICLE':
        raise policy.Blocked('FACTS_PERMISSION_IS_NOT_COPYRIGHT_LICENSE')
    if 'no_modifications' in conditions and mode!='ORIGINAL_REPUBLICATION':
        raise policy.Blocked('LICENSE_MODIFICATION_FORBIDDEN')
    attribution=rights.get('attribution') or {}
    if 'attribution' in conditions and not attribution.get('author'): raise policy.Blocked('LICENSE_ATTRIBUTION_MISSING')
    if 'license_notice' in conditions and not attribution.get('license_url'): raise policy.Blocked('LICENSE_NOTICE_MISSING')
    if attribution.get('license_url'):
        from urllib.parse import urlparse
        link=urlparse(attribution['license_url'])
        if link.scheme!='https' or not link.hostname or link.username or link.password:
            raise policy.Blocked('LICENSE_NOTICE_URL_UNSAFE')
    if rights.get('status')!='allowed' or rights.get('mode')!=mode or rights.get('source_hash')!=source['content_hash']:
        raise policy.Blocked('RIGHTS_NOT_ESTABLISHED')
    if mode=='ORIGINAL_REPUBLICATION' and source['language']!='ru': raise policy.Blocked('ORIGINAL_LANGUAGE_MISMATCH')
    if mode=='FULL_TRANSLATION' and source['language']=='ru': raise policy.Blocked('TRANSLATION_LANGUAGE_MISMATCH')
