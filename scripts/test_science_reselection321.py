"""Regression tests for 387 News 3.2.1 original-source fallback. No network/API."""
import unittest
from unittest.mock import patch
try:
    from scripts import editorial31 as e
except ImportError:
    import editorial31 as e


def fixture():
    categories = (['Наука'] * 4 + ['История и культура'] * 3 +
                  ['Семья'] * 3 + ['Москва и путешествия'] * 3 +
                  ['Здоровье и движение'] * 3)
    candidates, sources = [], []
    for i, cat in enumerate(categories):
        title = f'Документированный сюжет {i+1}'
        kind = 'новость' if i == 0 else 'очерк'
        sid = f'S{i+1:03d}'
        candidates.append({
            'title': title, 'category': cat, 'kind': kind, 'source_ids': [sid],
            'hook': 'Подробные документированные обстоятельства истории',
            'long': i in (0, 4, 7, 10, 13),
            'score': 25 if i == 0 else 24 - (i % 3),
            'novelty': 5, 'reader_interest': 5, 'specificity': 5,
            'evidence': 5, 'fit': 5,
        })
        sources.append({'id': sid, 'url': f'https://original{i}.org/report',
                        'evidence': 'Достоверные сведения и подтверждённые факты. ' * 150,
                        'recent': True, 'abstract_only': False, 'title': title})
    return candidates, sources


class OriginalSourceReplacementTests(unittest.TestCase):
    def test_unsupported_scientific_news_replaced_without_weakening_plan(self):
        candidates, sources = fixture()
        initial = e.select_balanced_plan(candidates, sources)
        self.assertTrue(any(x['title'] == 'Документированный сюжет 1' for x in initial))
        def verify(srcs, plan, *, strict=True):
            for item in plan:
                if item['title'] == 'Документированный сюжет 1':
                    if strict:
                        raise RuntimeError('original missing')
                    item['original_unverified'] = True
            return srcs, plan
        with patch.object(e, 'enrich_originals', side_effect=verify):
            result_sources, plan = e.select_plan_with_verified_science(
                sources, candidates, initial_plan=initial)
        self.assertIs(result_sources, sources)
        self.assertEqual(len(plan), 8)
        self.assertNotIn('Документированный сюжет 1', [p['title'] for p in plan])
        self.assertTrue(e.LIFE.issubset({p['category'] for p in plan}))
        self.assertGreaterEqual(sum(p['category'] in e.LIFE for p in plan), 4)
        self.assertGreaterEqual(sum(p['long'] for p in plan), 2)
        self.assertLessEqual(sum(p['long'] for p in plan), 3)

    def test_no_substitute_keeps_publication_blocked(self):
        candidates, sources = fixture()
        initial = e.select_balanced_plan(candidates, sources)
        # Restrict to exactly the initially selected eight stories: no fallback
        # can replace the unsupported science candidate without violating the
        # eight-story issue contract.
        chosen = {p['title'] for p in initial}
        candidates = [c for c in candidates if c['title'] in chosen]
        for c in candidates:
            if c['category'] == 'Наука':
                c['kind'] = 'новость'
        initial = e.select_balanced_plan(candidates, sources)
        def reject_every_science(srcs, plan, *, strict=True):
            for p in plan:
                if p['category'] == 'Наука':
                    p['original_unverified'] = True
            return srcs, plan
        with patch.object(e, 'enrich_originals', side_effect=reject_every_science):
            with self.assertRaisesRegex(RuntimeError, 'No balanced issue after excluding|Not enough supported'):
                e.select_plan_with_verified_science(sources, candidates, initial_plan=initial)

    def test_strict_enrichment_still_vetoes_unsupported_original(self):
        source = {'id': 'S101', 'url': 'https://unknown.example/secondary',
                  'title': 'News', 'recent': True, 'published': '2026-10-24',
                  'evidence': 'A summary'}
        plan = [{'title':'Непроверенная работа', 'category':'Наука',
                 'kind':'новость', 'source_ids':['S101']}]
        with patch.object(e.news, 'http_get', side_effect=OSError('offline')):
            with self.assertRaisesRegex(RuntimeError,'original accessible'):
                e.enrich_originals([source], plan)

if __name__ == '__main__':
    unittest.main()
