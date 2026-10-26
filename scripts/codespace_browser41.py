"""Synthetic real TLS reverse-proxy test; does not claim GitHub authorization."""
from datetime import datetime,timedelta,timezone
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import ipaddress
from pathlib import Path
import ssl
import tempfile
from threading import Thread
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def check(files,date):
    from scripts import review_viewer41 as v
    from playwright.sync_api import sync_playwright
    upstream=v.ReviewServer(files,date)
    class Gateway(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            connection=http.client.HTTPConnection('127.0.0.1',upstream.server_port,timeout=15)
            try:
                connection.request('GET',self.path,headers=dict(self.headers))
                response=connection.getresponse();body=response.read()
                self.send_response(response.status)
                for name,value in response.getheaders():
                    if name.lower() not in ('server','date','connection','transfer-encoding'): self.send_header(name,value)
                self.end_headers();self.wfile.write(body)
            finally:connection.close()
    gateway=ThreadingHTTPServer(('127.0.0.1',0),Gateway)
    origin=f'https://127.0.0.1:{gateway.server_port}';upstream.external_origin=origin
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic loopback TLS')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
          .not_valid_after(datetime.now(timezone.utc)+timedelta(hours=1))
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .sign(key,hashes.SHA256()))
    threads=[]
    report={'synthetic':True,'github_authorization_verified':False,'tls_proxy':True,'pages':0,'viewports':[]}
    with tempfile.TemporaryDirectory(prefix='387-synthetic-tls-') as temp:
        cert_path=Path(temp)/'cert.pem';key_path=Path(temp)/'key.pem'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        key_path.chmod(0o600)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert_path,key_path)
        gateway.socket=context.wrap_socket(gateway.socket,server_side=True)
        for server in (upstream,gateway):
            thread=Thread(target=server.serve_forever,daemon=True);thread.start();threads.append(thread)
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                # Only this synthetic self-signed loopback certificate is accepted for the test.
                ctx=browser.new_context(ignore_https_errors=True)
                for width in (320,390,768,1440):
                    page=ctx.new_page(viewport={'width':width,'height':900});failures=[]
                    page.on('response',lambda response:failures.append(response.status) if response.status>=400 else None)
                    page.goto(upstream.url,wait_until='networkidle')
                    urls=page.locator(f'a[href*="/issues/{date}/articles/"]').evaluate_all('(nodes)=>[...new Set(nodes.map(n=>n.getAttribute("href")))]')
                    if len(urls)!=12: raise ValueError('PROXY_TWELVE_LINKS_REQUIRED')
                    for url in urls:
                        page.goto(origin+url,wait_until='networkidle')
                        if page.evaluate('document.documentElement.scrollWidth>innerWidth+1'):raise ValueError('PROXY_HORIZONTAL_OVERFLOW')
                        if not page.locator('.article-body').is_visible():raise ValueError('PROXY_BODY_HIDDEN')
                        if not page.evaluate('document.styleSheets.length>0'):raise ValueError('PROXY_CSS_MISSING')
                        if page.locator('.source-primary').count()!=1:raise ValueError('PROXY_SOURCE_MISSING')
                        report['pages']+=1
                    if failures:raise ValueError('PROXY_BROKEN_RESOURCE')
                    page.close();report['viewports'].append(width)
                browser.close()
        finally:
            for server in (gateway,upstream):server.shutdown();server.server_close()
            for thread in threads:thread.join()
    return report
