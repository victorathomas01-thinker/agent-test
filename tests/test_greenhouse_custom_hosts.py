"""Synthetic tests for explicitly approved company-hosted Greenhouse links."""
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent import core
from agent.submission import official_job_url


class GreenhouseCustomHostTests(unittest.TestCase):
    URL = "https://careers.duolingo.com/jobs/8503886002?gh_jid=8503886002"

    def test_only_approved_company_host_same_posting_id(self):
        cases = [
            (self.URL, True),
            ("https://careers.duolingo.com/jobs/8503886002", True),
            ("https://careers.duolingo.com/jobs/8503886002/?gh_jid=8503886002", True),
            ("https://careers.duolingo.com.evil.test/jobs/8503886002", False),
            ("https://careers.duolingo.com@evil.test/jobs/8503886002", False),
            ("https://evil@careers.duolingo.com/jobs/8503886002", False),
            ("http://careers.duolingo.com/jobs/8503886002", False),
            ("https://careers.duolingo.com/jobs/8503886003", False),
            ("https://careers.duolingo.com/jobs/8503886002?gh_jid=8503886003", False),
            ("https://careers.duolingo.com/jobs/8503886002?gh_jid=8503886002&gh_jid=9", False),
            ("https://careers.duolingo.com:8443/jobs/8503886002", False),
            ("https://careers.duolingo.com/jobs/8503886002/../../invalid", False),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(core.approved_greenhouse_hosted_url(
                    url, 8503886002, ["careers.duolingo.com"]), expected)
        self.assertFalse(core.approved_greenhouse_hosted_url(self.URL, 8503886002, None))
        self.assertFalse(core.approved_greenhouse_hosted_url(self.URL, "not-a-job-id",
                                                             ["careers.duolingo.com"]))

    def test_official_board_read_accepts_only_configured_host_and_preserves_no_submission(self):
        data = {"jobs": [
            {"id": 8503886002, "title": "Synthetic QA Intern", "absolute_url": self.URL,
             "location": {"name": "Pittsburgh"}, "content": "<p>Testing APIs</p>"},
        ]}
        with patch.object(core, "http_json", return_value=data):
            covered, audit = [], {}
            rows = core.fetch_board("greenhouse", "duolingo", "Duolingo", 10,
                                    coverage=covered, audit=audit,
                                    approved_custom_hosts=["careers.duolingo.com"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], "greenhouse:duolingo:8503886002")
            self.assertEqual(rows[0]["verification"], "api_listing")
            self.assertTrue(audit["complete"])
            self.assertEqual(covered, [("greenhouse", "duolingo")])
            self.assertFalse(official_job_url(rows[0]),
                             "Custom-domain URLs cannot enter the attended submission flow.")

        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "agent.sqlite3"):
                core.store_jobs(rows, core.with_defaults({}))
                with closing(core.connect()) as con:
                    job = con.execute("SELECT * FROM jobs WHERE id=?", (rows[0]["id"],)).fetchone()
                    check = con.execute("SELECT verification FROM web_checks WHERE job_id=?",
                                        (rows[0]["id"],)).fetchone()
                    self.assertIsNotNone(job)
                    self.assertEqual(check[0], "api_listing")
                    self.assertIn("careers.duolingo.com", job["url"])

    def test_unsafe_and_unapproved_hosts_cannot_make_a_complete_scan(self):
        rows = [
            {"id": 200, "title": "Safe", "absolute_url": "https://careers.duolingo.com/jobs/200"},
            {"id": 201, "title": "Unapproved", "absolute_url": "https://other.example/jobs/201"},
            {"id": 202, "title": "ID mismatch",
             "absolute_url": "https://careers.duolingo.com/jobs/999?gh_jid=999"},
        ]
        with patch.object(core, "http_json", return_value={"jobs": rows}):
            covered, audit = [], {}
            accepted = core.fetch_board("greenhouse", "duolingo", "Duolingo", 10,
                                        coverage=covered, audit=audit,
                                        approved_custom_hosts=["careers.duolingo.com"])
        self.assertEqual([row["id"] for row in accepted], ["greenhouse:duolingo:200"])
        self.assertFalse(audit["complete"])
        self.assertEqual(covered, [])

    def test_default_allowlist_is_narrow_and_contains_no_untrusted_wildcards(self):
        defaults = core.with_defaults({})["discovery"]["greenhouse_custom_hosts"]
        self.assertEqual(defaults, {"duolingo": ["careers.duolingo.com"]})
        self.assertNotIn("*", str(defaults))


if __name__ == "__main__":
    unittest.main()
