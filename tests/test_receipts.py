from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import core
from agent.receipts import record_receipt, scan_receipts

CONFIRMATION = """Application confirmation

Thank you for applying to Example Employer for the Software Engineer Intern role.
Confirmation reference: synthetic-123.
"""


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        database = Path(folder.name) / 'agent.sqlite3'
        self.enterContext(patch.object(core, 'DB', database))
        self.con = self.enterContext(closing(core.connect()))
        with self.con:
            self.con.executemany(
                """INSERT INTO jobs(id, company, title, source, eligible, score)
                   VALUES (?, 'Example Employer', 'Software Engineer Intern', 'greenhouse', 1, 40)""",
                [('job-one',), ('job-two',)],
            )

    def test_matching_receipt_updates_log_without_storing_text_or_reopening_job(self):
        self.assertTrue(record_receipt(self.con, 'job-one', CONFIRMATION))
        self.assertFalse(record_receipt(self.con, 'job-one', CONFIRMATION))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 1)
        attempt = self.con.execute('SELECT * FROM attempts').fetchone()
        self.assertEqual(attempt['outcome'], 'submitted')
        self.assertNotIn('synthetic-123', attempt['details'])
        self.assertEqual(self.con.execute('SELECT length(fingerprint) FROM receipts').fetchone()[0], 64)
        core.add_attempt('job-one', 'needs_review', 'Previously started dry run finished.')
        job = self.con.execute("SELECT * FROM jobs WHERE id='job-one'").fetchone()
        self.assertEqual(job['status'], 'submitted')
        self.assertIsNotNone(job['submitted_at'])
        self.assertEqual(core.claim_preview(self.con, daily_limit=5)['id'], 'job-two')

    def test_invalid_and_duplicate_receipts_leave_other_job_unmodified(self):
        with self.assertRaisesRegex(ValueError, 'explicit acknowledgment'):
            record_receipt(self.con, 'job-two',
                           'We have not received your application for Software Engineer Intern at Example Employer.')
        with self.assertRaisesRegex(ValueError, 'same employer and job title'):
            record_receipt(self.con, 'job-two', CONFIRMATION.replace('Example Employer', 'Other Company'))
        self.assertTrue(record_receipt(self.con, 'job-one', CONFIRMATION))
        with self.assertRaisesRegex(ValueError, 'another listing'):
            record_receipt(self.con, 'job-two', CONFIRMATION.replace('\n', '\r\n'))
        job = self.con.execute("SELECT * FROM jobs WHERE id='job-two'").fetchone()
        self.assertEqual(job['status'], 'found')
        self.assertIsNone(job['submitted_at'])

    def test_inbox_matches_only_dated_unambiguous_pending_receipts(self):
        for job_id in ('job-one', 'job-two'):
            core.add_attempt(job_id, 'submission_pending', 'Synthetic hold.')
        self.con.execute("UPDATE attempts SET at='2025-01-01T12:00:00+00:00'")
        self.con.commit()
        with tempfile.TemporaryDirectory() as folder:
            inbox = Path(folder)

            def message(name, date, content=CONFIRMATION):
                (inbox / f'{name}.eml').write_text(
                    f'Date: {date}\nContent-Type: text/plain; charset=utf-8\n\n{content}',
                    encoding='utf-8',
                )

            message('fresh', 'Wed, 01 Jan 2025 13:00:00 +0000')
            message('old', 'Tue, 31 Dec 2024 13:00:00 +0000')
            message('quoted', 'Wed, 01 Jan 2025 13:00:00 +0000',
                    '\n'.join('> ' + line for line in CONFIRMATION.splitlines()))
            self.assertEqual(scan_receipts(self.con, inbox),
                             {'matched': 0, 'unmatched': 2, 'ambiguous': 1, 'unreadable': 0})
            self.con.execute("UPDATE jobs SET url='https://example.invalid/jobs/1' WHERE id='job-one'")
            self.con.commit()
            self.assertEqual(scan_receipts(self.con, inbox)['ambiguous'], 1)
            message('fresh', 'Wed, 01 Jan 2025 13:00:00 +0000',
                    CONFIRMATION + '\nhttps://example.invalid/jobs/1?ref=receipt')
            self.assertEqual(scan_receipts(self.con, inbox)['matched'], 1)
            self.assertEqual(scan_receipts(self.con, inbox)['matched'], 0)
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id='job-one'").fetchone()[0],
                         'submitted')
        self.assertEqual(self.con.execute("SELECT status FROM jobs WHERE id='job-two'").fetchone()[0],
                         'submission_pending')
