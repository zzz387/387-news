"""Validate existing production bindings in Actions; never print their values."""
import json
import os
try:
    from scripts import policy41 as p,staged_news as stage
except ImportError:
    import policy41 as p
    import staged_news as stage


def check(env=os.environ):
    if (env.get('GITHUB_ACTIONS')!='true' or env.get('GITHUB_REPOSITORY')!='zzz387/387-news'
            or env.get('GITHUB_REF_NAME')!='main'):raise RuntimeError('PRODUCTION_ACTIONS_MAIN_REQUIRED')
    use43=env.get('NEWS_POLICY_VERSION')=='4.3'
    if not use43 and not env.get('GEMINI_API_KEY','').strip():raise RuntimeError('GEMINI_SECRET_MISSING')
    stage.validate_key(env.get('DRAFT_ENCRYPTION_KEY',''))
    if p.VERSION!='4.1' or p.ARTICLE_COUNT!=12 or p.RELEASE_TIME!='06:00':raise RuntimeError('PRODUCTION_POLICY_CONFIG_INVALID')
    result={'policy_version':p.VERSION,'article_target':p.ARTICLE_COUNT,'release_time':'06:00 Europe/Moscow',
            'gemini_secret_present':True,'draft_secret_valid':True,
            'automation_enabled':env.get('NEWS_AUTOMATION_V31_ENABLED')=='true',
            'release_approved':env.get('NEWS_RELEASE_APPROVED')=='true'}
    if use43:
        try:from scripts import editorial43
        except ImportError:import editorial43
        if not editorial43.CONFIG['enabled']:raise RuntimeError('POLICY43_DISABLED')
        result.update(policy_version='4.3',article_target=8,minimum_articles=1,reserve_without_gemini=True,gemini_secret_present=bool(env.get('GEMINI_API_KEY','').strip()))
    if not result['automation_enabled']:raise RuntimeError('AUTOMATION_VARIABLE_NOT_ENABLED')
    if not result['release_approved']:raise RuntimeError('RELEASE_VARIABLE_NOT_ENABLED')
    return result


def pages_status():
    try:
        page=stage.request_json('https://api.github.com/repos/zzz387/387-news/pages')
        return {'verified':True,'build_type':page.get('build_type'),'cname':page.get('cname'),
                'https_enforced':page.get('https_enforced')}
    except Exception as exc:
        return {'verified':False,'code':'PAGES_METADATA_UNAVAILABLE','http_status':getattr(exc,'code',None)}


def require_pages():
    result=pages_status()
    if not result['verified']:raise RuntimeError('PAGES_SETTINGS_UNVERIFIED')
    if result.get('build_type')!='workflow':raise RuntimeError('PAGES_SOURCE_MUST_BE_GITHUB_ACTIONS')
    if result.get('cname')!='387.su':raise RuntimeError('PAGES_CUSTOM_DOMAIN_MISMATCH')
    return result


if __name__=='__main__':
    try:
        print('[production-preflight] '+json.dumps(check()))
        print('[pages-settings] '+json.dumps(pages_status()))
    except Exception as exc:
        print('[production-preflight] blocked='+str(exc) if isinstance(exc,RuntimeError) else '[production-preflight] blocked=INVALID_ENCRYPTION_BINDING')
        raise SystemExit(1)
