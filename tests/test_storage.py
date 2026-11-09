import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import core
from agent.browser import run_browser


class StorageTest(unittest.TestCase):
    def test_csv_filters_and_attempt_log(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.csv'
            path.write_text(
                'title,location,url\n'
                'Senior Software Engineer,Remote,https://example.invalid/senior\n'
                'Software Engineer Intern,Remote,https://example.invalid/intern\n',
                encoding='utf-8',
            )
            with patch.object(core, 'DB', Path(folder) / 'log.sqlite3'):
                cfg = core.with_defaults({})
                self.assertEqual(core.import_urls(path, cfg), 2)
                self.assertEqual(core.import_urls(path, cfg), 0)
                con = core.connect()
                try:
                    core.refresh_eligibility(con, cfg)
                    rows = con.execute('SELECT * FROM jobs WHERE eligible=1').fetchall()
                    self.assertEqual([row['title'] for row in rows], ['Software Engineer Intern'])
                    with patch('agent.browser.preview', return_value=('prepared', 'mock preview')):
                        run_browser(rows[0], cfg)
                    self.assertEqual(con.execute('SELECT outcome FROM attempts').fetchone()[0], 'prepared')
                    self.assertEqual(con.execute('SELECT status FROM jobs WHERE id=?',
                                                 (rows[0]['id'],)).fetchone()[0], 'prepared')
                finally:
                    con.close()

    def test_verified_question_uses_complete_wording(self):
        cfg = core.with_defaults({})
        cfg['verified_questions']['do you speak french'] = 'Yes'
        self.assertEqual(core.answer_for('Do you speak French?', cfg)[0], 'Yes')
        self.assertIsNone(core.answer_for('Do you speak French at a professional level?', cfg)[0])
        self.assertIsNone(core.answer_for('Are you authorized to work in Canada?', cfg)[0])
