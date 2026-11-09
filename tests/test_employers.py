import unittest
from unittest.mock import patch

from agent import core
from agent.employers import board_from_url, find_boards


class EmployerDiscoveryTest(unittest.TestCase):
    def test_recognizes_only_direct_supported_posting_links(self):
        self.assertEqual(
            board_from_url('https://boards.greenhouse.io/example/jobs/123?ref=feed'),
            ('greenhouse', 'example'),
        )
        self.assertEqual(
            board_from_url('https://jobs.lever.co/example/12345678-abcd-4321-bcda-123456789012/apply'),
            ('lever', 'example'),
        )
        for url in (
            'https://boards.greenhouse.io.example.com/example/jobs/123',
            'https://other.example@boards.greenhouse.io/example/jobs/123',
            'https://boards.greenhouse.io/embed/job_app?token=123',
        ):
            self.assertIsNone(board_from_url(url))

    def test_rank_deduplicate_and_ignore_closed_and_configured(self):
        def listing(board, timestamp, active=True):
            return dict(url=f'https://boards.greenhouse.io/{board}/jobs/{timestamp}',
                        active=active, date_posted=timestamp, company_name=board.title())

        rows = [listing('known', 7), listing('closed', 6, False), listing('new', 4),
                listing('new', 5), listing('older', 2)]
        boards, errors = find_boards(['feed'], {('greenhouse', 'known')}, 1,
                                    lambda _: rows, lambda _: 0)
        self.assertEqual(boards, [('greenhouse', 'new')])
        self.assertEqual(errors, [])

    def test_only_imports_active_board_api_postings_and_keeps_fallback(self):
        cfg = core.with_defaults({'discovery': {
            'greenhouse_boards': ['known'], 'lever_sites': [],
            'employer_feeds': ['broken', 'feed'],
        }})
        clue = dict(url='https://boards.greenhouse.io/new/jobs/100', active=True,
                    company_name='New Employer')
        board = 'https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=true'
        responses = {
            'feed': [clue],
            board.format('new'): {'jobs': [
                {'id': 101, 'absolute_url': 'https://job-boards.greenhouse.io/new/jobs/101'},
                {'id': 102, 'absolute_url': 'https://example.invalid/apply'},
            ]},
            board.format('known'): {'jobs': [
                {'id': 200, 'absolute_url': 'https://boards.greenhouse.io/known/jobs/200'},
            ]},
        }

        def fetch(url):
            if url == 'broken':
                raise OSError('feed unavailable')
            return responses[url]

        with patch.object(core, 'http_json', side_effect=fetch):
            jobs, errors = core.discover(cfg)
        self.assertEqual({job['id'] for job in jobs}, {'greenhouse:new:101', 'greenhouse:known:200'})
        self.assertEqual(jobs[1]['company'], 'new')
        self.assertEqual(len(errors), 1)
        self.assertIn('feed unavailable', errors[0])
