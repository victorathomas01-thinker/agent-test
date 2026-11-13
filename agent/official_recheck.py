"""One-job public ATS recheck; only a confirmed matching listing can refresh SQLite.

No applications, logins, cookies, personal information, browser sessions or
unbounded board scans. Failed/404/blocked requests never mark jobs as closed.
Only exact official Greenhouse/Lever posting API GETs are supported initially.
"""
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import core
from .employers import board_from_url
from .pilot_audit import open_readonly
from .posting_freshness import parse_day

RECHECKABLE = {'found', 'prepared', 'needs_review', 'failed'}
UUID = re.compile(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}')
SLUG = re.compile(r'[a-zA-Z0-9_-]{1,80}')
MAX_BYTES = 2_000_000


class DenyRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even a same-origin redirect is not proof this particular API job
        # exists. Do not follow redirects to login, another job or an intranet.
        raise ValueError('Official posting API redirected; no job verified.')


def public_api_json(url):
    """Bounded public GET only. URL is constructed by target_for(), not input."""
    host = urlsplit(url).hostname
    if host not in {'boards-api.greenhouse.io', 'api.lever.co'}:
        raise ValueError('Unsupported public posting API origin.')
    request = Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'PersonalJobAgent/0.1 (one-job public listing verification)',
    }, method='GET')
    with build_opener(DenyRedirects()).open(request, timeout=15) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Official posting response exceeded safe limit.')
        content_type = response.headers.get('Content-Type', '').lower()
        if 'json' not in content_type:
            raise ValueError('Official posting response was not JSON.')
        data = json.loads(raw.decode('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Expected one structured posting.')
    return data


def target_for(job, cfg):
    """Return the only approved single-job endpoint, or None without traffic."""
    source, _, suffix = str(job.get('id') or '').partition(':')
    parts = suffix.split(':')
    if (source not in {'greenhouse', 'lever'} or
            source != job.get('source') or len(parts) != 2):
        return None
    slug, identifier = parts
    if not SLUG.fullmatch(slug):
        return None
    if source == 'greenhouse':
        if not re.fullmatch(r'[0-9]{1,20}', identifier):
            return None
    elif not UUID.fullmatch(identifier):
        return None

    url = job.get('url') or ''
    board = board_from_url(url)
    if board != (source, slug.lower()):
        hosts = (cfg.get('discovery', {}).get('greenhouse_custom_hosts', {})
                 if source == 'greenhouse' else {})
        if (source != 'greenhouse' or not core.approved_greenhouse_hosted_url(
                url, identifier, hosts.get(slug.casefold(), []))):
            return None
    if source == 'greenhouse':
        return (f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/'
                f'{identifier}?content=true')
    return f'https://api.lever.co/v0/postings/{slug}/{identifier}?mode=json'


def _string(value, limit):
    return value if isinstance(value, str) and 0 < len(value.strip()) <= limit else None


def normalize_response(job, cfg, response):
    """Prove returned posting ID, job URL and employer board match saved row."""
    source = job['source']
    identifier = job['id'].rsplit(':', 1)[-1]
    payload_id = response.get('id')
    if not isinstance(payload_id, (str, int)) or str(payload_id).lower() != identifier.lower():
        return None
    if source == 'greenhouse':
        title = _string(response.get('title'), 400)
        location = response.get('location') or {}
        if not isinstance(location, dict):
            return None
        location = location.get('name') or ''
        url = response.get('absolute_url')
        description = response.get('content')
        updated_deadline = response.get('application_deadline')
    else:
        title = _string(response.get('text'), 400)
        categories = response.get('categories') or {}
        if not isinstance(categories, dict):
            return None
        location = core.lever_location(response)
        url = response.get('applyUrl') or response.get('hostedUrl')
        description = response.get('descriptionPlain') or response.get('description')
        updated_deadline = None
    if (not title or not isinstance(location, str) or len(location) > 500
            or not isinstance(url, str) or not isinstance(description, str)
            or len(description) > MAX_BYTES):
        return None
    if core.canonical_url(url) != core.canonical_url(job['url']):
        return None
    if source == 'greenhouse':
        slug = job['id'].split(':')[1]
        if board_from_url(url) != ('greenhouse', slug.lower()):
            hosts = cfg.get('discovery', {}).get('greenhouse_custom_hosts', {})
            if not core.approved_greenhouse_hosted_url(
                    url, identifier, hosts.get(slug.casefold(), [])):
                return None
    elif board_from_url(url) != ('lever', job['id'].split(':')[1].lower()):
        return None

    deadline = str(job.get('deadline') or '')
    if updated_deadline:
        parsed = parse_day(updated_deadline)
        if parsed is None:
            # Unparseable new deadline metadata is a blocker, not permission
            # to replace an old deadline with an unsafe value.
            return None
        deadline = parsed.isoformat()
    return {
        'title': title,
        'location': location,
        'description': core.plain(description),
        'deadline': deadline,
    }


def recheck_saved(job_id, cfg, *, database=None, fetch=public_api_json, now=None):
    """One-off check with safe result labels; mutate only on exact positive proof.

    Run from the explicitly selected CLI command. No scheduled or automatic
    employer requests. Source failures and missing jobs do not change SQLite.
    """
    if not isinstance(job_id, str) or len(job_id) > 240:
        raise ValueError('Provide a short official listing ID.')
    database = Path(database if database is not None else core.DB)
    with closing(open_readonly(database)) as con:
        original = con.execute(
            """SELECT j.*, COALESCE(w.deadline,'') AS deadline, w.verification
               FROM jobs j LEFT JOIN web_checks w ON w.job_id=j.id WHERE j.id=?""",
            (job_id,)
        ).fetchone()
        if original is None:
            return {'status': 'not_in_local_database', 'updated': False}
        job = dict(original)

    if job['status'] not in RECHECKABLE or job['submitted_at']:
        return {'status': 'already_tracked_or_closed', 'updated': False}
    endpoint = target_for(job, cfg)
    if not endpoint:
        return {'status': 'unsupported_or_unsafe_source', 'updated': False}
    try:
        response = fetch(endpoint)
    except HTTPError as error:
        if error.code in (404, 410):
            return {'status': 'not_found_unconfirmed', 'updated': False}
        if error.code in (401, 403):
            return {'status': 'access_denied', 'updated': False}
        if error.code == 429:
            return {'status': 'rate_limited', 'updated': False}
        return {'status': 'source_unavailable', 'updated': False}
    except (URLError, OSError, ValueError, TypeError, KeyError, TimeoutError):
        return {'status': 'source_unavailable', 'updated': False}

    if not isinstance(response, dict):
        return {'status': 'invalid_source_response', 'updated': False}
    updated = normalize_response(job, cfg, response)
    if updated is None:
        return {'status': 'listing_identity_or_metadata_mismatch', 'updated': False}
    fresh_at = now() if now is not None else core.utc_now()
    if core.canonical_url(job['url']) == '':
        return {'status': 'listing_identity_or_metadata_mismatch', 'updated': False}
    from .posting_freshness import observation_day
    if observation_day(fresh_at) is None:
        raise ValueError('Fresh observation must be an offset-aware UTC timestamp.')

    with closing(sqlite3.connect(database, timeout=10)) as con:
        con.row_factory = sqlite3.Row
        with con:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute(
                """SELECT j.*, COALESCE(w.deadline,'') AS deadline, w.verification
                   FROM jobs j LEFT JOIN web_checks w ON w.job_id=j.id WHERE j.id=?""",
                (job_id,)
            ).fetchone()
            if (current is None or current['url'] != job['url']
                    or current['status'] not in RECHECKABLE
                    or current['submitted_at'] is not None
                    or current['last_seen'] != job['last_seen']
                    or current['description'] != job['description']
                    or str(current['deadline'] or '') != str(job['deadline'] or '')):
                return {'status': 'listing_changed_during_recheck', 'updated': False}
            snapshot = dict(current)
            snapshot.update(updated)
            snapshot['last_seen'] = fresh_at
            snapshot['verification'] = 'api_listing'
            score, eligible, reason = core.evaluate(snapshot, cfg)
            changed = con.execute(
                """UPDATE jobs
                   SET title=?,location=?,description=?,last_seen=?,
                       score=?,eligible=?,reason=?
                   WHERE id=? AND source=? AND url=? AND status=?
                     AND submitted_at IS NULL AND last_seen IS ?""",
                (updated['title'], updated['location'], updated['description'],
                 fresh_at, score, int(eligible), reason, job_id, job['source'],
                 job['url'], job['status'], job['last_seen'])
            ).rowcount
            if changed != 1:
                return {'status': 'listing_changed_during_recheck', 'updated': False}
            con.execute(
                """INSERT INTO web_checks(job_id,verification,deadline)
                   VALUES (?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET
                     verification=excluded.verification,deadline=excluded.deadline""",
                (job_id, 'api_listing', updated['deadline'])
            )
    return {'status': 'verified_listed', 'updated': True,
            'eligible_after_recheck': bool(eligible)}


def print_result(result):
    print('Official single-job public source recheck:', result['status'])
    if result.get('updated'):
        print('Stored listing re-observed with matching identity; eligibility recalculated.')
        print('Eligible under local saved rules:', result['eligible_after_recheck'])
    else:
        print('Existing saved posting, status, and applicant data were not changed.')
    if result['status'] == 'not_found_unconfirmed':
        print('The public API did not return this posting; this is not proof of closure.')
    print('No application fields, resumes, credentials or submissions were sent.')
