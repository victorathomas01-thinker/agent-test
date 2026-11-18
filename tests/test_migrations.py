import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from agent.storage import SCHEMA_VERSION, initialize


class MigrationTest(unittest.TestCase):
    def test_baseline_upgrade_keeps_jobs_and_is_repeatable(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "agent.sqlite3"
            with closing(sqlite3.connect(file)) as database:
                database.execute(
                    "CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT, eligible INTEGER, score INTEGER)"
                )
                database.execute("INSERT INTO jobs VALUES ('old', 'prepared', 1, 70)")
                database.commit()
                initialize(database)
                initialize(database)
                self.assertEqual(
                    database.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
                )
                self.assertEqual(
                    database.execute("SELECT * FROM jobs").fetchone(), ("old", "prepared", 1, 70)
                )
                self.assertIn(
                    "jobs_review_order",
                    [index[1] for index in database.execute("PRAGMA index_list(jobs)")],
                )
