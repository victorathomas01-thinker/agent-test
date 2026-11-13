"""Local-only beta installation guard, runs before pip or SQLite initialization.

No network, migrations, profile imports, or application submission. The sole
possible write is an explicitly approved, verified private SQLite snapshot.
No user values, employer data or filesystem paths are printed.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from agent import core, local_safety


class InstallBlocked(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    mode: str
    database: str
    configuration: str
    backup_required: bool = False


def _supported_mvp(path: Path | None):
    """Reject accidental profile imports, unreadable JSON, or symlinks."""
    if path is None:
        return
    if path.is_symlink() or not path.is_file():
        raise InstallBlocked("Explicit legacy config file is missing or is a symlink.")
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        raise InstallBlocked("Explicit legacy config must be valid JSON.")
    if not isinstance(config, dict):
        raise InstallBlocked("Explicit legacy config must be a JSON object.")
    if not isinstance(config.get("profile", {}), dict):
        raise InstallBlocked("Legacy profile section has incompatible structure.")


def plan(root: Path, *, from_mvp: Path | None = None,
         allow_upgrade: bool = False, initialize_missing: bool = False) -> Plan:
    """Decide what is allowed without ever modifying a local file."""
    root = Path(root).expanduser().resolve()
    database, config = root / "agent.sqlite3", root / "config.json"
    _supported_mvp(from_mvp)

    if database.is_symlink() or config.is_symlink():
        raise InstallBlocked("Database and config must be regular local files, not symlinks.")
    if any((root / extra).exists() for extra in
           ("agent.sqlite3-wal", "agent.sqlite3-shm", "agent.sqlite3-journal")) and not database.is_file():
        raise InstallBlocked("Orphaned SQLite journal files exist; restore the original database first.")
    if database.exists() and not database.is_file():
        raise InstallBlocked("The local database path is not a regular file.")
    if config.exists() and not config.is_file():
        raise InstallBlocked("The local configuration path is not a regular file.")
    if from_mvp is not None and (database.exists() or config.exists()):
        raise InstallBlocked("Legacy configuration import is only allowed on an entirely new install.")

    if database.is_file():
        report = local_safety.inspect(database, config)
        if report["config"] != "valid":
            raise InstallBlocked(
                "Existing local settings are missing, invalid or have live submission enabled. "
                "Repair settings locally before installation.")
        status = report["database"]
        if status == "ready":
            return Plan("existing_ready", status, report["config"])
        if status == "upgradeable":
            if not allow_upgrade:
                raise InstallBlocked(
                    "Older compatible database detected. Run 'python main.py doctor' and "
                    "retry setup.ps1 -AllowSchemaUpgrade to approve a verified private SQLite backup.")
            return Plan("existing_backup_then_upgrade", status, report["config"],
                        backup_required=True)
        raise InstallBlocked(
            "Local database has an incompatible or unreadable schema. "
            "Do NOT initialize, overwrite, or migrate it.")

    config_state = local_safety.config_report(config)
    if config.is_file():
        if config_state != "valid":
            raise InstallBlocked("Existing local settings are invalid or allow live submission.")
        if not initialize_missing:
            raise InstallBlocked(
                "Configuration exists but database is missing. Restore the historical SQLite "
                "database or explicitly retry setup.ps1 -InitializeMissingDatabase.")
        return Plan("explicit_new_db_for_existing_config", "missing", config_state)
    return Plan("new_with_import" if from_mvp else "fresh_new", "missing", config_state)


def run(root: Path, *, from_mvp: Path | None = None,
        allow_upgrade: bool = False, initialize_missing: bool = False,
        dry_run: bool = False) -> Plan:
    decision = plan(root, from_mvp=from_mvp, allow_upgrade=allow_upgrade,
                    initialize_missing=initialize_missing)
    print("Beta install preflight:", decision.mode)
    print("Database:", decision.database, "| Config:", decision.configuration)
    if decision.backup_required:
        if dry_run:
            print("A verified SQLite backup is REQUIRED before any schema expansion; none was created.")
        else:
            local_safety.backup_local(Path(root) / "agent.sqlite3", root=root)
            print("Verified private SQLite snapshot created before schema expansion.")
    print("The installation guard does not contact employers or enable live submission.")
    return decision


def main(argv=None):
    parser = argparse.ArgumentParser(description="Non-destructive beta installer guard.")
    parser.add_argument("--from-mvp", type=Path, default=None)
    parser.add_argument("--allow-upgrade", action="store_true")
    parser.add_argument("--initialize-missing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        run(core.ROOT, from_mvp=args.from_mvp, allow_upgrade=args.allow_upgrade,
            initialize_missing=args.initialize_missing, dry_run=args.dry_run)
    except (InstallBlocked, OSError, ValueError, sqlite3.Error) as error:
        # These messages contain safe canned advice only; never emit raw
        # tracebacks or profiles/filesystem paths in install status.
        print("Beta install BLOCKED:", str(error))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
