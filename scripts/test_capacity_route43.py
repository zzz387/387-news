"""Only configured free models; model503 capacity is distinct from a global429 hold."""
import io,json,os,unittest
from datetime import datetime,timezone
from urllib.error import HTTPError
from unittest.mock import patch
from scripts import news,generation_runtime as rt

class CapacityRouteTests(unittest.TestCase):
    def ledger(self):return {'day':datetime.now(timezone.utc).date().isoformat(),'requests':0,'models':{},'cooldowns':{}}
    def response(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self):return json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}]}).encode()
        return Response()
    def test_503_pauses_once_then_a_later_call_uses_the_existing_healthy_model(self):
        ledger=self.ledger();budget=rt.RequestBudget(ledger,gap=0);urls=[]
        def get(request,**kwargs):
            urls.append(request.full_url)
            if len(urls)==1:raise HTTPError(request.full_url,503,'UNAVAILABLE',{},io.BytesIO(b'{"error":{"status":"UNAVAILABLE","message":"high demand"}}'))
            return self.response()
        with patch.dict(os.environ,GEMINI_API_KEY='synthetic',GEMINI_MODELS='gemini-3.5-flash-lite,gemini-3.1-flash-lite'),patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(news,'urlopen',side_effect=get):
            with self.assertRaises(rt.GenerationPaused):news.gemini('synthetic')
            self.assertEqual(len(urls),1);self.assertTrue(news.gemini('synthetic')['ok'])
        self.assertIn('3.5-flash-lite',urls[0]);self.assertIn('3.1-flash-lite',urls[1]);self.assertEqual(ledger['requests'],2);self.assertEqual(budget.used,2)
    def test_429_holds_every_model_and_never_spends_another_request(self):
        ledger=self.ledger();budget=rt.RequestBudget(ledger,gap=0);error=HTTPError('synthetic',429,'QUOTA',{'Retry-After':'1200'},io.BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED"}}'))
        with patch.dict(os.environ,GEMINI_API_KEY='synthetic',GEMINI_MODELS='gemini-3.5-flash-lite,gemini-3.1-flash-lite'),patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(news,'urlopen',side_effect=error) as get:
            with self.assertRaises(rt.GenerationPaused):news.gemini('synthetic')
            with self.assertRaises(rt.GenerationPaused):news.gemini('synthetic')
        self.assertEqual(get.call_count,1);self.assertEqual(ledger['requests'],1);self.assertIn('__all_models__',ledger['cooldowns'])
    def test_capacity_routing_never_changes_the_allowed_models_or_request_caps(self):
        ledger=self.ledger();ledger['requests']=220;ledger['cooldowns']['gemini-3.5-flash-lite']=1
        budget=rt.RequestBudget(ledger,day_limit=220,gap=0)
        with patch.dict(os.environ,GEMINI_API_KEY='synthetic',GEMINI_MODELS='gemini-3.5-flash-lite,gemini-3.1-flash-lite'),patch.object(news.runtime,'ACTIVE_BUDGET',budget),patch.object(news,'urlopen',side_effect=AssertionError('No quota bypass')):
            with self.assertRaises(rt.GenerationPaused):news.gemini('synthetic')
        self.assertEqual(ledger['requests'],220);self.assertEqual(budget.used,0)
    def test_global_hold_survives_snapshot_restore_and_utc_rollover(self):
        snapshot=self.ledger();snapshot['cooldowns']['__all_models__']=9999999999
        ledger={};rt.merge_snapshot(ledger,snapshot)
        budget=rt.RequestBudget(ledger,gap=0)
        with self.assertRaises(rt.GenerationPaused):budget.reserve('gemini-3.1-flash-lite')
        self.assertEqual(ledger['requests'],0)

if __name__=='__main__':unittest.main()
