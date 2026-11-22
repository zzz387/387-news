"""Workers AI Free only. Read billing/whole-account usage before every inference."""
import base64,json,os,re,time,hashlib,math
from datetime import datetime,timezone,timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from scripts.generation_runtime import GenerationPaused

MODEL='@cf/black-forest-labs/flux-1-schnell'
BASE='https://api.cloudflare.com/client/v4'
_LAST=0

def credentials():
    def unquote(value):
        value=value.strip()
        return value[1:-1].strip() if len(value)>1 and value[0]==value[-1] and value[0] in ('\"',"'") else value
    account=unquote(os.getenv('CLOUDFLARE_ACCOUNT_ID',''))
    token=unquote(os.getenv('CLOUDFLARE_API_TOKEN',''))
    token=unquote(re.sub(r'(?i)^(?:authorization:\s*)?bearer\s+','',token,count=1))
    return account,token

def credential_fingerprint():
    # Stored only in the encrypted editorial checkpoint, never public metadata.
    return hashlib.sha256('\0'.join(credentials()).encode()).hexdigest()

def status(config):
    if config.get('provider')!='cloudflare_workers_ai':return 'IMAGE_PAID_PROVIDER_DISABLED'
    if config.get('billing_allowed') is not False or config.get('free_plan_only') is not True or config.get('model')!=MODEL:return 'CF_FREE_CONFIGURATION_REQUIRED'
    account,token=credentials()
    if not account or not token:return 'CLOUDFLARE_CREDENTIALS_MISSING'
    if not re.fullmatch(r'[a-fA-F0-9]{32}',account):return 'CLOUDFLARE_ACCOUNT_INVALID'
    if not token.isascii() or any(ch.isspace() for ch in token):return 'CLOUDFLARE_TOKEN_FORMAT_INVALID'
    if os.getenv('NEWS_CF_PROBE_STATUS') and os.getenv('NEWS_CF_PROBE_STATUS')!='READY':return os.environ['NEWS_CF_PROBE_STATUS']
    return 'READY'

def protected():
    if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_REPOSITORY')!='zzz387/387-news' or os.getenv('GITHUB_REF_NAME')!='main':raise RuntimeError('IMAGE_PROTECTED_ACTIONS_REQUIRED')

def safe_errors(body):
    details=[]
    for error in body.get('errors',[])[:3]:
        message=str(error.get('message',''))
        for secret in credentials():
            if secret:message=message.replace(secret,'[redacted]')
        message=re.sub(r'[A-Za-z0-9_-]{24,}','[redacted]',message)
        details.append({'code':error.get('code'),'message':message[:240]})
    return details

def authentication_code(details):
    return next(('CF_AUTHENTICATION_FAILED_'+str(e['code']) for e in details if e.get('code') in (9106,10000)),None)

def api(path,data=None):
    protected();_,token=credentials()
    stage='subscriptions' if '/subscriptions' in path else 'analytics' if path=='/graphql' else 'inference'
    req=Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST' if data is not None else 'GET')
    try:
        with urlopen(req,timeout=60) as response:
            if response.headers.get_content_type()!='application/json':raise RuntimeError('CF_RESPONSE_TYPE_INVALID')
            raw=response.read(12000000)
            if len(raw)>=12000000:raise RuntimeError('CF_RESPONSE_LIMIT')
            result=json.loads(raw)
    except HTTPError as exc:
        code=exc.code
        details=[]
        try:
            details=safe_errors(json.loads(exc.read(8192)))
        except Exception:pass
        print('[cf-api-error] '+json.dumps({'stage':stage,'http_status':code,'errors':details}),flush=True)
        if code in (429,503):raise GenerationPaused('CF_HTTP_'+str(code)) from None
        error=RuntimeError(authentication_code(details) or 'CF_HTTP_'+str(code));error.stage=stage
        raise error from None
    if result.get('success') is False or result.get('errors'):
        print('[cf-api-error] '+json.dumps({'stage':stage,'http_status':200,'errors':safe_errors(result)}),flush=True)
        error=RuntimeError(authentication_code(safe_errors(result)) or 'CF_RESPONSE_REJECTED');error.stage=stage
        raise error
    return result

