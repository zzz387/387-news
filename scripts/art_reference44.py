"""Deterministic museum-reference selection and local CIELAB color diagnostics.

Heuristics describe color and metadata overlap, never certify artistic quality.
"""
import colorsys,hashlib,io,json,math,re
from pathlib import Path
from PIL import Image,ImageStat

VERSION='387-reference-selection-1'
PROFILE_VERSION='387-color-lab-1'
CONFIG=json.loads((Path(__file__).resolve().parents[1]/'config/art-directions44.json').read_text())
FIELDS=('art_movement','medium','selected_reference_id','reference_images_sent','reference_selection_version','reference_selection_score','reference_selection_reason','palette','color_match','artwork_license','reference_attribution','reference_source_url','reference_adaptation')

def lab(rgb):
    v=[x/255 for x in rgb];r,g,b=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in v]
    xyz=[(.4124564*r+.3575761*g+.1804375*b)/.95047,.2126729*r+.7151522*g+.072175*b,(.0193339*r+.119192*g+.9503041*b)/1.08883]
    x,y,z=[t**(1/3) if t>216/24389 else (24389/27*t+16)/116 for t in xyz]
    return [116*y-16,500*(x-y),200*(y-z)]

def delta(a,b):return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))

def profile(raw):
    with Image.open(io.BytesIO(raw)) as image:
        image=image.convert('RGB');image.thumbnail((128,128));pixels=list(image.getdata());total=len(pixels)
        quant=image.quantize(colors=12,method=Image.Quantize.MEDIANCUT);pal=quant.getpalette();groups=[]
        for n,index in sorted(quant.getcolors(),reverse=True):
            rgb=pal[index*3:index*3+3];groups.append({'color':'#'+''.join(f'{v:02x}' for v in rgb),'share':round(n/total,4),'lab':[round(v,3) for v in lab(rgb)]})
        sats=[colorsys.rgb_to_hsv(*(v/255 for v in rgb))[1] for rgb in pixels];lights=sorted(lab(rgb)[0] for rgb in pixels)
        saturation=sum(sats)/total;contrast=lights[int((total-1)*.95)]-lights[int((total-1)*.05)]
        warmth=sum(g['share']*(g['lab'][2]+.35*g['lab'][1]) for g in groups)
        return {'version':PROFILE_VERSION,'sha256':hashlib.sha256(raw).hexdigest(),'groups':groups,
            'dominant':[g['color'] for g in groups if g['share']>=.15] or [groups[0]['color']],
            'secondary':[g['color'] for g in groups if .05<=g['share']<.15],
            'accent':[g['color'] for g in groups if g['share']<.05],
            'temperature':'warm' if warmth>6 else 'cool' if warmth< -6 else 'neutral',
            'saturation':'low' if saturation<.2 else 'high' if saturation>.55 else 'moderate',
            'saturation_value':round(saturation,3),'lightness':round(sum(lights)/total,2),
            'dark_share':round(sum(x<30 for x in lights)/total,3),'light_share':round(sum(x>75 for x in lights)/total,3),
            'contrast':'high' if contrast>55 else 'low' if contrast<25 else 'moderate','contrast_value':round(contrast,2)}

def distance(a,b):
    # Greedy CIELAB transport conserves color-group mass. Matching only nearest
    # colors would incorrectly accept the same hues with inverted area ratios.
    x=a['groups'];y=b['groups'];sx=sum(g['share'] for g in x);sy=sum(g['share'] for g in y)
    left=[g['share']/sx for g in x];right=[g['share']/sy for g in y];cost=0
    edges=sorted((delta(g['lab'],h['lab']),i,j) for i,g in enumerate(x) for j,h in enumerate(y))
    for dist,i,j in edges:
        mass=min(left[i],right[j]);cost+=mass*dist;left[i]-=mass;right[j]-=mass
    return cost+.15*abs(a['lightness']-b['lightness'])+10*abs(a['saturation_value']-b['saturation_value'])

def compare(reference,generated):
    score=distance(reference,generated);thresholds=CONFIG['color_thresholds']
    status='COLOR_MATCH_OK' if score<=thresholds['ok'] else 'COLOR_MATCH_WARNING' if score<=thresholds['warning'] else 'COLOR_MISMATCH'
    return {'metric':'CIELAB_GREEDY_COLOR_MASS_TRANSPORT_V1','status':status,'lab_distance':round(score,3),'reference_temperature':reference['temperature'],'generated_temperature':generated['temperature'],
            'reference_saturation':reference['saturation_value'],'generated_saturation':generated['saturation_value'],'generated_profile':generated,'quality_claim':'COLOR_ONLY_NOT_ARTISTIC_QUALITY'}

def description(palette):
    shares=', '.join(f"{g['color']} {round(g['share']*100)}%" for g in palette['groups'])
    return f"Measured reference: {shares}; {palette['temperature']}, {palette['saturation']} saturation, {palette['contrast']} contrast; lightness {palette['lightness']}/100, dark area {round(palette['dark_share']*100)}%, light area {round(palette['light_share']*100)}%."

