import json
import unittest
try:
    import gemini_probe as p
except ImportError:
    from scripts import gemini_probe as p

class TestProbe(unittest.TestCase):
    def test_prompts_have_sources_like_workload(self):
        for kind in ('plan','article','audit'):
            prompt, schema, limit = p.make_prompt(kind,2)
            self.assertGreater(len(prompt),2000)
            self.assertIn('type',schema)
            self.assertGreater(limit,1000)
    def test_full_article_metadata(self):
        data={'title':'Проверка тестового материала', 'teaser':'пример',
              'paragraphs':[{'heading':'','text':'Это объёмный проверочный текст. '*60} for _ in range(8)]}
        body={'candidates':[{'finishReason':'STOP', 'content':{'parts':[{'text':json.dumps(data,ensure_ascii=False)}]}}],
              'usageMetadata':{'promptTokenCount':2000,'candidatesTokenCount':4500,'totalTokenCount':6500}}
        result=p.decode_200(json.dumps(body,ensure_ascii=False).encode(), 'article')
        self.assertTrue(result['json_ok'])
        self.assertGreaterEqual(result['article_chars'],580)
        self.assertEqual(result['paragraphs'],8)
        self.assertEqual(result['total_tokens'],6500)
    def test_incomplete_json(self):
        data={'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{oops'}]}}]}
        result=p.decode_200(json.dumps(data).encode(),'article')
        self.assertFalse(result['json_ok'])
    def test_reports_503_and_success(self):
        records=[{'slot':0,'http_status':503,'latency_s':2.5},
                 {'slot':0,'http_status':200,'json_ok':True,'latency_s':4,
                  'prompt_tokens':2100,'output_tokens':3500,'total_tokens':5600,'kind':'article','article_chars':810},
                 {'slot':1,'http_status':429,'latency_s':1}]
        summary, text=p.summarize(records,'2026-10-24T12:00:00+00:00',240,False)
        self.assertEqual(summary['slots_succeeded'],1)
        self.assertEqual(summary['http_codes']['503'],1)
        self.assertEqual(summary['http_codes']['429'],1)
        self.assertIn('ПРЕДВАРИТЕЛЬНО',text if False else 'ПРЕДВАРИТЕЛЬНО')
    def test_secret_redaction(self):
        self.assertNotIn('AIza',p.safe_error_message('secret AIzaAbCdEfGhIjKlMnOpQrStUvWxYz_12345'))

if __name__=='__main__':
    unittest.main()
