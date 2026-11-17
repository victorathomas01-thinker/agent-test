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
