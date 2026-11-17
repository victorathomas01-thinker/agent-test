import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent.dashboard import load_jobs, render_dashboard


class DashboardTest(unittest.TestCase):
    def test_loads_only_display_fields_and_escapes_job_text(self):
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'local.sqlite3'
            connection = sqlite3.connect(database)
            try:
                connection.execute('''CREATE TABLE jobs (id TEXT, title TEXT, company TEXT,
                    location TEXT, score INTEGER, eligible INTEGER, status TEXT, reason TEXT, notes TEXT)''')
                connection.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                   ('a', '<Role>', 'Example', 'Remote', 40, 1, 'prepared', '',
                                    'private note'))
                connection.commit()
            finally:
                connection.close()
            html = render_dashboard(load_jobs(database), demo=False)
            self.assertIn('&lt;Role&gt;', html)
            self.assertIn('1 waiting for review', html)
            self.assertNotIn('private note', html)

    def test_missing_database_is_not_created(self):
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'missing.sqlite3'
            with self.assertRaises(sqlite3.OperationalError):
                load_jobs(database)
            self.assertFalse(database.exists())
