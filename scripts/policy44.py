"""Policy4.4 on the existing controller: content subjects and explicit deficits."""
import copy,re
from collections import Counter
from scripts import policy41 as p

REVISION=4
GROUPS=('family','health','sport')
PATTERNS={
 'family':r'воспитан|родител|реб[её]н|дет(?:и|ей|ям|ьми|ях)\b|детск|детств|дошколь|школьни|супруж|супруг|материнств|отцовств|\bбрак\b|marital relationship|couple relationship|married|семейн.{0,18}(?:игр|традиц|отношен|досуг|занят)|parent(?:ing|s)?\b|children|child(?:hood|care)?\b|kids?\b|child development|family (?:activit|relationship|game|tradition)|marital|marriage',
 'health':r'здоров.{0,12}питан|рацион|нутриц|диет|пищев|долголет|медицин|лечени|клиническ|профилакт|заболеван|(?:режим|качество|недостаток|гигиена).{0,12}сн|\bсон\b|\bсна\b|здоров(?:ье|ья|ью)|human health|healthy (?:eating|diet|habits)|public health|healthcare|nutrition|dietary|hygiene|dental|dentist|tooth|teeth|handwash|wash(?:ing)? (?:your )?hands|стоматолог|гигиен|мыть.{0,15}рук|зуб(?:ы|ов|н|а|у)|medicine|medical|\bhealth(?:y)?\b|врач|пациент|симптом|бессон|diabetes|hypertension|asthma|dehydration|insulin|symptom|clinical|disease|longevity|sleep|cardiovascular',
 'sport':r'велосип|велоспорт|веломаршрут|йог|подвижност|растяжк|гибкост|кардио|вынослив|трениров|физическ.{0,18}(?:активност|нагруз)|спорт(?:а|ом|у|е)?\b|спорт(?:ивн|смен)|\bбег(?:а|ом)?\b|ходьб|плаван|гимнастик|exercise|fitness|walking|swimming|pilates|mobility|бегун|марафон|триатлон|triathl|\bironman\b|бегов|бегат|атлет|силов.{0,12}нагруз|physical (?:activity|exercise|training)|cycling|yoga|workout|endurance|aerobic|running|stretching|strength training'}
RX={k:re.compile(v,re.I) for k,v in PATTERNS.items()}
ART=re.compile(r'(?i)картин|худож|живопис|пейзаж|полотн|o.keeffe|painting|artwork')
POWER=re.compile(r'(?i)электропитан|резервн.{0,15}питан|кухонн.{0,20}техник|бытов.{0,15}(?:техник|прибор)|power supply|battery backup|fridgeguard|электростанц')
NON_HUMAN=re.compile(r'(?i)мамонт|динозавр|осминог|собак|кошк|птиц|ворон|ветерин|экосистем|животн|mammoth|dinosaur|octopus|\bdogs?\b|\bcats?\b|\bbirds?\b|veterinar|animal')
HUMAN_TITLE=re.compile(r'(?i)человек|люд|для (?:детей|родителей|взрослых)|развити.{0,12}дет|human|people|adult|parenting|your|you\b')
COMPUTING=re.compile(r'(?i)обучени.{0,12}(?:модел|нейросет)|трениров.{0,12}(?:модел|нейросет)|model training|machine learning')

def active(state):return state.get('policy_version')=='4.4' and not state.get('special43_revision')

def texts(row):
    a=row.get('article',{});src=row.get('source',{})
    if a:return str(a.get('title','')),str(a.get('teaser','')),' '.join(b.get('text','') for b in a.get('blocks',[]))
    return str(row.get('title') or src.get('title','')),str(row.get('summary','')),' '.join(b.get('text','') for b in src.get('blocks',[]))

def subject(row):
    title,teaser,body=texts(row);sentences=[s for s in re.split(r'[.!?;\n]+',body) if len(s.strip())>12]
    scores={}
    for group,rx in RX.items():
        t=len(rx.findall(title));h=len(rx.findall(teaser));hits=sum(bool(rx.search(s)) for s in sentences)
        share=hits/max(1,len(sentences))
        supported=(t and hits and share>=.1) or (h and hits>=2 and share>=.15) or (hits>=3 and share>=.25 and rx.search(body[:1000]))
        if (row.get('article') or body) and not supported:continue
        if not row.get('article') and not body and not (t or h):continue
        if NON_HUMAN.search(title+' '+teaser) and not HUMAN_TITLE.search(title):continue
        if group=='family' and re.search(r'(?i)child process|parent process|parent company|parent corporation|родительск.{0,15}(?:процесс|класс)|дочерн.{0,10}процесс|материнск.{0,10}компани',title):continue
        if group=='family' and ART.search(title) and not rx.search(title):continue
        if group=='health' and POWER.search(title):continue
        if group=='health' and re.search(r'(?i)healthy (?:forest|ecosystem|tree|reef|planet|soil)|(?:здоровь|здоров).{0,12}(?:лес|экосистем|дерев|почв|планет)|financial health|economic health|здоровь.{0,12}(?:бизнес|финанс|экономик)',title):continue
        if group=='health' and re.search(r'(?i)отел|гостиниц|hotel|hostel|lodging|accommodation',title) and not re.search(r'(?i)здоров|недосып|бессон|гигиен|health|insomnia|sleep quality|sleep disorder|hygiene',title):continue
        if group=='sport' and COMPUTING.search(title) and not re.search(r'(?i)велосип|йог|бегун|спортсмен|athlete|cycl',title):continue
        scores[group]=5*t+3*h+min(hits,8)
    # One concrete article counts once; exercise benefits remain SPORT, not HEALTH too.
    return max(scores,key=lambda k:(scores[k],{'sport':3,'health':2,'family':1}[k])) if scores else None

