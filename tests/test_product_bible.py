import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent import core
from agent.careers import crawl_careers
from agent.facts import effective_answers, revoke_fact
from agent.priority import classify, weighted_score
from agent.submission import allowed_form_frame
from agent.workbench import all_jobs, claim_selected, queue_selected, select_jobs


class ProductBibleTest(unittest.TestCase):
    def test_exact_weights_and_categories(self):
        self.assertEqual(weighted_score(dict(competitiveness=100, career_value=60,
                                             schedule=50, compensation=20, interests=80)), 66.0)
        self.assertEqual(classify('Clinical Application Support Analyst')[0], 'Healthcare technology')
        self.assertEqual(classify('Hospital Patient Access Representative')[0], 'Bridge employment')

    def test_embedded_form_must_match_posting_and_origin(self):
        url = 'https://job-boards.greenhouse.io/example/jobs/123'
        job = {'id': 'greenhouse:example:123', 'url': url}
        self.assertTrue(allowed_form_frame(job, 'https://job-boards.greenhouse.io/embed/job_app?token=123'))
        self.assertFalse(allowed_form_frame(job, 'https://job-boards.greenhouse.io/embed/job_app?token=456'))
        self.assertFalse(allowed_form_frame(job, 'https://example.invalid/embed/job_app?token=123'))

    def test_fact_revocation_and_semantic_scope(self):
        cfg = core.with_defaults({'verified_answers': {'work_authorized_us': True}})
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'DB', Path(folder) / 'db.sqlite3'):
            answers = effective_answers(cfg)
            self.assertEqual(core.answer_for('Are you legally permitted to work in the United States?', answers)[0], 'Yes')
            for question in ('Are you not authorized to work in the United States?',
                             'Do you have unrestricted work authorization in the United States?',
                             'Are you legally permitted to work in Canada?'):
                self.assertIsNone(core.answer_for(question, answers)[0])
            with closing(core.connect()) as con, con:
                self.assertTrue(revoke_fact(con, 'work_authorized_us'))
            self.assertIsNone(effective_answers(cfg)['verified_answers']['work_authorized_us'])

    def test_every_job_visible_and_stale_claim_recovers(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'DB', Path(folder) / 'db.sqlite3'):
            with closing(core.connect()) as con, con:
                con.executemany('INSERT INTO jobs(id,title,status,eligible) VALUES (?,?,?,?)', [
                    (str(number), 'Synthetic job ' + str(number), 'expired' if number == 99 else 'found',
                     0 if number == 99 else 1) for number in range(105)
                ])
            select_jobs(['0', '99'], True)
            queue_selected()
            with closing(core.connect()) as con:
                self.assertEqual(len(all_jobs(con)), 105)
                self.assertEqual(claim_selected(con)['id'], '0')
                self.assertEqual(claim_selected(con)['id'], '99')
                self.assertIsNone(claim_selected(con))
                with con:
                    con.execute("UPDATE selections SET updated_at='2000-01-01' WHERE job_id='0'")
                self.assertEqual(claim_selected(con)['id'], '0')

    def test_career_crawl_preserves_unverified_and_respects_robots(self):
        root = 'https://example.invalid'
        schema = {'@type': 'JobPosting', 'title': 'IT Support Intern', 'url': root + '/jobs/1',
                  'description': 'Help desk', 'jobLocation': {'address': {'addressLocality': 'Charlotte'}}}
        pages = {
            root + '/robots.txt': 'User-agent: *\nDisallow: /jobs/blocked',
            root + '/careers': '<a href="/jobs/1">IT Support Intern</a><a href="/jobs/2">Data Analyst</a>'
                               '<a href="/jobs/blocked">Blocked Role</a><a href="https://other.invalid/jobs/3">External role</a>',
            root + '/jobs/1': '<script type="application/ld+json">' + json.dumps(schema) + '</script>',
            root + '/jobs/2': '<h1>Data Analyst</h1>',
        }
        seen = []
        def fetch(url, _):
            seen.append(url)
            return pages[url]
        with patch('agent.careers.public_host', return_value=True), patch('agent.careers.sleep'):
            jobs = crawl_careers({'company': 'Example', 'url': root + '/careers'}, 4, core.plain, fetch)
        self.assertEqual([job['verification'] for job in jobs], ['structured', 'unverified'])
        self.assertNotIn(root + '/jobs/blocked', seen)
