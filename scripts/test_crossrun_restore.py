"""Regression tests for GitHub artifact downloads across workflow runs."""
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

try:
    from scripts import locate_checkpoint as locator
except ImportError:
    import locate_checkpoint as locator

LABEL = '387news-test-2026-10-25'

class CrossRunDownloadTests(unittest.TestCase):
    def run_locator(self, artifacts):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'github-output'
            env = {
                'PHASE': 'check', 'PREVIEW': 'true',
                'TARGET_DATE': '2026-10-25',
                'GITHUB_REPOSITORY': 'zzz387/387-news',
                'GITHUB_RUN_ID': '9999999999',
                'GITHUB_OUTPUT': str(output),
            }
            with patch.dict(os.environ, env, clear=True), patch.object(locator.staged_news,'request_json', return_value={'artifacts': artifacts}):
                locator.main()
            return dict(line.split('=',1) for line in output.read_text().strip().splitlines())

    def test_previous_run_id_is_exported_separately_from_artifact_id(self):
        old = {'id': 12573497396, 'name': LABEL, 'expired': False,
               'created_at': '2026-10-24T19:00:00Z',
               'workflow_run': {'id': 40126605275}}
        out = self.run_locator([old])
        self.assertEqual(out['found'], 'true')
        self.assertEqual(out['artifact_id'], '12573497396')
        self.assertEqual(out['run_id'], '40126605275')
        self.assertNotEqual(out['run_id'],'9999999999')

    def test_latest_valid_checkpoint_selects_its_own_run(self):
        old = {'id': 10, 'name': LABEL, 'expired': False,
               'created_at': '2026-10-24T12:00:00Z',
               'workflow_run': {'id': 11}}
        newer = {'id': 20, 'name': LABEL, 'expired': False,
                 'created_at': '2026-10-24T13:00:00Z',
                 'workflow_run': {'id': 22}}
        expired = {'id': 30, 'name': LABEL, 'expired': True,
                   'created_at': '2026-10-24T14:00:00Z',
                   'workflow_run': {'id': 33}}
        other = {'id': 40, 'name': LABEL.replace('test','production'),
                 'created_at': '2026-10-24T15:00:00Z',
                 'workflow_run': {'id': 44}}
        out = self.run_locator([old, newer, expired, other])
        self.assertEqual(out['artifact_id'], '20')
        self.assertEqual(out['run_id'], '22')

    def test_no_artifact_stays_first_run_safe(self):
        self.assertEqual(self.run_locator([]), {'found':'false'})

    def test_missing_source_run_fails_closed(self):
        artifact = {'id': 10, 'name': LABEL, 'expired': False}
        with self.assertRaisesRegex(RuntimeError, 'source workflow run ID'):
            self.run_locator([artifact])

    def test_workflow_explicitly_passes_source_run_id(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/daily-v3.yml').read_text()
        self.assertIn('run-id: ${{ steps.checkpoint.outputs.run_id }}', text)
        self.assertIn('github-token: ${{ github.token }}', text)
        self.assertIn('artifact-ids: ${{ steps.checkpoint.outputs.artifact_id }}', text)

if __name__ == '__main__':
    unittest.main()
