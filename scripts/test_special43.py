"""4.3 reissue adapter: synthetic checkpoints only, no production material/API."""
import copy,json,os,shutil,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from scripts import special43 as r,editorial43 as e,special003r as old,special_publication41 as pub,policy41 as p,staged_news as stage,release_queue as queue,special_continue41 as continuation
from scripts.test_policy41 import source
from scripts.test_special003r import complete_special
from scripts.test_daily43 import RESERVE_FIXTURE


def ready_issue():
    s=complete_special();s['policy_version']='4.3';s['special43_revision']=1
    for row in s['candidates']:
        full=[]
        for i,item in enumerate(row['supporting_sources']):
            item=dict(source(i+100),url=item['url'],canonical=item['url'],id=p.digest(item['url']))
            full.append(item)
        row['supporting_sources']=full;row['article']['activities']=[]
        row['article']['title']='Один самостоятельный аспект '+str(row['special_slot'])
        row['checks']['final43']={'approved':True,'input_hash':e.fingerprint(row),**{key:True for key in e.CHECKS}}
    return s


class Special43Tests(unittest.TestCase):
    def test_migration_preserves_quota_sources_old_refusals_and_does_not_approve_rejected_drafts(self):
        s=old.new_state();s['_quota_snapshot']={'day':'2026-10-28','requests':193,'models':{'lite':193},'cooldowns':{'lite':100}}
        row=s['candidates'][0];row.update(status='needs_review',article={'title':'Previously refused work'})
        row['rejected_part']={'result':{'approve':False,'issues':['Real copying concern']}}
        row['progress']['article_repair_count']=2;before=copy.deepcopy(s)
        r.migrate(s)
        self.assertEqual(s['policy41_checkpoint'],before);self.assertEqual(s['_quota_snapshot'],before['_quota_snapshot'])
        self.assertNotIn('article',row);self.assertFalse(e.eligible(row));self.assertEqual(row['progress']['article_repair_count'],2)
        self.assertEqual(s['version'],41);self.assertEqual(s['policy_version'],'4.3')
        self.assertIs(r.migrate(s),s);self.assertEqual(len(s['policy41_checkpoint']['candidates']),8)
        restored=stage.decipher(stage.cipher(s,bytes(range(32))),bytes(range(32)))
        self.assertEqual(restored,s)

    def test_writer_reuses_literal_grounded_facts_without_author_quotation_or_reanalysis(self):
        s=old.new_state();r.migrate(s);row=s['candidates'][0];src=source()
        row['source']=src;row['claims']=[{'id':'c','source_id':src['id'],'fact':'A previously checked neutral fact','quote':src['blocks'][-1]['text']}]
        editor=r.Editor(call=lambda *a,**k:self.fail('No inference in saved fact projection'));basis=editor.writing_basis(row)
        self.assertEqual(basis['previously_grounded_facts'][0]['fact'],'A previously checked neutral fact')
        self.assertNotIn('quote',str(basis));self.assertNotIn('blocks',basis)
        row['claims'][0]['quote']='NOT IN FULL SOURCE';self.assertIn('full_originals',editor.writing_basis(row))

    def test_seven_cannot_publish_but_eight_short_works_without_21_activities_can(self):
        s=ready_issue();self.assertEqual(len(r.validate_ready(s)),8)
        self.assertEqual(s['candidates'][2]['article']['activities'],[])
        s['candidates'][4]['checks']['final43']['facts']=False
        with self.assertRaisesRegex(p.Blocked,'SPECIAL_EIGHT_TOPICS_REQUIRED'):r.validate_ready(s)

    def test_daily_first_admission_and_global_cooldown_and_reserve_are_not_bypassed(self):
        now=datetime(2026,10,28,12,tzinfo=p.TZ);day=now.astimezone(timezone.utc).date().isoformat()
        daily={'version':43,'branch':'main','preview':False};ledger={'day':day,'requests':3,'models':{'lite':3},'cooldowns':{}}
        with tempfile.TemporaryDirectory() as temp,patch.object(r.daily43,'reserve_catalog',return_value=[RESERVE_FIXTURE]):
            root=Path(temp);self.assertEqual(r.admit(root,daily,ledger,now)[1],'CURRENT_DAILY_NOT_PUBLISHED')
            (root/'issues'/now.date().isoformat()).mkdir(parents=True)
            (root/'issues'/now.date().isoformat()/'index.html').write_text('<main data-policy-version="4.3">')
            before=copy.deepcopy(ledger);self.assertTrue(r.admit(root,daily,ledger,now)[0]);self.assertEqual(ledger,before)
            self.assertEqual(r.admit(root,daily,dict(ledger,requests=196),now)[1],'DAILY_QUOTA_RESERVED')
            self.assertEqual(r.admit(root,daily,dict(ledger,cooldowns={'lite':now.timestamp()+60}),now)[1],'GEMINI_COOLDOWN')

    def test_special_projection_preserves_real_daily_home_and_original003_and_eight_pages(self):
        s=ready_issue()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for folder in ('assets','issues','archive'):shutil.copytree(p.ROOT/folder,root/folder)
            shutil.copyfile(p.ROOT/'index.html',root/'index.html');home=(root/'index.html').read_bytes()
            original={str(f.relative_to(root)):f.read_bytes() for f in (root/'issues/2026-10-26').rglob('*') if f.is_file()}
            self.assertTrue(pub.build(s,root));self.assertEqual(pub.validate(root)['policy_version'],'4.3')
            self.assertEqual((root/'index.html').read_bytes(),home)
            self.assertEqual(original,{str(f.relative_to(root)):f.read_bytes() for f in (root/'issues/2026-10-26').rglob('*') if f.is_file()})
            self.assertEqual(len(list((root/'issues/2026-10-26-v41/articles').glob('*/article.md'))),8)
            self.assertIn('редакция4.3',(root/'archive/index.html').read_text())
            def fetch(url):
                path=root/url.split('https://387.su/',1)[1]
                if url.endswith('/'):path=path/'index.html'
                return path.read_text()
            self.assertEqual(pub.check_public(root,fetch)['status'],'PUBLISHED')

    def test_continuation_waits_for_daily_reserve_and_other_queued_producers(self):
        now=datetime.now(timezone.utc);ledger={'day':now.date().isoformat(),'requests':196,'models':{},'cooldowns':{}}
        self.assertEqual(continuation.decision(ledger,[],1,now,reserve=24)[1],'DAILY_QUOTA_RESERVED')
        ledger['requests']=5
        self.assertFalse(continuation.decision(ledger,[{'id':2,'status':'queued'}],1,now,reserve=24)[0])
        self.assertTrue(continuation.decision(ledger,[],1,now,reserve=24)[0])

    def test_after_verified_morning_delivery_the_next_daily_date_prepares_automatically(self):
        now=datetime(2026,10,28,8,tzinfo=p.TZ)
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,NEWS_POLICY_VERSION='4.3'):
            root=Path(temp);(root/'issues/2026-10-28').mkdir(parents=True)
            (root/'issues/2026-10-28/index.html').write_text('data-policy-version="4.3"')
            self.assertEqual(queue.target_date(root,now,lambda **k:{'https':'verified'}),'2026-10-29')
            self.assertEqual(queue.target_date(root,now,lambda **k:(_ for _ in ()).throw(OSError('not delivered'))),'2026-10-28')
