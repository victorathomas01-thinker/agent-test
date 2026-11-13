"""One-time, read-only public Lever per-job GET with synthetic SQLite only.

The two requests are limited to official Lever posting JSON; the first listing
sample is capped with ?limit=5. No applicant data, uploaded files or application
form interactions, ever.
"""
import json
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener
from unittest.mock import patch

from agent import core
from agent.employers import board_from_url
from agent.official_recheck import DenyRedirects, MAX_BYTES, recheck_saved

BOARD = "zoox"
LIST_URL = f"https://api.lever.co/v0/postings/{BOARD}?mode=json&limit=5"


def one_limited_public_listing_get():
    request = Request(LIST_URL, method="GET", headers={
        "User-Agent": "PersonalJobAgent/0.1 (one-time public single-job validation)",
        "Accept": "application/json",
    })
    with build_opener(DenyRedirects()).open(request, timeout=15) as response:
        if "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Official Lever listing sample was not JSON.")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Official Lever listing sample exceeded safe response limit.")
        data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Official Lever listing sample was not an array.")
    return data[:5]


def pick_candidate(entries):
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ident = entry.get("id")
        if not isinstance(ident, str):
            continue
        url = entry.get("applyUrl") or entry.get("hostedUrl")
        if board_from_url(url) != ("lever", BOARD):
            continue
        if not entry.get("text") or not (
                entry.get("descriptionPlain") or entry.get("description")):
            continue
        return {
            "id": f"lever:{BOARD}:{ident}",
            "title": entry["text"],
            "url": url,
        }
    return None


def check():
    cfg = core.with_defaults({})
    job = pick_candidate(one_limited_public_listing_get())
    if job is None:
        print("No strict official Lever identity found in the first five public listings.")
        return 2
    with tempfile.TemporaryDirectory(prefix="public-lever-synthetic-") as temp:
        path = Path(temp) / "synthetic.sqlite3"
        with patch.object(core, "DB", path):
            with closing(core.connect()) as con, con:
                con.execute(
                    """INSERT INTO jobs(id,source,company,title,location,url,description,
                       eligible,status,last_seen,notes)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (job["id"], "lever", "Synthetic Company", job["title"],
                     "Charlotte, NC", job["url"], "Synthetic prior listing text",
                     0, "found", "2026-10-01T00:00:00+00:00",
                     "No applicant facts in this synthetic database"),
                )
            result = recheck_saved(job["id"], cfg, database=path)
            if result.get("status") != "verified_listed" or not result.get("updated"):
                print("Lever single-posting verification outcome:",
                      result.get("status", "unknown"))
                return 2
            with closing(core.connect()) as con:
                record = con.execute(
                    "SELECT url, status, last_seen FROM jobs WHERE id=?",
                    (job["id"],),
                ).fetchone()
                observed = datetime.fromisoformat(
                    record["last_seen"].replace("Z", "+00:00")
                ).astimezone(timezone.utc).date()
                if observed != datetime.now(timezone.utc).date():
                    raise ValueError("Synthetic last_seen was not refreshed.")
                if record["url"] != job["url"] or record["status"] != "found":
                    raise ValueError("Official identity or job status changed.")
    print("VERIFIED: one official Lever posting ID and URL matched the detail API.")
    print("VERIFIED: synthetic SQLite observation updated, identity/status preserved.")
    print("At most two public API GETs; no applicant data, forms or submissions.")
    print("This does not prove the application form is open or the candidate is eligible.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(check())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Public Lever single-posting check unavailable:", type(error).__name__)
        raise SystemExit(2)
