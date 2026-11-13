"""Synthetic, private-data-free offline preparation effort scoring."""
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agent import core, form_diagnostics, workbench


def preview(*reasons, outcome="needs_review"):
    return outcome, json.dumps({
        "mode": "dry-run", "filled": ["first_name", "email"],
        "unresolved": [{"field": "PRIVATE_LABEL", "required": True, "reason": x}
                       for x in reasons],
    })


class OfflineReadinessTests(unittest.TestCase):
    def test_no_preview_is_unassessed_not_zero(self):
        result = form_diagnostics.readiness_for_attempt(
            "needs_review", "Sign-in needed.")
        self.assertIsNone(result["score"])
        self.assertEqual(result["tier"], "not_assessed")
        self.assertIsNone(form_diagnostics.readiness_for_attempt(
            "needs_review", '{"mode":"dry-run","unresolved":[]}'
        )["score"])

    def test_prepared_current_step_only(self):
        outcome, detail = preview(outcome="prepared")
        result = form_diagnostics.readiness_for_attempt(outcome, detail)
        self.assertEqual((result["score"], result["tier"]),
                         (100, "current_step_clear"))

    def test_lighter_manual_review_is_prioritized(self):
        out, detail = preview("no verified answer",
                              "checkbox requires explicit applicant review")
        result = form_diagnostics.readiness_for_attempt(out, detail)
        self.assertEqual(result["score"], 76)
        self.assertEqual(result["tier"], "light_manual_review")
        self.assertEqual(result["manual_fields"], 2)

    def test_unknown_steps_and_identity_enforce_caps(self):
        out, detail = preview("preview covers the current step only")
        result = form_diagnostics.readiness_for_attempt(out, detail)
        self.assertLessEqual(result["score"], 40)
        out, detail = preview(
            "could not identify and fill applicant name or resume and email")
        result = form_diagnostics.readiness_for_attempt(out, detail)
        self.assertLessEqual(result["score"], 25)
        self.assertEqual(result["tier"], "major_blockers")

    def test_many_blockers_never_negative(self):
        out, detail = preview(*(["custom dropdown options unavailable offline"] * 10))
        result = form_diagnostics.readiness_for_attempt(out, detail)
        self.assertEqual(result["score"], 0)

    def test_latest_only_and_no_private_labels_in_dashboard_response(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(core, "DB", Path(directory) / "agent.sqlite3"):
                with closing(core.connect()) as con, con:
                    con.execute("""INSERT INTO jobs(id,title,source,status,score)
                        VALUES ('example','Fictional Intern','manual','found',60)""")
                    a, first = preview("no verified answer")
                    b, second = preview("preview covers the current step only")
                    con.executemany(
                        "INSERT INTO attempts(job_id,outcome,details) VALUES(?,?,?)",
                        [("example", a, first), ("example", b, second)],
                    )
                with closing(core.connect()) as con:
                    result = workbench.all_jobs(con, core.with_defaults({}))
                    summary = form_diagnostics.summarize(con)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["offline_readiness"]["tier"],
                                 "substantial_manual_review")
                self.assertEqual(summary["offline_readiness_tiers"],
                                 {"substantial_manual_review": 1})
                self.assertNotIn("PRIVATE_LABEL", repr(result))
                self.assertNotIn("PRIVATE_LABEL", repr(summary))


if __name__ == "__main__":
    unittest.main()
