"""Real loopback HTTP/CSRF tests plus mocked GitHub contracts. No Gemini or private data."""
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode
from scripts import codespace41 as c,review_viewer41 as v
from scripts.test_owner_review41 import reader_zip,DATE

ENV={'CODESPACES':'true','CODESPACE_NAME':'test-owner-123','GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN':'app.github.dev'}


class CodespaceTests(unittest.TestCase):
    def test_origin_accepts_only_explicit_github_domain(self):
        self.assertEqual(c.codespace_origin(ENV),'https://test-owner-123-8765.app.github.dev')
        for changes in ({'CODESPACES':'false'},{'CODESPACE_NAME':'evil/host'},{'GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN':'evil.example'}):
            with self.assertRaises(RuntimeError): c.codespace_origin(dict(ENV,**changes))

    def test_access_requires_actual_owner_repository_and_private_port(self):
        responses=[{'login':'zzz387'},{'owner':{'login':'zzz387'},'repository':{'full_name':v.REPO}},[{'sourcePort':8765,'visibility':'private'}]]
        with patch.dict(os.environ,ENV),patch.object(v,'gh',side_effect=responses): c.Access().check()
        for bad in ('public','org',None):
            with patch.dict(os.environ,ENV),patch.object(v,'gh',side_effect=responses[:2]+[[{'sourcePort':8765,'visibility':bad}]]):
                with self.assertRaisesRegex(RuntimeError,'PRIVATE_PORT'): c.Access().check()
        with patch.dict(os.environ,ENV),patch.object(v,'gh',return_value={'login':'outsider'}):
            with self.assertRaisesRegex(RuntimeError,'OWNER_AUTH'): c.Access().check()

    def test_key_storage_survives_restart_outside_repository(self):
        with patch.dict(os.environ,ENV): self.assertEqual(str(v.key_directory()),'/workspaces/.387-news-owner-review')
        with tempfile.TemporaryDirectory() as temp:
            key,pub=v.owner_key(temp); (Path(temp)/'session.json').write_text('{"date":"2026-10-28"}')
            self.assertEqual(v.owner_key(temp)[1],pub)
            self.assertEqual(c.session(Path(temp))['date'],'2026-10-28')

    def test_forwarded_host_and_https_origin_are_exact_not_wildcards(self):
        origin='https://test-owner-123-8765.app.github.dev'
        server=v.ReviewServer(v.read_files(reader_zip(),DATE),DATE,external_origin=origin,access_check=lambda:None)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}/{server.access_token}/'
        try:
            with urlopen(Request(base,headers={'Host':origin[8:],'Origin':origin,'Sec-Fetch-Site':'same-origin'})) as r:
                self.assertEqual(r.status,200);self.assertIn(('/'+server.access_token+'/assets/').encode(),r.read())
            for headers in ({'Host':'evil.app.github.dev'},{'Host':origin[8:],'Origin':'http://'+origin[8:]},
                            {'Host':origin[8:],'Origin':'https://evil.example'}, {'Host':origin[8:],'Sec-Fetch-Site':'cross-site'}):
                with self.assertRaises(HTTPError):urlopen(Request(base,headers=headers))
            server.access_check=lambda: (_ for _ in ()).throw(RuntimeError('PRIVATE_PORT_NOT_VERIFIED'))
            with self.assertRaises(HTTPError):urlopen(Request(base,headers={'Host':origin[8:]}))
        finally:server.shutdown();server.server_close();thread.join()

    def test_panel_post_requires_token_origin_and_csrf(self):
        class Access:
            origin='https://test-owner-123-8765.app.github.dev'
            def check(self): pass
        with tempfile.TemporaryDirectory() as temp:
            server=c.Panel(temp,Access(),port=0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}/{server.access_token}/control/'
            headers={'Host':Access.origin[8:],'Origin':Access.origin,'Content-Type':'application/x-www-form-urlencoded'}
            try:
                with urlopen(Request(base,headers={'Host':Access.origin[8:]})) as r:
                    self.assertEqual(r.status,200);self.assertIn('Запустить испытание',r.read().decode())
                    self.assertIn("form-action 'self'",r.headers['Content-Security-Policy'])
                for body,hdr in [({'action':'start','csrf':'wrong'},headers),
                    ({'action':'start','csrf':server.access_token},dict(headers,Origin='https://evil.example')),
                    ({'action':'merge','csrf':server.access_token},headers)]:
                    with self.assertRaises(HTTPError):urlopen(Request(base,data=urlencode(body).encode(),headers=hdr))
                # Valid POST actually reaches the handler, with automatic redirects disabled to avoid a second Host header.
                import http.client
                with patch.object(server,'operate') as operation:
                    con=http.client.HTTPConnection('127.0.0.1',server.server_port)
                    con.request('POST','/'+server.access_token+'/control/',urlencode({'action':'status','csrf':server.access_token}),headers)
                    response=con.getresponse();self.assertEqual(response.status,303);response.read();con.close()
                    for _ in range(100):
                        if operation.called:break
                        __import__('time').sleep(.01)
                    operation.assert_called_once()
            finally:server.shutdown();server.server_close();thread.join()

    def test_error_output_cannot_expose_credentials(self):
        self.assertEqual(c.safe_error(RuntimeError('token secret-123 https://private/token')),'CODESPACE_OPERATION_FAILED')
        self.assertEqual(c.safe_error(RuntimeError('OWNER_GITHUB_CLI_REQUEST_FAILED status=403 secret')),'OWNER_GITHUB_CLI_REQUEST_FAILED status=403')

    def test_startup_does_not_dispatch_generate_or_access_secrets(self):
        root=Path(__file__).resolve().parents[1]
        setup=(root/'.devcontainer/setup.sh').read_text(); start=(root/'.devcontainer/start.sh').read_text()
        self.assertNotIn('trial_control41',setup+start)
        self.assertNotIn('GEMINI_API_KEY',setup+start)
        config=json.loads((root/'.devcontainer/devcontainer.json').read_text())
        self.assertEqual(config['portsAttributes']['8765']['visibility'],'private')
        self.assertEqual(config['customizations']['codespaces']['repositories'][v.REPO]['permissions'],{'contents':'read','actions':'write'})

    def test_recovery_refuses_wrong_run_and_does_not_generate(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(c.control,'api',return_value={'head_sha':'a'*40,'event':'push'}):
            with self.assertRaises(ValueError):c.recover(Path(temp),1,DATE)
            self.assertFalse((Path(temp)/'session.json').exists())


if __name__=='__main__':unittest.main()
