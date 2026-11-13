"""Offline integrated acceptance using a disposable install and synthetic records.

Unlike unit tests, exercises the actual command-line app against an isolated
working tree. Runs zero network requests and never reads the user's database.
"""
import csv
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "SYNTHETIC_SECRET_NEVER_LOGGED"
DAY = "2026-10-10"


def run(app, *arguments):
    result = subprocess.run(
        [sys.executable, *arguments], cwd=app,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
    )
    combined = result.stdout + result.stderr
    if SENTINEL in combined:
        raise AssertionError("Private synthetic applicant data appeared in CLI output.")
    if result.returncode:
        # Only report the CLI command and exit status; stderr may contain
        # actual absolute paths, even in a future non-synthetic use.
        raise AssertionError(f"Isolated command {arguments[:3]!r} failed "
                             f"with exit code {result.returncode}.")
    return result.stdout


def make_sandbox(app):
    app.mkdir()
    for name in ("main.py", "config.example.json", ".gitignore"):
        shutil.copy2(ROOT / name, app / name)
    shutil.copytree(ROOT / "agent", app / "agent",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (app / "examples").mkdir()
    shutil.copy2(ROOT / "examples" / "public_requirements_benchmark.json",
                 app / "examples" / "public_requirements_benchmark.json")


def database_rows(db):
    with closing(sqlite3.connect(db)) as con:
        tables = tuple(row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        result = []
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            entries = con.execute(f"SELECT * FROM {quoted} ORDER BY rowid").fetchall()
            result.append((table, entries))
        return result


def seed(db):
    with closing(sqlite3.connect(db)) as con, con:
        for index in range(20):
            provider = "greenhouse" if index < 10 else "lever"
            identifier = f"{provider}:synthetic:{index}"
            con.execute(
                """INSERT INTO jobs(id,source,company,title,location,url,description,
                    status,last_seen,notes) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (identifier, provider, "Synthetic Employer",
                 f"IT Support Intern {index}", "Charlotte NC",
                 "https://example.invalid/jobs/" + str(index),
                 "Synthetic qualification sentence",
                 "found", "2026-10-10T10:00:00+00:00", SENTINEL),
            )
            con.execute(
                """INSERT INTO job_details(job_id,published_at,workplace,employment_type,salary)
                   VALUES (?,?,?,?,?)""",
                (identifier, "2026-10-01", "hybrid", "internship", "Not provided"),
            )
            con.execute(
                "INSERT INTO web_checks(job_id,verification,deadline) VALUES (?,?,?)",
                (identifier, "api_listing", "2020-10-01" if index == 0 else ""),
            )
            # Include two attempts on the first job to check the most recent
            # history is chosen, not the highest number of rows per employer.
            if index == 0:
                con.execute(
                    "INSERT INTO attempts(job_id,at,outcome,details) VALUES (?,?,?,?)",
                    (identifier, "2026-10-09T10:00:00+00:00", "needs_review",
                     "Old pre-pilot attempt: " + SENTINEL),
                )
            reasons = (
                "no verified answer" if index < 7 else
                "checkbox requires explicit applicant review" if index < 13 else
                "no unique matching dropdown option" if index < 17 else
                "custom control requires manual input"
            )
            payload = {"mode": "dry-run", "filled": [SENTINEL],
                       "unresolved": [
                           {"field": "Synthetic private question " + SENTINEL,
                            "required": True, "reason": reasons},
                       ]}
            con.execute(
                "INSERT INTO attempts(job_id,at,outcome,details) VALUES (?,?,?,?)",
                (identifier, DAY + "T12:00:00+00:00", "needs_review",
                 json.dumps(payload)),
            )
        # A later login failure must not erase the prior detached preview
        # when reconstructing the original pilot's offline blockers.
        con.execute(
            "INSERT INTO attempts(job_id,at,outcome,details) VALUES (?,?,?,?)",
            ("greenhouse:synthetic:0", "2026-11-12T12:00:00+00:00",
             "needs_review", "Sign-in needed."),
        )
        con.execute(
            """INSERT INTO verified_facts(key,value,source,scope,verified_at,active)
               VALUES ('synthetic_private','' || ?, 'test', 'local', ?,1)""",
            (json.dumps(SENTINEL), DAY),
        )


def backup_roundtrip(original, restored):
    with closing(sqlite3.connect(original)) as source:
        with closing(sqlite3.connect(restored)) as target:
            source.backup(target)
    if database_rows(original) != database_rows(restored):
        raise AssertionError("SQLite backup did not reproduce all local tables and rows.")
    # Restored copy must be independently writable without touching source.
    with closing(sqlite3.connect(restored)) as dest, dest:
        dest.execute("UPDATE jobs SET status='expired' WHERE id='greenhouse:synthetic:0'")
    with closing(sqlite3.connect(original)) as con:
        status = con.execute(
            "SELECT status FROM jobs WHERE id='greenhouse:synthetic:0'"
        ).fetchone()[0]
    if status != "found":
        raise AssertionError("Restored copy unexpectedly changed the original database.")


def market_check(app):
    run(app, "-m", "agent.market_intelligence", "snapshot")
    run(app, "-m", "agent.market_intelligence", "snapshot")
    private = app / "private" / "market"
    warehouse = private / "market.sqlite3"
    with closing(sqlite3.connect(warehouse)) as con:
        snapshots = con.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        observations = con.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0]
    if (snapshots, observations) != (2, 40):
        raise AssertionError("Two repeated market snapshots changed historical record counts.")
    with (private / "powerbi" / "market_postings.csv").open(
            encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    if len(records) != 40 or sum(int(row["new_to_collector"]) for row in records) != 20:
        raise AssertionError("First-seen market-posting flags are not stable over snapshots.")
    for path in (private / "powerbi").glob("*.csv"):
        exported = path.read_text(encoding="utf-8")
        if SENTINEL in exported or "Synthetic private question" in exported:
            raise AssertionError("Private application data leaked into market exports.")
    return snapshots, observations


def legacy_upgrade(app):
    legacy_db = app / "legacy.sqlite3"
    with closing(sqlite3.connect(legacy_db)) as con, con:
        # Exact four-table base from the original early Job Agent main branch.
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
            PRIMARY KEY(day,job_id)
          );
          CREATE TABLE receipts (
            job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            recorded_at TEXT NOT NULL
          );
          INSERT INTO jobs(id,status,notes)
            VALUES('legacy:synthetic:1','found','LEGACY_PRESERVE');
          INSERT INTO attempts(job_id,at,outcome,details)
            VALUES('legacy:synthetic:1','2026-10-10','needs_review','LEGACY_ATTEMPT');
        """)
    # An offline legacy migration: temporarily swap an isolated copy into the
    # sandbox path and call the public main.py init command with no credentials.
    active = app / "agent.sqlite3"
    moved = app / "modern.sqlite3"
    active.rename(moved)
    try:
        legacy_db.rename(active)
        # A read-only preflight and explicit snapshot must work before any
        # call to core.connect() can add tables to the older database.
        before_legacy = active.read_bytes()
        preflight = run(app, "main.py", "doctor")
        if "Database state: upgradeable" not in preflight:
            raise AssertionError("Legacy schema was not identified as additive.")
        if active.read_bytes() != before_legacy:
            raise AssertionError("Legacy preflight mutated the source database.")
        run(app, "main.py", "doctor", "--backup")
        # This intentionally invokes a sandboxed migration AFTER backup.
        run(app, "main.py", "status")
        with closing(sqlite3.connect(active)) as con:
            tables = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "job_details" not in tables or "verified_facts" not in tables:
                raise AssertionError("Existing database could not gain missing schema tables.")
            job = con.execute("SELECT notes FROM jobs WHERE id='legacy:synthetic:1'").fetchone()
            attempt = con.execute(
                "SELECT details FROM attempts WHERE job_id='legacy:synthetic:1'").fetchone()
            if job != ("LEGACY_PRESERVE",) or attempt != ("LEGACY_ATTEMPT",):
                raise AssertionError("Legacy personal data did not survive schema expansion.")
    finally:
        if active.exists():
            active.rename(legacy_db)
        moved.rename(active)


def main():
    with tempfile.TemporaryDirectory(prefix="job-agent-disposable-") as temp:
        app = Path(temp) / "app"
        make_sandbox(app)
        if (app / "agent.sqlite3").exists():
            raise AssertionError("Unexpected job agent database in clean sandbox.")
        run(app, "main.py", "init")
        config = json.loads((app / "config.json").read_text(encoding="utf-8"))
        if config["automation"]["allow_live_submit"] is not False:
            raise AssertionError("New installs must keep live submission disabled.")
        db = app / "agent.sqlite3"
        if not db.is_file():
            raise AssertionError("New install did not create a local SQLite database.")
        seed(db)
        original_checksum = hashlib.sha256(db.read_bytes()).hexdigest()
        doctor = run(app, "main.py", "doctor")
        if "Database state: ready" not in doctor or "Configuration: valid" not in doctor:
            raise AssertionError("Modern database preflight did not pass.")
        if hashlib.sha256(db.read_bytes()).hexdigest() != original_checksum:
            raise AssertionError("Read-only doctor unexpectedly changed the original.")
        backed_up = run(app, "main.py", "doctor", "--backup")
        if "Verified SQLite snapshot" not in backed_up:
            raise AssertionError("CLI did not confirm its opt-in backup.")
        backups = list((app / "private" / "backups").glob("job-agent-db-*.sqlite3"))
        if len(backups) != 1 or database_rows(backups[0]) != database_rows(db):
            raise AssertionError("Private backup omitted or altered local agent records.")
        if hashlib.sha256(db.read_bytes()).hexdigest() != original_checksum:
            raise AssertionError("Backup changed the original local database.")
        audit = run(app, "main.py", "posting-audit")
        if hashlib.sha256(db.read_bytes()).hexdigest() != original_checksum:
            raise AssertionError("Read-only posting audit unexpectedly modified the source database.")
        if ("Unsubmitted job records: 20" not in audit
                or "Explicitly passed deadline, recheck required: 1" not in audit):
            raise AssertionError("Posting readiness report did not identify the saved expired cutoff.")
        output = run(app, "main.py", "pilot-audit", "--since", DAY,
                     "--through", DAY, "--offline-only",
                     "--limit", "20", "--expected", "20")
        recovered = run(app, "main.py", "pilot-audit", "--offline-only",
                        "--limit", "20", "--expected", "20")
        if "Examined 20 unique jobs" not in recovered or (
                "Offline previews with unresolved required fields: 20" not in recovered):
            raise AssertionError("Later sign-in failure displaced historical offline previews.")
        if "Examined 20 unique jobs" not in output or                 "Offline previews with unresolved required fields: 20" not in output:
            raise AssertionError("Pilot audit failed the 20-job synthetic scenario.")
        if "matching the expected" not in output.casefold():
            raise AssertionError("Pilot audit failed to warn that count alone proves nothing.")
        if hashlib.sha256(db.read_bytes()).hexdigest() != original_checksum:
            raise AssertionError("Read-only historical pilot audit mutated its source database.")
        output = run(app, "main.py", "benchmark-requirements")
        if "Annotated cases: 28" not in output or "Fixture label matches: 28" not in output:
            raise AssertionError("Public requirement benchmark did not validate all 28 examples.")
        backup_roundtrip(db, app / "restored.sqlite3")
        snapshots, observations = market_check(app)
        legacy_upgrade(app)
        with closing(sqlite3.connect(db)) as con:
            count = con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        if count != 22:
            raise AssertionError("Historical applicant attempts changed during acceptance.")
        print("PASS — read-only doctor, safe config gate, and private verified SQLite snapshots")
        print("PASS — persisted deadline and source-age review report; zero private data")
        print("PASS — isolated clean CLI init and live-submit safeguard")
        print("PASS — 20-job synthetic historical pilot audit; read-only source unchanged")
        print("PASS — 28 fictional-profile public requirement fixtures")
        print("PASS — full SQLite backup/restore and preserved historic attempts")
        print(f"PASS — {snapshots} market snapshots and {observations} observations, no private fields")
        print("PASS — 4-table legacy database expanded safely without losing existing records")
        print("NO private applicant data, real employer requests, or applications used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
