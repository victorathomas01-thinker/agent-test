"""Beta first-run acceptance tests; all applicant and SQLite records are fictional."""
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import core
from scripts import beta_guard, beta_status

SENTINEL = "FICTIONAL_PRIVATE_ACCOUNT_INFORMATION_DO_NOT_PRINT"


def config(path, *, enabled=False, complete=False):
    data = {"automation": {"allow_live_submit": enabled}, "profile": {}}
    if complete:
        data["profile"] = {
            "first_name": "Sample", "last_name": "Applicant",
            "email": "synthetic@example.invalid",
            "resume_path": "private/resume.txt",
        }
    path.write_text(json.dumps(data), encoding="utf-8")


def legacy_db(path):
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript("""
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT,
                location TEXT, url TEXT, description TEXT, score INTEGER DEFAULT 0,
                eligible INTEGER DEFAULT 1, reason TEXT DEFAULT '',
                status TEXT DEFAULT 'found', last_seen TEXT, submitted_at TEXT,
                notes TEXT DEFAULT ''
            );
            CREATE TABLE attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT,
                at TEXT, outcome TEXT, details TEXT
            );
            CREATE TABLE preview_claims (
                day TEXT NOT NULL, job_id TEXT NOT NULL, at TEXT NOT NULL,
                PRIMARY KEY(day, job_id)
            );
            CREATE TABLE receipts (
                job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                recorded_at TEXT NOT NULL
            );
        """)
        con.execute("INSERT INTO jobs(id,notes) VALUES('synthetic-1',?)", (SENTINEL,))
        con.execute(
            "INSERT INTO attempts(job_id,at,outcome,details) VALUES('synthetic-1','2026-10-01',?,?)",
            ("needs_review", SENTINEL),
        )


class BetaInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".gitignore").write_text("/private/\n/config.json\n/agent.sqlite3*\n")
        self.database = self.root / "agent.sqlite3"
        self.config = self.root / "config.json"

    def test_clean_install_is_nonmutating_and_never_imports_a_legacy_file(self):
        original = beta_guard.plan(self.root)
        self.assertEqual(original.mode, "fresh_new")
        output = io.StringIO()
        with redirect_stdout(output):
            beta_guard.run(self.root, dry_run=True)
        self.assertFalse(self.database.exists())
        self.assertFalse(self.config.exists())
        self.assertNotIn(SENTINEL, output.getvalue())

    def test_explicit_mvp_import_only_for_clean_install(self):
        legacy = self.root / "earlier.json"
        legacy.write_text(json.dumps({"profile": {"email": SENTINEL}}))
        self.assertEqual(beta_guard.plan(self.root, from_mvp=legacy).mode,
                         "new_with_import")
        config(self.config)
        with self.assertRaisesRegex(beta_guard.InstallBlocked, "entirely new"):
            beta_guard.plan(self.root, from_mvp=legacy)
        self.config.unlink()
        legacy.write_text("not-json")
        with self.assertRaisesRegex(beta_guard.InstallBlocked, "valid JSON"):
            beta_guard.plan(self.root, from_mvp=legacy)

    def test_existing_upgrade_requires_approval_and_creates_verified_snapshot(self):
        config(self.config)
        legacy_db(self.database)
        original_notes = self.database.read_bytes()
        with self.assertRaisesRegex(beta_guard.InstallBlocked, "Older compatible"):
            beta_guard.plan(self.root)
        self.assertFalse((self.root / "private").exists())
        proposal = beta_guard.plan(self.root, allow_upgrade=True)
        self.assertTrue(proposal.backup_required)
        self.assertEqual(proposal.database, "upgradeable")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            beta_guard.run(self.root, allow_upgrade=True, dry_run=True)
        self.assertFalse((self.root / "private").exists())
        with redirect_stdout(stdout):
            beta_guard.run(self.root, allow_upgrade=True)
        self.assertEqual(self.database.read_bytes(), original_notes)
        backups = list((self.root / "private" / "backups").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as con:
            self.assertEqual(
                con.execute("SELECT notes FROM jobs").fetchone()[0], SENTINEL)
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertNotIn(SENTINEL, stdout.getvalue())
        self.assertNotIn(str(self.root), stdout.getvalue())

    def test_corrupt_or_incompatible_database_fails_closed_without_backups(self):
        config(self.config)
        self.database.write_bytes(b"not-a-sqlite3-db")
        with self.assertRaisesRegex(beta_guard.InstallBlocked, "incompatible or unreadable"):
            beta_guard.plan(self.root, allow_upgrade=True)
        self.assertFalse((self.root / "private").exists())

    def test_existing_config_but_missing_db_requires_explicit_approval(self):
        config(self.config)
        with self.assertRaisesRegex(beta_guard.InstallBlocked, "database is missing"):
            beta_guard.plan(self.root)
        result = beta_guard.plan(self.root, initialize_missing=True)
        self.assertEqual(result.mode, "explicit_new_db_for_existing_config")
        self.assertFalse(self.database.exists())

    def test_existing_submission_enabled_config_blocks_setup_even_if_database_valid(self):
        config(self.config, enabled=True)
        legacy_db(self.database)
        with self.assertRaisesRegex(beta_guard.InstallBlocked, "live submission enabled"):
            beta_guard.plan(self.root, allow_upgrade=True)
        self.assertFalse((self.root / "private").exists())

    def test_orphaned_wal_and_symlinks_are_blocked(self):
        config(self.config)
        (self.root / "agent.sqlite3-wal").write_bytes(b"PRIVATE_OLD_WAL")
        with self.assertRaisesRegex(beta_guard.InstallBlocked, "Orphaned SQLite"):
            beta_guard.plan(self.root, initialize_missing=True)
        (self.root / "agent.sqlite3-wal").unlink()
        actual = self.root / "target.sqlite3"
        legacy_db(actual)
        try:
            self.database.symlink_to(actual)
        except (OSError, NotImplementedError):
            self.skipTest("OS lacks symlink permissions.")
        with self.assertRaisesRegex(beta_guard.InstallBlocked, "symlinks"):
            beta_guard.plan(self.root, allow_upgrade=True)

    def test_beta_status_is_readonly_and_does_not_show_private_values(self):
        config(self.config, complete=True)
        private = self.root / "private"
        private.mkdir()
        (private / "resume.txt").write_text(SENTINEL, encoding="utf-8")
        with patch.object(core, "DB", self.database):
            with closing(core.connect()) as con, con:
                con.execute("""INSERT INTO jobs
                    (id,source,title,company,location,url,description,
                     eligible,status,last_seen,notes) VALUES
                    ('fictional-1','manual','Synthetic Intern','Synthetic',
                     'Charlotte','https://example.invalid/posting','Hello',
                     1,'found','2026-11-13T00:00:00+00:00',?)""", (SENTINEL,))
        before = self.database.read_bytes()
        report = beta_status.inspect(self.root)
        self.assertTrue(report["profile_ready"])
        self.assertTrue(report["resume_present"])
        self.assertEqual(report["pending_opportunities"], 1)
        self.assertEqual(report["source_review_required"], 0)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            beta_status.print_status(report)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertNotIn(SENTINEL, stdout.getvalue())
        self.assertNotIn("synthetic@example.invalid", stdout.getvalue())
        self.assertNotIn(str(self.root), stdout.getvalue())

    def test_beta_status_reports_missing_profile_without_crashing(self):
        config(self.config)
        with patch.object(core, "DB", self.database):
            with closing(core.connect()):
                pass
        result = beta_status.inspect(self.root)
        self.assertEqual(result["database"], "ready")
        self.assertFalse(result["profile_ready"])
        self.assertFalse(result["resume_present"])
        output = io.StringIO()
        with redirect_stdout(output):
            beta_status.print_status(result)
        self.assertIn("not yet", output.getvalue())
        self.assertIn("set and confirm", output.getvalue())


if __name__ == "__main__":
    unittest.main()
