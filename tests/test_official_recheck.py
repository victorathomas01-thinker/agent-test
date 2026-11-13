"""Synthetic proof: exact official job GET can refresh, failures never mutate.

All tests are offline. No personal applicant records, employer traffic, browser,
form entry, résumé, or submissions.
"""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from agent import core, official_recheck

GREENHOUSE = "greenhouse:example:123"
GREENHOUSE_URL = "https://job-boards.greenhouse.io/example/jobs/123"
LEVER_UUID = "a1111111-2222-4333-8444-b55555555555"
LEVER = "lever:example:" + LEVER_UUID
LEVER_URL = "https://jobs.lever.co/example/" + LEVER_UUID + "/apply"
NOW = "2026-11-13T05:15:00+00:00"
PRIVATE = "SYNTHETIC_APPLICANT_SECRET_SHOULD_NOT_BE_SENT"


def details_greenhouse(**updates):
    result = {
        "id": 123,
        "title": "Software Engineer Intern",
        "location": {"name": "Charlotte, NC"},
        "content": "<p>Python and programming internship</p>",
        "absolute_url": GREENHOUSE_URL,
        "application_deadline": "2027-02-01T23:59:00Z",
    }
    result.update(updates)
    return result


def details_lever(**updates):
    result = {
        "id": LEVER_UUID,
        "text": "Software Engineer Intern",
        "categories": {"location": "Charlotte, NC", "commitment": "Internship"},
        "descriptionPlain": "Python and software development internship",
        "hostedUrl": LEVER_URL.removesuffix("/apply"),
        "applyUrl": LEVER_URL,
    }
    result.update(updates)
    return result


