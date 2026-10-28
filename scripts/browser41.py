"""Desktop/mobile checks; screenshots remain inside the private review bundle."""
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import Thread


def launch_browser(playwright):
    # Hosted GitHub Ubuntu runners already include Chrome (Chromium engine).
    # Other environments keep Playwright's bundled Chromium installation.
    channel=os.getenv('NEWS_BROWSER_CHANNEL','')
    if channel not in ('','chrome'): raise ValueError('BROWSER_CHANNEL_UNSUPPORTED')
    return playwright.chromium.launch(**({'channel':channel} if channel else {}))


def check(root,date,output,*,expected_count=12,overview_path="/"):
    from playwright.sync_api import sync_playwright
    root=Path(root); output=Path(output); output.mkdir(parents=True,exist_ok=True)
    class Silent(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Silent,directory=str(root)))
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    report={'viewports':[],'pages':0,'horizontal_overflow':False,'visible_overflow_pages':0}
    try:
        with sync_playwright() as playwright:
            browser=launch_browser(playwright)
            for width in (320,390,768,1440):
                page=browser.new_page(viewport={'width':width,'height':900})
                base=f'http://127.0.0.1:{server.server_port}'
                page.goto(base+overview_path,wait_until='networkidle')
                if page.evaluate('document.documentElement.scrollWidth>innerWidth+1'): raise ValueError('BROWSER_HOMEPAGE_HORIZONTAL_OVERFLOW')
                urls=page.locator(f'a[href^="/issues/{date}/articles/"]').evaluate_all('(nodes)=>[...new Set(nodes.map(n=>n.getAttribute("href")))]')
                if len(urls)!=expected_count: raise ValueError('BROWSER_ARTICLE_COUNT_MISMATCH')
                if expected_count==0:
                    digest=page.locator('.source-digest')
                    if digest.count()!=1 or digest.locator('li').count()<1 or not digest.is_visible():raise ValueError('BROWSER_EMPTY_DIGEST')
                    if page.locator('h1').inner_text()!='Обзор источников':raise ValueError('BROWSER_MISLABELLED_DIGEST')
                    if digest.locator('a').evaluate_all('(nodes)=>nodes.some(n=>!n.getAttribute("href").startsWith("https://"))'):raise ValueError('BROWSER_DIGEST_LINK_INVALID')
                    page.screenshot(path=str(output/f'{width}-digest.png'));report['pages']+=1
                for index,url in enumerate(urls):
                    page.goto(base+url,wait_until='networkidle')
                    if page.evaluate('document.documentElement.scrollWidth>innerWidth+1'): raise ValueError('BROWSER_HORIZONTAL_OVERFLOW')
                    body=page.locator('.article-body')
                    metrics=body.evaluate('(n)=>({scroll:n.scrollHeight,client:n.clientHeight,overflow:getComputedStyle(n).overflowY})')
                    if not body.is_visible(): raise ValueError('BROWSER_BODY_HIDDEN')
                    if metrics['scroll']>metrics['client']+1:
                        if metrics['overflow']!='visible': raise ValueError('BROWSER_BODY_CLIPPED')
                        report['visible_overflow_pages']+=1
                    if page.locator('.source-primary').count()!=1: raise ValueError('BROWSER_SOURCE_BLOCK_COUNT')
                    if body.locator('p,li,h2,h3,blockquote').evaluate_all('(nodes)=>nodes.some(n=>{const s=getComputedStyle(n);return s.display==="none"||s.visibility==="hidden"||(n.scrollHeight>n.clientHeight+1&&s.overflowY!=="visible")})'):
                        raise ValueError('BROWSER_BODY_HIDDEN')
                    if page.evaluate('Math.max(...[...document.querySelectorAll(".article-body p,.article-body li,.article-body h2,.article-body h3,.article-body blockquote")].map(n=>n.getBoundingClientRect().bottom))>document.querySelector(".source-primary").getBoundingClientRect().top+1'):
                        raise ValueError('BROWSER_SOURCE_OVERLAPS_BODY')
                    page.screenshot(path=str(output/f'{width}-{index+1:02d}-top.png'))
                    page.evaluate('window.scrollTo(0,document.documentElement.scrollHeight)')
                    page.screenshot(path=str(output/f'{width}-{index+1:02d}-end.png'))
                    report['pages']+=1
                page.close(); report['viewports'].append(width)
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()
    return report


