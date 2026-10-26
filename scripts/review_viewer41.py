"""Owner PC fallback: decrypt reader-only output in RAM and bind loopback only.

No production key, no external hosting, no plaintext extraction, no public URL.
"""
import argparse
import html
import io
import json
import mimetypes
import os
from pathlib import Path,PurePosixPath
import re
import secrets
import stat
import subprocess
import tempfile
from threading import Thread
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import unquote,urlsplit
import webbrowser
import zipfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
try:
    from scripts import review_crypto41 as crypto
except ImportError: import review_crypto41 as crypto

REPO='zzz387/387-news'
BRANCH='codex/editorial-policy-v41'
WORKFLOW='.github/workflows/daily-v31.yml'
MAX_BYTES=64*1024*1024  # technical memory budget, never a publication length target


def key_directory(): return Path.home()/'.local/share/387-news-owner-review'


def owner_key(directory=None):
    directory=Path(directory or key_directory())
    if directory.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('OWNER_PRIVATE_KEY_MUST_STAY_OUTSIDE_REPOSITORY')
    directory.mkdir(parents=True,mode=0o700,exist_ok=True)
    if directory.is_symlink(): raise ValueError('OWNER_KEY_DIRECTORY_SYMLINK')
    if os.name=='posix': directory.chmod(0o700)
    path=directory/'owner-review-key.pem'
    if path.is_symlink(): raise ValueError('OWNER_PRIVATE_KEY_SYMLINK')
    if path.exists():
        if os.name=='posix' and path.stat().st_mode&0o077: raise ValueError('OWNER_PRIVATE_KEY_PERMISSIONS_REQUIRE_0600')
        key=serialization.load_pem_private_key(path.read_bytes(),password=None)
        if not isinstance(key,rsa.RSAPrivateKey) or key.key_size<3072: raise ValueError('OWNER_PRIVATE_KEY_INVALID')
    else:
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        blob=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as stream: stream.write(blob)
    encoded=crypto.encode_public(key.public_key())
    (directory/'owner-review-public.txt').write_text(encoded+'\n')
    return key,encoded


def gh(args,json_result=False,input_json=None):
    result=subprocess.run(['gh',*args],input=json.dumps(input_json) if input_json is not None else None,
        capture_output=True,text=True,timeout=120)
    if result.returncode:
        # Do not echo CLI stderr, credentials or API response bodies.
        status=re.search(r'HTTP\s+(\d{3})',result.stderr)
        raise RuntimeError('OWNER_GITHUB_CLI_REQUEST_FAILED status='+ (status[1] if status else 'unavailable'))
    return json.loads(result.stdout) if json_result else result.stdout


def verify_run(run,commit):
    if (run.get('event')!='workflow_dispatch' or run.get('head_sha')!=commit
            or run.get('head_branch')!=BRANCH or run.get('status')!='completed' or run.get('conclusion')!='success'
            or (run.get('actor') or {}).get('login','').casefold()!='zzz387'
            or run.get('path','').split('@')[0]!=WORKFLOW
            or (run.get('repository') or {}).get('full_name')!=REPO):
        raise ValueError('OWNER_REVIEW_RUN_PROVENANCE_INVALID')


def read_files(data,date):
    if len(data)>MAX_BYTES: raise ValueError('OWNER_REVIEW_MEMORY_LIMIT')
    files={}; total=0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist())>512: raise ValueError('OWNER_REVIEW_FILE_COUNT_LIMIT')
        for entry in archive.infolist():
            name=entry.filename; path=PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or '\\' in name
                    or stat.S_ISLNK(entry.external_attr>>16)): raise ValueError('OWNER_REVIEW_UNSAFE_PATH')
            if entry.is_dir(): continue
            allowed=(name in ('index.html','archive/index.html','sitemap.xml','review.json')
                or name.startswith('assets/') and path.suffix.lower() in ('.css','.js','.svg','.png','.jpg','.jpeg','.webp','.gif','.woff','.woff2','.ico')
                or name.startswith('screenshots/') and path.suffix.lower()=='.png'
                or bool(re.fullmatch(r'issues/'+re.escape(date)+r'/(?:index.html|articles/[a-z0-9-]+/(?:index.html|article.md))',name)))
            if not allowed or name in files: raise ValueError('OWNER_REVIEW_UNEXPECTED_FILE')
            total+=entry.file_size
            if total>MAX_BYTES: raise ValueError('OWNER_REVIEW_MEMORY_LIMIT')
            files[name]=archive.read(entry)
    articles=[n for n in files if re.fullmatch(r'issues/'+re.escape(date)+r'/articles/[^/]+/index.html',n)]
    if len(articles)!=12 or 'index.html' not in files or 'review.json' not in files:
        raise ValueError('OWNER_REVIEW_TWELVE_ARTICLES_REQUIRED')
    return files


