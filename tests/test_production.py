import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent import core
from agent.matching import qualifications
from agent.operations import track_application, write_dashboard
from agent.packages import prepare_package


class PreparationTest(unittest.TestCase):
    def test_hard_and_preferred_gpa_and_graduation(self):
        profile = {'graduation': 'December 2027'}
        self.assertFalse(qualifications('Minimum GPA of 3.0 preferred.', profile, 2.79))
        self.assertTrue(qualifications('Minimum GPA of 3.0 is required.', profile, 2.79))
        self.assertFalse(qualifications('Applicants must graduate between May 2027 and December 2027.', profile, 2.79))
        self.assertTrue(qualifications('Applicants must graduate between January 2028 and May 2028.', profile, 2.79))

    def test_canonical_urls_drop_tracking_and_preserve_job_parameters(self):
        url = 'https://job-boards.greenhouse.io/test/jobs/123'
        self.assertEqual(core.canonical_url(url), core.canonical_url(url + '?gh_src=tracking'))
        self.assertEqual(core.canonical_url(url), core.canonical_url(url.replace('job-boards.', 'boards.')))
        self.assertNotEqual(core.canonical_url('https://example.invalid/?job=1'),
                            core.canonical_url('https://example.invalid/?job=2'))
        self.assertFalse(core.valid_application_url('https://127.0.0.1/jobs'))

    def test_package_and_tracker_preserve_source_and_submission(self):
        cfg = core.with_defaults({})
        job = {'id': 'greenhouse:test:123', 'source': 'greenhouse', 'company': 'Example',
               'title': 'Junior Software Engineer', 'location': 'Charlotte',
               'url': 'https://job-boards.greenhouse.io/test/jobs/123', 'description': 'Python testing'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resume = root / 'master.txt'
            resume.write_text('Synthetic Applicant\n\nExperience\n• Built Python testing tools for a class project.\n\nProjects\nPython tools\n', encoding='utf-8')
            with patch.object(core, 'ROOT', root), patch.object(core, 'DB', root / 'db.sqlite3'):
                package, version = prepare_package(resume, job, cover=True)
                self.assertEqual(prepare_package(resume, job, cover=True)[1], version)
                manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
                self.assertEqual(manifest['cover_letter'], 'draft_requires_review')
                self.assertEqual((package / 'master.txt').read_bytes(), resume.read_bytes())
                core.store_jobs([job, {**job, 'id': 'manual:copy', 'source': 'manual'}], cfg)
                core.add_attempt(job['id'], 'submitted', 'Synthetic receipt.')
                with closing(core.connect()) as con:
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)
                    track_application(con, job['id'], 'interview', '2026-12-01')
                    dashboard = write_dashboard(con, cfg).read_text(encoding='utf-8')
                    self.assertIn('interview', dashboard)
                    self.assertIn('Follow-up 2026-12-01', dashboard)
                    self.assertNotIn('Synthetic Applicant', dashboard)
                    self.assertIsNotNone(con.execute('SELECT submitted_at FROM jobs').fetchone()[0])

    def test_ashby_and_smartrecruiters_adapters(self):
        job_url = 'https://jobs.ashbyhq.com/example/12345678-abcd-4321-bcda-123456789012/application'
        ashby = {'jobs': [{'title': 'QA Intern', 'isListed': True, 'applyUrl': job_url,
                            'location': 'Charlotte', 'employmentType': 'Intern'},
                          {'isListed': False, 'applyUrl': job_url}]}
        with patch.object(core, 'http_json', return_value=ashby):
            jobs = core.fetch_board('ashby', 'example', 'Example', 5)
        self.assertEqual([job['employment_type'] for job in jobs], ['Intern'])
        detail = {'name': 'IT Support', 'postingUrl': 'https://jobs.smartrecruiters.com/Example/123-it-support',
                  'location': {'city': 'Charlotte', 'region': 'NC'},
                  'jobAd': {'sections': {'qualifications': {'text': '<p>Python</p>'}}}}
        with patch.object(core, 'http_json', side_effect=[{'content': [{'id': '123'}]}, detail]) as fetch:
            jobs = core.fetch_board('smartrecruiters', 'Example', 'Example', 50)
        self.assertEqual(jobs[0]['location'], 'Charlotte, NC')
        self.assertIn('Python', jobs[0]['description'])
        self.assertIn('limit=50', fetch.call_args_list[0].args[0])

    def test_only_complete_board_scans_expire_old_unsubmitted_jobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(core, 'DB', Path(temporary) / 'agent.sqlite3'):
                with closing(core.connect()) as con, con:
                    con.executemany('INSERT INTO jobs(id,status,last_seen) VALUES (?,?,?)', [
                        ('greenhouse:complete:1', 'found', '2026-01-01'),
                        ('greenhouse:complete:2', 'submission_pending', '2026-01-01'),
                        ('greenhouse:complete:3', 'found', '2026-01-03'),
                        ('greenhouse:partial:1', 'found', '2026-01-01'),
                    ])
                self.assertEqual(core.expire_unlisted([('greenhouse', 'complete')], [], '2026-01-02'), 1)
                with closing(core.connect()) as con:
                    self.assertEqual([row['status'] for row in con.execute('SELECT status FROM jobs ORDER BY id')],
                                     ['expired', 'submission_pending', 'found', 'found'])
