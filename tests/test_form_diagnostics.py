"""All records are synthetic; no employee portals or browser execution."""
import io
import json
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import core, form_diagnostics


def review(*unresolved, outcome="needs_review"):
    return outcome, json.dumps({
        "mode": "dry-run", "filled": ["first_name", "email"],
        "unresolved": list(unresolved),
    })


def field(reason, required=True):
    return {"field": "PRIVATE_PERSONAL_FIELD_LABEL", "required": required, "reason": reason}


class FormDiagnosticsTests(unittest.TestCase):
    def test_latest_per_job_and_required_fields_only(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "agent.sqlite3"):
                with closing(core.connect()) as con, con:
                    attempts = [
                        ("job1", *review(field("no verified answer"))),
                        ("job2", *review(field("no verified answer", required=False), outcome="prepared")),
                        ("job3", "needs_review", "Sign-in needed."),
                        # Latest attempt for job1 supersedes its earlier record.
                        ("job1", *review(field("no unique matching dropdown option"),
                                         field("custom control requires manual input"))),
                    ]
                    con.executemany("INSERT INTO attempts(job_id,outcome,details) VALUES (?,?,?)",
                                    attempts)
                with closing(core.connect()) as con:
                    result = form_diagnostics.summarize(con)
                self.assertEqual(result["latest_jobs"], 3)
                self.assertEqual(result["dry_run_previews"], 2)
                self.assertEqual(result["prepared_current_step_only"], 1)
                self.assertEqual(result["required_blockers"]["dropdown_choice_ambiguous"], 1)
                self.assertEqual(result["required_blockers"]["unsupported_custom_control"], 1)
                self.assertEqual(result["required_blockers"]["login_required"], 1)
                self.assertNotIn("missing_verified_answer", result["required_blockers"])
                self.assertNotIn("PRIVATE_PERSONAL_FIELD_LABEL", repr(result))
                output = io.StringIO()
                with redirect_stdout(output):
                    form_diagnostics.print_report()
                self.assertIn("3 latest job attempts", output.getvalue())
                self.assertIn("NOT a verified live", output.getvalue())
                self.assertNotIn("PRIVATE_PERSONAL_FIELD_LABEL", output.getvalue())

    def test_multiple_required_fields_group_by_category_and_job(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "local.sqlite3"):
                with closing(core.connect()) as con, con:
                    con.execute("INSERT INTO attempts(job_id,outcome,details) VALUES (?,?,?)",
                                ("example", *review(field("no verified answer"),
                                                    field("no verified answer"))))
                with closing(core.connect()) as con:
                    data = form_diagnostics.summarize(con)
                self.assertEqual(data["required_blockers"]["missing_verified_answer"], 2)
                self.assertEqual(data["jobs_affected"]["missing_verified_answer"], 1)

    def test_no_attempts_and_invalid_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "local.sqlite3"):
                with closing(core.connect()) as con:
                    self.assertEqual(form_diagnostics.summarize(con)["latest_jobs"], 0)
                    with self.assertRaisesRegex(ValueError, "Invalid"):
                        form_diagnostics.latest_reviews(con, 0)

    def test_expired_signin_and_errors_are_distinct_from_complete_previews(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "local.sqlite3"):
                with closing(core.connect()) as con, con:
                    con.executemany("INSERT INTO attempts(job_id,outcome,details) VALUES (?,?,?)", [
                        ("a", "expired", "The posting returned HTTP 404 or 410."),
                        ("b", "failed", "Browser preview failed (TimeoutError)."),
                        ("c", "needs_review", "Application page was unavailable."),
                    ])
                with closing(core.connect()) as con:
                    result = form_diagnostics.summarize(con)
                self.assertEqual(result["dry_run_previews"], 0)
                self.assertEqual(result["required_blockers"]["posting_unavailable"], 1)
                self.assertEqual(result["required_blockers"]["browser_preview_error"], 1)
                self.assertEqual(result["required_blockers"]["page_unavailable"], 1)


if __name__ == "__main__":
    unittest.main()
