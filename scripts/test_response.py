import json
import unittest
from unittest.mock import patch

try:
    import news
except ImportError:
    from scripts import news


class _FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return json.dumps(self.payload).encode('utf-8')


class GeminiResponseTests(unittest.TestCase):
    def test_valid_json(self):
        response = {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"articles": []}'}]}}]}
        self.assertEqual(news._parse_gemini_response(response), {'articles':[]})

    def test_reject_max_tokens(self):
        response = {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{"articles": ['}]}}],
                    'usageMetadata':{'thoughtsTokenCount':3333}}
        with self.assertRaisesRegex(news.GeminiResponseError, 'MAX_TOKENS'):
            news._parse_gemini_response(response)

    def test_retries_after_truncation(self):
        bad = {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{"ok":'}]}}]}
        good = {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true,"reasons":[]}'}]}}]}
        responses = [_FakeHTTPResponse(bad),_FakeHTTPResponse(good)]
        seen=[]
        def mocked_urlopen(request, timeout=125):
            payload = json.loads(request.data)
            seen.append(payload['generationConfig'])
            return responses.pop(0)
        with patch.dict(news.os.environ, {'GEMINI_API_KEY':'test-private-key'}, clear=False), \
             patch.object(news,'urlopen',side_effect=mocked_urlopen), \
             patch.object(news.time, 'sleep'):
            result = news.gemini('Reply briefly', output_tokens=4500, schema='audit')
        self.assertTrue(result['ok'])
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]['thinkingConfig']['thinkingLevel'], 'minimal')
        self.assertGreaterEqual(seen[1]['maxOutputTokens'], seen[0]['maxOutputTokens'])
        self.assertEqual(seen[0]['responseJsonSchema']['required'], ['ok', 'reasons'])

    def test_errors_fail_closed(self):
        bad = {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'broken json'}]}}]}
        with patch.dict(news.os.environ, {'GEMINI_API_KEY':'test-private-key'}, clear=False), \
             patch.object(news,'urlopen',return_value=_FakeHTTPResponse(bad)), \
             patch.object(news.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'All allowed free Gemini models failed'):
                news.gemini('test', output_tokens=3500)


if __name__ == '__main__':
    unittest.main()
