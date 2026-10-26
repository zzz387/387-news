"""Desktop/mobile checks; screenshots remain inside the private review bundle."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import Thread


def check(root,date,output):
    from playwright.sync_api import sync_playwright
    root=Path(root); output=Path(output); output.mkdir(parents=True,exist_ok=True)
    class Silent(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Silent,directory=str(root)))
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    report={'viewports':[],'pages':0,'horizontal_overflow':False}
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            for width in (320,390,1440):
                page=browser.new_page(viewport={'width':width,'height':900})
                base=f'http://127.0.0.1:{server.server_port}'
                page.goto(base+'/',wait_until='networkidle')
                urls=page.locator(f'a[href^="/issues/{date}/articles/"]').evaluate_all('(nodes)=>[...new Set(nodes.map(n=>n.getAttribute("href")))]')
                if len(urls)!=12: raise ValueError('BROWSER_TWELVE_ARTICLES_REQUIRED')
                for index,url in enumerate(urls):
                    page.goto(base+url,wait_until='networkidle')
                    if page.evaluate('document.documentElement.scrollWidth>innerWidth+1'): raise ValueError('BROWSER_HORIZONTAL_OVERFLOW')
                    body=page.locator('.article-body')
                    if not body.is_visible() or body.evaluate('(n)=>n.scrollHeight>n.clientHeight+1'): raise ValueError('BROWSER_BODY_CLIPPED')
                    if page.locator('.source-primary').count()!=1: raise ValueError('BROWSER_SOURCE_BLOCK_COUNT')
                    if body.locator('p,li,h2,h3,blockquote').evaluate_all('(nodes)=>nodes.some(n=>getComputedStyle(n).display==="none"||getComputedStyle(n).visibility==="hidden")'):
                        raise ValueError('BROWSER_BODY_HIDDEN')
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
        from scripts import policy41 as p,publication41
        from scripts.test_policy41 import issue
    except ImportError:
        import policy41 as p
        import publication41
        from test_policy41 import issue
    parser=argparse.ArgumentParser(); parser.add_argument('--synthetic',action='store_true',required=True)
    parser.add_argument('--output',required=True); args=parser.parse_args()
    # Only the explicitly synthetic fixture is available to CI. No real draft is loaded.
    with tempfile.TemporaryDirectory(prefix='387-synthetic-browser-') as temp:
        root=Path(temp)/'site'; root.mkdir(); shutil.copytree(p.ROOT/'assets',root/'assets')
        (root/'archive').mkdir(); (root/'issues').mkdir()
        state=issue(); publication41.build(state,root)
        report=check(root,state['date'],Path(temp)/'screenshots')
    Path(args.output).write_text(json.dumps(report)); print(json.dumps(report))


if __name__=='__main__': main()
