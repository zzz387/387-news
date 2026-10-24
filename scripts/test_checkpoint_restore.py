import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from scripts import staged_news as s, locate_checkpoint as l
except ImportError:
    import staged_news as s
    import locate_checkpoint as l


class CheckpointRestoreTests(unittest.TestCase):
    def setUp(self):
        self.key=bytes(range(32))
        self.state={'version':3,'date':'2026-10-25','articles':{},'plan':[{'category':'Семья'}]}

    def test_official_downloaded_encrypted_file_restored(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'news-draft.enc'
            p.write_bytes(s.cipher(self.state,self.key))
            with patch.dict('os.environ',{'NEWS_CHECKPOINT_FILE':str(p),
                                          'NEWS_CHECKPOINT_EXPECTED':'true'}):
                self.assertEqual(s.fetch_latest_checkpoint('test',self.key),self.state)

    def test_absent_checkpoint_permitted_for_initial_plan(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict('os.environ',{'NEWS_CHECKPOINT_FILE':str(Path(d)/'absent.enc'),
                                          'NEWS_CHECKPOINT_EXPECTED':'false'}):
                self.assertIsNone(s.fetch_latest_checkpoint('test',self.key))

    def test_missing_expected_file_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.dict('os.environ',{'NEWS_CHECKPOINT_FILE':str(Path(d)/'absent.enc'),
                                          'NEWS_CHECKPOINT_EXPECTED':'true'}):
                with self.assertRaisesRegex(RuntimeError,'downloaded encrypted file is missing'):
                    s.fetch_latest_checkpoint('test',self.key)

    def test_wrong_key_never_decrypts(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'news-draft.enc'
            p.write_bytes(s.cipher(self.state,self.key))
            with patch.dict('os.environ',{'NEWS_CHECKPOINT_FILE':str(p),
                                          'NEWS_CHECKPOINT_EXPECTED':'true'}):
                with self.assertRaises(Exception):
                    s.fetch_latest_checkpoint('test',bytes(range(1,33)))

    def test_selects_latest_matching_nonexpired_artifact(self):
        records=[
          {'id':1,'name':'387news-test-2026-10-25','created_at':'2026-10-24T10:00:00Z'},
          {'id':2,'name':'387news-test-2026-10-25','created_at':'2026-10-24T11:00:00Z'},
          {'id':3,'name':'387news-test-2026-10-25','created_at':'2026-10-24T12:00:00Z','expired':True},
          {'id':4,'name':'387news-production-2026-10-25','created_at':'2026-10-24T13:00:00Z'}]
        self.assertEqual(l.newest_artifact(records,'387news-test-2026-10-25')['id'],2)

    def test_no_test_production_leak(self):
        records=[{'id':5,'name':'387news-production-2026-10-25'}]
        self.assertIsNone(l.newest_artifact(records,'387news-test-2026-10-25'))

if __name__ == '__main__':
    unittest.main()
