"""Synthetic checks of the live probe's reporting and budgets.

These tests do not access any employer network or user-specific files.
"""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import probe_public_workday as probe


class PublicSourceProbeTests(unittest.TestCase):
    def test_bounded_report_has_no_listing_content_or_urls(self):
        def fake_reader(url, company, maximum, audit):
            self.assertEqual(maximum, 2)
            audit.update(complete=False, reason="partial_mock")
            return [{"verification": "structured",
                     "description": "SECRET_RESUME_NEVER_LOGGED",
                     "url": url + "/job/synthetic"}]

        rows = probe.probe(
            [{"company": "Example", "url": "https://example.wd5.myworkdayjobs.com/External"}],
            2, read=fake_reader)
        self.assertEqual(rows, [{
            "company": "Example", "status": "partial", "records": 1,
            "verified": 1, "reason": "partial_mock",
        }])
        self.assertNotIn("SECRET", str(rows))
        self.assertNotIn("https://", str(rows))

    def test_official_roots_are_required_before_probe(self):
        from agent.workday import select_workday_sources
        with self.assertRaises(ValueError):
            select_workday_sources(
                [{"company": "Bad", "url": "https://127.0.0.1/External"}], 1)

    def test_blocked_and_transient_errors_are_not_called_successes(self):
        def blocked_reader(url, company, maximum, audit):
            raise PermissionError("synthetic_disallowed")
        rows = probe.probe(
            [{"company": "Example", "url": "https://example.wd5.myworkdayjobs.com/External"}],
            1, read=blocked_reader)
        self.assertEqual(rows[0]["status"], "blocked")
        self.assertEqual(rows[0]["verified"], 0)
        self.assertEqual(rows[0]["reason"], "unknown:PermissionError")

    def test_reject_unsafe_or_excessive_probe_budgets(self):
        for argv in (["--max-sites", "50"], ["--per-site", "10"],
                     ["--per-site", "0"], ["--max-sites", "0"]):
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as exit_:
                    probe.main(argv)
                self.assertEqual(exit_.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
