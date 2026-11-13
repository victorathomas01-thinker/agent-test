"""Offline review-queue and token-guarded one-click recheck regression suite.

The synthetic local dashboard server never contacts a real employer: the
single-posting rechecker is patched and its invocation count is asserted.
"""
import http.client
import io
import json
import re
import tempfile
import threading
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import core, dashboard, workbench
from main import print_review_queue

ID = "lever:example:a1111111-2222-4333-8444-b55555555555"
URL = "https://jobs.lever.co/example/a1111111-2222-4333-8444-b55555555555/apply"


def insert_sample(con, *, selected=True):
    with con:
        con.execute(
            """INSERT INTO jobs(id,source,title,company,location,url,description,
                   eligible,score,reason,status,last_seen)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ID, "lever", "IT Support Intern", "Synthetic Company",
             "Charlotte, NC", URL, "Synthetic posting", 0, 60,
             "Listing last observed over 14 days ago — recheck source",
             "prepared", "2026-09-01T08:00:00+00:00"),
        )
        con.execute(
            "INSERT INTO web_checks(job_id,verification,deadline) VALUES(?,?,?)",
            (ID, "api_listing", ""),
        )
        if selected:
            con.execute(
                """INSERT INTO selections(job_id,status,updated_at,attempts,blocker,version)
                   VALUES(?,?,?,?,?,?)""",
                (ID, "needs_attention", "2026-10-01", 1,
                 "Review stale posting source", "synthetic"),
            )


class ReviewRecheckTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "synthetic.sqlite3"
        self.cfg = core.with_defaults({})
        self.patch_db = patch.object(core, "DB", self.db)
        self.patch_db.start()
        self.addCleanup(self.patch_db.stop)
        with closing(core.connect()) as con:
            insert_sample(con)

    def test_dashboard_model_shows_stale_ineligible_selected_job_and_button_capability(self):
        with closing(core.connect()) as con:
            rows = workbench.all_jobs(con, self.cfg)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["eligible"])
        self.assertEqual(rows[0]["recheck_status"], "needs_recheck")
        self.assertTrue(rows[0]["can_recheck"])
        self.assertIn("last observed", " ".join(rows[0]["recheck_reasons"]))
        # Do not expose application description in dashboard list results.
        self.assertNotIn("description", rows[0])

    def test_cli_review_queue_keeps_stale_prepared_job_after_ineligibility(self):
        with closing(core.connect()) as con:
            output = io.StringIO()
            with redirect_stdout(output):
                print_review_queue(con, 20, self.cfg)
        content = output.getvalue()
        self.assertIn(ID, content)
        self.assertIn("Source recheck needed:", content)
        self.assertIn(f"python main.py recheck-job {ID}", content)
        self.assertNotIn("No applications", content)

    def test_terminal_job_never_offers_recheck_even_if_old(self):
        with closing(core.connect()) as con, con:
            con.execute("UPDATE jobs SET status='submission_pending' WHERE id=?", (ID,))
            jobs = workbench.all_jobs(con, self.cfg)
            self.assertFalse(jobs[0]["can_recheck"])
            self.assertEqual(jobs[0]["recheck_status"], "not_applicable")
            output = io.StringIO()
            with redirect_stdout(output):
                print_review_queue(con, 20, self.cfg)
            self.assertIn("Verify the employer receipt", output.getvalue())
            self.assertNotIn("recheck-job", output.getvalue())

    def test_no_timestamp_source_requires_recheck_before_preparation(self):
        with closing(core.connect()) as con, con:
            con.execute("UPDATE jobs SET last_seen=NULL, status='found' WHERE id=?", (ID,))
            items = workbench.all_jobs(con, self.cfg)
            self.assertEqual(items[0]["recheck_status"], "needs_recheck")
            self.assertTrue(items[0]["can_recheck"])
            self.assertIn("Missing dated ATS observation",
                          " ".join(items[0]["recheck_reasons"]))

    def test_user_clicked_recheck_requires_valid_token_origin_and_only_one_call(self):
        with patch("agent.dashboard.local_safety.inspect",
                   return_value={"database": "ready", "config": "valid"}), \
             patch("agent.dashboard.official_recheck.recheck_saved",
                   return_value={"status": "verified_listed", "updated": True,
                                 "eligible_after_recheck": False}) as recheck:
            server, _ = dashboard.server_for(self.cfg, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_port

                def request(method, path, data=None, headers=None):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    connection.request(method, path, body=data, headers=headers or {})
                    response = connection.getresponse()
                    body = response.read()
                    connection.close()
                    return response.status, body

                status, homepage = request("GET", "/")
                self.assertEqual(status, 200)
                match = re.search(rb"const token = '([^']+)';", homepage)
                self.assertIsNotNone(match)
                token = match[1].decode("ascii")
                status, data = request("GET", "/api/jobs")
                self.assertEqual(status, 200)
                jobs = json.loads(data)
                self.assertEqual(jobs[0]["recheck_status"], "needs_recheck")
                self.assertTrue(jobs[0]["can_recheck"])
                recheck.assert_not_called()  # A dashboard view never contacts employers.

                body = json.dumps({"id": ID}).encode("utf-8")
                base = {"Content-Type": "application/json"}
                status, _ = request("POST", "/api/recheck", body, base)
                self.assertEqual(status, 403)
                status, _ = request("POST", "/api/recheck", body,
                                    {**base, "Origin": f"http://127.0.0.1:{port}",
                                     "X-Workbench-Token": "invalid"})
                self.assertEqual(status, 403)
                recheck.assert_not_called()

                headers = {**base, "Origin": f"http://127.0.0.1:{port}",
                           "X-Workbench-Token": token}
                status, result = request("POST", "/api/recheck", body, headers)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(result)["status"], "verified_listed")
                recheck.assert_called_once_with(ID, self.cfg)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=10)

    def test_dashboard_fails_closed_on_incompatible_local_preflight(self):
        with patch("agent.dashboard.local_safety.inspect",
                   return_value={"database": "incompatible", "config": "invalid"}), \
             patch("agent.dashboard.official_recheck.recheck_saved") as recheck:
            server, _ = dashboard.server_for(self.cfg, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_port
                def request(method, path, body=None, headers=None):
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(method, path, body, headers or {})
                    response = conn.getresponse()
                    payload = response.read()
                    conn.close()
                    return response.status, payload
                _, homepage = request("GET", "/")
                token = re.search(rb"const token = '([^']+)';", homepage)[1].decode()
                payload = json.dumps({"id": ID}).encode()
                status, response = request("POST", "/api/recheck", payload, {
                    "Origin": f"http://127.0.0.1:{port}",
                    "X-Workbench-Token": token,
                    "Content-Type": "application/json",
                })
                self.assertEqual(status, 409)
                self.assertNotIn(b"synthetic posting", response)
                recheck.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=10)


if __name__ == "__main__":
    unittest.main()
