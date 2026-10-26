"""Synthetic owner-preview and admission tests. No real dossier, credential or API."""
import base64
from datetime import datetime,timedelta,timezone
import io
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import zipfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from scripts import review_crypto41 as crypto,review_viewer41 as viewer,trial_control41 as control,trial_admission41 as admission,policy41 as p

DATE='2026-10-28'; SHA='a'*40


def reader_zip(extra=None):
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w') as archive:
        archive.writestr('index.html','<html><body><a href="/issues/'+DATE+'/">Все статьи</a><link href="/assets/style.css"></body></html>')
        archive.writestr('review.json','{"synthetic":true}')
        archive.writestr('assets/style.css','body{background:#fff}')
        for i in range(12): archive.writestr(f'issues/{DATE}/articles/fixture-{i}/index.html','<html><body>Фикстура</body></html>')
        if extra: archive.writestr(*extra)
    return memory.getvalue()


class CryptoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.recipient=crypto.encode_public(cls.key.public_key())

    def test_independent_recipient_roundtrip_uses_no_production_key(self):
        payload=reader_zip()
        with patch.dict(os.environ,{'DRAFT_ENCRYPTION_KEY':'DO-NOT-READ-SYNTHETIC'}):
            encrypted=crypto.seal(payload,self.recipient,DATE,SHA)
            self.assertNotIn('Фикстура'.encode(),encrypted)
            self.assertEqual(crypto.open_bundle(encrypted,self.key,SHA,DATE),payload)

    def test_metadata_tamper_and_wrong_run_or_date_fail_closed(self):
        encrypted=crypto.seal(reader_zip(),self.recipient,DATE,SHA)
        for commit,date in [('b'*40,DATE),(SHA,'2026-10-29')]:
            with self.assertRaisesRegex(ValueError,'PROVENANCE'): crypto.open_bundle(encrypted,self.key,commit,date)
        altered=json.loads(encrypted); altered['metadata']['issue_date']='2026-10-29'
        with self.assertRaises(Exception): crypto.open_bundle(json.dumps(altered).encode(),self.key,SHA,'2026-10-29')

    def test_ciphertext_tamper_is_authenticated(self):
        envelope=json.loads(crypto.seal(reader_zip(),self.recipient,DATE,SHA))
        blob=bytearray(base64.b64decode(envelope['ciphertext'])); blob[-1]^=1
        envelope['ciphertext']=base64.b64encode(blob).decode()
        with self.assertRaises(Exception): crypto.open_bundle(json.dumps(envelope).encode(),self.key,SHA,DATE)

    def test_public_input_rejects_private_or_weak_keys(self):
        weak=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with self.assertRaises(ValueError): crypto.public_key(crypto.encode_public(weak.public_key()))
        private=self.key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        with self.assertRaises(ValueError): crypto.public_key(base64.b64encode(private).decode())

    def test_new_session_keys_are_random(self):
        one=crypto.seal(reader_zip(),self.recipient,DATE,SHA)
        two=crypto.seal(reader_zip(),self.recipient,DATE,SHA)
        self.assertNotEqual(one,two)