def synthetic_browser_check(root,date):
    """Real encryption/decryption, loopback navigation and CSS in Chromium; synthetic only."""
    from playwright.sync_api import sync_playwright
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in Path(root).rglob('*'):
            if path.is_file(): archive.write(path,path.relative_to(root))
        archive.writestr('review.json',json.dumps({'synthetic':True,'human_review':'pending'}))
    key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    sha='a'*40
    encrypted=crypto.seal(buffer.getvalue(),crypto.encode_public(key.public_key()),date,sha)
    files=read_files(crypto.open_bundle(encrypted,key,sha,date),date)
    server=ReviewServer(files,date); thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    report={'pages':0,'viewports':[],'decryption':'RSA-OAEP-SHA256 + AES-256-GCM','production_key_used':False,'loopback_only':True}
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            for width in (320,390,1440):
                page=browser.new_page(viewport={'width':width,'height':900})
                response=page.goto(server.url,wait_until='networkidle')
                if response.status!=200: raise ValueError('OWNER_READER_HOMEPAGE_FAILED')
                urls=page.locator(f'a[href*="/issues/{date}/articles/"]').evaluate_all('(nodes)=>[...new Set(nodes.map(n=>n.getAttribute("href")))]')
                if len(urls)!=12: raise ValueError('OWNER_READER_TWELVE_LINKS_REQUIRED')
                for url in urls:
                    response=page.goto('http://127.0.0.1:'+str(server.server_port)+url,wait_until='networkidle')
                    if response.status!=200 or not page.locator('.article-body').is_visible(): raise ValueError('OWNER_READER_ARTICLE_FAILED')
                    if page.evaluate('document.documentElement.scrollWidth>innerWidth+1'): raise ValueError('OWNER_READER_HORIZONTAL_OVERFLOW')
                    if page.locator('.source-primary').count()!=1: raise ValueError('OWNER_READER_SOURCE_BLOCK_FAILED')
                    if not page.evaluate('document.styleSheets.length>0'): raise ValueError('OWNER_READER_STYLES_NOT_LOADED')
                    report['pages']+=1
                page.close(); report['viewports'].append(width)
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(); files.clear()
    return report


