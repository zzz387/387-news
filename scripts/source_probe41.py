"""Network-only source trial: never invokes a model or emits source/dossier text."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
import re
from pathlib import Path
try:
    from scripts import policy41 as p, source41, rights41, content41
except ImportError:
    import policy41 as p
    import source41
    import rights41
    import content41


def probe(item,fetch=source41.fetch):
    row={'test_id':item['test_id'],'url':item['url'],'tags':item['tags'],
         'category_hint':item.get('category_hint'),'trial_eligible':bool(item.get('trial_eligible'))}
    try:
        source=fetch(item['url']); pieces=content41.chunks(source['blocks'])
        mode,decision=rights41.select_mode(source)
        body_urls=any(re.search(r'https?://|www\.',b['text']) for b in source['blocks'])
        if body_urls and mode!='INDEPENDENT_ARTICLE':
            decision=rights41.decision(source,'INDEPENDENT_ARTICLE')
            if decision.get('status')!='allowed': raise p.Blocked('ORIGINAL_READER_FORMAT_CONFLICT')
            mode='INDEPENDENT_ARTICLE'
        row.update(status='eligible',mode=mode,metadata_gaps=source.get('metadata_gaps',[]),
            source_hash=source['content_hash'],blocks=len(source['blocks']),
            technical_characters=sum(len(b['text']) for b in source['blocks']),
            old_analysis_operations=len(pieces),analysis_operations=len(content41.operation_groups(pieces)),
            source_sections=sum(b['kind']=='heading' for b in source['blocks']),
            reader_body_has_urls=body_urls,
            declared_license=source.get('declared_license'),rights_verification=decision.get('verification'))
        if item['test_id']=='unicef-21':
            # This is structure evidence only, never a claim that Gemini produced 21 safe games.
            row['original_activity_headings']=sum(b['kind']=='heading' and b.get('heading_level')==4 for b in source['blocks'])
            groups=[]; active=False
            for block in source['blocks']:
                if block['kind']=='heading' and block.get('heading_level',2)<=3:
                    active=bool(re.match(r'Activities for ',block['text'],re.I))
                    if active: groups.append(0)
                elif active and block['kind']=='heading' and block.get('heading_level')==4: groups[-1]+=1
            row['original_activity_groups']=groups
    except p.Blocked as exc:
        row.update(status='rejected',code=exc.code)
        cause=exc.__cause__
        if cause is not None: row['cause_code']=type(cause).__name__
        if isinstance(getattr(cause,'code',None),int): row['http_status']=cause.code
        if exc.code=='SOURCE_EXTRACTION_PARTIAL' and fetch is source41.fetch:
            # Robots already passed in fetch. Public DOM labels only, never prose or a dossier.
            try:
                try: from scripts import source_dom41 as dom
                except ImportError: import source_dom41 as dom
                document=dom.Document(); document.feed(source41.transport(item['url'])); document.close()
                nodes=list(document.root.all())
                row['dom_diagnostics']={'semantic_regions':[{ 'tag':n.tag,'closed':n.closed} for n in nodes if n.tag in ('article','main')],
                    'candidates':[{'tag':n.tag,'class':n.attrs.get('class',''),'id':n.attrs.get('id',''),'closed':n.closed}
                        for n in nodes if n.tag in ('div','section') and any(w in (n.attrs.get('class','')+' '+n.attrs.get('id','')).lower() for w in ('article','body','content'))][:50],
                    'paragraphs':sum(n.tag=='p' for n in nodes)}
            except Exception as error: row['diagnostic_code']=type(error).__name__
    except Exception as exc:
        row.update(status='unavailable',code=type(exc).__name__)
        if isinstance(getattr(exc,'code',None),int): row['http_status']=exc.code
    return row


def run(catalog,fetch=source41.fetch):
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows=list(pool.map(lambda item:probe(item,fetch),catalog['candidates']))
    eligible=[r for r in rows if r['status']=='eligible']
    trial=[r for r in eligible if r['trial_eligible']]
    coverage={'at_least_12_trial_candidates':len(trial)>=p.ARTICLE_COUNT,
              'required_category_hints':p.REQUIRED<={r['category_hint'] for r in trial},
              'licensed_translation':any(r['mode']=='FULL_TRANSLATION' for r in trial),
              'russian_primary':any('russian' in r['tags'] for r in trial),
              'unicef_21_original':any(r['test_id']=='unicef-21' for r in trial),
              'independent_child_evidence':any(r['test_id']=='who-under-five' for r in eligible),
              'independent_health_evidence':any(r['test_id']=='nih-adult-health' for r in eligible)}
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'gemini_requests':0,'sources':rows,
            'eligible':len(eligible),'trial_candidates':len(trial),'coverage':coverage,
            'source_pool_sufficient':all(coverage.values())}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True); args=parser.parse_args()
    report=run(json.loads((p.ROOT/'config/trial-sources.json').read_text()))
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    # The report contains only public URLs, statuses, hashes and technical counts.
    print(json.dumps(report,ensure_ascii=False))
    if not report['source_pool_sufficient']: raise SystemExit('SOURCE_POOL_INCOMPLETE: inspect public diagnostics; no Gemini calls were made')


if __name__=='__main__': main()
