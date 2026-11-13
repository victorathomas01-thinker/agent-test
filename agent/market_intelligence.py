"""Read-only job-market observations for local SQL and Power BI analysis.

This module NEVER reads applicant answers, application attempts, notes, resumes,
submissions, or eligibility reasons. Its SQLite warehouse and CSV exports belong
in the gitignored private directory unless a test calls the library directly.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from agent.priority import classify

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "private"
SCHEMA = Path(__file__).with_name("schema.sql")

SOURCE_COLUMNS = (
    "j.id", "j.source", "j.company", "j.title", "j.location",
    "j.last_seen", "d.published_at", "d.workplace",
    "d.employment_type", "d.salary", "w.verification",
)
POSTING_FIELDS = (
    "snapshot_id", "captured_at", "posting_key", "source",
    "company", "title", "category", "location", "workplace",
    "employment_type", "published_at", "last_seen_at",
    "source_verification", "salary_disclosed", "seen_within_7_days",
    "new_to_collector",
)


def utc_stamp(value):
    """Return a timezone-aware UTC datetime or None for uncertain timestamps."""
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(timezone.utc)
    except ValueError:
        return None


def source_connection(path):
    """Open the original job database in read-only mode without creating it."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError("The local job database does not exist.")
    uri = "file:" + quote(str(source).replace("\\", "/"), safe="/:") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def warehouse_connection(path):
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(destination)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    return con