class ReviewServer(ThreadingHTTPServer):
    def __init__(self,files,date):
        self.files=dict(files); self.date=date; self.access_token=secrets.token_urlsafe(32)
        report=json.loads(files['review.json'])
        rows=[]; notes={a.get('title'):a for a in report.get('articles',[])}
        for path,data in files.items():
            if not re.fullmatch(r'issues/'+re.escape(date)+r'/articles/[^/]+/index.html',path): continue
            match=re.search(r'<h1[^>]*>(.*?)</h1>',data.decode(),re.S)
            title=html.unescape(re.sub('<[^>]*>','',match[1])) if match else path
            info=notes.get(title,{})
            rows.append('<li><a href="/'+html.escape(path.removesuffix('index.html'),quote=True)+'">'+html.escape(title)+'</a><p>'+
                html.escape(str(info.get('category','')))+' · '+html.escape(str(info.get('mode','')))+ '</p></li>')
        panel=('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Закрытый редакционный просмотр</title><style>body{max-width:850px;margin:24px auto;padding:16px;font:18px/1.6 Georgia,serif;overflow-wrap:anywhere}li{margin-bottom:20px}</style></head><body>'
            '<h1>Закрытый просмотр · '+html.escape(date)+'</h1><p>Все 12 статей доступны целиком. '
            'Автоматические шлюзы не заменяют ручную литературную оценку. Отметка владельца: ожидается.</p>'+
            ('<p>Синтетическая проверка механизма, не выпуск Gemini.</p>' if report.get('synthetic') else '')+
            '<p><a href="/">Главная номера</a> · <a href="/review.json">Технический редакционный протокол</a></p><ol>'+''.join(rows)+'</ol></body></html>')
        self.files['_review/index.html']=panel.encode()
        super().__init__(('127.0.0.1',0),ReviewHandler)
    @property
    def url(self): return f'http://127.0.0.1:{self.server_port}/{self.access_token}/'


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass  # URLs contain a local bearer token; never log it
    def do_GET(self):
        server=self.server
        hosts={f'127.0.0.1:{server.server_port}',f'localhost:{server.server_port}'}
        if (self.headers.get('Host') not in hosts or
                self.headers.get('Origin') not in (None,*('http://'+host for host in hosts)) or
                self.headers.get('Sec-Fetch-Site') not in (None,'none','same-origin')):
            self.send_error(403); return
        path=unquote(urlsplit(self.path).path); prefix='/'+server.access_token+'/'
        if not path.startswith(prefix): self.send_error(404); return
        relative=path[len(prefix):]
        if '..' in PurePosixPath(relative).parts or '\\' in relative: self.send_error(404); return
        if not relative or relative.endswith('/'): relative+='index.html'
        data=server.files.get(relative)
        if data is None: self.send_error(404); return
        if relative.endswith('.html'):
            text=data.decode('utf-8')
            banner='<nav style="padding:12px;text-align:center;font:14px Arial,sans-serif"><a href="/_review/">Закрытый просмотр · протокол и все 12 статей</a></nav>'
            text=re.sub(r'(<body[^>]*>)',lambda m:m[1]+banner,text,count=1,flags=re.I)
            text=re.sub(r'\b(href|src)=("|\')/(?!/)',lambda m:m[1]+'='+m[2]+prefix,text)
            data=text.encode('utf-8')
        elif relative.endswith('.css'):
            data=re.sub(rb'url\((\s*["\']?)/(?!/)',lambda m:b'url('+m[1]+prefix.encode(),data)
        self.send_response(200)
        self.send_header('Content-Type',(mimetypes.guess_type(relative)[0] or 'application/octet-stream')+('; charset=utf-8' if relative.endswith(('.html','.css','.js','.md','.json')) else ''))
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store, max-age=0')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; object-src 'none'")
        self.end_headers(); self.wfile.write(data)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run',required=True,type=int)
    parser.add_argument('--expected-sha',required=True); parser.add_argument('--date',required=True)
    parser.add_argument('--key-dir',type=Path); args=parser.parse_args()
    if os.getenv('GITHUB_ACTIONS')=='true': raise RuntimeError('OWNER_PC_VIEWER_CLI_ONLY')
    if not re.fullmatch('[0-9a-f]{40}',args.expected_sha) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',args.date):
        raise ValueError('OWNER_REVIEW_ARGUMENTS_INVALID')
    run=gh(['api',f'repos/{REPO}/actions/runs/{args.run}'],True); verify_run(run,args.expected_sha)
    name=f'v41-owner-review-{args.date}-{args.run}'
    artifacts=gh(['api',f'repos/{REPO}/actions/runs/{args.run}/artifacts'],True).get('artifacts',[])
    if not any(a.get('name')==name and not a.get('expired') for a in artifacts): raise ValueError('OWNER_REVIEW_NOT_READY_OR_EXPIRED')
    key,_=owner_key(args.key_dir)
    with tempfile.TemporaryDirectory(prefix='387-owner-ciphertext-') as temp:
        gh(['run','download',str(args.run),'--repo',REPO,'--name',name,'--dir',temp])
        path=Path(temp)/'owner-review.enc'
        if path.stat().st_size>MAX_BYTES*2: raise ValueError('OWNER_REVIEW_TRANSFER_LIMIT')
        data=crypto.open_bundle(path.read_bytes(),key,args.expected_sha,args.date)
        files=read_files(data,args.date)
    server=ReviewServer(files,args.date)
    opened=webbrowser.open(server.url)
    print('Закрытый просмотр открыт на этом ПК.' if opened else 'Откройте на этом ПК: '+server.url)
    print('Ctrl+C завершает сервер. Этот loopback-адрес не доступен с телефона.')
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); server.files.clear(); files.clear()


if __name__=='__main__': main()
