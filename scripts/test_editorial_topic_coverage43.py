"""Regression: semantic topic de-duplication and personal-topic preparation order."""
import unittest

from scripts import priorities43, selection43


def candidate(title, n, *, teaser='', source_title='', status='discovered'):
    return {
        'id': str(n), 'url': f'https://example.org/story/{n}',
        'title': title, 'status': status, 'summary': teaser,
        'source': {'title': source_title}, 'checks': {}, 'progress': {},
        'editorial_priority': 50, 'quality_score': 50,
    }


class EditorialTopicCoverageTests(unittest.TestCase):
    def test_november_5_living_materials_stories_collapse_as_one_topic(self):
        a = candidate(
            'Живые строительные материалы меняют подход к проектированию городской среды', 5,
            teaser='Микроорганизмы в строительных блоках позволяют создавать самовосстанавливающуюся инфраструктуру.')
        b = candidate(
            'Самовосстанавливающийся бетон и мицелий меняют облик городской архитектуры', 6,
            teaser='Инженерные живые материалы на основе бактерий и грибов для ремонта зданий.')
        self.assertTrue(selection43.duplicate(a, b))
        self.assertEqual(len(selection43.unique_ready([a, b])), 1)

    def test_narrow_theme_does_not_swallow_unrelated_engineering_story(self):
        biological = candidate('Самовосстанавливающийся бетон на основе бактерий', 1)
        unrelated = candidate('Новый сорт бетона с переработанным стеклом для мостов', 2)
        self.assertFalse(selection43.duplicate(biological, unrelated))

    def test_order_first_attempts_family_moscow_health_if_candidates_exist(self):
        rows = [
            candidate('Квантовые вычисления и новый эксперимент', 1),
            candidate('Космическая миссия к далекой звезде', 2),
            candidate('Семейный досуг и совместные игры с детьми', 3),
            candidate('История Москвы: забытая улица', 4),
            candidate('Йога и подвижность после тренировки', 5),
        ]
        ordered = selection43.order({'date': '2026-11-06', 'candidates': rows}, [])
        groups = [priorities43.classify(row)['group'] for row in ordered[:3]]
        self.assertEqual(set(groups), {'A', 'B', 'C'})

    def test_no_core_candidates_does_not_block_science_selection(self):
        rows = [candidate('Нейтрино в новом эксперименте', 1),
                candidate('Гравитационные волны от далекой звезды', 2)]
        self.assertEqual(len(selection43.order({'date':'2026-11-06','candidates':rows}, [])), 2)

    def test_preparing_article_resumes_before_new_topic(self):
        existing = candidate('Нейтрино в новом эксперименте', 1, status='preparing')
        family = candidate('Семейные игры в выходные', 2)
        result = selection43.order({'date':'2026-11-06','candidates':[family,existing]}, [])
        self.assertEqual(result[0]['id'], '1')


if __name__ == '__main__':
    unittest.main()