def main():
    import argparse
    import json
    import shutil
    import tempfile
    try:
        from scripts import policy41 as p,publication41,editorial41,rights41
        from scripts.test_policy41 import issue
    except ImportError:
        import policy41 as p
        import publication41
        import editorial41
        import rights41
        from test_policy41 import issue
    parser=argparse.ArgumentParser(); parser.add_argument('--synthetic',action='store_true',required=True)
    parser.add_argument('--output',required=True); args=parser.parse_args()
    # Only the explicitly synthetic fixture is available to CI. No real draft is loaded.
    with tempfile.TemporaryDirectory(prefix='387-synthetic-browser-') as temp:
        root=Path(temp)/'site'; root.mkdir(); shutil.copytree(p.ROOT/'assets',root/'assets')
        (root/'archive').mkdir(); (root/'issues').mkdir()
        state=issue()
        # Stress actual server-rendered HTML, not an injected DOM or a short card.
        first=state['candidates'][0]
        title='Сверхдлинныйзаголовокдляпроверкипереносов'*5
        text=('Полная учебная история с конкретным вымышленным примером. '*800)+'Последняя существенная оговорка.'
        first['source']['title']=first['article']['title']=title
        first['source']['blocks'][0]['text']=first['article']['blocks'][0]['text']=title
        first['source']['blocks'][-1]['text']=first['article']['blocks'][-1]['text']=text
        first['source']['content_hash']=p.digest(first['source']['blocks'])
        first['rights']=rights41.decision(first['source'],first['mode'])
        fp=editorial41.article_hash(first['article'],first['source'],first['rights'])
        for name in p.STAGES: first['checks'][name]={'approved':True,'input_hash':fp}
        first['checks']['source_verified']['input_hash']=p.digest({'source':first['source']['content_hash'],'rights':first['rights'],'images':[]})
        state['issue_approval_hash']=p.digest([editorial41.article_hash(r['article'],r['source'],r['rights']) for r in state['candidates']])
        publication41.build(state,root)
        report=check(root,state['date'],Path(temp)/'screenshots')
        try: from scripts import review_viewer41
        except ImportError: import review_viewer41
        report['owner_reader']=review_viewer41.synthetic_browser_check(root,state['date'])
        from unittest.mock import patch
        from scripts import special_contract41 as sc,special_publication41 as sp
        from scripts.test_special003r import complete_special
        special=complete_special();config=json.loads(json.dumps(sc.definition()))
        original={'number':3,'date':sc.ORIGINAL,'articles':[{'title':'Вымышленная исходная тема '+str(i)} for i in range(8)]}
        config['original_manifest_hash']=p.digest(original)
        special['special_edition']['definition_hash']=p.digest(config)
        special['published_at']='2026-10-28T13:00:00+03:00'
        folder=root/'issues'/sc.ORIGINAL;folder.mkdir(exist_ok=True)
        (folder/'issue.json').write_text(json.dumps(original))
        (folder/'index.html').write_text('<html><body>Вымышленный оригинал</body></html>')
        with patch.object(sc,'definition',return_value=config):
            sp.build(special,root)
            report['special_003_r']=check(root,sc.SLUG,Path(temp)/'special-screenshots',expected_count=8,overview_path='/issues/'+sc.SLUG+'/')

    Path(args.output).write_text(json.dumps(report)); print(json.dumps(report))


if __name__=='__main__': main()
