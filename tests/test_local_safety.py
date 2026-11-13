"""Synthetic-only preflight/backup tests; never reads real applicant records."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import core, local_safety

SECRET = "PRIVATE_SSN_EMAIL_AND_APPLICATION_NEVER_PRINT"


def set_config(path, *, submit=False):
    path.write_text(json.dumps({
        "profile": {"email": SECRET},
        "automation": {"allow_live_submit": submit},
        "verified_answers": {}, "discovery": {}, "preferences": {},
    }), encoding="utf-8")


def legacy(path):
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript("""
          CREATE TABLE jobs(
            id TEXT PRIMARY KEY,source TEXT,company TEXT,title TEXT,location TEXT,
            url TEXT,description TEXT,score INTEGER DEFAULT 0,eligible INTEGER DEFAULT 1,
            reason TEXT DEFAULT '',status TEXT DEFAULT 'found',last_seen TEXT,
            submitted_at TEXT,notes TEXT DEFAULT '');
          CREATE TABLE attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT,at TEXT,
            outcome TEXT,details TEXT);
          CREATE TABLE preview_claims(
            day TEXT NOT NULL,job_id TEXT NOT NULL,at TEXT NOT NULL,
            PRIMARY KEY(day,job_id));
          CREATE TABLE receipts(
            job_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,
            recorded_at TEXT NOT NULL);
        """)
        con.execute("INSERT INTO jobs(id,notes) VALUES('fake:1',?)", (SECRET,))
        con.execute(
            "INSERT INTO attempts(job_id,at,outcome,details) VALUES('fake:1','2026-10-01','needs_review',?)",
            (SECRET,))


class LocalPreflightTests(unittest.TestCase):
    def test_missing_database_and_missing_config_do_not_create_anything(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db, cfg = root / "not_there.sqlite3", root / "no_config.json"
            result = local_safety.inspect(db, cfg)
            self.assertEqual(result["database"], "missing")
            self.assertEqual(result["config"], "not_initialized")
            self.assertFalse(db.exists())
            output = io.StringIO()
            with redirect_stdout(output):
                local_safety.report(result)
            self.assertNotIn(str(root), output.getvalue())

    def test_legacy_table_shape_upgradeable_and_safe_to_inspect(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db, cfg = root / "legacy.sqlite3", root / "config.json"
            legacy(db)
            set_config(cfg)
            before = db.read_bytes()
            result = local_safety.inspect(db, cfg)
            self.assertEqual(result["database"], "upgradeable")
            self.assertEqual(result["config"], "valid")
            self.assertEqual(result["jobs"], 1)
            self.assertEqual(result["attempts"], 1)
            self.assertGreater(result["missing_new_tables"], 0)
            self.assertEqual(before, db.read_bytes(), "Doctor must never mutate existing SQLite bytes.")
            output = io.StringIO()
            with redirect_stdout(output):
                local_safety.report(result)
            self.assertNotIn(SECRET, output.getvalue())
            self.assertIn("back up before", output.getvalue())

    def test_modern_init_is_ready_even_without_lazy_coverage_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db, cfg = root / "agent.sqlite3", root / "config.json"
            set_config(cfg)
            with patch.object(core, "DB", db):
                with closing(core.connect()):
                    pass
            report = local_safety.inspect(db, cfg)
            self.assertEqual(report["database"], "ready")
            self.assertEqual(report["missing_new_tables"], 0)
            self.assertEqual(report["config"], "valid")

    def test_conflicting_schema_and_broken_file_are_not_migratable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bad = root / "wrong.sqlite3"
            with closing(sqlite3.connect(bad)) as con, con:
                con.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY, notes TEXT)")
                con.execute("CREATE TABLE attempts(id INTEGER PRIMARY KEY, details TEXT)")
            report = local_safety.inspect(bad, root / "config.json")
            self.assertEqual(report["database"], "incompatible")
            self.assertGreater(report["incompatible_tables"], 0)
            broken = root / "broken.sqlite3"
            broken.write_text("Not a database " + SECRET, encoding="utf-8")
            report = local_safety.inspect(broken, root / "config.json")
            self.assertEqual(report["database"], "corrupt_or_unreadable")

    def test_submission_enabled_config_and_malformed_configs_flagged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = root / "config.json"
            set_config(cfg, submit=True)
            self.assertEqual(local_safety.config_report(cfg), "submission_enabled")
            cfg.write_text("{ malformed", encoding="utf-8")
            self.assertEqual(local_safety.config_report(cfg), "invalid")
            cfg.write_text(json.dumps({"automation": []}), encoding="utf-8")
            self.assertEqual(local_safety.config_report(cfg), "invalid")

    def test_backup_is_private_integrity_checked_and_leaves_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "agent.sqlite3"
            legacy(db)
            (root / ".gitignore").write_text("/private/\n", encoding="utf-8")
            before = db.read_bytes()
            out = local_safety.backup_local(db, root=root)
            self.assertTrue(out.exists())
            self.assertTrue(out.is_relative_to(root / "private" / "backups"))
            self.assertEqual(db.read_bytes(), before)
            with closing(sqlite3.connect(out)) as con:
                self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(con.execute("SELECT details FROM attempts").fetchone()[0], SECRET)
            with closing(sqlite3.connect(out)) as con, con:
                con.execute("UPDATE jobs SET notes='RESTORED_COPY_CHANGED'")
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(con.execute("SELECT notes FROM jobs").fetchone()[0], SECRET)

    def test_snapshot_includes_uncheckpointed_wal_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "agent.sqlite3"
            legacy(db)
            (root / ".gitignore").write_text("/private/\n", encoding="utf-8")
            with closing(sqlite3.connect(db)) as source:
                source.execute("PRAGMA journal_mode=WAL")
                source.execute("INSERT INTO jobs(id,notes) VALUES('fake:2',?)", (SECRET,))
                source.commit()
                out = local_safety.backup_local(db, root=root)
            with closing(sqlite3.connect(out)) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)

    def test_symlinks_and_unignored_backups_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "agent.sqlite3"
            legacy(db)
            with self.assertRaisesRegex(ValueError, "gitignore"):
                local_safety.backup_local(db, root=root)
            (root / ".gitignore").write_text("/private/\n", encoding="utf-8")
            if hasattr(os, "symlink"):
                external = root / "external"
                external.mkdir()
                link = root / "private"
                try:
                    link.symlink_to(external, target_is_directory=True)
                except (OSError, NotImplementedError):
                    self.skipTest("Current OS cannot create test symlinks without privileges.")
                with self.assertRaisesRegex(ValueError, "symlink"):
                    local_safety.backup_local(db, root=root)

    def test_invalid_backup_target_not_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".gitignore").write_text("/private/\n", encoding="utf-8")
            bad = root / "fake.sqlite3"
            bad.write_text("unreadable", encoding="utf-8")
            with self.assertRaises(sqlite3.Error):
                local_safety.backup_local(bad, root=root)
            self.assertEqual(list((root / "private" / "backups").glob("*.sqlite3")), [])


if __name__ == "__main__":
    unittest.main()
