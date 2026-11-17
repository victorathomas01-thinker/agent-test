"""Evaluate job ranking against a labeled fixture without network or applicant data."""

import argparse
import json
from math import log2
from pathlib import Path
import re

from .eligibility import evaluate

DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / 'examples' / 'ranking-benchmark.json'


def title_overlap(job, config):
    """Count exact preferred phrases in the listing title."""
    title = job['title'].casefold()
    return sum(bool(re.search(r'(?<!\w)' + re.escape(phrase.casefold()) + r'(?!\w)', title))
               for phrase in config['preferences']['keywords'])


def discounted_gain(relevance):
    return sum((2 ** grade - 1) / log2(index + 2) for index, grade in enumerate(relevance))


def ranking_metrics(cases, scores, cutoff):
    order = sorted(cases, key=lambda case: (-scores[case['id']], case['id']))
    top = order[:cutoff]
    ideal = discounted_gain(sorted((case['relevance'] for case in cases), reverse=True)[:cutoff])
    return {
        'ndcg': discounted_gain([case['relevance'] for case in top]) / ideal if ideal else 0.0,
        'strong_matches': sum(case['relevance'] == 2 for case in top),
        'top_ids': [case['id'] for case in top],
    }


def run_benchmark(fixture, cutoff):
    cases = fixture['cases']
    config = fixture['config']
    if not cases or not 1 <= cutoff <= len(cases):
        raise ValueError('Cutoff must be between 1 and the number of labeled jobs.')
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Fixture job IDs must be unique.')
    if any(case['relevance'] not in (0, 1, 2) or type(case['eligible']) is not bool for case in cases):
        raise ValueError('Use relevance grades 0–2 and boolean eligibility labels.')

    decisions = {case['id']: evaluate(case, config) for case in cases}
    baseline = {case['id']: title_overlap(case, config) for case in cases}
    agent = {job_id: score for job_id, (score, _, _) in decisions.items()}
    eligible_cases = [case for case in cases if decisions[case['id']][1]]
    return {
        'eligible_only': {
            'jobs': len(eligible_cases),
            'cutoff': min(cutoff, len(eligible_cases)),
            'title_overlap': ranking_metrics(eligible_cases, baseline, cutoff),
            'agent_score': ranking_metrics(eligible_cases, agent, cutoff),
        },
        'jobs': len(cases),
        'cutoff': cutoff,
        'title_overlap': ranking_metrics(cases, baseline, cutoff),
        'agent_score': ranking_metrics(cases, agent, cutoff),
        'eligibility_correct': sum(decisions[case['id']][1] == case['eligible'] for case in cases),
        'eligibility_mismatches': [
            {'id': case['id'], 'expected': case['eligible'],
             'actual': decisions[case['id']][1], 'reason': decisions[case['id']][2]}
            for case in cases if decisions[case['id']][1] != case['eligible']
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument('--cutoff', type=int, default=5)
    args = parser.parse_args()
    try:
        report = run_benchmark(json.loads(args.fixture.read_text(encoding='utf-8')), args.cutoff)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
