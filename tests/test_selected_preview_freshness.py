"""Selected-preview freshness gate tests; synthetic data and no employer traffic."""
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent import core, workbench

JOB_ID = "greenhouse:synthetic:123"
URL = "https://job-boards.greenhouse.io/synthetic/jobs/123"


class SelectedPreviewFreshnessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "agent.sqlite3"
        self.patcher = patch.object(core, "DB", self.db)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        with closing(core.connect()) as con, con:
            con.execute(
                """INSERT INTO jobs
                (id,source,title,company,location,url,description,eligible,
                 status,last_seen,score) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (JOB_ID, "greenhouse", "IT Support Intern", "Synthetic",
                 "Charlotte", URL, "Synthetic public listing", 1, "found",
                 core.utc_now(), 80),
            )
            con.execute(
                """INSERT INTO selections(job_id,status,updated_at,attempts)
                VALUES (?,?,?,?)""", (JOB_ID, "queued", core.utc_now(), 0)
            )

    def _run_without_browser(self):
        with patch.object(workbench, "prepare_package") as package, \
             patch.object(workbench, "run_browser") as browser:
            workbench.prepare_selected(core.with_defaults({}))
            return package.call_count, browser.call_count

    def _state(self):
        with closing(core.connect()) as con:
            return con.execute(
                "SELECT status,blocker FROM selections WHERE job_id=?", (JOB_ID,)
            ).fetchone()

    def test_expired_metadata_deadline_blocks_package_even_if_cached_eligible(self):
        with closing(core.connect()) as con, con:
            con.execute(
                "INSERT INTO web_checks(job_id,verification,deadline) VALUES(?,'api_listing',?)",
                (JOB_ID, "2020-01-01"),
            )
        self.assertEqual(self._run_without_browser(), (0, 0))
        row = self._state()
        self.assertEqual(row["status"], "needs_attention")
        self.assertIn("deadline passed", row["blocker"])
        with closing(core.connect()) as con:
            self.assertEqual(con.execute(
                "SELECT eligible,status FROM jobs WHERE id=?", (JOB_ID,)
            ).fetchone()["status"], "found")

    def test_stale_source_blocks_package(self):
        with closing(core.connect()) as con, con:
            con.execute("UPDATE jobs SET last_seen='2020-01-01T00:00:00Z'")
        self.assertEqual(self._run_without_browser(), (0, 0))
        self.assertIn("last observed", self._state()["blocker"])

    def test_missing_source_timestamp_blocks_package(self):
        with closing(core.connect()) as con, con:
            con.execute("UPDATE jobs SET last_seen=NULL")
        self.assertEqual(self._run_without_browser(), (0, 0))
        self.assertIn("Missing dated source", self._state()["blocker"])

    def test_conflicting_deadlines_require_review(self):
        with closing(core.connect()) as con, con:
            con.execute(
                "UPDATE jobs SET description='Applications close December 31, 2099.'")
            con.execute(
                "INSERT INTO web_checks(job_id,verification,deadline) VALUES(?,'api_listing',?)",
                (JOB_ID, "2020-01-01"),
            )
        self.assertEqual(self._run_without_browser(), (0, 0))
        self.assertIn("Conflicting", self._state()["blocker"])

    def test_recent_verified_date_has_no_freshness_blocker(self):
        with closing(core.connect()) as con:
            job = con.execute("SELECT * FROM jobs WHERE id=?", (JOB_ID,)).fetchone()
            self.assertEqual(workbench.preview_freshness_blocker(con, job), "")


if __name__ == "__main__":
    unittest.main()
