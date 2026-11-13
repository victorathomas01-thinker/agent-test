"""Synthetic-only tests for historical pilot auditing: no applicant database."""
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from agent import pilot_audit
from agent.requirement_benchmark import evaluate_cases, load_cases


def fixture(path):
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript("""
          CREATE TABLE jobs (id TEXT PRIMARY KEY, source TEXT, company TEXT);
          CREATE TABLE attempts (id INTEGER PRIMARY KEY AUTOINCREMENT,
             job_id TEXT, at TEXT, outcome TEXT, details TEXT);
          CREATE TABLE verified_facts (key TEXT, value TEXT);
        """)
        con.executemany("INSERT INTO jobs VALUES (?,?,?)", [
            ("greenhouse:private:1", "greenhouse", "PRIVATE_COMPANY"),
            ("lever:private:2", "lever", "PRIVATE_COMPANY"),
        ])
        con.execute("INSERT INTO verified_facts VALUES ('email','PRIVATE_EMAIL')")
        data = [
            ("greenhouse:private:1", "2026-10-01T00:00:00+00:00",
             "needs_review", json.dumps({"mode": "dry-run", "unresolved": [
                 {"field": "PRIVATE_OLD_LABEL", "required": True, "reason": "no verified answer"}
             ], "filled": ["PRIVATE_EMAIL"]})),
            ("greenhouse:private:1", "2026-11-12T11:00:00+00:00",
             "needs_review", json.dumps({"mode": "dry-run", "unresolved": [
                 {"field": "PRIVATE_QUESTION", "required": True,
                  "reason": "checkbox requires explicit applicant review"},
                 {"field": "PRIVATE_SECOND", "required": True,
                  "reason": "no unique matching dropdown option"},
             ], "filled": ["PRIVATE_EMAIL"]})),
            ("lever:private:2", "2026-11-12T12:00:00+00:00",
             "prepared", json.dumps({"mode": "dry-run", "unresolved": [
                 {"field": "PRIVATE_OPTIONAL", "required": False,
                  "reason": "no verified answer"}
             ], "filled": ["PRIVATE_EMAIL"]})),
            ("lever:private:2", "2026-11-13T12:00:00+00:00",
             "needs_review", "Sign-in needed."),
        ]
        con.executemany(
            "INSERT INTO attempts(job_id,at,outcome,details) VALUES (?,?,?,?)", data)


class PilotAuditTests(unittest.TestCase):
    def test_scoped_history_from_readonly_db_and_no_leaks(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "agent.sqlite3"
            fixture(db)
            before = db.read_bytes()
            with closing(pilot_audit.open_readonly(db)) as con:
                rows = pilot_audit.selected_attempts(
                    con, since="2026-11-12", through="2026-11-12", limit=20)
                summary = pilot_audit.summarize(rows, expected=20)
            self.assertEqual(db.read_bytes(), before)
            self.assertEqual(summary["sampled_unique_jobs"], 2)
            self.assertFalse(summary["matches_expected_count_only"])
            self.assertEqual(summary["dry_run_previews"], 2)
            self.assertEqual(summary["offline_current_step_prepared"], 1)
            self.assertEqual(summary["offline_previews_with_required_blockers"], 1)
            self.assertEqual(summary["required_field_counts"]["checkbox_attestation_or_choice"], 1)
            self.assertEqual(summary["required_field_counts"]["dropdown_choice_ambiguous"], 1)
            self.assertEqual(summary["providers"], {"greenhouse": 1, "lever": 1})
            self.assertNotIn("PRIVATE_", repr(summary))
            output = io.StringIO()
            with redirect_stdout(output):
                pilot_audit.render(summary, "2026-11-12", "2026-11-12")
            for private in ("PRIVATE_COMPANY", "PRIVATE_EMAIL", "PRIVATE_QUESTION",
                            "greenhouse:private:1"):
                self.assertNotIn(private, output.getvalue())
            self.assertIn("different count", output.getvalue())

    def test_historical_window_not_replaced_by_later_login_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "pilot.sqlite3"
            fixture(db)
            with closing(pilot_audit.open_readonly(db)) as con:
                rows = pilot_audit.selected_attempts(
                    con, since="2026-11-13", through="2026-11-13", limit=20)
                report = pilot_audit.summarize(rows)
            self.assertEqual(report["sampled_unique_jobs"], 1)
            self.assertEqual(report["dry_run_previews"], 0)
            self.assertEqual(report["nonjson_failure_categories"], {"login_required": 1})

    def test_unscoped_sample_is_not_automatically_the_prior_pilot(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "pilot.sqlite3"
            fixture(db)
            with closing(pilot_audit.open_readonly(db)) as con:
                rows = pilot_audit.selected_attempts(con, limit=1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["outcome"], "needs_review")

    def test_missing_or_wrong_db_fails_without_creating_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.sqlite3"
            with self.assertRaises(FileNotFoundError):
                pilot_audit.open_readonly(path)
            self.assertFalse(path.exists())
            with closing(sqlite3.connect(path)) as con, con:
                con.execute("CREATE TABLE other(value TEXT)")
            with self.assertRaisesRegex(ValueError, "required local agent tables"):
                pilot_audit.open_readonly(path)

    def test_reject_ambiguous_windows_and_unreasonable_limits(self):
        for value in ("not-a-date", "2026-02-30", "11/12/2026"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pilot_audit.parse_day(value)
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "pilot.sqlite3"
            fixture(db)
            with closing(pilot_audit.open_readonly(db)) as con:
                with self.assertRaisesRegex(ValueError, "first audit date"):
                    pilot_audit.selected_attempts(con, "2026-11-13", "2026-11-12")
                with self.assertRaisesRegex(ValueError, "between 1 and 1000"):
                    pilot_audit.selected_attempts(con, limit=0)

    def test_public_requirement_fixtures_have_annotated_categories(self):
        cases = load_cases()
        report = evaluate_cases(cases)
        self.assertGreaterEqual(report["cases"], 25)
        self.assertGreaterEqual(report["unique_source_postings"], 8)
        self.assertEqual(report["mismatched_cases"], [], report)
        self.assertEqual(report["matches"], report["cases"])


if __name__ == "__main__":
    unittest.main()
