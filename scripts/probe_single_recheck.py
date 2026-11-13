"""One-time public Greenhouse single-posting verification on a synthetic DB.

Only two official, read-only API GET requests. The GitHub workflow is path-
gated, unscheduled and manual-by-code-review. Never accesses applicant records
or downloads application questions, contacts, resumes, files or credentials.
"""
import json
import re
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener

from agent import core
from agent.employers import board_from_url
from agent.official_recheck import DenyRedirects, MAX_BYTES, recheck_saved

BOARD = "duolingo"
LIST_URL = f"https://boards-api.greenhouse.io/v1/boards/{BOARD}/jobs?content=false"


def public_first_candidate(data, cfg):
    if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
        return None
    for entry in data['jobs'][:100]:
        if not isinstance(entry, dict):
            continue
        ident = str(entry.get('id') or '')
        url = entry.get('absolute_url') or ''
        if not re.fullmatch(r'[0-9]{1,20}', ident):
            continue
        if (board_from_url(url) != ('greenhouse', BOARD)
                and not core.approved_greenhouse_hosted_url(
                    url, ident, cfg['discovery']['greenhouse_custom_hosts'].get(BOARD, []))):
            continue
        if not isinstance(entry.get('title'), str) or not entry['title'].strip():
            continue
        return {'id': f'greenhouse:{BOARD}:{ident}',
                'url': url,
                'title': entry['title']}
    return None


def one_bounded_board_get():
    request = Request(LIST_URL, method='GET', headers={
        "User-Agent": "PersonalJobAgent/0.1 (one-time public API verification)",
        "Accept": "application/json",
    })
    with build_opener(DenyRedirects()).open(request, timeout=15) as response:
        if 'json' not in response.headers.get('Content-Type', '').lower():
            raise ValueError('Public board did not return JSON.')
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Public board listing exceeded request size cap.')
        return json.loads(raw.decode('utf-8'))


def check():
    cfg = core.with_defaults({})
    listing = public_first_candidate(one_bounded_board_get(), cfg)
    if listing is None:
        print("No safe official public posting was found in the bounded listing sample.")
        return 2
    with tempfile.TemporaryDirectory(prefix="single-posting-public-smoke-") as directory:
        path = Path(directory) / "synthetic.sqlite3"
        from unittest.mock import patch
        with patch.object(core, 'DB', path):
            with closing(core.connect()) as con, con:
                con.execute(
                    """INSERT INTO jobs(id,source,company,title,location,url,description,
                       eligible,status,last_seen,notes)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (listing['id'], 'greenhouse', 'Synthetic Company',
                     listing['title'], 'Charlotte, NC', listing['url'],
                     'Synthetic previous description', 0, 'found',
                     '2026-10-01T12:00:00+00:00', 'Synthetic, not applicant data')
                )
            result = recheck_saved(listing['id'], cfg, database=path)
            if result['status'] != 'verified_listed' or not result['updated']:
                print('Single public posting recheck result:', result['status'])
                return 2
            with closing(core.connect()) as con:
                row = con.execute(
                    'SELECT last_seen, status, url FROM jobs WHERE id=?', (listing['id'],)
                ).fetchone()
                observed = datetime.fromisoformat(row['last_seen'].replace('Z', '+00:00'))
                if observed.astimezone(timezone.utc).date() != datetime.now(timezone.utc).date():
                    print("A public posting was verified but the synthetic local refresh was not observed.")
                    return 2
                if row['status'] != 'found' or row['url'] != listing['url']:
                    print("Synthetic posting changed identity or status.")
                    return 2
    print("VERIFIED: one exact Greenhouse public posting ID, URL and detail GET matched.")
    print("VERIFIED: synthetic SQLite timestamp refreshed without changing job URL or status.")
    print("Two public GET requests, zero application requests, no private applicant data.")
    print("This does not confirm employer application-form availability or job eligibility.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(check())
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Don't print exception messages: some errors embed URLs or headers.
        print("Public posting smoke check unavailable:", type(error).__name__)
        raise SystemExit(2)