def work_profile(root,work,state):
    cache=state.setdefault('art_library44',{}).setdefault('color_profiles',{});key=work['sha256']
    if key not in cache or cache[key].get('version')!=PROFILE_VERSION:
        raw=(Path(root)/work['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=key:raise ValueError('ART_REFERENCE_HASH_INVALID')
        cache[key]=profile(raw)
    return cache[key]

def tokens(text):return set(re.findall(r'[a-zа-яё]{4,}',text.casefold()))

def select(root,state,item,row,registry,previous):
    from scripts import art_library44
    saved=state.setdefault('art_library44',{}).setdefault('reference_choices',{});key=row['id']+'/'+item['key']
    works=[registry['artworks'][i] for i in row['artwork_ids']]
    if len(works)!=4 or not all(art_library44.file_valid(root,w) for w in works):raise ValueError('ART_SET_INTEGRITY')
    cached=saved.get(key)
    if cached:
        work=next((w for w in works if w['id']==cached['selected_reference_id']),None)
        if work is None or cached['sha256']!=work['sha256']:raise ValueError('ART_REFERENCE_SELECTION_CHANGED')
        return work,cached
    preferred=item.get('preferred_reference_id')
    if preferred:
        selected=[w for w in works if w['id']==preferred]
        if not selected:raise ValueError('ART_REFERENCE_SELECTION_CHANGED')
        works=selected
    subject=' '.join(str(v) for v in item['descriptor'].values());words=tokens(subject);weights=CONFIG['selection_weights'];rated=[]
    for work in works:
        palette=work_profile(root,work,state);metadata=' '.join(str(work.get(k,'')) for k in ('title','genre_evidence','artist'))
        overlap=len(words&tokens(metadata))/max(1,min(8,len(words)))
        # Bright/calm or dramatic contrast is a disclosed proxy, not invented museum mood metadata.
        dramatic=bool(re.search(r'conflict|storm|crisis|race|dynamic|movement',subject,re.I))
        tonal=palette['contrast_value']/100 if dramatic else 1-min(1,palette['contrast_value']/100)
        fit=min(1,.5+overlap*.4+tonal*.1)
        variety=min(1,min((distance(palette,p) for p in previous),default=50)/50)
        score=weights['meaning']*fit+weights['diversity']*variety
        rated.append((score,work['id'],work,palette,fit,variety))
    score,_,work,palette,fit,variety=min(rated,key=lambda r:(-r[0],r[1]))
    choice={'selected_reference_id':work['id'],'sha256':work['sha256'],'palette':palette,'reference_selection_version':VERSION,
            'reference_selection_score':round(score,5),'reference_selection_reason':{'metadata_and_tonal_proxy':round(fit,5),'palette_diversity':round(variety,5),'weights':weights,'mood_inference':'TRANSPARENT_HEURISTIC_NOT_VERIFIED_MOOD','preserved_for_prompt_correction':bool(preferred)}}
    saved[key]=choice;return work,choice

def direction(genre):return CONFIG['directions'].get(genre,CONFIG['directions']['Графика тушью'])

def prompt(item):
    d=item['descriptor'];scene=(d.get('visual_subject_en') or d['title']+'. '+d.get('summary','')).strip()
    style=direction(item['genre']);palette=item.get('palette')
    material=' Clearly render separated pigment strokes, broken optical edges and a visibly painted surface; avoid photographic fidelity or camera-like rendering.' if style['art_movement']=='impressionism' else ''
    color=description(palette) if isinstance(palette,dict) else 'Use the actual palette of the attached museum painting.'
    green_share=sum(g['share'] for g in palette['groups'] if g['lab'][1]<-8) if isinstance(palette,dict) else None
    if green_share is not None and green_share<.05:
        color+=' The reference has no dominant green field. Translate vegetation and other naturally colored objects into its measured color families; do not add a dominant green background.'
    conventions='; '.join(style[k] for k in ('space','line','light','texture','abstraction'))
    if style['art_movement']=='constructivism':
        conventions+='; flat Constructivist artwork, not an architectural visualization: radical asymmetry, diagonal structural axes, overlapping angular planes and schematic botanical shapes; no realistic foliage, 3D building render or depth-of-field'

    composition={'constructivism':'Structure the subject with functional geometric planes and an asymmetric axis', 'art nouveau':'Weave flowing organic rhythms into the scene itself, without an enclosing frame or ornamental border and without copying museum figures', 'cubism':'Resolve the subject into interlocking planes and simultaneous viewpoints', 'impressionism':'Stage the subject in changing natural light with optical spatial depth'}.get(style['art_movement'],item.get('composition','Independent asymmetric composition serving the subject'))
    text=(f"Using the artistic language and actual colors of image 0, create an original, unsigned, visibly non-photographic {style['art_movement']} fine-art illustration. No text or artist signatures anywhere. Never reproduce reference inscriptions; leave all four corners blank and unmarked. ARTICLE SUBJECT: {scene}\nART MOVEMENT: {style['art_movement']}. MEDIUM: {style['medium']}. "
        f"ARTISTIC CHARACTERISTICS: {style['characteristics']}{material} {conventions}.\n"
        'Use the single attached painting, image 0 (input_image_0), as the primary style reference. Render the new article subject in the artistic language, surface texture, light and tonal structure of image 0. '
        'Follow its actual color palette closely. Preserve dominant, secondary and accent proportions, temperature, saturation, contrast and light/dark distribution. '
        'Do not substitute a generic editorial color palette or dominant green unless present in the reference or necessary for the subject. '
        f"{color}\nCOMPOSITION: {composition}. "
        'Do not copy the museum scene, figures or distinctive arrangement. Avoid plastic surfaces, artificial glow, excessive symmetry, decorative particles and inappropriate hyper-detail. '
        'Respect the movement and the article facts. No text, letters, signatures, logos, labels, borders or watermarks.')
    if item.get('color_retry'):text+=' COLOR CORRECTION: retain the reference’s measured area ratios exactly as guidance, especially its dominant hue groups; reduce hues absent from it.'
    if len(text)>4000:raise ValueError('ART_PROMPT_TOO_LONG')
    return text

def comparison(root,state,items,baseline,output):
    """Only approved public texts' artwork and openly licensed museum images; no private drafts."""
    import base64,shutil
    from html import escape
    output=Path(output);output.mkdir(parents=True,exist_ok=True);rows=[];paired_old=[];paired_new=[];objects=state.get('art44',{}).get('objects',{})
    for item in items:
        slug=item['article_slug'];old=baseline['images'].get(slug)
        if not old or old.get('model')!='@cf/black-forest-labs/flux-1-schnell':continue
        prefix=slug+'-';old_name=prefix+'before.webp';shutil.copyfile(Path(root)/old['path'],output/old_name)
        obj=objects.get(item['key']);new_name=None
        if obj:
            raw=base64.b64decode(obj['webp'],validate=True)
            if hashlib.sha256(raw).hexdigest()!=obj['sha256']:raise ValueError('ART_COMPARISON_HASH_INVALID')
            new_name=prefix+'after.webp';(output/new_name).write_bytes(raw)
            paired_old.append(profile((Path(root)/old['path']).read_bytes()));paired_new.append(profile(raw))
        registry=state.get('_comparison_registry',{});work=registry.get('artworks',{}).get(item.get('selected_reference_id'),{})
        ref_name=None
        if work:
            ref_name=prefix+'reference.webp';shutil.copyfile(Path(root)/work['path'],output/ref_name)
        rows.append({'slug':slug,'genre':item['genre'],'before':old_name,'after':new_name,'reference':ref_name,'artist':work.get('artist'),'title':work.get('title'),'source':work.get('source_url'),'license':work.get('license'),'license_url':work.get('license_url'),'attribution':work.get('attribution'),'reference_change':'Resized WebP','model':obj.get('model') if obj else None,'prompt_version':item.get('prompt_version'),'old_sha256':old['sha256'],'new_sha256':obj.get('sha256') if obj else None,'reference_set_id':item.get('reference_set_id'),'selected_reference_id':item.get('selected_reference_id'),'palette':item.get('palette'),'color_match':obj.get('color_match') if obj else None,'reference_images_sent':obj.get('reference_images_sent') if obj else None})
    def variety(values):
        scores=[distance(a,b) for i,a in enumerate(values) for b in values[i+1:]]
        return round(sum(scores)/len(scores),3) if scores else None
    (output/'summary.json').write_text(json.dumps({'paired_images':len(paired_new),'targets':len(rows),'old_palette_diversity':variety(paired_old),'new_palette_diversity':variety(paired_new),'metric':'mean pairwise CIELAB color-mass transport; not an artistic quality score'},indent=2)+'\n')
    (output/'report.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    body='<html><meta charset="utf-8"><title>№029 — сравнение иллюстраций</title><style>body{font:16px sans-serif;max-width:1400px;margin:auto}section{border-bottom:1px solid;padding:24px}figure{display:inline-block;width:42%;vertical-align:top}img{max-width:100%;height:auto}.ref{width:220px}</style><h1>№029: старые и новые иллюстрации</h1>'
    for r in rows:
        body+='<section><h2>'+escape(r['slug']+' · '+r['genre'])+'</h2><figure><figcaption>FLUX.1 Schnell — до</figcaption><img src="'+r['before']+'"></figure><figure><figcaption>После · '+escape(r['model'] or 'ещё не готово')+'</figcaption>'
        if r['after']:body+='<img src="'+r['after']+'">'
        body+='</figure><p>'+escape(str(r['artist'] or '')+' · '+str(r['title'] or ''))+'</p>'
        if r['reference']:body+='<img class="ref" src="'+r['reference']+'"><p><a href="'+escape(r['source'],quote=True)+'">Музейный источник</a> · <a href="'+escape(r['license_url'],quote=True)+'">'+escape(r['license'])+'</a> · Уменьшено, преобразовано в WebP'+(' · Новая ИИ-композиция также CC BY-SA 4.0' if r['license']=='CC BY-SA 4.0' else '')+'</p>'
        body+='<pre>'+escape(json.dumps({'palette':r['palette'],'color_match':r['color_match']},ensure_ascii=False,indent=2))+'</pre></section>'
    (output/'index.html').write_text(body+'</html>')
    return rows
