"""Local, read-only beta readiness overview.

No public network calls, scheduling, database initialization, applicant values,
or resume contents. Counts only and explicit next steps for first-time users.
"""
from __future__ import annotations

import json
import re
import sys
from contextlib import closing
from pathlib import Path

from agent import core, form_diagnostics, local_safety, posting_freshness


def inspect(root: Path):
    root = Path(root).expanduser().resolve()
    database, config = root / "agent.sqlite3", root / "config.json"
    safety = local_safety.inspect(database, config)
    report = {
        "database": safety["database"], "config": safety["config"],
        "stored_jobs": safety["jobs"], "historical_attempts": safety["attempts"],
        "profile_ready": False, "resume_present": False,
        "pending_opportunities": 0, "source_review_required": 0,
        "dry_run_previews": 0, "required_blockers": 0,
    }
    if safety["config"] == "valid":
        try:
            raw = json.loads(config.read_text(encoding="utf-8-sig"))
            profile = raw.get("profile", {})
            if isinstance(profile, dict):
                name = (
                    isinstance(profile.get("first_name"), str)
                    and bool(profile["first_name"].strip())
                    and isinstance(profile.get("last_name"), str)
                    and bool(profile["last_name"].strip())
                )
                email = profile.get("email")
                report["profile_ready"] = bool(
                    name and isinstance(email, str) and re.fullmatch(
                        r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()))
                resume = profile.get("resume_path")
                if isinstance(resume, str) and resume.strip():
                    candidate = Path(resume).expanduser()
                    if not candidate.is_absolute():
                        candidate = root / candidate
                    report["resume_present"] = (
                        candidate.is_file() and candidate.suffix.casefold() in
                        {".pdf", ".doc", ".docx", ".rtf", ".txt"})
        except (OSError, ValueError, TypeError):
            report["config"] = "invalid"

    if safety["database"] == "ready":
        try:
            with closing(local_safety.readonly_connection(database)) as con:
                report["pending_opportunities"] = con.execute(
                    """SELECT COUNT(*) FROM jobs
                       WHERE status='found' AND eligible=1
                         AND submitted_at IS NULL"""
                ).fetchone()[0]
                report["source_review_required"] = sum(
                    1 for job in con.execute(
                        """SELECT j.source,j.last_seen,j.description,
                                  COALESCE(w.deadline,'') AS deadline
                           FROM jobs j LEFT JOIN web_checks w ON w.job_id=j.id
                           WHERE j.status IN ('found','prepared','needs_review')"""
                    ) if (
                        posting_freshness.risk_reasons(dict(job))
                        or (job["source"] in {"greenhouse", "lever"}
                            and posting_freshness.observation_day(job["last_seen"]) is None)
                    )
                )
                forms = form_diagnostics.summarize(con, limit=500)
                report["dry_run_previews"] = forms["dry_run_previews"]
                report["required_blockers"] = sum(forms["required_blockers"].values())
        except (OSError, ValueError, TypeError):
            report["database"] = "unreadable_at_beta_status"
    return report


def print_status(report):
    print("PERSONAL JOB AGENT BETA STATUS — aggregate local checks only")
    print("Database:", report["database"], "| configuration:", report["config"])
    print("Applicant name/email fields configured:",
          "yes" if report["profile_ready"] else "not yet")
    print("Supported local resume file found:",
          "yes" if report["resume_present"] else "not yet")
    print("Stored job records:", report["stored_jobs"],
          "| historical attempts:", report["historical_attempts"])
    print("Cached eligible unsubmitted job records:",
          report["pending_opportunities"], "(not confirmed open)")
    print("Jobs needing a fresh source/deadline check:",
          report["source_review_required"])
    print("Latest offline form previews:", report["dry_run_previews"],
          "| unresolved required blockers:", report["required_blockers"])
    if report["config"] == "valid" and report["database"] == "ready":
        if not (report["profile_ready"] and report["resume_present"]):
            print("Next: set and confirm local profile fields and master resume, then rerun beta-status.")
        elif report["pending_opportunities"] == 0:
            print("Next: run manual public discovery, inspect rankings, and select one safe preview.")
        else:
            print("Next: inspect list --all, open the local dashboard, and try ONE offline preview.")
    else:
        print("Next: run 'python main.py doctor'; do not initialize or migrate an unsafe database.")
    print("This is a local beta readiness indicator, not real-form acceptance or application submission.")
    print("Live submission remains disabled under the beta install guard.")


def main(argv=None):
    from argparse import ArgumentParser
    parser = ArgumentParser(description="Read-only local beta readiness overview.")
    parser.add_argument("--root", type=Path, default=core.ROOT,
                        help="Directory with the local agent config and database.")
    args = parser.parse_args(argv)
    report = inspect(args.root)
    print_status(report)
    return 0 if report["database"] == "ready" and report["config"] == "valid" else 2


if __name__ == "__main__":
    sys.exit(main())
