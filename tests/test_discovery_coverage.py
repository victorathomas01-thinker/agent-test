"""All test postings are synthetic; no requests to actual employers."""
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import core, source_health
from agent.careers import discover_sites


def sample_smart_detail(i):
    return {"name": f"IT Support Intern {i}",
            "postingUrl": f"https://jobs.smartrecruiters.com/Example/{i}-support",
            "location": {"city": "Charlotte", "region": "NC"}}


class DiscoveryCoverageTests(unittest.TestCase):
    def test_smartrecruiters_pages_through_full_public_result(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if "offset=0" in url:
                return {"totalFound": 3, "content": [{"id": "100"}, {"id": "101"}]}
            if "offset=2" in url:
                return {"totalFound": 3, "content": [{"id": "102"}]}
            return sample_smart_detail(url.rsplit("/", 1)[-1])
        with patch.object(core, "http_json", side_effect=fetch):
            complete, audit = [], {}
            rows = core.fetch_board("smartrecruiters", "Example", "Example", 2, coverage=complete, audit=audit)
        self.assertEqual(len(rows), 2)
        self.assertFalse(audit["complete"], "An intentional cap must not imply the board is complete.")
        self.assertFalse(complete)
        self.assertIn("limit=2", calls[0])

        calls.clear()
        def fetch_all(url):
            calls.append(url)
            if "offset=0" in url:
                return {"totalFound": 3, "content": [{"id": "100"}, {"id": "101"}]}
            if "offset=2" in url:
                return {"totalFound": 3, "content": [{"id": "102"}]}
            return sample_smart_detail(url.rsplit("/", 1)[-1])
        with patch.object(core, "http_json", side_effect=fetch_all):
            complete, audit = [], {}
            rows = core.fetch_board("smartrecruiters", "Example", "Example", 2, coverage=complete, audit=audit)
            self.assertEqual(len(rows), 2)
            rows = core.fetch_board("smartrecruiters", "Example", "Example", 3, coverage=complete, audit=audit)
        # When the total equals the cap and its only request supplies every row,
        # API's explicit totalFound (not len == cap) establishes completeness.
        self.assertEqual(len(rows), 2)
        self.assertFalse(audit["complete"])
        self.assertNotIn(("smartrecruiters", "Example"), complete)

    def test_smartrecruiters_multi_page_with_explicit_total(self):
        def fetch(url):
            if "offset=0" in url:
                return {"totalFound": 3, "content": [{"id": "100"}, {"id": "101"}]}
            if "offset=2" in url:
                return {"totalFound": 3, "content": [{"id": "102"}]}
            return sample_smart_detail(url.rsplit("/", 1)[-1])
        # Production pages request up to 100; use 102 synthetic postings
        # to exercise the actual offset progression.
        def big_fetch(url):
            if "offset=0" in url:
                return {"totalFound": 102, "content": [{"id": str(i)} for i in range(100, 200)]}
            if "offset=100" in url:
                return {"totalFound": 102, "content": [{"id": "200"}, {"id": "201"}]}
            return sample_smart_detail(url.rsplit("/", 1)[-1])
        with patch.object(core, "http_json", side_effect=big_fetch):
            covered, audit = [], {}
            rows = core.fetch_board("smartrecruiters", "Example", "Example", 150,
                                    coverage=covered, audit=audit)
        self.assertEqual(len(rows), 102)
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["total"], 102)
        self.assertEqual(covered, [("smartrecruiters", "Example")])

    def test_smartrecruiters_partial_detail_failure_preserves_old_jobs(self):
        def fetch(url):
            if "?offset=" in url:
                return {"totalFound": 2, "content": [{"id": "100"}, {"id": "101"}]}
            if url.endswith("/101"):
                raise OSError("synthetic transient failure")
            return sample_smart_detail("100")
        with patch.object(core, "http_json", side_effect=fetch):
            covered, audit = [], {}
            rows = core.fetch_board("smartrecruiters", "Example", "Example", 10,
                                    coverage=covered, audit=audit)
        self.assertEqual(len(rows), 1)
        self.assertFalse(audit["complete"])
        self.assertEqual(covered, [])

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(core, "DB", Path(folder) / "local.sqlite3"):
                with closing(core.connect()) as con, con:
                    con.execute("""INSERT INTO jobs(id,status,last_seen)
                                    VALUES ('smartrecruiters:Example:999','found','2025-01-01')""")
                self.assertEqual(core.expire_unlisted(covered, rows, "2026-11-12"), 0)
                with closing(core.connect()) as con:
                    self.assertEqual(con.execute("""SELECT status FROM jobs WHERE id=
                        'smartrecruiters:Example:999'""").fetchone()[0], "found")

    def test_unknown_total_never_certifies_smartrecruiters_completeness(self):
        def fetch(url):
            if "?offset=" in url:
                return {"content": [{"id": "100"}]}
            return sample_smart_detail("100")
        with patch.object(core, "http_json", side_effect=fetch):
            covered, audit = [], {}
            rows = core.fetch_board("smartrecruiters", "Example", "Example", 20,
                                    coverage=covered, audit=audit)
        self.assertEqual(len(rows), 1)
        self.assertFalse(audit["complete"])
        self.assertFalse(covered)

    def test_greenhouse_bad_url_and_cap_are_partial_not_complete(self):
        site = "https://job-boards.greenhouse.io/example/jobs/"
        good = {"id": 101, "absolute_url": site + "101"}
        foreign = {"id": 102, "absolute_url": "https://example.invalid/jobs/102"}
        with patch.object(core, "http_json", return_value={"jobs": [good, foreign]}):
            covered, audit = [], {}
            rows = core.fetch_board("greenhouse", "example", "Example", 10,
                                    coverage=covered, audit=audit)
        self.assertEqual([row["id"] for row in rows], ["greenhouse:example:101"])
        self.assertFalse(audit["complete"])
        self.assertFalse(covered)
        with patch.object(core, "http_json", return_value={"jobs": [good, good]}):
            covered, audit = [], {}
            core.fetch_board("greenhouse", "example", "Example", 1,
                             coverage=covered, audit=audit)
        self.assertFalse(audit["complete"])
        self.assertFalse(covered)

    def test_collector_coverage_tracks_feed_and_board_errors(self):
        cfg = core.with_defaults({"discovery": {
            "greenhouse_boards": ["example"], "lever_sites": [],
            "ashby_boards": [], "smartrecruiters_companies": [],
            "employer_feeds": ["https://example.invalid/feed.json"],
            "max_discovered_boards": 5, "max_per_source": 10,
        }})
        def fetch(url):
            if url.endswith("feed.json"):
                raise OSError("synthetic feed timeout")
            return {"jobs": [{"id": 100,
                              "absolute_url": "https://job-boards.greenhouse.io/example/jobs/100"}]}
        with patch.object(core, "http_json", side_effect=fetch):
            complete, checks = [], []
            jobs, errors = core.discover(cfg, complete, checks)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(checks), 2)
        self.assertEqual(sorted(c["status"] for c in checks), ["complete", "error"])
        self.assertTrue(checks[0]["key"].startswith("feed:"))
        self.assertNotIn("example.invalid/feed", str(checks))
        self.assertEqual(complete, [("greenhouse", "example")])

    def test_bounded_company_site_remains_partial(self):
        seeds = [{"company": "Synthetic", "url": "https://example.invalid/careers"}]
        posts = [{"id": "careers:synthetic1", "verification": "structured"}]
        with patch("agent.careers.crawl_careers", return_value=posts):
            checks = []
            jobs, errors = discover_sites(seeds, 2, core.plain, report=checks)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(errors, [])
        self.assertEqual(checks[0]["status"], "partial")
        self.assertIn("bounded_crawl", checks[0]["detail"])
        self.assertNotIn("https", str(checks))

    def test_source_ledger_is_local_and_does_not_contain_application_details(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(core, "DB", Path(folder) / "db.sqlite3"):
                checks = [
                    source_health.check("ats", "greenhouse:example", "complete", 3),
                    source_health.check("feed", "feed:abcdef", "error", 0, "OSError"),
                ]
                id_ = source_health.record(checks, "2026-11-12T13:00:00+00:00")
                self.assertEqual(id_, 1)
                run, rows = source_health.latest()
                self.assertEqual(run["source_count"], 2)
                self.assertEqual(len(rows), 2)
                with closing(core.connect()) as con:
                    query = con.execute("SELECT * FROM discovery_coverage_checks").fetchall()
                self.assertEqual(len(query), 2)
                output = io.StringIO()
                with redirect_stdout(output):
                    source_health.print_latest()
                self.assertIn("error=1", output.getvalue())
                self.assertIn("complete=1", output.getvalue())

    def test_invalid_status_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            source_health.check("ats", "sample", "all_jobs_on_earth", 5)


if __name__ == "__main__":
    unittest.main()
