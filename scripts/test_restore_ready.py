import copy
import unittest
from unittest.mock import patch
try:
    from scripts import restore_ready as restore
    from scripts.test_editorial31 import article
except ImportError:
    import restore_ready as restore
    from test_editorial31 import article

class RestoreReadyTests(unittest.TestCase):
    def fixture(self):
        categories=['Семья','Москва и путешествия','Здоровье и движение','Семья','Наука','История и культура','Технологии','Экономика и бизнес']
        state={'version':31,'date':'2026-10-26','branch':restore.EXPECTED_BRANCH,
               'preview':True,'stage':'audited','audit_passed':True,
               'articles':{},'plan':[],'sources':[],'dossiers':{}}
        for i,category in enumerate(categories):
            a=article(long=i<2,category=category,idx=i+1)
            a['_review_scope']='title_teaser_body_v1'
            sid=f'S{i+1:03d}'
            quotes=[f'Literal evidence about observation {i} and documented fact {j}.' for j in range(8)]
            state['articles'][str(i)]=a
            state['plan'].append({'category':category,'kind':a['kind'],'long':i<2,'source_ids':[sid]})
            state['sources'].append({'id':sid,'evidence':' '.join(quotes)})
            state['dossiers'][str(i)]={'claims':[{'source_id':sid,'quote':q} for q in quotes]}
        return state

    def test_accepts_the_original_dated_issue_without_generation(self):
        state=self.fixture()
        before=copy.deepcopy(state)
        with patch.object(restore.stage.news,'gemini',side_effect=AssertionError('No API calls on restore')):
            self.assertGreaterEqual(restore.validate_prepared(state),5000)
        self.assertEqual(state,before)

    def test_refuses_redating_partial_or_unreviewed_material(self):
        for field,value in [('date','2026-10-25'),('branch','unknown'),('preview',False),('audit_passed',False)]:
            with self.subTest(field=field):
                state=self.fixture(); state[field]=value
                with self.assertRaises(RuntimeError): restore.validate_prepared(state)
        state=self.fixture(); del state['articles']['7']
        with self.assertRaises(RuntimeError): restore.validate_prepared(state)

    def test_refuses_corrupt_source_evidence_and_unreviewed_teaser(self):
        state=self.fixture(); state['sources'][0]['evidence']='Not the recorded evidence'
        with self.assertRaises(RuntimeError): restore.validate_prepared(state)
        state=self.fixture(); state['articles']['0'].pop('_review_scope')
        with self.assertRaises(RuntimeError): restore.validate_prepared(state)

    def test_actual_restore_is_forbidden_outside_github_actions(self):
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'false'}),patch('sys.argv',['restore_ready']):
            with self.assertRaisesRegex(RuntimeError,'restricted to GitHub Actions'): restore.main()
