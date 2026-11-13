"""All records are synthetic; no employee portals or browser execution."""
import io
import json
import tempfile
import unittest
from threading import Thread
from urllib.request import urlopen
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

    def test_actionable_form_blocker_remediation_uses_only_fixed_safe_text(self):
        from agent.form_diagnostics import BLOCKER_ACTIONS
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "local.sqlite3"):
                with closing(core.connect()) as con, con:
                    con.executemany(
                        "INSERT INTO attempts(job_id,outcome,details) VALUES(?,?,?)", [
                            ("a", *review(field("checkbox requires explicit applicant review"))),
                            ("b", *review(field("custom control requires manual input"))),
                        ])
                with closing(core.connect()) as con:
                    report = form_diagnostics.summarize(con)
                actions = report["recommended_next_actions"]
                self.assertEqual(
                    actions["checkbox_attestation_or_choice"],
                    BLOCKER_ACTIONS["checkbox_attestation_or_choice"])
                self.assertIn("Applicant must review", actions["checkbox_attestation_or_choice"])
                self.assertIn("manual review", actions["unsupported_custom_control"])
                self.assertNotIn("PRIVATE_PERSONAL_FIELD_LABEL", repr(report))
                self.assertNotIn("applicant@example.invalid", repr(report))
                self.assertEqual(set(actions), set(report["required_blockers"]))

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

    def test_dashboard_aggregate_endpoint_is_readonly_and_does_not_expose_labels(self):
        from agent.dashboard import server_for
        cfg = core.with_defaults({})
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(core, "DB", Path(temp) / "local.sqlite3"):
                with closing(core.connect()) as con, con:
                    con.execute("INSERT INTO attempts(job_id,outcome,details) VALUES (?,?,?)",
                                ("sample", *review(field("no verified answer"))))
                server, _ = server_for(cfg, 0)
                with server:
                    worker = Thread(target=server.serve_forever, daemon=True)
                    worker.start()
                    try:
                        with urlopen(f"http://127.0.0.1:{server.server_port}/api/form-audit",
                                     timeout=5) as response:
                            payload = json.load(response)
                        self.assertEqual(payload["required_blockers"]["missing_verified_answer"], 1)
                        self.assertNotIn("PRIVATE_PERSONAL_FIELD_LABEL", str(payload))
                        with urlopen(f"http://127.0.0.1:{server.server_port}/",
                                     timeout=5) as response:
                            page = response.read().decode("utf-8")
                        self.assertIn("Form Readiness", page)
                    finally:
                        server.shutdown()
                        worker.join(timeout=5)

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
