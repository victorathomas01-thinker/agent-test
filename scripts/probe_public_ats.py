"""One-off low-volume check of two explicitly selected official public ATS APIs.

No applicant configuration, database access, personal information, application
forms, browser sessions, or job submissions.
"""
import sys
from urllib.error import HTTPError, URLError

from agent import core

# Fixed, existing configured public boards; no user-supplied URLs.
SOURCES = (("greenhouse", "duolingo"), ("lever", "zoox"))


def probe(fetch=core.fetch_board):
    results = []
    for provider, slug in SOURCES:
        audit = {}
        try:
            jobs = fetch(provider, slug, slug, 4, audit=audit)
            results.append({
                "source": provider + ":" + slug,
                "status": "complete" if audit.get("complete")
                          else "partial" if jobs else "empty_or_incomplete",
                "sample_records": len(jobs),
                "plausible_urls": sum(core.valid_application_url(j.get("url", "")) for j in jobs),
                "reason": str(audit.get("reason") or "unknown"),
            })
        except (HTTPError, URLError, OSError, ValueError, KeyError, TypeError) as error:
            status = getattr(error, "code", None)
            results.append({
                "source": provider + ":" + slug,
                "status": "blocked" if status in (401, 403) else "error",
                "sample_records": 0, "plausible_urls": 0,
                "reason": f"HTTP_{status}" if isinstance(status, int) else type(error).__name__,
            })
    return results


def main():
    results = probe()
    print("OFFICIAL ATS API READ-ONLY SMOKE CHECK — bounded to 2 boards and 4 postings each")
    for item in results:
        print("{source}: {status}; sample={sample_records}; valid_https_urls={plausible_urls}; {reason}".format(**item))
    verified = sum(row["plausible_urls"] for row in results)
    if not verified:
        print("NO VERIFIED PUBLIC API LISTINGS. Official ATS access still unvalidated.")
        return 2
    print(f"{verified} posting URLs passed basic HTTPS validation. "
          "This does NOT verify open status, applicant eligibility, or full coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