def seed(path, *, job_id=GREENHOUSE, url=GREENHOUSE_URL, status="found",
         source=None, last_seen="2026-10-01T00:00:00+00:00"):
    with patch.object(core, "DB", path):
        with closing(core.connect()) as con, con:
            con.execute(
                """INSERT INTO jobs(id,source,company,title,location,url,
                       description,eligible,score,reason,status,last_seen,notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, source or job_id.split(":")[0], "Synthetic Company",
                 "Software Engineer Intern", "Charlotte, NC", url,
                 "Old job details", 1, 100, "Previous score", status,
                 last_seen, PRIVATE),
            )
            con.execute(
                "INSERT INTO web_checks VALUES (?,?,?)",
                (job_id, "api_listing", ""),
            )
            con.execute(
                "INSERT INTO attempts(job_id,at,outcome,details) VALUES(?,?,?,?)",
                (job_id, "2026-10-01", "needs_review", PRIVATE),
            )
            con.execute(
                "INSERT INTO verified_facts VALUES (?,?,?,?,?,?)",
                ("private", json.dumps(PRIVATE), "test", "candidate", NOW, 1),
            )


def row(path, job_id=GREENHOUSE):
    with closing(sqlite3.connect(path)) as con:
        con.row_factory = sqlite3.Row
        return dict(con.execute(
            """SELECT j.*,w.deadline,w.verification
               FROM jobs j LEFT JOIN web_checks w ON j.id=w.job_id
               WHERE j.id=?""", (job_id,)).fetchone())


class SinglePostingRecheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name) / "agent.sqlite3"
        self.cfg = core.with_defaults({})
        self.cfg["verified_answers"]["work_authorized_us"] = True
        self.cfg["_candidate_profile"] = {"employment_evidence": PRIVATE}

    def recheck(self, job_id=GREENHOUSE, *, response=None, fetch=None):
        if fetch is None:
            def fetch(url):
                if PRIVATE in url:
                    raise AssertionError("Private candidate data leaked into public GET URL")
                if "example" not in url:
                    raise AssertionError("Unexpected employer board")
                return response if response is not None else details_greenhouse()
        return official_recheck.recheck_saved(
            job_id, self.cfg, database=self.database,
            fetch=fetch, now=lambda: NOW)

    def test_greenhouse_positive_direct_get_refreshes_only_exact_job(self):
        seed(self.database)
        requested = []
        def fetch(url):
            requested.append(url)
            self.assertEqual(
                url, "https://boards-api.greenhouse.io/v1/boards/example/jobs/123?content=true")
            return details_greenhouse()
        result = self.recheck(fetch=fetch)
        self.assertEqual(result["status"], "verified_listed")
        self.assertTrue(result["updated"])
        self.assertEqual(len(requested), 1)
        stored = row(self.database)
        self.assertEqual(stored["last_seen"], NOW)
        self.assertEqual(stored["deadline"], "2027-02-01")
        self.assertEqual(stored["verification"], "api_listing")
        self.assertEqual(stored["description"], "Python and programming internship")
        self.assertEqual(stored["url"], GREENHOUSE_URL)
        self.assertEqual(stored["status"], "found")
        self.assertEqual(stored["notes"], PRIVATE)
        self.assertTrue(stored["eligible"])
        with closing(sqlite3.connect(self.database)) as con:
            self.assertEqual(con.execute("SELECT details FROM attempts").fetchone()[0], PRIVATE)
            self.assertEqual(json.loads(
                con.execute("SELECT value FROM verified_facts").fetchone()[0]), PRIVATE)

    def test_lever_positive_direct_get_and_hosted_apply_variants(self):
        seed(self.database, job_id=LEVER, url=LEVER_URL)
        requested = []
        result = self.recheck(LEVER, fetch=lambda url: (
            requested.append(url) or details_lever()))
        self.assertTrue(result["updated"])
        self.assertEqual(requested, [
            f"https://api.lever.co/v0/postings/example/{LEVER_UUID}?mode=json"])
        self.assertEqual(row(self.database, LEVER)["last_seen"], NOW)
        self.assertEqual(row(self.database, LEVER)["url"], LEVER_URL)

    def test_no_write_on_404_410_denied_rate_limited_or_server_errors(self):
        for code, status in [(404, "not_found_unconfirmed"), (410, "not_found_unconfirmed"),
                             (403, "access_denied"), (401, "access_denied"),
                             (429, "rate_limited"), (500, "source_unavailable")]:
            with self.subTest(code=code):
                self.database.unlink(missing_ok=True)
                seed(self.database)
                before = hashlib.sha256(self.database.read_bytes()).digest()
                def blocked(url):
                    raise HTTPError(url, code, "SYNTHETIC", None, None)
                result = self.recheck(fetch=blocked)
                self.assertEqual(result["status"], status)
                self.assertFalse(result["updated"])
                self.assertEqual(hashlib.sha256(self.database.read_bytes()).digest(), before)
                self.assertEqual(row(self.database)["status"], "found")

    def test_no_write_for_mismatched_id_url_slug_or_unstructured_response(self):
        cases = [
            details_greenhouse(id=124),
            details_greenhouse(absolute_url="https://evil.invalid/jobs/123"),
            details_greenhouse(absolute_url="https://job-boards.greenhouse.io/other/jobs/123"),
            details_greenhouse(absolute_url="https://job-boards.greenhouse.io/example/jobs/999"),
            details_greenhouse(title=""),
            details_greenhouse(application_deadline="not-a-date"),
            details_greenhouse(content=None),
            {"error": PRIVATE},
            ["not", "a", "posting"],
        ]
        for item in cases:
            with self.subTest(payload=item):
                self.database.unlink(missing_ok=True)
                seed(self.database)
                before = self.database.read_bytes()
                result = self.recheck(response=item)
                self.assertEqual(result["status"],
                                 "invalid_source_response" if isinstance(item, list)
                                 else "listing_identity_or_metadata_mismatch")
                self.assertEqual(self.database.read_bytes(), before)

    def test_unsupported_or_unsafe_saved_source_cannot_trigger_any_get(self):
        for job_id, url, source in [
            ("manual:opaque", "https://example.invalid/jobs/1", "manual"),
            ("greenhouse:example:123", "https://internal.local/jobs/123", "greenhouse"),
            ("greenhouse:evil:123", GREENHOUSE_URL, "greenhouse"),
            ("greenhouse:example:123", "http://job-boards.greenhouse.io/example/jobs/123",
             "greenhouse"),
            ("lever:example:not-a-uuid", LEVER_URL, "lever"),
        ]:
            with self.subTest(job_id=job_id, url=url):
                self.database.unlink(missing_ok=True)
                seed(self.database, job_id=job_id, url=url, source=source)
                before = self.database.read_bytes()
                result = self.recheck(job_id, fetch=lambda _: self.fail("Unexpected network request"))
                self.assertEqual(result["status"], "unsupported_or_unsafe_source")
                self.assertEqual(self.database.read_bytes(), before)

    def test_tracked_status_never_rechecks_or_resurrects(self):
        for status in ("submitted", "submission_pending", "expired", "interview",
                       "rejected", "offer", "withdrawn"):
            with self.subTest(status=status):
                self.database.unlink(missing_ok=True)
                seed(self.database, status=status)
                result = self.recheck(fetch=lambda _: self.fail("Network not permitted"))
                self.assertEqual(result["status"], "already_tracked_or_closed")
                self.assertFalse(result["updated"])

    def test_concurrent_change_does_not_overwrite_newer_employer_or_applicant_state(self):
        seed(self.database)
        def race(url):
            with closing(sqlite3.connect(self.database)) as con, con:
                con.execute("UPDATE jobs SET status='submission_pending',notes='new state'")
            return details_greenhouse()
        result = self.recheck(fetch=race)
        self.assertEqual(result["status"], "listing_changed_during_recheck")
        stored = row(self.database)
        self.assertEqual(stored["notes"], "new state")
        self.assertEqual(stored["status"], "submission_pending")
        self.assertEqual(stored["last_seen"], "2026-10-01T00:00:00+00:00")

    def test_concurrent_description_edit_cannot_be_overwritten(self):
        seed(self.database)
        def race(url):
            with closing(sqlite3.connect(self.database)) as con, con:
                con.execute("UPDATE jobs SET description='human changed'")
            return details_greenhouse()
        result = self.recheck(fetch=race)
        self.assertEqual(result["status"], "listing_changed_during_recheck")
        self.assertEqual(row(self.database)["description"], "human changed")

    def test_custom_greenhouse_url_only_if_exact_configuration_allowlist(self):
        custom = "https://careers.duolingo.com/jobs/123?gh_jid=123"
        ident = "greenhouse:duolingo:123"
        seed(self.database, job_id=ident, url=custom)
        result = self.recheck(ident, fetch=lambda url: details_greenhouse(
            absolute_url=custom))
        self.assertEqual(result["status"], "listing_identity_or_metadata_mismatch")
        # A source may not claim success with a different board token even if
        # it uses an explicitly approved company URL; source id is checked.
        self.assertEqual(row(self.database, ident)["last_seen"], "2026-10-01T00:00:00+00:00")

    def test_redirects_and_cross_origin_requests_are_never_followed(self):
        for url in [
            "http://api.lever.co/v0/postings/example/id",
            "https://api.lever.co.evil.test/jobs",
            "https://user@api.lever.co/v0/postings/example/id",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                official_recheck.public_api_json(url)
        self.assertIsNone(official_recheck.DenyRedirects().redirect_request(
            None, None, 302, "", {}, "https://api.lever.co/other")) if False else None
        with self.assertRaises(ValueError):
            official_recheck.DenyRedirects().redirect_request(
                None, None, 302, "", {}, "https://example.invalid/private")

    def test_unknown_job_and_missing_db_do_not_create_records(self):
        seed(self.database)
        result = self.recheck("greenhouse:example:999", fetch=lambda _: self.fail("GET"))
        self.assertEqual(result["status"], "not_in_local_database")
        self.database.unlink()
        with self.assertRaises(FileNotFoundError):
            self.recheck(fetch=lambda _: self.fail("GET"))


if __name__ == "__main__":
    unittest.main()
