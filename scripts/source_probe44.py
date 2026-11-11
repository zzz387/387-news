"""Public source diagnostics only. No model, Secrets, or unpublished text."""
import argparse,json
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from scripts import catalog43 as catalog,public_sources41,policy41 as p

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    ids=set(json.loads((p.ROOT/'config/light_sources44.json').read_text())['publisher_ids'])
    sources=[s for s in catalog.registry()['publishers'] if s['id'] in ids]
    def check(row):
        # Independent origin sessions prevent shared transport races.
        return catalog.inspect_publisher(row,public_sources41.Session(timeout=7),article_limit=2)[0]
    with ThreadPoolExecutor(max_workers=6) as pool:rows=list(pool.map(check,sources))
    result={'checked_at':datetime.now(p.TZ).isoformat(),'gemini_requests':0,'publishers':rows}
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for row in rows:print('[source44-public] '+json.dumps(row,ensure_ascii=False),flush=True)
    print('[source44-summary] '+json.dumps({'checked_at':result['checked_at'],'checked':len(rows),'discovery_verified':sum(r['status'] in ('discovery_verified','full_sources_verified') and r['discovered']>0 for r in rows),'full_sources':sum(r['eligible'] for r in rows),'gemini_requests':0}),flush=True)
if __name__=='__main__':main()
