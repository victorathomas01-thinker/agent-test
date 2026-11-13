"""Historical offline-pilot blocker analysis, from a local read-only SQLite file.

No profile, resume, application questions, job descriptions, or raw attempt
details leave the machine. No database or report is created as a side effect.
"""
import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from . import core
from .form_diagnostics import classify

QUALIFYING_OUTCOMES = ("prepared", "needs_review", "failed", "expired")
PUBLIC_SOURCES = {"greenhouse", "lever", "ashby", "smartrecruiters",
                  "workday", "careers", "manual"}
QUERY = """
    SELECT a.id, a.job_id, a.at, a.outcome, a.details, j.source
    FROM attempts AS a
    JOIN (
        SELECT job_id, MAX(id) AS last_id FROM attempts
        WHERE outcome IN ('prepared','needs_review','failed','expired')
          AND (? IS NULL OR at >= ?)
          AND (? IS NULL OR at < ?)
        GROUP BY job_id
    ) latest ON a.id=latest.last_id
    LEFT JOIN jobs AS j ON j.id=a.job_id
    ORDER BY a.id DESC LIMIT ?
"""


def parse_day(value):
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Date format must be YYYY-MM-DD.")
        return parsed
    except (TypeError, ValueError) as error:
        raise ValueError("Dates must be valid YYYY-MM-DD calendar dates.") from error


