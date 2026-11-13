"""Exercise the real production module entrypoint, not only imported functions."""
import base64,json,os,subprocess,sys,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from scripts import policy41 as p

class ProductionModuleTests(unittest.TestCase):
    def test_workflow_module_command_restores_and_previews_without_model_or_public_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);day=datetime.now(timezone.utc).date().isoformat()
            ledger={'day':day,'requests':3,'models':{'synthetic':3},'cooldowns':{}}
            quota=folder/'quota.json';quota.write_text(json.dumps(ledger))
            output=folder/'outputs';output.touch();home=(p.ROOT/'index.html').read_bytes()
            env={**os.environ,'DRAFT_ENCRYPTION_KEY':base64.b64encode(bytes(range(32))).decode(),
                'NEWS_POLICY_VERSION':'4.3','GEMINI_API_KEY':'','GH_TOKEN':'','GITHUB_REPOSITORY':'',
                'NEWS_RELEASE_APPROVED':'false','GITHUB_REF_NAME':'synthetic','RUNNER_TEMP':temp,'GITHUB_OUTPUT':str(output),
                'NEWS_CHECKPOINT_FILE':str(folder/'absent.enc'),'NEWS_CHECKPOINT_EXPECTED':'false',
                'NEWS_QUOTA_FILE':str(quota),'NEWS_QUOTA_EXPECTED':'true','NEWS_SPECIAL_QUOTA_EXPECTED':'false',
                'NEWS_SPECIAL_QUOTA_FILE':str(folder/'absent-special.enc'),'NEWS_MAX_REQUESTS_PER_DAY':'220'}
            result=subprocess.run([sys.executable,'-m','scripts.staged_news','--phase','run','--preview',
                '--target-date',datetime.now(p.TZ).date().isoformat()],cwd=p.ROOT,env=env,text=True,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('"policy_version": "4.3"',result.stdout)
            self.assertEqual(json.loads(quota.read_text()),ledger);self.assertEqual((p.ROOT/'index.html').read_bytes(),home)
            self.assertTrue((folder/'news-draft.enc').is_file())
            workflow=(p.ROOT/'.github/workflows/daily-v31.yml').read_text()
            self.assertIn('python -m scripts.staged_news "${arguments[@]}"',workflow)


"""Regression for the actual script-path loader which blocked Oct30 delivery."""
import os,subprocess,sys,tempfile,unittest
from pathlib import Path

class BrowserImport43Tests(unittest.TestCase):
    def test_script_directory_loader_can_validate_the_new_source_footer(self):
        scripts=Path(__file__).resolve().parent
        code='''import sys
sys.path.insert(0,sys.argv[1])
import browser41
source={'url':'https://example.org/full','publisher':'Synthetic','title':'Source','language':'en'}
html=browser41.source_links43.html_source(source)
assert browser41.source_links43.validate(html,required=True)
print('SCRIPT_SOURCE_FOOTER_VALIDATED')
'''
        with tempfile.TemporaryDirectory() as temp:
            env=dict(os.environ,PYTHONPATH='')
            result=subprocess.run([sys.executable,'-c',code,str(scripts)],cwd=temp,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('SCRIPT_SOURCE_FOOTER_VALIDATED',result.stdout)

class CompactRunnerTests(unittest.TestCase):
    def test_quick_scope_and_failure_exit_preserve_ci_protection(self):
        import contextlib,io
        from scripts import run_tests,ci_scope
        self.assertIn('scripts.test_stock_recovery43',run_tests.quick_modules(changed=['scripts/stock43.py']))
        self.assertIn('scripts.test_site_checks',run_tests.quick_modules(changed=['.github/workflows/daily-v31.yml']))
        self.assertEqual(ci_scope.scope(['scripts/editorial43.py']),dict(legacy=False,translation=False,sources=False))
        self.assertTrue(all(ci_scope.scope(['assets/style.css','scripts/source_links43.py','scripts/catalog43.py']).values()))
        from unittest.mock import patch
        for failed in (False,True):
            def example():
                if failed:raise AssertionError('Synthetic expected test failure')
            with self.subTest(failed=failed),tempfile.TemporaryDirectory() as temp,patch.object(unittest.TestLoader,'loadTestsFromNames',return_value=unittest.TestSuite([unittest.FunctionTestCase(example)])),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_tests.main(['--quick','--log',str(Path(temp)/'tests.log')]),int(failed))

if __name__=='__main__':unittest.main()