def category(row,fallback='Общество'):
    group=subject(row)
    if group:return {'family':'Семья','health':'Здоровье и движение','sport':'Здоровье и движение'}[group]
    title,_,_=texts(row)
    if ART.search(title):return 'История и культура'
    if POWER.search(title):return 'Технологии'
    return fallback if fallback not in ('Семья','Здоровье и движение') else 'Общество'

def counts(rows):return {g:sum(subject(r)==g for r in rows) for g in GROUPS}

def standard(state,rows=None,notes=None):
    from scripts import selection43,light43
    rows=selection43.ready(state) if rows is None else rows;notes=light43.ready(state) if notes is None else notes
    groups=counts(rows);deficits={g:max(0,2-groups[g]) for g in GROUPS}
    return {'policy_version':'4.4','main_articles':len(rows),'topics':groups,'main_deficit':max(0,8-len(rows)),
        'topic_deficits':deficits,'light_notes':len(notes),'light_deficit':max(0,8-len(notes)),
        'compliant':len(rows)>=8 and not any(deficits.values()) and len(notes)>=8}

def require(state,rows=None,notes=None):
    result=standard(state,rows,notes)
    if not result['compliant']:raise p.Blocked('EDITORIAL_STANDARD_NOT_MET')
    return result

def migrate(state):
    """Unpublished only, called by existing CLI migration. No text/counter resets."""
    from scripts import editorial43 as e
    previous=state.get('policy_version');state['policy_version']='4.4'
    for row in state.get('candidates',[]):
        row['topic_policy_version']='4.4'
        if not row.get('article'):continue
        old=row['article'].get('category');new=category(row,old or 'Общество')
        if old==new:continue
        gate=row.get('checks',{}).get('final43',{});approved=e.eligible(row);old_fp=e.fingerprint(row)
        row['article']['category']=new;row['category']=row['category_hint']=new
        if approved:gate['input_hash']=e.fingerprint(row)
        row.setdefault('history',[]).append({'code':'CATEGORY44_METADATA_CORRECTION','previous':old,'current':new,'previous_hash':old_fp,'reviewed_content_unchanged':True})
    state['audit_passed']=False
    if previous!='4.4':state.setdefault('history',[]).append({'code':'POLICY44_MIGRATION','previous':previous,'accepted_text_and_quota_preserved':True})
    return state

def search_deficits(state):
    from scripts import selection43,stock43
    current=selection43.ready(state)
    planned=stock43.available(state,state['date']) if all(n>=2 for n in counts(current).values()) else current
    return {g:max(0,2-n) for g,n in counts(planned).items()}

def publisher_score(row,group):
    ids={'family':{1,2,3},'health':{12,16},'sport':{13,14,15}}
    return (-len(ids[group]&set(row.get('priority_ids',[])))/max(1,len(row.get('priority_ids',[]))),-row.get('availability',{}).get('full_originals_verified',0),-row.get('editorial_priority',50))


def publisher_order(rows,state):
    wanted={g for g,n in search_deficits(state).items() if n}
    ids={'family':{1,2,3},'health':{12,16},'sport':{13,14,15}};pending=list(rows);selected=[]
    for group in sorted(wanted):
        options=[r for r in pending if ids[group]&set(r.get('priority_ids',[]))]
        if options:
            row=min(options,key=lambda r:publisher_score(r,group))
            pending.remove(row);selected.append(dict(row,search_group=group))
    return selected+[dict(r,**({'search_group':None} if r.get('search_group') else {})) for r in pending]


def from_html(page):
    """Classify only the reader's article body, excluding sources/nav/footer."""
    from scripts.source_dom41 import Document
    doc=Document();doc.feed(page)
    nodes=list(doc.root.all())
    title=next((n.text() for n in nodes if n.tag=='h1'),'')
    teaser=next((n.text() for n in nodes if 'dek' in n.attrs.get('class','').split()),'')
    body=next((n for n in nodes if 'article-body' in n.attrs.get('class','').split()),None)
    return {'article':{'title':title,'teaser':teaser,'blocks':[{'text':n.text()} for n in body.all() if n.tag in ('p','li')] if body else []}}
