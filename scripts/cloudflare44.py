"""Workers AI Free only. Read billing/whole-account usage before every inference."""
import base64,json,os,re,time,hashlib,math
from datetime import datetime,timezone,timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from scripts.generation_runtime import GenerationPaused

MODEL='@cf/black-forest-labs/flux-1-schnell'
REFERENCE_MODEL='@cf/black-forest-labs/flux-2-klein-4b'
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

def output_rejection_code(details):
    return 'CF_OUTPUT_REJECTED' if any(e.get('code')==3030 and re.search(r'output.*flagged',e.get('message',''),re.I) for e in details) else None

def multipart_payload(fields,images):
    boundary='387-art-'+hashlib.sha256(b''.join(images)).hexdigest()[:24]
    chunks=[]
    for key,value in fields.items():chunks.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+str(value)+'\r\n').encode())
    for i,data in enumerate(images):chunks.extend([('--'+boundary+'\r\nContent-Disposition: form-data; name="input_image_'+str(i)+'"; filename="reference-'+str(i)+'.webp"\r\nContent-Type: image/webp\r\n\r\n').encode(),data,b'\r\n'])
    chunks.append(('--'+boundary+'--\r\n').encode())
    return b''.join(chunks),'multipart/form-data; boundary='+boundary

def api(path,data=None,images=None):
    protected();_,token=credentials()
    stage='subscriptions' if '/subscriptions' in path else 'analytics' if path=='/graphql' else 'inference'
    body=json.dumps(data).encode() if data is not None else None;content_type='application/json'
    if images is not None:body,content_type=multipart_payload(data,images)
    req=Request(BASE+path,data=body,headers={'Authorization':'Bearer '+token,'Content-Type':content_type},method='POST' if data is not None else 'GET')
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
        error=RuntimeError(authentication_code(details) or output_rejection_code(details) or 'CF_HTTP_'+str(code));error.stage=stage
        raise error from None
    if result.get('success') is False or result.get('errors'):
        print('[cf-api-error] '+json.dumps({'stage':stage,'http_status':200,'errors':safe_errors(result)}),flush=True)
        error=RuntimeError(authentication_code(safe_errors(result)) or output_rejection_code(safe_errors(result)) or 'CF_RESPONSE_REJECTED');error.stage=stage
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
    from scripts import art_reference44
    return art_reference44.prompt(item)

def generate(item,budget,config):
    global _LAST
    if status(config)!='READY':raise RuntimeError(status(config))
    protected()
    references=item.get('reference_images')
    images=[];input_tiles=0;model=MODEL
    if references is not None:
        if len(references)!=1:raise RuntimeError('CF_ONE_REFERENCE_REQUIRED')
        if config.get('reference_model')!=REFERENCE_MODEL:raise RuntimeError('CF_REFERENCE_MODEL_NOT_AUTHORIZED')
        from scripts import policy41
        from PIL import Image
        import io
        for ref in references:
            path=__import__('pathlib').Path(ref['path'])
            if path.is_absolute() or '..' in path.parts or path.parts[:2]!=('assets','art'):raise RuntimeError('CF_REFERENCE_PATH_INVALID')
            target=(policy41.ROOT/path).resolve()
            if not target.is_relative_to(policy41.ROOT.resolve()):raise RuntimeError('CF_REFERENCE_PATH_INVALID')
            from scripts import art_library44
            registry=art_library44.load(policy41.ROOT)
            chosen=registry['artworks'].get(item.get('selected_reference_id'),{})
            group=registry['sets'].get(item.get('reference_set_id'),{})
            if chosen.get('path')!=ref['path'] or chosen.get('sha256')!=ref['sha256'] or group.get('artwork_ids')!=item.get('reference_artwork_ids') or item.get('selected_reference_id') not in group.get('artwork_ids',[]):raise RuntimeError('CF_REFERENCE_LIBRARY_INVALID')
            raw=target.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise RuntimeError('CF_REFERENCE_HASH_INVALID')
            with Image.open(io.BytesIO(raw)) as image:
                image.verify();w,h=image.size
                if not 0<w<512 or not 0<h<512:raise RuntimeError('CF_REFERENCE_DIMENSIONS_INVALID')
                input_tiles+=math.ceil(w/512)*math.ceil(h/512)
            images.append(raw)
        model=REFERENCE_MODEL
    if config.get('reference_required') and item.get('protocol')==2 and item.get('date','')>=config.get('first_reference_issue','9999-12-31') and not images:raise RuntimeError('CF_ONE_REFERENCE_REQUIRED')
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
    width,height={'3:2':(960,640),'4:5':(768,960),'1:1':(896,896),'3:4':(768,1024),'16:9':(1024,576)}.get(item.get('ratio'),(1024,768))
    for attempt in range(config.get('max_retries_per_article',2)):
        if state.get('cooldown_until',0)>time.time():raise GenerationPaused('CF_COOLDOWN')
        used=free_usage();state['observed_account_neurons']=used
        reserve=config.get('reserve_neurons_per_request',256)
        if images:
            # Current published Klein tile pricing, doubled, within the same
            # configured per-request ceiling; never rewrite historical reserves.
            forecast=5.37*input_tiles+26.05*math.ceil(width/512)*math.ceil(height/512)
            reserve=min(reserve,math.ceil(2*forecast))
        if state['reserved_neurons']+reserve>config['image_neuron_budget'] or used+reserve>10000-config.get('account_headroom',1500):
            state['cooldown_until']=(datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1,minutes=5)).timestamp();budget.persist();raise GenerationPaused('CF_FREE_QUOTA_EXHAUSTED')
        if budget.remaining_seconds()<90:raise GenerationPaused('CF_STAGE_TIME_LIMIT')
        time.sleep(max(0,config.get('request_gap_seconds',3)-(time.monotonic()-_LAST)))
        state['reserved_neurons']+=reserve;state['requests']+=1;budget.persist();_LAST=time.monotonic()
        try:
            if images:
                result=api('/accounts/'+account+'/ai/run/'+model,{'prompt':prompt(item),'width':width,'height':height},images=images)
            else:result=api('/accounts/'+account+'/ai/run/'+model,{'prompt':prompt(item),'steps':config['steps']})
            data=base64.b64decode(result['result']['image'],validate=True)
            if not data:raise ValueError()
            from PIL import Image
            import io
            with Image.open(io.BytesIO(data)) as image:
                image.verify();w,h=image.size
                if not 0<w<=2048 or not 0<h<=2048:raise ValueError()
            estimate=5.37*input_tiles+26.05*math.ceil(w/512)*math.ceil(h/512) if images else 4.8*math.ceil(w/512)*math.ceil(h/512)+9.6*config['steps']
            state['estimated_neurons']+=estimate
            state['reserved_neurons']+=max(0,(math.ceil(2*estimate) if images else estimate)-reserve)
            try:state['observed_account_neurons']=free_usage()
            except Exception:state['usage_after_pending']=True
            budget.persist()
            print('[cloudflare-art] '+json.dumps({'free_plan_verified':True,'model':model,'reference_images':len(images),'image_bytes':len(data),'estimated_neurons':estimate,'request_reservation':reserve,'reservation_basis':'PUBLISHED_REQUEST_TILES_X2_WITH_UNCHANGED_CEILING' if images else 'FIXED','reserved_today':state['reserved_neurons'],'account_usage_observed':state['observed_account_neurons'],'actual_per_request_neurons':'NOT_EXPOSED_BY_IMAGE_RESPONSE'}),flush=True)
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
