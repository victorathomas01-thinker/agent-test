"""Synthetic-only public Workday discovery and URL security tests."""
import json
import unittest
from unittest.mock import patch

from agent import core
from agent.workday import parse_board, read_workday_jobs, safe_external_path

BOARD = "https://example.wd5.myworkdayjobs.com/en-US/External"
JOB = "/job/Charlotte-NC/IT-Support_JR100"


def detail_for(external):
    return {"jobPostingInfo": {
        "title": "IT Support Intern",
        "jobDescription": "<p>Help desk and Python</p>",
        "location": "Charlotte, NC",
        "startDate": "2026-11-10",
        "timeType": "Part time",
    }}


class WorkdayPublicAdapterTests(unittest.TestCase):
    def test_only_configured_official_workday_roots(self):
        board = parse_board(BOARD)
        self.assertEqual(board.tenant, "example")
        self.assertEqual(board.site, "External")
        self.assertEqual(board.locale, "en-US")
        self.assertEqual(board.api, "https://example.wd5.myworkdayjobs.com/wday/cxs/example/External")
        self.assertEqual(parse_board("https://example.wd5.myworkdayjobs.com/External").site, "External")
        for bad in (
            "http://example.wd5.myworkdayjobs.com/External",
            "https://example.wd5.myworkdayjobs.com.evil.test/External",
            "https://bad@example.wd5.myworkdayjobs.com/External",
            "https://example.wd5.myworkdayjobs.com:8443/External",
            "https://example.wd5.myworkdayjobs.com/en-US/External/job/foo",
            "https://example.wd5.myworkdayjobs.com/en-US/External?token=secret",
            "https://127.0.0.1/External",
            "https://example.myworkdayjobs.com/External",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_board(bad)

    def test_external_paths_are_same_board_only(self):
        self.assertEqual(safe_external_path(JOB), JOB)
        for bad in (
            "https://evil.invalid/job/foo", "//evil.invalid/job/foo",
            "/job/../secrets", "/job/%2e%2e/secrets",
            "/job/%2Fredirect", "/job/demo?email=test",
            "/wday/cxs/example/External", "/job/a#frag",
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(safe_external_path(bad))

    def test_public_pagination_and_detail_validation(self):
        visited = []
        def fetch(method, url, payload, board):
            visited.append((method, url, payload))
            if method == "POST":
                offset = payload["offset"]
                if offset == 0:
                    return {"total": 21, "jobPostings": [
                        {"title": "IT Support Intern", "locationsText": "Charlotte, NC",
                         "externalPath": f"/job/Charlotte/Tech_JR{i:03d}"} for i in range(20)
                    ]}
                return {"total": 0, "jobPostings": [
                    {"title": "IT Support Intern", "locationsText": "Charlotte, NC",
                     "externalPath": "/job/Charlotte/Tech_JR020"}
                ]}
            return detail_for(url)

        audit = {}
        rows = read_workday_jobs(BOARD, "Example", 40, fetch_json=fetch,
                                 fetch_robots=lambda b: "User-agent: *\nAllow: /",
                                 pause=lambda _: None, audit=audit)
        self.assertEqual(len(rows), 21)
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["total"], 21)
        self.assertEqual(len({row["id"] for row in rows}), 21)
        self.assertTrue(all(row["verification"] == "structured" for row in rows))
        self.assertTrue(all(row["url"].startswith(BOARD + "/job/") for row in rows))
        self.assertEqual(rows[0]["published_at"], "2026-11-10")
        calls = [x for x in visited if x[0] == "POST"]
        self.assertEqual([call[2]["offset"] for call in calls], [0, 20])
        self.assertTrue(all(call[2]["limit"] == 20 for call in calls))
        self.assertTrue(all(set(call[2]) == {"appliedFacets", "limit", "offset", "searchText"} for call in calls))
        self.assertNotIn("email", str(visited).lower())

    def test_cap_never_proves_complete_board(self):
        def fetch(method, url, data, board):
            if method == "POST":
                return {"total": 35, "jobPostings": [
                    {"title": "Analyst", "externalPath": f"/job/Charlotte/Analyst_JR{i}"}
                    for i in range(20)
                ]}
            return detail_for(url)

        audit = {}
        rows = read_workday_jobs(BOARD, "Example", 10, fetch_json=fetch,
                                 fetch_robots=lambda b: "User-agent: *\nAllow: /",
                                 pause=lambda _: None, audit=audit)
        self.assertEqual(len(rows), 10)
        self.assertFalse(audit["complete"])
        self.assertEqual(audit["total"], 35)

    def test_robots_block_prevents_any_json_requests(self):
        visited = []
        audit = {}
        rows = read_workday_jobs(
            BOARD, "Example", 10, fetch_json=lambda *a: visited.append(a),
            fetch_robots=lambda b: "User-agent: *\nDisallow: /wday/cxs/",
            pause=lambda _: None, audit=audit,
        )
        self.assertEqual(rows, [])
        self.assertEqual(visited, [])
        self.assertTrue(audit["blocked"])
        self.assertFalse(audit["complete"])

    def test_detail_fetch_failure_preserves_unverified_listing(self):
        def fetch(method, url, payload, board):
            if method == "POST":
                return {"total": 1, "jobPostings": [
                    {"title": "Software Engineer Intern", "locationsText": "Charlotte, NC",
                     "externalPath": JOB}
                ]}
            raise OSError("synthetic detail timeout")

        audit = {}
        rows = read_workday_jobs(BOARD, "Example", 10, fetch_json=fetch,
                                 fetch_robots=lambda b: "User-agent: *\nAllow: /",
                                 pause=lambda _: None, audit=audit)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verification"], "unverified")
        self.assertFalse(audit["complete"])
        cfg = core.with_defaults({})
        score, eligible, why = core.evaluate(rows[0], cfg)
        self.assertFalse(eligible)
        self.assertIn("could not be verified", why)

    def test_duplicate_job_paths_and_missing_total_remain_partial(self):
        def fetch(method, url, payload, board):
            if method == "POST":
                return {"jobPostings": [
                    {"title": "Support Analyst", "externalPath": JOB},
                    {"title": "Support Analyst", "externalPath": JOB},
                ]}
            return detail_for(url)
        audit = {}
        rows = read_workday_jobs(BOARD, "Example", 10, fetch_json=fetch,
                                 fetch_robots=lambda b: "User-agent: *\nAllow: /",
                                 pause=lambda _: None, audit=audit)
        self.assertEqual(len(rows), 1)
        self.assertFalse(audit["complete"])

    def test_opt_in_configuration_and_private_source_label(self):
        cfg = core.with_defaults({"discovery": {
            "greenhouse_boards": [], "lever_sites": [], "ashby_boards": [],
            "smartrecruiters_companies": [], "employer_feeds": [],
            "workday_sites": [{"company": "Example Hospital", "url": BOARD}],
            "max_workday_per_site": 10,
        }})
        def mocked(url, company, maximum, audit=None):
            self.assertEqual(url, BOARD)
            self.assertEqual(maximum, 10)
            audit.update(complete=False, blocked=False, reason="bounded_or_incomplete_cxs")
            return [{"id": "workday:synthetic", "source": "workday",
                     "company": company, "title": "IT Support Intern",
                     "location": "Charlotte", "url": BOARD + JOB,
                     "description": "", "verification": "unverified"}]

        with patch.object(core, "read_workday_jobs", side_effect=mocked):
            covered, checks = [], []
            jobs, errors = core.discover(cfg, covered, checks)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(errors, [])
        self.assertEqual(covered, [], "Experimental Workday source cannot expire old records.")
        self.assertEqual(checks[0]["status"], "partial")
        self.assertTrue(checks[0]["key"].startswith("workday:example-hospital:"))
        self.assertNotIn("https", str(checks))

    def test_unavailable_source_is_logged_not_the_user_career_url(self):
        cfg = core.with_defaults({"discovery": {
            "greenhouse_boards": [], "lever_sites": [], "ashby_boards": [],
            "smartrecruiters_companies": [], "employer_feeds": [],
            "workday_sites": [{"company": "Example Hospital", "url": BOARD}],
        }})
        with patch.object(core, "read_workday_jobs", side_effect=PermissionError("robots restricted")):
            jobs, errors = core.discover(cfg, source_checks := [], source_checks2 := [])
        self.assertEqual(jobs, [])
        self.assertEqual(len(errors), 1)
        self.assertNotIn(BOARD, errors[0])
        self.assertEqual(source_checks2[0]["status"], "blocked")

    def test_configured_only_not_in_default_company_scan(self):
        cfg = core.with_defaults({})
        self.assertEqual(cfg["discovery"]["workday_sites"], [])


if __name__ == "__main__":
    unittest.main()