class ViewerTests(unittest.TestCase):
    def test_zip_never_extracts_and_rejects_dossiers_traversal_and_private_assets(self):
        self.assertEqual(len(viewer.read_files(reader_zip(),DATE)),15)
        for path in ('../outside','/absolute','dossier.json','assets/key.pem','assets/context.json','issues/'+DATE+'/issue.json'):
            with self.subTest(path=path),self.assertRaises(ValueError): viewer.read_files(reader_zip((path,'SYNTHETIC')),DATE)

    def test_partial_review_is_not_a_complete_number(self):
        with self.assertRaises(ValueError): viewer.read_files(reader_zip(),'2026-10-29')

    def test_loopback_requires_token_and_rejects_foreign_host_and_origin(self):
        server=viewer.ReviewServer(viewer.read_files(reader_zip(),DATE),DATE)
        thread=Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            self.assertEqual(server.server_address[0],'127.0.0.1')
            with urlopen(server.url) as response:
                text=response.read().decode(); self.assertIn('/'+server.access_token+'/issues/',text)
                self.assertEqual(response.headers['Cache-Control'],'no-store, max-age=0')
                self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
            for url,headers in [(server.url.replace(server.access_token,''),{}),(server.url,{'Host':'evil.example'}),
                                (server.url,{'Origin':'https://evil.example'}),(server.url,{'Sec-Fetch-Site':'cross-site'})]:
                with self.subTest(headers=headers),self.assertRaises(HTTPError): urlopen(Request(url,headers=headers))
            with urlopen(server.url+'assets/style.css') as response: self.assertEqual(response.status,200)
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_private_key_remains_in_owner_directory_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            key,public=viewer.owner_key(directory)
            again,public_again=viewer.owner_key(directory)
            self.assertEqual(public,public_again)
            self.assertEqual(key.private_numbers(),again.private_numbers())
            if os.name=='posix': self.assertEqual((Path(directory)/'owner-review-key.pem').stat().st_mode&0o777,0o600)
        with self.assertRaises(ValueError): viewer.owner_key(p.ROOT/'unsafe-review-key')

    def test_official_run_provenance_is_required(self):
        run={'event':'workflow_dispatch','head_sha':SHA,'head_branch':viewer.BRANCH,'status':'completed','conclusion':'success',
             'actor':{'login':'zzz387'},'path':viewer.WORKFLOW,'repository':{'full_name':viewer.REPO}}
        viewer.verify_run(run,SHA)
        for key,value in [('event','push'),('head_sha','b'*40),('head_branch','main'),('conclusion','failure'),
                          ('actor',{'login':'someone'}),('path','.github/workflows/other.yml')]:
            with self.subTest(key=key),self.assertRaises(ValueError): viewer.verify_run(dict(run,**{key:value}),SHA)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,26,15,0,tzinfo=p.TZ)
        self.production={'date':'2026-10-27','branch':'main','preview':False,'version':31,
                         'stage':'audited','audit_passed':True,'articles':{str(i):{} for i in range(8)}}
        self.ledger={'day':'2026-10-26','requests':190,'models':{}}

    def root(self,directory):
        root=Path(directory); path=root/'issues/2026-10-26'; path.mkdir(parents=True); (path/'issue.json').write_text('{}')
        return root

    def test_only_spare_quota_after_upcoming_production_is_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.root(directory)
            self.assertTrue(admission.assess(root,self.production,self.ledger,self.now)[0])
            for field,value in [('audit_passed',False),('preview',True),('branch','codex/editorial-policy-v41'),('articles',{})]:
                self.assertFalse(admission.assess(root,dict(self.production,**{field:value}),self.ledger,self.now)[0])

    def test_high_load_or_missing_production_defers_without_api_budget_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=self.root(directory)
            ledger=dict(self.ledger,requests=197)
            self.assertEqual(admission.assess(root,self.production,ledger,self.now)[1],'NO_SPARE_TRIAL_RUN_QUOTA')
            self.assertEqual(ledger['requests'],197)
            self.assertEqual(admission.assess(root,None,self.ledger,self.now)[1],'UPCOMING_PRODUCTION_NOT_APPROVED')

    def test_current_release_and_moscow_calendar_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertEqual(admission.assess(root,self.production,self.ledger,self.now)[1],'CURRENT_PRODUCTION_NOT_PUBLISHED')
        utc=datetime(2026,10,26,22,0,tzinfo=timezone.utc)
        self.assertEqual(admission.production_date(utc),'2026-10-28')


class ControllerTests(unittest.TestCase):
    def test_mutations_cannot_target_main_other_environment_or_automatic_approval(self):
        for method,path,body in [('PUT','repos/zzz387/387-news/environments/production',{}),
            ('POST','repos/zzz387/387-news/pulls/7/merge',{}),
            ('POST',control.WORKFLOW_PATH+'/dispatches',{'ref':'main','inputs':{'phase':'trial'}}),
            ('POST','repos/zzz387/387-news/actions/runs/1/pending_deployments',{})]:
            with patch.object(viewer,'gh',side_effect=AssertionError('Must not contact API')),self.assertRaises(ValueError):
                control.api(method,path,body)

    def test_existing_reviewers_self_review_rule_and_wait_timer_are_preserved(self):
        calls=[]
        initial={'protection_rules':[{'type':'required_reviewers','prevent_self_review':True,
            'reviewers':[{'type':'User','reviewer':{'id':2}}]},{'type':'wait_timer','wait_timer':10}],
            'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True}}
        def api(method,path,body=None):
            calls.append((method,path,body))
            if path.endswith('per_page=100'): return {'branch_policies':[{'name':viewer.BRANCH}]}
            if method=='PUT': return {}
            result=json.loads(json.dumps(initial))
            if any(m=='PUT' for m,_,_ in calls): result['protection_rules'][0]['reviewers'].append({'type':'User','reviewer':{'id':1}})
            return result
        result=control.ensure_environment(1,api)
        sent=next(body for method,_,body in calls if method=='PUT')
        self.assertTrue(sent['prevent_self_review']); self.assertEqual(sent['wait_timer'],10)
        self.assertEqual(sent['reviewers'],[{'type':'User','id':2},{'type':'User','id':1}])
        self.assertTrue(result['required_reviewers'])

    def test_successful_http_without_reviewers_is_not_proof(self):
        with self.assertRaisesRegex(RuntimeError,'NOT_CONFIRMED'):
            control.ensure_environment(1,lambda *a:{'protection_rules':[]})

    def test_real_route_requires_successful_route_job_and_skipped_production(self):
        def api(method,path,body=None):
            if path.endswith('/jobs'): return {'jobs':[{'name':'trial-route','conclusion':'success'},
                {'name':'trial','conclusion':'skipped'},{'name':'prepare','conclusion':'skipped'},{'name':'deploy','conclusion':'skipped'}]}
            return {'status':'completed','conclusion':'success'}
        self.assertTrue(control.verify_route({'id':1},api,lambda _:None))
        with self.assertRaises(RuntimeError): control.verify_route({'id':1},lambda *a:{'status':'completed','conclusion':'success','jobs':[]},lambda _:None)


if __name__=='__main__': unittest.main()
