"""One-off, low-volume public Workday source smoke test for Github Actions.

No credentials, personal profile, applicant database, or application traffic.
The probe prints only source-level counts/error types, never raw job descriptions,
applicant data, URL tokens, or employer form contents.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError

from agent.workday import read_workday_jobs, select_workday_sources

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "examples" / "charlotte_workday_sites.json"


def probe(sites, per_site, read=read_workday_jobs):
    checks = []
    for site in sites:
        company = site["company"]
        audit = {}
        try:
            rows = read(site["url"], company, per_site, audit=audit)
            verified = sum(job.get("verification") == "structured" for job in rows)
            status = ("blocked" if audit.get("blocked")
                      else "complete" if audit.get("complete")
                      else "partial" if rows else "empty_or_unavailable")
            checks.append(dict(company=company, status=status, records=len(rows),
                               verified=verified, reason=audit.get("reason", "unknown")))
        except (OSError, ValueError, KeyError, TypeError, HTTPError, URLError) as error:
            code = getattr(error, "code", None)
            phase = str(audit.get("phase") or "unknown")
            # HTTP response code and phase are sufficient to diagnose a source.
            # Never log exception strings, which may contain full URLs or headers.
            label = (f"HTTP_{code}" if isinstance(code, int)
                     else type(error).__name__)
            checks.append(dict(company=company,
                               status=("blocked" if code in (401, 403)
                                       or isinstance(error, PermissionError) else "error"),
                               records=0, verified=0, reason=f"{phase}:{label}"))
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded read-only public Workday smoke check.")
    parser.add_argument("--max-sites", type=int, default=2)
    parser.add_argument("--per-site", type=int, default=2)
    args = parser.parse_args(argv)
    if not 1 <= args.max_sites <= 3 or not 1 <= args.per_site <= 3:
        parser.error("Smoke checks are limited to 3 sites and 3 postings per site.")
    sites = select_workday_sources(json.loads(BANK.read_text(encoding="utf-8")), args.max_sites)
    results = probe(sites, args.per_site)
    print("PUBLIC WORKDAY READ-ONLY SMOKE CHECK")
    print("This tests only access to a small public slice, not current vacancy census.")
    for result in results:
        print("{company}: {status}; collected={records}; verified_details={verified}; {reason}".format(**result))
    summary = Counter(item["status"] for item in results)
    print("Source statuses:", dict(sorted(summary.items())))
    verified_total = sum(item["verified"] for item in results)
    print(f"Total verified public detail reads: {verified_total}")
    if verified_total == 0:
        print("NO LIVE VERIFIED DETAILS: candidate employer discovery remains unvalidated.")
        return 2
    print("At least one live source returned verified public detail. This does not establish eligibility, "
          "posting openness, or reliable coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
