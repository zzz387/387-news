"""Failure injection for repair, request limits and independent-process recovery."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

try:
    from scripts import news, editorial31 as ed, staged_news as stage, generation_runtime as rt
    from scripts import test_longform322 as longform_fixture
    from scripts.test_response import _FakeHTTPResponse
    from scripts import locate_checkpoint as locator
except ImportError:
    import news, editorial31 as ed, staged_news as stage, generation_runtime as rt
    import test_longform322 as longform_fixture
    from test_response import _FakeHTTPResponse
    import locate_checkpoint as locator



class AutonomousTests(unittest.TestCase):
    def fixture(self):
        fixture = longform_fixture.Longform323Tests()
        fixture.setUp()
        fixture.doCleanups()  # use production retry default here
        def response(index, length=150):
            part = fixture.response(index, length)
            missing = length - ed.wc(ed.article_body(part))
            part['paragraphs'][-1]['text'] += ' уточнение' * missing
            return part
        return fixture.plan, fixture.dossier, response

    def test_96_and_77_words_repaired_with_feedback(self):
        plan, dossier, response = self.fixture()
        answers = [response(0,96), response(0,77)] + [response(i,150) for i in range(8)]
        with patch.object(news, 'gemini', side_effect=answers) as api:
            article = ed.write_from_dossier(plan, dossier, '2026-10-26')
        self.assertEqual(api.call_count, 10)
        self.assertIn('96 words', api.call_args_list[1].args[0])
        self.assertIn('77 words', api.call_args_list[2].args[0])
        self.assertGreaterEqual(article['word_count'], 1050)
        self.assertEqual(len(dossier['_longform_progress']['parts']), 8)
        self.assertEqual(dossier['_longform_progress']['failures']['0'], 2)

    def test_repeated_and_internally_duplicated_prose_repaired(self):
        plan, dossier, response = self.fixture()
        dup = response(2)
        dup['paragraphs'][1] = copy.deepcopy(dup['paragraphs'][0])
        answers = [response(0), response(0), dup] + [response(i) for i in range(1,8)]
        with patch.object(news, 'gemini', side_effect=answers) as api:
            ed.write_from_dossier(plan, dossier, '2026-10-26')
        self.assertEqual(api.call_count,10)
        self.assertIn('repeats', api.call_args_list[2].args[0])

    def test_terminal_evidence_rejection_is_bounded_across_runs(self):
        plan, dossier, response = self.fixture()
        with patch.object(news, 'gemini', return_value=response(0,75)) as api:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    ed.write_from_dossier(plan, dossier, '2026-10-26')
            with self.assertRaises(rt.EvidenceRejected):
                ed.write_from_dossier(plan, dossier, '2026-10-26')
            with self.assertRaises(rt.EvidenceRejected):
                ed.write_from_dossier(plan, dossier, '2026-10-26')
        self.assertEqual(api.call_count, 9)
        self.assertEqual(dossier['_longform_progress']['parts'], [])

    def test_fragment_persisted_before_next_request(self):
        plan, dossier, response = self.fixture()
        snapshots=[]
        def save():
            snapshots.append(copy.deepcopy(dossier))
        with patch.object(rt, 'CHECKPOINT', save), patch.object(news, 'gemini', side_effect=[response(0),rt.GenerationPaused('stop')]):
            with self.assertRaises(rt.GenerationPaused):
                ed.write_from_dossier(plan,dossier,'2026-10-26')
        self.assertEqual(len(snapshots[-1]['_longform_progress']['parts']), 1)

    def test_independent_processes_restore_and_continue_ciphertext(self):
        # Each subprocess has a fresh interpreter, no shared mocks or globals.
        code = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
from scripts import editorial31 as ed, staged_news as s, generation_runtime as rt
from scripts import test_longform322 as longform_fixture
f=longform_fixture.Longform323Tests(); f.setUp(); f.doCleanups()
p=Path(sys.argv[1]); key=bytes(range(32)); first=not p.exists()
state={'dossier':f.dossier} if first else s.decipher(p.read_bytes(),key)
d=state['dossier']; prior=len(d.get('_longform_progress',{}).get('parts',[]))
answers=[f.response(0)] + [f.response(1,96)]*3 if first else [f.response(i) for i in range(1,8)]
with patch.object(ed.news,'gemini',side_effect=answers) as api:
    try: result=ed.write_from_dossier(f.plan,d,'2026-10-26')
    except ValueError: result=None
p.write_bytes(s.cipher(state,key))
print(json.dumps({'prior':prior,'parts':len(d['_longform_progress']['parts']),'calls':api.call_count,'words':result['word_count'] if result else 0}))
'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'draft.enc'
            def run():
                result=subprocess.run([sys.executable,'-c',code,str(path)],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,check=True)
                return json.loads(result.stdout.splitlines()[-1])
            first=run(); second=run()
        self.assertEqual(first, {'prior':0,'parts':1,'calls':4,'words':0})
        self.assertEqual(second, {'prior':1,'parts':8,'calls':7,'words':1200})

    def test_budget_counts_failed_attempts_and_persists_between_runs(self):
        ledger={}; reservations=[]
        budget=rt.RequestBudget(ledger,lambda: reservations.append(copy.deepcopy(ledger)),run_limit=2,day_limit=3,gap=0)
        budget.reserve('lite'); budget.reserve('lite')
        with self.assertRaises(rt.GenerationPaused): budget.reserve('lite')
        restored=json.loads(json.dumps(ledger))
        second=rt.RequestBudget(restored,run_limit=2,day_limit=3,gap=0)
        second.reserve('lite')
        with self.assertRaises(rt.GenerationPaused): second.reserve('lite')
        self.assertEqual(restored['requests'],3)
        self.assertEqual(len(reservations),2)

    def test_actual_client_never_sends_request_after_budget(self):
        budget=rt.RequestBudget({},run_limit=1,day_limit=2,gap=0)
        bad={'candidates':[{'finishReason':'MAX_TOKENS'}]}
        with patch.dict(os.environ,{'GEMINI_API_KEY':'fake'}), patch.object(rt,'ACTIVE_BUDGET',budget), patch.object(news,'urlopen',return_value=_FakeHTTPResponse(bad)) as api, patch.object(news.time,'sleep'):
            with self.assertRaises(rt.GenerationPaused): news.gemini('test')
        self.assertEqual(api.call_count,1)

    def test_429_503_defer_without_fallback_or_request_storm(self):
        for status in (429,503):
            with self.subTest(status=status):
                budget=rt.RequestBudget({},gap=0)
                error=HTTPError('https://example.invalid',status,'error',{'Retry-After':'300'},io.BytesIO(b'{}'))
                with patch.dict(os.environ,{'GEMINI_API_KEY':'fake'}),patch.object(rt,'ACTIVE_BUDGET',budget),patch.object(news,'urlopen',side_effect=error) as api:
                    with self.assertRaises(rt.GenerationPaused): news.gemini('test')
                self.assertEqual(api.call_count,1)
                self.assertEqual(budget.ledger['requests'],1)
                restored=rt.RequestBudget(json.loads(json.dumps(budget.ledger)),gap=0)
                with self.assertRaises(rt.GenerationPaused): restored.reserve('gemini-3.5-flash-lite')

    def test_candidate_survives_review_transport_outage(self):
        candidate={'title':'A sufficiently long headline', 'word_count':580}
        state={'date':'2026-10-26','sources':[{'id':'S001'}], 'plan':[{'category':'Семья','long':False}], 'articles':{}, 'dossiers':{'0':{'claims':[]}}}
        with patch.object(ed,'write_from_dossier',return_value=candidate) as write, patch.object(ed,'verify_article',side_effect=[rt.GenerationPaused('503'),True]):
            with self.assertRaises(rt.GenerationPaused): stage.write_batch(state)
            state=stage.decipher(stage.cipher(state,bytes(range(32))),bytes(range(32)))
            stage.write_batch(state)
        self.assertEqual(write.call_count,1)
        self.assertIn('0',state['articles'])

    def test_queue_does_not_starve_later_stories(self):
        state={'date':'2026-10-26','sources':[], 'plan':[{'category':'Семья'}]*8,'articles':{}}
        with patch.object(ed,'make_dossier',side_effect=RuntimeError('temporary')):
            stage.write_batch(state,2); stage.write_batch(state,2)
        self.assertEqual(set(state['rejections']),{'0','1','2','3'})

    def test_artifact_service_failure_never_treated_as_empty(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'PHASE':'plan','PREVIEW':'true','TARGET_DATE':'2026-10-26','GITHUB_REPOSITORY':'zzz387/387-news','GITHUB_OUTPUT':directory+'/out'}),patch.object(stage,'request_json',side_effect=HTTPError('url',503,'unavailable',{},None)):
            with self.assertRaises(HTTPError): locator.main()
            self.assertFalse(Path(directory+'/out').exists())

    def test_corrupt_ciphertext_and_wrong_mode_never_publish(self):
        blob=bytearray(stage.cipher({'date':'2026-10-26'},bytes(range(32))))
        blob[-1]^=1
        with self.assertRaises(Exception): stage.decipher(bytes(blob),bytes(range(32)))
        with self.assertRaisesRegex(RuntimeError,'No approved'): stage.render({'audit_passed':False},True)
        with patch.dict(os.environ,{'GITHUB_REF_NAME':'codex/test','NEWS_RELEASE_APPROVED':'true'}):
            with self.assertRaisesRegex(RuntimeError,'only main'): stage.render({'date':'2026-10-23','audit_passed':True,'stage':'audited'},False)

    def test_preview_branch_checkpoint_isolation(self):
        with patch.dict(os.environ,{'GITHUB_REF_NAME':'main'}): main=stage.artifact_label('2026-10-26',True)
        with patch.dict(os.environ,{'GITHUB_REF_NAME':'codex/test'}): branch=stage.artifact_label('2026-10-26',True)
        self.assertNotEqual(main,branch)

    def test_workflow_upload_failure_blocks_release(self):
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/daily-v31.yml').read_text()
        self.assertIn("success() && github.ref == 'refs/heads/main'",workflow)
        self.assertNotIn('continue-on-error',workflow)
        self.assertIn('if-no-files-found: error',workflow)

if __name__ == '__main__': unittest.main()
