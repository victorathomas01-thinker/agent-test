"""Local source-by-source job discovery audit; never includes applicant records.

Statuses describe what the collector verified, not market-wide job availability.
"""
from contextlib import closing
from datetime import datetime, timezone

from . import core

STATUSES = frozenset({"complete", "partial", "empty", "blocked", "error"})
KINDS = frozenset({"ats", "feed", "employer_site"})


def check(kind, key, status, records=0, detail=""):
    if kind not in KINDS or status not in STATUSES:
        raise ValueError("Unknown discovery coverage status.")
    if not isinstance(key, str) or not key or len(key) > 160:
        raise ValueError("Invalid public source identifier.")
    if not isinstance(records, int) or records < 0:
        raise ValueError("Negative source record count.")
    return {
        "kind": kind, "key": key, "status": status,
        "records": records, "detail": detail[:160],
    }


def record(checks, started_at, finished_at=None):
    """Persist an isolated, local coverage run after ingestion succeeds.

    Do not store API keys, full feed/career URLs or exception messages.
    This is the source-coverage ledger, NOT an applications ledger.
    """
    finished_at = finished_at or core.utc_now()
    entries = list(checks)
    with closing(core.connect()) as con, con:
        con.execute("""CREATE TABLE IF NOT EXISTS discovery_coverage_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            source_count INTEGER NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS discovery_coverage_checks (
            run_id INTEGER NOT NULL REFERENCES discovery_coverage_runs(id),
            kind TEXT NOT NULL, source_key TEXT NOT NULL,
            status TEXT NOT NULL, records INTEGER NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (run_id, kind, source_key)
        )""")
        cursor = con.execute(
            "INSERT INTO discovery_coverage_runs(started_at,finished_at,source_count) VALUES (?,?,?)",
            (started_at, finished_at, len(entries)),
        )
        run_id = cursor.lastrowid
        con.executemany(
            """INSERT INTO discovery_coverage_checks
               (run_id,kind,source_key,status,records,detail) VALUES (?,?,?,?,?,?)""",
            [(run_id, row["kind"], row["key"], row["status"],
              row["records"], row["detail"]) for row in entries],
        )
    return run_id


def latest(limit=100):
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("Invalid source coverage limit.")
    with closing(core.connect()) as con:
        if not con.execute("""SELECT 1 FROM sqlite_master
             WHERE type='table' AND name='discovery_coverage_runs'""").fetchone():
            return None, []
        run = con.execute("SELECT * FROM discovery_coverage_runs ORDER BY id DESC LIMIT 1").fetchone()
        if run is None:
            return None, []
        rows = con.execute(
            """SELECT kind,source_key,status,records,detail FROM discovery_coverage_checks
               WHERE run_id=? ORDER BY CASE status WHEN 'error' THEN 0
                   WHEN 'blocked' THEN 1 WHEN 'partial' THEN 2
                   WHEN 'empty' THEN 3 ELSE 4 END,kind,source_key LIMIT ?""",
            (run["id"], limit),
        ).fetchall()
        return dict(run), [dict(row) for row in rows]


def print_latest(limit=50):
    run, rows = latest(limit)
    if run is None:
        print("No source coverage runs recorded yet. Run discover first.")
        return
    total = {}
    for row in rows:
        total[row["status"]] = total.get(row["status"], 0) + 1
    print("Latest discovery coverage | "
          + run["started_at"] + " | "
          + str(run["source_count"]) + " sources attempted")
    print("Source checks shown: " + str(len(rows)) + "; " +
          ", ".join(f"{key}={value}" for key, value in sorted(total.items())))
    for row in rows:
        print(f"{row['status']:8s} | {row['kind']:13s} | {row['source_key']} | "
              f"{row['records']} records | {row['detail']}")
    if run["source_count"] > len(rows):
        print("Additional sources omitted by output limit. Use --limit to see more.")
    print("Complete = full bounded ATS/feed response; not the entire hiring market.")
    print("Partial/empty/error must never be interpreted as no vacancies.")