def free_usage():
    account,_=credentials()
    # The documented subscriptions.get endpoint has no query parameters.
    response=api('/accounts/'+account+'/subscriptions')
    subscriptions=response.get('result');info=response.get('result_info') or {}
    if not isinstance(subscriptions,list):raise RuntimeError('CF_FREE_PLAN_UNVERIFIED')
    total=info.get('total_count');page_size=info.get('per_page')
    if total is not None and (type(total) is not int or total!=len(subscriptions)):raise RuntimeError('CF_FREE_PLAN_UNVERIFIED')
    if total is None and type(page_size) is int and page_size>0 and len(subscriptions)>=page_size:raise RuntimeError('CF_FREE_PLAN_UNVERIFIED')
    # Default accounts without paid subscriptions are Free. Reject ambiguous or
    # paid account subscriptions, even when a free allowance would still exist.
    for sub in subscriptions:
        plan=sub.get('rate_plan',{})
        if plan.get('id')!='free' or sub.get('price',0)!=0:raise RuntimeError('CF_FREE_PLAN_UNVERIFIED')
    start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    query='query($account:string!,$start:Time!,$end:Time!){viewer{accounts(filter:{accountTag:$account}){aiInferenceAdaptiveGroups(limit:10000,filter:{datetime_geq:$start,datetime_lt:$end}){sum{totalNeurons}}}}}'
    result=api('/graphql',{'query':query,'variables':{'account':account,'start':start.isoformat(),'end':datetime.now(timezone.utc).isoformat()}})
    try:
        accounts=result['data']['viewer']['accounts']
        if len(accounts)!=1:raise ValueError()
        rows=accounts[0]['aiInferenceAdaptiveGroups']
        if len(rows)>=10000:raise ValueError()
        total=sum(float(r['sum']['totalNeurons']) for r in rows)
        if not math.isfinite(total) or total<0:raise ValueError()
    except (KeyError,TypeError,ValueError):raise RuntimeError('CF_ACCOUNT_USAGE_UNVERIFIED') from None
    return total

# FLUX Schnell follows English visual descriptions more reliably than Russian prose.
STYLE_EN=dict(zip(
    ('Акварель','Импрессионизм','Пастель','Символизм','Метафизическая живопись','Сюрреализм','Японская гравюра','Минималистичная живопись','Графика тушью','Футуризм','Экспрессионизм','Плакатная графика','Офорт','Историческая живопись','Ар-нуво','Конструктивизм','Кубизм','Ар-деко','Натурализм','Линогравюра','Ботаническая живопись','Романтизм','Темпера','Абстракционизм','Геометрическая абстракция','Супрематизм','Коллаж','Индустриальная графика','Масло'),
    ('watercolor','impressionism','pastel painting','symbolism','metaphysical painting','surrealism','Japanese woodblock print','minimalist painting','ink drawing','futurism','expressionism','painted poster art','etching','historical painting','art nouveau','constructivism','cubism','art deco','naturalist painting','linocut','botanical painting','romanticism','tempera','abstract painting','geometric abstraction','suprematism','paper collage','industrial graphic art','oil painting')))

def prompt(item):
    d=item['descriptor'];scene=d.get('visual_subject_en','').strip()
    style=STYLE_EN.get(item['genre'],'editorial painting')
    lead='Original fine-art illustration. '+style+'. Visible brushwork or hand-printed texture, expressive visual metaphor, not a photograph. '
    # Put the actual subject first; long Russian source prose previously drowned it out.
    if not scene:scene=d['title']+'. '+d.get('summary','')
    return (lead+'Subject: '+scene[:1400]+'. Balanced editorial composition, muted ochre, cream, deep green and indigo. Entirely pictorial, blank unmarked surfaces, unsigned. No text, writing, letters, signatures, logos, watermarks, labels or borders.')[:2048]