def snapshot(source_path, warehouse_path, captured_at=None):
    """Append one atomic observation of currently stored public job metadata.

    Records may be old or incomplete. A snapshot is NOT a fresh search, a census
    of current vacancies, or evidence that a missing listing has closed.
    """
    captured = utc_stamp(captured_at) if captured_at is not None else datetime.now(timezone.utc)
    if captured is None:
        raise ValueError("captured_at must be a timezone-aware ISO timestamp.")
    time_text = captured.isoformat(timespec="microseconds")
    if Path(source_path).expanduser().resolve() == Path(warehouse_path).expanduser().resolve():
        raise ValueError("The read-only agent database and market warehouse must differ.")

    with closing(source_connection(source_path)) as original:
        required = {"jobs", "job_details", "web_checks"}
        present = {row["name"] for row in original.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not required <= present:
            raise ValueError("Source is missing required job tables; no snapshot was written.")
        query = """SELECT j.id,j.source,j.company,j.title,j.location,j.last_seen,
                          d.published_at,d.workplace,d.employment_type,d.salary,
                          w.verification
                   FROM jobs j LEFT JOIN job_details d ON d.job_id=j.id
                   LEFT JOIN web_checks w ON w.job_id=j.id
                   WHERE j.source IS NOT NULL AND j.source!='manual'
                     AND j.last_seen IS NOT NULL AND j.last_seen!=''
                   ORDER BY j.id"""
        rows = original.execute(query).fetchall()

    observations = []
    for row in rows:
        key = str(row["id"] or "")
        if not key:
            continue
        # A hash maintains across-snapshot identity without exposing raw job IDs.
        identity = hashlib.sha256((str(row["source"]) + "\x00" + key).encode("utf-8")).hexdigest()[:24]
        last = utc_stamp(row["last_seen"])
        recent = int(last is not None and timedelta(0) <= captured - last <= timedelta(days=7))
        source = str(row["source"])
        verification = str(row["verification"] or (
            "api_listing" if source in {"greenhouse", "lever", "ashby", "smartrecruiters"}
            else "unknown"))
        observations.append((
            identity, source, str(row["company"] or ""), str(row["title"] or ""),
            classify(row["title"] or "")[0], str(row["location"] or ""),
            str(row["workplace"] or ""), str(row["employment_type"] or ""),
            str(row["published_at"] or ""), str(row["last_seen"] or ""),
            verification, int(bool(str(row["salary"] or "").strip())), recent,
        ))

    with closing(warehouse_connection(warehouse_path)) as con:
        with con:
            cursor = con.execute(
                "INSERT INTO market_snapshots(captured_at, stored_public_records) VALUES (?, ?)",
                (time_text, len(observations)),
            )
            index = cursor.lastrowid
            con.executemany(
                """INSERT INTO market_observations(
                       snapshot_id,posting_key,source,company,title,category,location,
                       workplace,employment_type,published_at,last_seen_at,
                       source_verification,salary_disclosed,seen_within_7_days)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(index, *values) for values in observations],
            )
    return {"snapshot_id": index, "records": len(observations), "captured_at": time_text}


def safe_csv_value(value):
    """Prevent spreadsheet programs from executing expressions in external labels."""
    if not isinstance(value, str):
        return value
    if value and (value.lstrip().startswith(("=", "+", "-", "@"))
                  or value[0] in "\t\r\n"):
        return "'" + value
    return value


EXPORTS = {
    "market_snapshots.csv": """
        SELECT id AS snapshot_id, captured_at, stored_public_records
        FROM market_snapshots ORDER BY id""",
    "market_postings.csv": """
        SELECT o.snapshot_id,s.captured_at,o.posting_key,o.source,o.company,
               o.title,o.category,o.location,o.workplace,o.employment_type,
               o.published_at,o.last_seen_at,o.source_verification,
               o.salary_disclosed,o.seen_within_7_days,
               CASE WHEN o.snapshot_id=(
                   SELECT MIN(first.snapshot_id) FROM market_observations first
                   WHERE first.posting_key=o.posting_key
               ) THEN 1 ELSE 0 END AS new_to_collector
        FROM market_observations o
        JOIN market_snapshots s ON s.id=o.snapshot_id
        ORDER BY o.snapshot_id,o.posting_key""",
    "market_by_category_source.csv": """
        SELECT o.snapshot_id,s.captured_at,o.category,o.source,
               COUNT(*) AS records,
               SUM(o.salary_disclosed) AS salary_disclosed_records,
               SUM(o.seen_within_7_days) AS seen_within_7_days
        FROM market_observations o
        JOIN market_snapshots s ON s.id=o.snapshot_id
        GROUP BY o.snapshot_id,s.captured_at,o.category,o.source
        ORDER BY o.snapshot_id,o.category,o.source""",
}


def export_csvs(warehouse_path, output_directory):
    """Export allowlisted PUBLIC-posting columns; no personal job-agent tables."""
    out = Path(output_directory).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    with closing(sqlite3.connect(Path(warehouse_path).expanduser().resolve())) as con:
        for filename, statement in EXPORTS.items():
            cursor = con.execute(statement)
            path = out / filename
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow([field[0] for field in cursor.description])
                writer.writerows(tuple(safe_csv_value(v) for v in row) for row in cursor)
            paths[filename] = path
    return paths


def require_private(path):
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_relative_to(PRIVATE.resolve()):
        raise ValueError("Real job-market data must stay under the gitignored private/ directory.")
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local-only job market BI snapshots (never submits applications).")
    parser.add_argument("action", choices=("snapshot", "export"))
    parser.add_argument("--source", type=Path, default=ROOT / "agent.sqlite3")
    parser.add_argument("--warehouse", type=Path, default=PRIVATE / "market" / "market.sqlite3")
    parser.add_argument("--out", type=Path, default=PRIVATE / "market" / "powerbi")
    args = parser.parse_args(argv)
    try:
        warehouse = require_private(args.warehouse)
        output = require_private(args.out)
        if args.action == "snapshot":
            report = snapshot(args.source, warehouse)
            print("Snapshot recorded: " + str(report["records"]) + " stored public posting records.")
            print("Records seen within the last 7 days are flagged separately; no fresh crawl occurred.")
        paths = export_csvs(warehouse, output)
        print("Power BI CSV outputs: " + ", ".join(str(path) for path in paths.values()))
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, "Market intelligence failed safely: " + str(error) + "\n")


if __name__ == "__main__":
    main()
