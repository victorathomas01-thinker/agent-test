"""Offline, deterministic posting-deadline and source-freshness regression tests."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from agent import core, posting_freshness
from agent.submission import reserve_submission

BASE_DAY = date(2026, 11, 13)
POST_URL = "https://job-boards.greenhouse.io/example/jobs/123"
JOB_ID = "greenhouse:example:123"


def job(**fields):
    record = {
        "id": JOB_ID, "source": "greenhouse", "company": "Synthetic",
        "title": "IT Support Intern", "description": "",
        "location": "Charlotte, NC", "url": POST_URL,
        "last_seen": "2026-11-13T10:15:00+00:00",
    }
    record.update(fields)
    return record


class PostingFreshnessTests(unittest.TestCase):
    def test_only_absolute_unambiguous_days_are_parsed(self):
        cases = {
            "2026-10-26": date(2026, 10, 26),
            "2026-10-26T23:59:59Z": date(2026, 10, 26),
            "2026-10-26T23:59:59-04:00": date(2026, 10, 26),
            "October 26, 2026": date(2026, 10, 26),
            "Oct 26 2026": date(2026, 10, 26),
            "Nov. 5th, 2026": date(2026, 11, 5),
            "2026-02-30": None,
            "10/26/2026": None,
            "tomorrow": None,
            "26-10-2026": None,
            "": None,
            None: None,
        }
        for text, expected in cases.items():
            with self.subTest(value=text):
                self.assertEqual(posting_freshness.parse_day(text), expected)

    def test_explicit_posting_deadlines_and_ambiguous_different_dates(self):
        examples = (
            "Applications close October 26, 2026.",
            "Application deadline: Oct 26, 2026",
            "Apply by 2026-10-26.",
            "Posting closes on October 26, 2026.",
        )
        for text in examples:
            with self.subTest(text=text):
                result, ambiguous = posting_freshness.explicit_text_deadline(text)
                self.assertEqual(result, date(2026, 10, 26))
                self.assertFalse(ambiguous)
        none, _ = posting_freshness.explicit_text_deadline(
            "Graduation: October 26, 2026. Start Date: January 4, 2027."
        )
        self.assertIsNone(none)
        conflict = "Applications close November 3, 2026. Apply by November 12, 2026."
        self.assertEqual(posting_freshness.explicit_text_deadline(conflict), (None, True))

    def test_expired_deadline_is_not_marked_closed_until_after_one_day_grace(self):
        listing = job(description="Application deadline: November 11, 2026.")
        self.assertEqual(posting_freshness.risk_reasons(listing, today=date(2026, 11, 12)), [])
        flagged = posting_freshness.risk_reasons(listing, today=BASE_DAY)
        self.assertEqual(flagged, ["Explicit application deadline passed — verify employer posting"])
        future = job(deadline="2027-01-01")
        self.assertEqual(posting_freshness.risk_reasons(future, today=BASE_DAY), [])

    def test_stale_source_is_a_review_flag_not_closed_status(self):
        record = job(last_seen="2026-10-01T15:00:00Z")
        self.assertIn("Listing last observed over 14 days ago — recheck source",
                      posting_freshness.risk_reasons(record, today=BASE_DAY))
        self.assertEqual(posting_freshness.risk_reasons(
            job(last_seen="2026-11-01T10:00:00Z"), today=BASE_DAY), [])
        # Manual imports may not have ATS scan provenance.
        self.assertEqual(posting_freshness.risk_reasons(
            job(source="manual", last_seen="2025-01-01T00:00:00Z"), today=BASE_DAY), [])
        self.assertIsNone(posting_freshness.observation_day("unparseable"))

    def test_conflicting_metadata_does_not_confidently_mark_closed(self):
        listing = job(deadline="2026-10-01",
                      description="Applications close December 31, 2099.")
        reasons = posting_freshness.risk_reasons(listing, today=BASE_DAY)
        self.assertEqual(reasons, ["Conflicting explicit application deadlines — verify employer posting"])

    def test_explain_evaluator_finds_existing_explicit_deadline(self):
        cfg = core.with_defaults({})
        score, eligible, reason = core.evaluate(job(
            description="Application deadline: October 26, 2020."
        ), cfg)
        self.assertFalse(eligible)
        self.assertIn("Explicit application deadline passed", reason)
        score, eligible, reason = core.evaluate(job(
            last_seen="2020-01-01T00:00:00+00:00"
        ), cfg)
        self.assertFalse(eligible)
        self.assertIn("Listing last observed over 14 days ago", reason)

    def test_sqlite_eligibility_refresh_uses_web_check_deadline_column(self):
        cfg = core.with_defaults({})
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "agent.sqlite3"):
                with closing(core.connect()) as con:
                    with con:
                        con.execute(
                            """INSERT INTO jobs(id,source,company,title,location,url,
                               description,eligible,status,last_seen)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (JOB_ID, "greenhouse", "Synthetic", "IT Support Intern",
                             "Charlotte, NC", POST_URL, "Current role", 1, "found",
                             core.utc_now()),
                        )
                        con.execute(
                            "INSERT INTO web_checks(job_id,verification,deadline) VALUES (?,?,?)",
                            (JOB_ID, "api_listing", "2020-10-26"),
                        )
                    core.refresh_eligibility(con, cfg)
                    record = con.execute(
                        "SELECT eligible,reason,status FROM jobs WHERE id=?", (JOB_ID,)
                    ).fetchone()
                    self.assertEqual(record["eligible"], 0)
                    self.assertIn("Explicit application deadline passed", record["reason"])
                    self.assertEqual(record["status"], "found",
                                     "A warning must not invent a closed status.")
                    self.assertIsNone(core.claim_preview(con, 5))

    def test_attended_reservation_checks_current_deadline_and_status_again(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "agent.sqlite3"):
                with closing(core.connect()) as con:
                    with con:
                        con.execute(
                            """INSERT INTO jobs(id,source,title,url,eligible,status,last_seen)
                               VALUES(?,?,?,?,?,?,?)""",
                            (JOB_ID, "greenhouse", "IT Support Intern", POST_URL,
                             1, "found", core.utc_now()),
                        )
                        con.execute(
                            "INSERT INTO web_checks(job_id,verification,deadline) VALUES(?,?,?)",
                            (JOB_ID, "api_listing", "2020-01-01"),
                        )
                    candidate = dict(con.execute(
                        "SELECT * FROM jobs WHERE id=?", (JOB_ID,)
                    ).fetchone())
                    with self.assertRaisesRegex(ValueError, "re-verification"):
                        reserve_submission(con, candidate)
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)
                    with con:
                        con.execute("UPDATE web_checks SET deadline='' WHERE job_id=?", (JOB_ID,))
                        con.execute("UPDATE jobs SET status='expired' WHERE id=?", (JOB_ID,))
                    with self.assertRaisesRegex(ValueError, "closed or already tracked"):
                        reserve_submission(con, candidate)
                    with con:
                        con.execute("UPDATE jobs SET status='found', last_seen=NULL WHERE id=?", (JOB_ID,))
                    with self.assertRaisesRegex(ValueError, "no dated public-source"):
                        reserve_submission(con, candidate)
                    with con:
                        con.execute("UPDATE jobs SET last_seen=? WHERE id=?",
                                    (core.utc_now(), JOB_ID))
                    reserve_submission(con, candidate)
                    self.assertEqual(con.execute(
                        "SELECT status FROM jobs WHERE id=?", (JOB_ID,)).fetchone()[0],
                        "submission_pending")
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

    def test_readonly_aggregate_of_deadline_and_source_age(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "agent.sqlite3"):
                with closing(core.connect()) as con:
                    with con:
                        data = (
                            ("synthetic:1", "greenhouse", "Application deadline: October 20, 2026.",
                             "2026-11-12T12:00:00Z", "found"),
                            ("synthetic:2", "lever", "Some job opening",
                             "2026-10-01T12:00:00Z", "found"),
                            ("synthetic:3", "greenhouse",
                             "Apply by September 10, 2026. Applications close December 1, 2026.",
                             "2026-11-12T12:00:00Z", "found"),
                            ("synthetic:4", "greenhouse", "No explicit deadline", None, "found"),
                            ("synthetic:5", "greenhouse", "Application deadline: October 1, 2026.",
                             "2026-11-12T12:00:00Z", "submitted"),
                        )
                        con.executemany(
                            "INSERT INTO jobs(id,source,description,last_seen,status) VALUES(?,?,?,?,?)",
                            data)
                    report = posting_freshness.aggregate(con, today=BASE_DAY)
                    self.assertEqual(report, {
                        "active_or_unconfirmed": 4,
                        "passed_deadline": 1,
                        "stale_source": 1,
                        "conflicting_deadline": 1,
                        "missing_source_timestamp": 1,
                    })


if __name__ == "__main__":
    unittest.main()
