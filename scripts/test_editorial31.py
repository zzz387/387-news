import unittest
from unittest.mock import patch
try:
    from scripts import editorial31 as e, staged_news as s
except ImportError:
    import editorial31 as e
    import staged_news as s


def article(long=False, category='Наука', idx=1, words=None):
    n = words or (1120 if long else 580)
    arr = ['Модель']*n
    paragraphs=[]
    length=max(1,n//9)
    for i in range(9):
        part=' '.join(arr[i*length:(i+1)*length] if i<8 else arr[i*length:])
        paragraphs.append({'heading':f'Раздел {i}' if i>0 else '', 'text':part})
    a={'title':f'История {idx} о достоверном исследовании и исторических деталях',
       'teaser':' '.join(['Детально']*40), 'paragraphs':paragraphs,
       'word_count':e.wc(' '.join(p['text'] for p in paragraphs)),
       'category':category,'kind':'очерк', 'long':long, 'source_ids':[f'S{idx:03d}']}
    return a

class Editorial31Tests(unittest.TestCase):
    def test_characters_are_not_enough_to_pass_short_story(self):
        a=article(words=160)
        with self.assertRaisesRegex(ValueError,'words; required'):
            e.article_form(a,{'long':False})
    def test_longform_requires_1050_words(self):
        a=article(long=True,words=550)
        with self.assertRaisesRegex(ValueError,'1050'):
            e.article_form(a,{'long':True})
    def test_longform_passes_with_good_length(self):
        self.assertGreater(e.article_form(article(long=True),{'long':True}),1050)
    def test_generic_lead_veto(self):
        a=article()
        a['paragraphs'][0]['text']='Современный мир ' + a['paragraphs'][0]['text']
        a['paragraphs'][1]['text']='Это уникальная возможность. '+a['paragraphs'][1]['text']
        with self.assertRaisesRegex(ValueError,'Banal'):
            e.article_form(a,{'long':False})
    def test_fuzzy_duplicate(self):
        self.assertTrue(e.meaningfully_same('Как учёные исследуют Бенну', 'Как ученые исследуют Бенну'))
        self.assertFalse(e.meaningfully_same('Бенну и Юпитер', 'Экскурсия в Кусково'))
    def test_candidate_score(self):
        self.assertEqual(e.candidate_score({'novelty':5,'reader_interest':4,'specificity':5,'evidence':5,'fit':5}),24)
    def test_shortlist_does_not_pad_with_generic_landing_pages(self):
        src=[{'id':f'S{i:03d}','url':f'https://a.org/{i}', 'evidence':'х'*1900,
              'published':'2026-10-24', 'feed':'science','recent':True,'title':f't{i}'}
             for i in range(25)]
        weak=[dict(title=f'Тема {i}',category='Наука', kind='очерк',
                   source_ids=[f'S{i:03d}'],hook='факт',why_now='не сейчас',long=False,
                   novelty=1,reader_interest=1,specificity=1,evidence=1,fit=1)
              for i in range(25)]
        with patch.object(e.news,'gemini',return_value={'candidates':weak}), \
             patch.object(e.news,'previous_titles',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'refuse to pad'):
                e.shortlist(src,'2026-10-25')
    def test_dossier_requires_verbatim_quotes(self):
        src={'S001':{'id':'S001','url':'https://one.org/one',
             'evidence':'Эксперимент показал существенное отличие наблюдений и вызвал вопросы. '*10,
             'published':'2026-10-24','title':'A'}}
        fake={'angle':'a','chronology':'b','stakes':'c','claims':[
            {'source_id':'S001','quote':'Другая выдуманная цитата о показателях в эксперименте',
             'explanation':'X'} for _ in range(9)]}
        with patch.object(e.news,'gemini',return_value=fake):
            with self.assertRaisesRegex(RuntimeError,'Insufficient exact source evidence'):
                e.make_dossier({'source_ids':['S001'],'long':False},src,'2026-10-25')
    def test_dossier_keeps_only_existing_sources(self):
        quote='Эксперимент показал существенное отличие наблюдений и вызвал вопросы.'
        src={'S001':{'id':'S001','url':'https://one.org/one', 'evidence':quote*9,
             'published':'2026-10-24','title':'A'}}
        claims=[{'source_id':'S001','quote':quote[:40]+str(i),'explanation':'a'} for i in range(6)]
        fake={'angle':'a','chronology':'b','stakes':'c','claims':claims}
        with patch.object(e.news,'gemini',return_value=fake):
            with self.assertRaisesRegex(RuntimeError,'Insufficient'):
                e.make_dossier({'source_ids':['S001'],'long':False},src,'2026-10-25')
    def test_revision_queue_preserves_other_articles(self):
        prior={'version':31,'date':'2026-10-26',
               'sources':[{'id':'S001'}],
               'articles':{'0':{'title':'Keep'}}, 'plan':[{'category':'Семья'}]*8,
               'dossiers':{},'rejections':{},'audit_passed':False}
        with patch.object(e,'make_dossier',side_effect=RuntimeError('weak evidence')):
            out=s.write_batch(prior,2)
        self.assertEqual(out['articles']['0']['title'],'Keep')
        self.assertIn('1',out['rejections'])
    def test_unsafe_release_blocked_even_if_audited(self):
        state={'audit_passed':True,'stage':'audited','date':'2026-10-23',
               'articles':{},'sources':[]}
        with patch.dict('os.environ',{'NEWS_RELEASE_APPROVED':'false'}):
            with self.assertRaisesRegex(RuntimeError,'Release veto'):
                s.render(state,False)
    def test_v31_uses_different_checkpoint_namespace(self):
        self.assertTrue(s.artifact_label('2026-10-26',True).startswith('387news31-test'))
        self.assertNotEqual(s.artifact_label('2026-10-26',True), '387news-test-2026-10-26')
    def test_novel_scientific_news_needs_original(self):
        source={'id':'S001','title':'СМИ о науке','url':'https://example.org/summary',
                'published':'2026-10-24','evidence':'Внешний пересказ','recent':True}
        plan=[{'category':'Наука','kind':'новость','source_ids':['S001']}]
        with patch.object(e.news,'http_get',side_effect=OSError('not available')):
            with self.assertRaisesRegex(RuntimeError,'original accessible'):
                e.enrich_originals([source],plan)
    def test_full_incremental_pipeline_never_needs_api_in_mock(self):
        target='2026-10-26'
        sources=[{'id':f'S{i:03d}','title':f'Source {i}',
                  'url':f'https://example.org/{i}','evidence':'A fact '*450,
                  'published':'2026-10-24','recent':True} for i in range(1,17)]
        cats=['Семья','Москва и путешествия','Здоровье и движение','Семья',
              'Наука','История и культура','Экономика и бизнес','Технологии']
        plan=[{'category':cat,'title':f'Topic {i}', 'kind':'очерк', 'long':i<2,
               'source_ids':[f'S{i+1:03d}'],'editorial_score':24}
              for i,cat in enumerate(cats)]
        dossiers={'claims':[{'source_id':'S001','quote':'A fact verified','explanation':'X'}]}
        with patch.object(s.news,'gather_sources',return_value=sources), \
             patch.object(e,'choose_plan',return_value=(plan,[])), \
             patch.object(e,'enrich_originals',side_effect=lambda ss,pp:(ss,pp)), \
             patch.object(e,'make_dossier',return_value=dossiers), \
             patch.object(e,'write_from_dossier',side_effect=lambda p,d,dt,rr='':
                 dict(title=p['title'],word_count=1250 if p['long'] else 580,
                      category=p['category'],kind=p['kind'],source_ids=p['source_ids'])), \
             patch.object(e,'verify_article',return_value=True), \
             patch.object(e,'audit_issue',return_value=5950):
            state=s.build_plan(None,target)
            self.assertEqual(state['version'],31)
            for n in (2,4,6,8):
                state=s.write_batch(state,2)
                self.assertEqual(len(state['articles']),n)
                state=s.decipher(s.cipher(state,bytes(range(32))),bytes(range(32)))
            state=s.audit(state)
            self.assertTrue(state['audit_passed'])
            self.assertEqual(state['word_count'],5950)
            self.assertEqual(state['stage'],'audited')

    def test_issue_veto_for_insufficient_total(self):
        cats=['Семья','Москва и путешествия','Здоровье и движение','Семья',
              'Наука','История и культура','Экономика и бизнес','Технологии']
        docs=[article(long=i<2,category=c,idx=i+1,words=(1070 if i<2 else 460))
              for i,c in enumerate(cats)]
        for i, a in enumerate(docs): a['title'] = ['Первые шаги в изучении детей', 'Петровский дворец архитектурный очерк', 'Белок митохондрий у грызунов', 'Экспедиция в семь далёких стран', 'Как образуются древние астероиды', 'Неизвестные факты о коллекциях', 'Судебная практика по долгам', 'Что увидел инженер на заводе'][i]
        plan=[{'long':i<2,'category':cats[i],'kind':'очерк'} for i in range(8)]
        with self.assertRaisesRegex(ValueError,'Total'):
            e.audit_issue(docs,plan,{f'S{i+1:03d}':{'url':f'https://a.org/{i}'} for i in range(8)})

if __name__=='__main__':unittest.main()
