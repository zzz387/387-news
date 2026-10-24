import base64
from datetime import datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
try:
 from scripts import staged_news as s
except ImportError:
 import staged_news as s

class StagedSafetyTests(unittest.TestCase):
 def setUp(self):
  self.key=bytes(range(32))
  self.state={'version':3,'date':'2026-10-25','articles':{'0':{'title':'Пример'}}}
 def test_aes_gcm_roundtrip(self):
  self.assertEqual(s.decipher(s.cipher(self.state,self.key),self.key),self.state)
 def test_no_plaintext_in_artifact(self):
  self.assertNotIn(b'\\u041f',s.cipher(self.state,self.key))
 def test_wrong_key_rejected(self):
  with self.assertRaises(Exception):s.decipher(s.cipher(self.state,self.key),bytes(range(1,33)))
 def test_exact_key_length(self):
  self.assertEqual(s.validate_key(base64.b64encode(self.key).decode()),self.key)
  with self.assertRaises(RuntimeError):s.validate_key('hello')
 def test_plan_date_next_day(self):
  now=datetime(2026,10,24,12,17,tzinfo=ZoneInfo('Europe/Moscow'))
  self.assertEqual(s.phase_date('plan',now,None),'2026-10-25')
 def test_post_midnight_write_today(self):
  now=datetime(2026,10,25,3,17,tzinfo=ZoneInfo('Europe/Moscow'))
  self.assertEqual(s.phase_date('write',now,None),'2026-10-25')
 def test_early_publish_fails_closed(self):
  state={**self.state,'audit_passed':True,'stage':'audited'}
  now=datetime(2026,10,24,3,17,tzinfo=ZoneInfo('Europe/Moscow'))
  with patch.object(s,'datetime') as d:
   d.now.return_value=now
   d.fromisoformat.side_effect=datetime.fromisoformat
   with self.assertRaisesRegex(RuntimeError,'Too early'):s.render(state,False)
 def test_partial_audit_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'Incomplete'):s.audit(self.state)
 def test_draft_label_scoping(self):
  self.assertNotEqual(s.artifact_label('2026-10-25',True),s.artifact_label('2026-10-25',False))

if __name__=='__main__':unittest.main()
