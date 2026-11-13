"""Conservative scope for optional browser generations and live source probes."""
import json
import os
from pathlib import Path
import subprocess

def scope(files):
    shared=any(f.startswith('assets/') or f in {'scripts/news.py','scripts/browser41.py','scripts/layout43.py','scripts/source_links43.py'} for f in files)
    return {
        'legacy':shared or any(f in {'scripts/publication41.py','scripts/browser43.py','scripts/review_viewer41.py'} for f in files),
        'translation':any(f in {'scripts/source_links43.py','scripts/translation_browser43.py'} for f in files),
        'sources':any(f in {'scripts/catalog43.py','scripts/source41.py','scripts/source_dom41.py','scripts/public_sources41.py','scripts/source_probe44.py','scripts/source_probe41.py','config/editorial_sources.json','config/source-profiles.json','config/light_sources44.json'} for f in files),
    }

def main():
    try:
        event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        base=event.get('pull_request',{}).get('base',{}).get('sha') or event.get('before')
        if not base or set(base)=={'0'}:raise ValueError('No trustworthy diff base')
        files=subprocess.check_output(['git','diff','--name-only',base,'HEAD'],text=True).splitlines()
        result=scope(files)
    except (KeyError,ValueError,OSError,subprocess.CalledProcessError):
        result=dict(legacy=True,translation=True,sources=True)
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:
        for key,value in result.items():output.write(key+'='+str(value).lower()+'\n')
    print('[ci-scope] '+json.dumps(result))

if __name__=='__main__':main()
