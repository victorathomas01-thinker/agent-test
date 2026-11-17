import json
import unittest

from agent.evaluation import DEFAULT_FIXTURE, ranking_metrics, run_benchmark


class EvaluationTest(unittest.TestCase):
    def test_ideal_order_has_unit_gain_and_ties_are_deterministic(self):
        cases = [{'id': 'b', 'relevance': 1}, {'id': 'a', 'relevance': 2}]
        metrics = ranking_metrics(cases, {'b': 1, 'a': 1}, 2)
        self.assertEqual(metrics, {'ndcg': 1.0, 'strong_matches': 1, 'top_ids': ['a', 'b']})

    def test_benchmark_reports_both_rankers_and_eligibility_mismatches(self):
        fixture = json.loads(DEFAULT_FIXTURE.read_text(encoding='utf-8'))
        report = run_benchmark(fixture, 5)
        self.assertEqual(len(report['title_overlap']['top_ids']), 5)
        self.assertEqual(len(report['agent_score']['top_ids']), 5)
        self.assertLessEqual(report['agent_score']['ndcg'], 1)
        self.assertEqual(report['eligibility_correct'] + len(report['eligibility_mismatches']), report['jobs'])

    def test_eligible_view_uses_one_pool_and_handles_an_empty_pool(self):
        from unittest.mock import patch
        cases = [
            dict(id='eligible', relevance=2, eligible=True),
            dict(id='excluded', relevance=0, eligible=False),
        ]
        fixture = dict(cases=cases, config={})
        with patch('agent.evaluation.title_overlap', return_value=1), patch(
                'agent.evaluation.evaluate',
                side_effect=lambda case, config: (50, case['eligible'], '')):
            report = run_benchmark(fixture, 2)
        self.assertEqual(report['eligible_only']['jobs'], 1)
        self.assertEqual(report['eligible_only']['cutoff'], 1)
        self.assertEqual(report['eligible_only']['agent_score']['top_ids'], ['eligible'])
        self.assertEqual(report['eligible_only']['title_overlap']['top_ids'], ['eligible'])
        with patch('agent.evaluation.title_overlap', return_value=1), patch(
                'agent.evaluation.evaluate', return_value=(50, False, 'review')):
            report = run_benchmark(fixture, 2)
        self.assertEqual(report['eligible_only']['jobs'], 0)
        self.assertEqual(report['eligible_only']['agent_score']['top_ids'], [])
