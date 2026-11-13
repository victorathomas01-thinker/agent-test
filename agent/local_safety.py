"""Read-only installation preflight and opt-in local SQLite safety snapshot.

No network, browser, applications, or automatic migration. All applicant data
remains in the existing local DB unless the operator explicitly requests a
snapshot in the gitignored private/backups directory. Raw values and sensitive
filenames are never printed by report().
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import core

ROOT = core.ROOT
DB = core.DB
CONFIG = core.CONFIG
BACKUP_DIRECTORY = ROOT / "private" / "backups"

# Existing table columns must already be compatible. Missing *tables* can be
# added by core.connect after an explicit backup and review; no ALTER is made
# automatically by this preflight. Keep this spec in sync with core.connect.
EXPECTED_COLUMNS = {
    "jobs": ("id", "source", "company", "title", "location", "url",
             "description", "score", "eligible", "reason", "status",
             "last_seen", "submitted_at", "notes"),
    "attempts": ("id", "job_id", "at", "outcome", "details"),
    "preview_claims": ("day", "job_id", "at"),
    "receipts": ("job_id", "fingerprint", "recorded_at"),
    "job_details": ("job_id", "published_at", "workplace", "employment_type", "salary"),
    "runs": ("id", "started_at", "finished_at", "status", "details"),
    "packages": ("job_id", "version", "created_at", "folder"),
    "followups": ("job_id", "due_on"),
    "selections": ("job_id", "status", "updated_at", "attempts", "blocker", "version"),
    "web_checks": ("job_id", "verification", "deadline"),
    "verified_facts": ("key", "value", "source", "scope", "verified_at", "active"),
    "eligibility_overrides": ("job_id", "created_at"),
    "discovery_coverage_runs": ("id", "started_at", "finished_at", "source_count"),
    "discovery_coverage_checks": ("run_id", "kind", "source_key", "status", "records", "detail"),
}


# The source-coverage ledger is created lazily by discovery, not init.
OPTIONAL_TABLES = {"discovery_coverage_runs", "discovery_coverage_checks"}


def readonly_connection(filename: Path) -> sqlite3.Connection:
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("There is no existing local SQLite database to inspect.")
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _schema_report(connection):
    known = {row["name"] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(set(EXPECTED_COLUMNS) - known)
    conflicts = []
    for table, required in EXPECTED_COLUMNS.items():
        if table not in known:
            continue
        # Every identifier here is an immutable, audited module constant.
        actual = {row["name"] for row in connection.execute(
            f'PRAGMA table_info("{table}")')}
        if not set(required) <= actual:
            conflicts.append(table)
    return missing, sorted(conflicts)


def config_report(filename: Path):
    path = Path(filename).expanduser()
    if not path.is_file():
        return "not_initialized"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return "invalid"
        if any(not isinstance(data.get(field, {}), dict)
               for field in ("profile", "automation", "verified_answers", "discovery", "preferences")):
            return "invalid"
        # This is a deployment safety diagnostic, not a live submission toggle.
        if data.get("automation", {}).get("allow_live_submit") is True:
            return "submission_enabled"
        return "valid"
    except (OSError, ValueError, UnicodeError):
        return "invalid"


def inspect(database=DB, config=CONFIG):
    """Return sanitized counts and compatibility flags; NEVER mutate inputs."""
    result = {
        "database": "missing",
        "config": config_report(config),
        "integrity": "not_checked",
        "existing_known_tables": 0,
        "missing_new_tables": 0,
        "incompatible_tables": 0,
        "jobs": 0,
        "attempts": 0,
    }
    try:
        with closing(readonly_connection(database)) as con:
            integrity = con.execute("PRAGMA integrity_check(1)").fetchone()[0]
            result["integrity"] = "ok" if integrity == "ok" else "failed"
            if result["integrity"] != "ok":
                result["database"] = "corrupt_or_unreadable"
                return result
            missing, conflicts = _schema_report(con)
            required_missing = set(missing) - OPTIONAL_TABLES
            result["existing_known_tables"] = len(EXPECTED_COLUMNS) - len(missing)
            result["missing_new_tables"] = len(required_missing)
            result["incompatible_tables"] = len(conflicts)
            if conflicts or "jobs" in missing or "attempts" in missing:
                result["database"] = "incompatible"
            elif required_missing:
                result["database"] = "upgradeable"
            else:
                result["database"] = "ready"
            # Counts contain no personal identifiers or applicant answers.
            if "jobs" not in missing and "jobs" not in conflicts:
                result["jobs"] = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if "attempts" not in missing and "attempts" not in conflicts:
                result["attempts"] = con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    except FileNotFoundError:
        result["database"] = "missing"
    except (sqlite3.Error, OSError, ValueError):
        result["database"] = "corrupt_or_unreadable"
        result["integrity"] = "failed"
    return result


def _private_backup_directory(root: Path):
    """Never write personal records into a tracked or unexpected directory."""
    root = Path(root).expanduser().resolve()
    ignore = root / ".gitignore"
    if not ignore.is_file() or "/private/" not in ignore.read_text(encoding="utf-8").splitlines():
        raise ValueError("Local gitignore must exclude /private/ before creating a backup.")
    private = root / "private"
    # Symlinks would evade the apparent private/ location and leak records.
    if private.is_symlink() or (private / "backups").is_symlink():
        raise ValueError("Refusing to back up through a symlink.")
    target = private / "backups"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not target.resolve().is_relative_to(root / "private"):
        raise ValueError("Backup destination escapes the gitignored private folder.")
    return target


def backup_local(database=DB, *, root=ROOT):
    """Create an atomic, verified SQLite snapshot when explicitly requested.

    This does not include config.json or other personal files; see docs.
    """
    source = Path(database).expanduser().resolve()
    # Never back up a missing database or a symlinked source.
    if Path(database).is_symlink() or not source.is_file():
        raise ValueError("Backup requires an existing regular local SQLite file.")
    destination_dir = _private_backup_directory(root)
    marker = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"job-agent-db-{marker}-{secrets.token_hex(5)}.sqlite3"
    final = destination_dir / name
    descriptor, temp = tempfile.mkstemp(prefix=".job-agent-", suffix=".sqlite3.tmp",
                                       dir=destination_dir)
    os.close(descriptor)
    temporary = Path(temp)
    try:
        os.chmod(temporary, 0o600)
        with closing(readonly_connection(source)) as original:
            with closing(sqlite3.connect(temporary, timeout=10)) as copied:
                original.backup(copied, pages=128, sleep=0.05)
        with closing(readonly_connection(temporary)) as verify:
            if verify.execute("PRAGMA integrity_check(1)").fetchone()[0] != "ok":
                raise ValueError("Backup verification failed; no backup published.")
            existing = {row["name"] for row in verify.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"jobs", "attempts"} <= existing:
                raise ValueError("Backup did not contain the expected application tables.")
        if final.exists():
            raise ValueError("Refusing to replace an existing backup.")
        os.replace(temporary, final)
        return final
    finally:
        temporary.unlink(missing_ok=True)


def report(result, backup=None):
    """Print only aggregates and safety statuses, never profile/record content."""
    print("JOB AGENT LOCAL PREFLIGHT — no applicant records displayed")
    print("Database state:", result["database"], "| SQLite integrity:", result["integrity"])
    print("Existing known tables:", result["existing_known_tables"],
          "| missing additive tables:", result["missing_new_tables"],
          "| incompatible tables:", result["incompatible_tables"])
    print("Stored jobs:", result["jobs"], "| historical attempts:", result["attempts"])
    print("Configuration:", result["config"])
    if backup is not None:
        print("Verified SQLite snapshot saved in ignored private/backups.")
        print("SQLite backup does not include config.json, candidate-profile.json, or attachments.")
    if result["database"] == "upgradeable":
        print("An additive schema update is possible; back up before any migration.")
    if result["database"] in ("incompatible", "corrupt_or_unreadable"):
        print("Do NOT initialize or migrate this database. Investigate the schema separately.")
    if result["config"] == "submission_enabled":
        print("WARNING: Live submission is enabled in local settings. Disable it for review.")
    print("This command does not submit applications, visit employers, or migrate your database.")


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Read-only local compatibility preflight.")
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--backup", action="store_true",
                        help="Explicitly create a private local SQLite snapshot.")
    args = parser.parse_args(argv)
    result = inspect(args.database, args.config)
    saved = None
    if args.backup:
        if result["database"] not in ("ready", "upgradeable"):
            parser.error("Cannot back up this missing, corrupt, or incompatible database.")
        try:
            saved = backup_local(args.database)
        except (OSError, sqlite3.Error, ValueError):
            parser.error("Private database backup failed safely; no backup was published.")
    report(result, saved)
    return 0 if result["database"] in ("ready", "upgradeable") and result["config"] == "valid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