def generate(item,budget,config):
    global _LAST
    if status(config)!='READY':raise RuntimeError(status(config))
    protected()
    date=item.get('date')
    if not date and os.getenv('CF_FREE_SMOKE')!='true':raise RuntimeError('CF_FINAL_APPROVAL_DATE_REQUIRED')
    if date and date<config['first_automatic_issue'] and date not in ('2026-11-20','2026-11-21'):raise RuntimeError('CF_DATE_NOT_AUTHORIZED')
    if config.get('max_retries_per_article',2) not in (1,2) or not 0<config.get('reserve_neurons_per_request',256)<=10000:raise RuntimeError('CF_FREE_CONFIGURATION_REQUIRED')
    if not 1<=config.get('steps',4)<=8 or not 0<config.get('image_neuron_budget',7500)<10000:raise RuntimeError('CF_FREE_CONFIGURATION_REQUIRED')
    account,_=credentials();day=datetime.now(timezone.utc).date().isoformat()
    ledger=budget.ledger;key=hashlib.sha256(account.encode()).hexdigest()
    current=ledger.get('cloudflare_ai',{})
    if current and current.get('account_hash')!=key:raise RuntimeError('CF_LEDGER_ACCOUNT_MISMATCH')
    if current.get('day')!=day:
        ledger['cloudflare_ai']={'day':day,'account_hash':key,'reserved_neurons':0,'estimated_neurons':0,'requests':0,'observed_account_neurons':None,'cooldown_until':current.get('cooldown_until',0)}
    state=ledger['cloudflare_ai'];last_error=None
    for attempt in range(config.get('max_retries_per_article',2)):
        if state.get('cooldown_until',0)>time.time():raise GenerationPaused('CF_COOLDOWN')
        used=free_usage();state['observed_account_neurons']=used
        reserve=config.get('reserve_neurons_per_request',256)
        if state['reserved_neurons']+reserve>config['image_neuron_budget'] or used+reserve>10000-config.get('account_headroom',1500):
            state['cooldown_until']=(datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1,minutes=5)).timestamp();budget.persist();raise GenerationPaused('CF_FREE_QUOTA_EXHAUSTED')
        if budget.remaining_seconds()<90:raise GenerationPaused('CF_STAGE_TIME_LIMIT')
        time.sleep(max(0,config.get('request_gap_seconds',3)-(time.monotonic()-_LAST)))
        state['reserved_neurons']+=reserve;state['requests']+=1;budget.persist();_LAST=time.monotonic()
        try:
            result=api('/accounts/'+account+'/ai/run/'+MODEL,{'prompt':prompt(item),'steps':config['steps']})
            data=base64.b64decode(result['result']['image'],validate=True)
            if not data:raise ValueError()
            from PIL import Image
            import io
            with Image.open(io.BytesIO(data)) as image:
                image.verify();w,h=image.size
                if not 0<w<=2048 or not 0<h<=2048:raise ValueError()
            estimate=4.8*math.ceil(w/512)*math.ceil(h/512)+9.6*config['steps']
            state['estimated_neurons']+=estimate
            state['reserved_neurons']+=max(0,estimate-reserve)
            try:state['observed_account_neurons']=free_usage()
            except Exception:state['usage_after_pending']=True
            budget.persist()
            print('[cloudflare-art] '+json.dumps({'free_plan_verified':True,'image_bytes':len(data),'estimated_neurons':estimate,'reserved_today':state['reserved_neurons'],'account_usage_observed':state['observed_account_neurons'],'actual_per_request_neurons':'NOT_EXPOSED_BY_IMAGE_RESPONSE'}),flush=True)
            return data
        except GenerationPaused as exc:
            last_error=exc
            if '429' in str(exc):state['cooldown_until']=time.time()+1800;budget.persist();raise
            if attempt+1>=config.get('max_retries_per_article',2):state['cooldown_until']=time.time()+300;budget.persist();raise
            time.sleep(3*(attempt+1))
        except (KeyError,ValueError,TypeError):raise RuntimeError('CF_IMAGE_INVALID') from None
    raise last_error or RuntimeError('CF_IMAGE_MISSING')

def github_secret_metadata():
    """Names/visibility only; GitHub's endpoint never returns secret values."""
    token=os.getenv('GH_TOKEN')
    if not token:return {'status':'GITHUB_METADATA_UNAVAILABLE'}
    result={}
    for name in ('CLOUDFLARE_ACCOUNT_ID','CLOUDFLARE_API_TOKEN'):
        request=Request('https://api.github.com/repos/zzz387/387-news/actions/secrets/'+name,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'387-News-Secret-Metadata'})
        try:
            with urlopen(request,timeout=15) as response:
                data=json.loads(response.read(16384));result[name]='PRESENT' if data.get('name')==name else 'UNVERIFIED'
        except HTTPError as exc:result[name]='HTTP_'+str(exc.code)
        except Exception:result[name]='UNAVAILABLE'
    return result

def diagnose(config,probe=False):
    normalized=dict(zip(('CLOUDFLARE_ACCOUNT_ID','CLOUDFLARE_API_TOKEN'),credentials()))
    result={'provider':'cloudflare_workers_ai','model':MODEL,'status':status(config),'credentials_present':{name:bool(os.getenv(name)) for name in normalized},'credential_normalization_applied':{name:os.getenv(name,'')!=value for name,value in normalized.items()},'missing_secrets':[name for name in normalized if not os.getenv(name)],'free_plan_verified':False,'authorization_verified':False,'billing_allowed':False,'image_requests':0}
    if probe and result['status']=='READY':
        try:result.update(free_plan_verified=True,authorization_verified=True,observed_account_neurons=free_usage())
        except Exception as exc:result.update(free_plan_verified=False,failure_stage=getattr(exc,'stage','configuration'),status=str(exc) if re.fullmatch('[A-Z_0-9]+',str(exc)) else type(exc).__name__)
    elif result['status']=='READY':result['status']='CLOUDFLARE_AUTH_UNVERIFIED'
    if probe and os.getenv('GITHUB_ACTIONS')=='true' and os.getenv('GITHUB_REPOSITORY')=='zzz387/387-news':result['github_secret_metadata']=github_secret_metadata()
    if probe and os.getenv('GITHUB_ACTIONS')=='true' and os.getenv('GITHUB_REF_NAME')=='main' and os.getenv('GITHUB_ENV'):
        code=result['status'] if re.fullmatch('[A-Z_0-9]+',result['status']) else 'CF_PROBE_FAILED'
        with open(os.environ['GITHUB_ENV'],'a') as stream:stream.write('NEWS_CF_PROBE_STATUS='+code+'\n')
    print('[cloudflare-capability] '+json.dumps(result),flush=True);return result
