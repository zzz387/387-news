"""Documented rights decisions, independent of a model's confidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
try:
    from scripts import policy41 as policy
except ImportError:
    import policy41 as policy

OPEN_LICENSES={
    'https://creativecommons.org/licenses/by/4.0/':{'name':'CC BY 4.0','attribution':True},
    'https://creativecommons.org/publicdomain/zero/1.0/':{'name':'CC0 1.0','attribution':False},
}


def configuration(path=None):
    return json.loads(Path(path or policy.ROOT/'config/rights.json').read_text(encoding='utf-8'))


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
    for grant in records:
        if grant.get('url')!=source['url'] or grant.get('content_hash')!=source['content_hash']: continue
        item=(grant.get('uses') or {}).get(mode)
        if documented(item):
            return dict(item,source_hash=source['content_hash'],mode=mode,verification='documented_grant',needs_review=item['status']=='unknown')
    license_url=source.get('declared_license')
    if license_url in OPEN_LICENSES and source.get('full_text_verified'):
        if not source.get('author'): return {'status':'unknown','mode':mode,'needs_review':True}
        return {'status':'allowed','mode':mode,'source_hash':source['content_hash'],
                'evidence_url':license_url,'basis':OPEN_LICENSES[license_url]['name'],
                'checked_by':'declared-page-license-v1','checked_at':source['access_checked_at'],
                'attribution':{'author':source['author'],'license':OPEN_LICENSES[license_url]['name'],'license_url':license_url},
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
    if conditions-{'attribution','license_notice','indicate_translation','no_modifications'}:
        raise policy.Blocked('LICENSE_CONDITIONS_UNSUPPORTED')
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
