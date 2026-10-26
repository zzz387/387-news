"""Public source-only reserve checks. No model, secrets, private drafts or inference."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import argparse,json,threading
from pathlib import Path
from scripts import source41,rights41,policy41 as p,editorial41 as e


def run(catalog,fetch=source41.fetch):
    if fetch is source41.fetch:
        from scripts.public_sources41 import Session
        fetch=Session().fetch
    candidates=catalog['candidates'];urls=list(dict.fromkeys(u for r in candidates for u in [r['url']]+r.get('verification_urls',[])))
    def inspect(url):
        try:
            source=fetch(url);mode,rights=rights41.select_mode(source);rights41.require(source,mode,rights)
            return {'url':url,'status':'eligible','mode':mode,'rights':rights['status'],'content_hash':source['content_hash'],
                'metadata_status':source['metadata_status'],'extraction':source['extraction_status'],'title':source['title']}
        except Exception as exc:
            row={'url':url,'status':'blocked','code':getattr(exc,'code',type(exc).__name__)}
            if 'source' in locals():row['metadata']={k:source.get(k) for k in ('language','author','published','metadata_gaps','extraction_method')}
            if row['code']=='SOURCE_EXTRACTION_PARTIAL':
                try:
                    from scripts import source_dom41 as dom
                    document=dom.Document();document.feed(source41.transport(url));document.close()
                    regions,method=dom.choose_region(document)
                    row['structure']={'method':method,'selected':len(regions),'candidates':[
                        {'tag':n.tag,'id':n.attrs.get('id'),'class':n.attrs.get('class'),'itemprop':n.attrs.get('itemprop'),'closed':n.closed}
                        for n in document.root.all() if n.tag in ('main','article','body','html') or n.attrs.get('itemprop')=='articleBody' or
                        any(token in (n.attrs.get('class','')+' '+n.attrs.get('id','')) for token in ('body','fulltext','article','content','main'))][:30]}
                except Exception as diagnostic:row['diagnostic_error']=type(diagnostic).__name__
            return row
    with ThreadPoolExecutor(max_workers=3) as pool:sources=list(pool.map(inspect,urls))
    by_url={r['url']:r for r in sources};eligible=[];rejected=[]
    for candidate in candidates:
        urls=[candidate['url']]+candidate.get('verification_urls',[])
        failures=[{'url':u,'code':by_url[u].get('code')} for u in urls if by_url[u]['status']!='eligible']
        if not failures:eligible.append(candidate)
        else:rejected.append({'url':candidate['url'],'topic_id':candidate['topic_id'],'failures':failures})
    topics={key:{'topic':title,'eligible_candidates':len({r['url'] for r in eligible if r['topic_id']==key})}
            for key,title in p.CONFIG['priority_topics'].items()}
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'gemini_requests':0,'sources':sources,
        'eligible_candidates':eligible,'rejected_candidates':rejected,'topics':topics,
        'unique_eligible':len({r['url'] for r in eligible}),'required_reserve':p.ARTICLE_COUNT+p.CONFIG['reserve_articles'],
        'all_twenty_topics_covered':all(t['eligible_candidates'] for t in topics.values()),
        'editorial_or_factual_approval':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    report=run(json.loads((p.ROOT/'config/source-reserve-proposals41.json').read_text()))
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('[source-reserve] '+json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
