from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import core


class ScheduleTest(unittest.TestCase):
    def test_parallel_runs_share_daily_quota(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(core, 'DB', Path(folder) / 'agent.sqlite3'):
                with closing(core.connect()) as con:
                    for number in range(8):
                        con.execute(
                            "INSERT INTO jobs(id, eligible, score, source) VALUES (?, 1, ?, 'lever')",
                            (str(number), number),
                        )
                    con.commit()

                def claim(_):
                    with closing(core.connect()) as con:
                        job = core.claim_preview(con, daily_limit=3)
                        return job['id'] if job is not None else None

                with ThreadPoolExecutor(max_workers=5) as pool:
                    claimed = list(pool.map(claim, range(8)))
                self.assertEqual({item for item in claimed if item is not None}, {'7', '6', '5'})
                self.assertEqual(claimed.count(None), 5)

    def test_unattended_claims_only_fresh_discovered_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(core, 'DB', Path(folder) / 'agent.sqlite3'):
                with closing(core.connect()) as con:
                    con.executemany(
                        'INSERT INTO jobs(id, eligible, score, source, last_seen) VALUES (?, 1, ?, ?, ?)',
                        [
                            ('stale', 90, 'greenhouse', '2000-01-01'),
                            ('manual', 80, 'manual', '2000-01-03'),
                            ('fresh', 20, 'lever', '2000-01-03'),
                        ],
                    )
                    con.commit()
                    job = core.claim_preview(con, daily_limit=3, fresh_since='2000-01-02')
                    self.assertEqual(job['id'], 'fresh')
                    self.assertIsNone(core.claim_preview(con, daily_limit=3, fresh_since='2000-01-02'))
