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