def open_readonly(path):
    file = Path(path).expanduser().resolve()
    if not file.is_file():
        raise FileNotFoundError("The requested local agent database was not found.")
    uri = "file:" + quote(str(file).replace("\\", "/"), safe="/:") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    required = {"jobs", "attempts"}
    names = {row["name"] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= names:
        con.close()
        raise ValueError("This SQLite file lacks the required local agent tables.")
    return con


def selected_attempts(con, since=None, through=None, limit=20, offline_only=False):
    """Select latest history per job, optionally excluding later non-preview events.

    For historical offline-only reconstruction, parse the local JSON in memory;
    never rely on SQLite JSON1 availability or expose raw details to stdout.
    """
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Pilot audit supports between 1 and 1000 unique jobs.")
    first, last = parse_day(since), parse_day(through)
    if first and last and first > last:
        raise ValueError("The first audit date must not follow the last.")
    left = first.isoformat() if first else None
    right = (last + timedelta(days=1)).isoformat() if last else None
    if not offline_only:
        return con.execute(QUERY, (left, left, right, right, limit)).fetchall()
    query = """
        SELECT a.id, a.job_id, a.at, a.outcome, a.details, j.source
        FROM attempts a LEFT JOIN jobs j ON j.id=a.job_id
        WHERE a.outcome IN ('prepared','needs_review','failed','expired')
          AND (? IS NULL OR a.at >= ?)
          AND (? IS NULL OR a.at < ?)
        ORDER BY a.id DESC
    """
    chosen, already_seen = [], set()
    for row in con.execute(query, (left, left, right, right)):
        if row["job_id"] in already_seen:
            continue
        try:
            details = json.loads(row["details"]) if row["details"] else None
        except (ValueError, TypeError):
            details = None
        if not isinstance(details, dict) or details.get("mode") != "dry-run":
            continue
        chosen.append(row)
        already_seen.add(row["job_id"])
        if len(chosen) >= limit:
            break
    return chosen


def summarize(rows, expected=20):
    if not isinstance(expected, int) or not 1 <= expected <= 1000:
        raise ValueError("Expected pilot size must be positive and at most 1000.")
    providers, outcomes, required_fields, affected, failure_groups = (
        Counter(), Counter(), Counter(), Counter(), Counter())
    dry_run = 0
    current_step_prepared = 0
    no_required_field = 0
    required_blocked = 0
    invalid_payloads = 0

    for row in rows:
        source = str(row["source"] or "").casefold()
        if source not in PUBLIC_SOURCES:
            prefix = str(row["job_id"] or "").partition(":")[0].casefold()
            source = prefix if prefix in PUBLIC_SOURCES else "other_or_missing"
        providers[source] += 1
        outcome = row["outcome"]
        outcomes[outcome] += 1
        try:
            payload = json.loads(row["details"]) if row["details"] else None
        except (ValueError, TypeError):
            payload = None

        if not isinstance(payload, dict) or payload.get("mode") != "dry-run":
            invalid_payloads += 1
            if outcome != "prepared":
                failure_groups[classify(row["details"])] += 1
            continue

        dry_run += 1
        unresolved = payload.get("unresolved")
        if not isinstance(unresolved, list):
            invalid_payloads += 1
            continue
        categories = set()
        for item in unresolved:
            if not isinstance(item, dict) or item.get("required") is not True:
                continue
            kind = classify(item.get("reason"))
            required_fields[kind] += 1
            categories.add(kind)
        for kind in categories:
            affected[kind] += 1
        if categories:
            required_blocked += 1
        else:
            no_required_field += 1
            if outcome == "prepared":
                current_step_prepared += 1

    return {
        "sampled_unique_jobs": len(rows),
        "expected_pilot_jobs": expected,
        "matches_expected_count_only": len(rows) == expected,
        "dry_run_previews": dry_run,
        "not_dry_run_or_bad_json": invalid_payloads,
        "offline_current_step_prepared": current_step_prepared,
        "offline_previews_with_required_blockers": required_blocked,
        "offline_previews_without_required_blockers": no_required_field,
        "outcomes": dict(sorted(outcomes.items())),
        "providers": dict(sorted(providers.items())),
        "required_field_counts": dict(sorted(required_fields.items())),
        "affected_job_counts": dict(sorted(affected.items())),
        "nonjson_failure_categories": dict(sorted(failure_groups.items())),
    }


def render(report, start=None, through=None, offline_only=False):
    title = "LOCAL HISTORICAL OFFLINE FORM AUDIT — no application data exported"
    print(title)
    mode = ("latest detached offline preview per job" if offline_only
            else "latest recorded attempt per job, including later non-preview failures")
    print(f"Window: {start or '(unbounded)'} through {through or '(unbounded)'}; " + mode + ".")
    print(f"Examined {report['sampled_unique_jobs']} unique jobs. "
          f"Expected pilot count: {report['expected_pilot_jobs']}.")
    if not report["matches_expected_count_only"]:
        print("WARNING: This sample has a different count from the documented pilot.")
    else:
        print("Matching the expected count does NOT prove these were the original pilot's jobs.")
    print(f"Dry-run previews: {report['dry_run_previews']}; "
          f"unclassified/legacy attempt details: {report['not_dry_run_or_bad_json']}.")
    print(f"Offline current-step prepared: {report['offline_current_step_prepared']} "
          "(NOT live final-submit-ready).")
    print("Offline previews with unresolved required fields:",
          report["offline_previews_with_required_blockers"])
    print("Sources (job counts):", report["providers"])
    print("Required blockers (fields):", report["required_field_counts"])
    print("Affected jobs by blocker:", report["affected_job_counts"])
    print("Other failure categories:", report["nonjson_failure_categories"])
    print("No job IDs, URLs, applicant answers, raw field labels, or descriptions were printed.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Audit locally saved historical offline form attempts; never accesses employers.")
    parser.add_argument("--database", type=Path, default=core.DB,
                        help="Existing local agent SQLite database, opened read-only.")
    parser.add_argument("--since", metavar="YYYY-MM-DD")
    parser.add_argument("--through", metavar="YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--expected", type=int, default=20)
    parser.add_argument("--offline-only", action="store_true",
                        help="Select the most recent detached preview per job, ignoring later non-preview attempts.")
    args = parser.parse_args(argv)
    try:
        with closing(open_readonly(args.database)) as con:
            rows = selected_attempts(con, args.since, args.through,
                                     args.limit, offline_only=args.offline_only)
            report = summarize(rows, args.expected)
        render(report, args.since, args.through,
               offline_only=args.offline_only)
        return 0
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(2, "Pilot audit failed safely (" + type(error).__name__ +
                    "). Verify the existing local database and date options.\n")


if __name__ == "__main__":
    raise SystemExit(main())
