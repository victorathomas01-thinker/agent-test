"""Bounded public-facing Workday career-site discovery; no login or apply actions.

Workday CXS is an observed careers-page JSON endpoint, not a documented
stable public API. Every URL is derived from an explicitly configured official
myworkdayjobs.com site. All HTTP responses are untrusted and validated.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from time import sleep
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

USER_AGENT = "PersonalJobAgent/0.1 (public careers discovery)"
HOST = re.compile(r"^([a-z0-9][a-z0-9-]{0,62})\.wd\d{1,3}\.myworkdayjobs\.com$", re.I)
SITE = re.compile(r"^[a-zA-Z0-9_-]{1,90}$")
LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
EXTERNAL_PATH = re.compile(r"^/job/[A-Za-z0-9._~/%-]{1,350}$")


@dataclass(frozen=True)
class WorkdayBoard:
    origin: str
    host: str
    tenant: str
    site: str
    locale: str
    api: str


def parse_board(url):
    """Only explicit, public company career-board roots, never arbitrary URLs."""
    if not isinstance(url, str):
        raise ValueError("A public Workday career-board URL is required.")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        match = HOST.fullmatch(host)
        if (parsed.scheme != "https" or not match or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment):
            raise ValueError("Only official public Workday board URLs are supported.")
    except ValueError as error:
        raise ValueError("Only official public Workday board URLs are supported.") from error
    segments = parsed.path.strip("/").split("/")
    if len(segments) == 1:
        locale, site = "en-US", segments[0]
    elif len(segments) == 2 and LOCALE.fullmatch(segments[0]):
        locale, site = segments
    else:
        raise ValueError("Configure the root Workday career site, not a job link.")
    if not SITE.fullmatch(site):
        raise ValueError("Invalid Workday career site name.")
    tenant = match[1]
    origin = "https://" + host
    return WorkdayBoard(origin, host, tenant, site, locale,
                        f"{origin}/wday/cxs/{tenant}/{site}")


def safe_external_path(value):
    """Forbid external origins, encoded traversal, query strings and redirects."""
    if not isinstance(value, str) or not EXTERNAL_PATH.fullmatch(value):
        return None
    path = unquote(value)
    if ("//" in path or "\\" in path or "?" in path or "#" in path
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or any(part in ("", ".", "..") for part in path.split("/")[1:])):
        return None
    return value


def _request(url, method="GET", data=None, origin=None, size_limit=2_000_000):
    class SameOrigin(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = urlsplit(newurl)
            if (target.scheme != "https" or
                    target.netloc.casefold() != urlsplit(origin).netloc.casefold()):
                raise ValueError("Workday endpoint redirected outside the configured origin.")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    if not origin or not url.startswith(origin + "/"):
        raise ValueError("Workday request outside the configured origin.")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=payload, headers=headers, method=method)
    with build_opener(SameOrigin()).open(request, timeout=15) as response:
        raw = response.read(size_limit + 1)
        if len(raw) > size_limit:
            raise ValueError("Workday response exceeded bounded size.")
        return raw


def public_json(method, url, data, board):
    raw = _request(url, method, data, board.origin)
    result = json.loads(raw.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Unexpected Workday JSON response.")
    return result


def robots_text(board):
    try:
        raw = _request(board.origin + "/robots.txt", origin=board.origin, size_limit=100_000)
    except HTTPError as error:
        if error.code == 404:
            return ""
        raise
    return raw.decode("utf-8", errors="replace")


def read_workday_jobs(board_url, company, maximum, *,
                      fetch_json=public_json, fetch_robots=robots_text,
                      pause=sleep, audit=None):
    """Collect a bounded preview of public listings and verified detail pages.

    Missing details remain explicitly unverified. Never claim all listings
    when capped, blocked, paginated incompletely or missing a trustworthy total.
    """
    board = parse_board(board_url)
    if not isinstance(company, str) or not company.strip() or len(company) > 120:
        raise ValueError("An explicit employer name is required.")
    if not isinstance(maximum, int) or not 1 <= maximum <= 60:
        raise ValueError("Workday job limit must be from 1 to 60.")

    robots = RobotFileParser()
    robots.parse(fetch_robots(board).splitlines())
    list_endpoint = board.api + "/jobs"
    if not robots.can_fetch(USER_AGENT, list_endpoint):
        if audit is not None:
            audit.update(blocked=True, complete=False, returned=0, reason="robots_denied")
        return []

    summaries, seen = [], set()
    total, complete, offset = None, True, 0
    while len(summaries) < maximum:
        # Workday publicly observed CXS list endpoint uses pages of 20.
        page_size = 20
        try:
            payload = fetch_json("POST", list_endpoint,
                                 {"appliedFacets": {}, "limit": page_size,
                                  "offset": offset, "searchText": ""}, board)
            rows = payload.get("jobPostings")
            if not isinstance(rows, list) or len(rows) > page_size:
                raise ValueError("Malformed Workday public postings page.")
            if offset == 0:
                count = payload.get("total")
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                    total = count
                else:
                    complete = False
            if not rows:
                if total is None or offset < total:
                    complete = False
                break
            for entry in rows:
                if not isinstance(entry, dict):
                    complete = False
                    continue
                external = safe_external_path(entry.get("externalPath"))
                if not external or external in seen:
                    complete = False
                    continue
                seen.add(external)
                if len(summaries) >= maximum:
                    complete = False
                    break
                summaries.append((external, entry))
            offset += len(rows)
            if total is not None and offset >= total:
                break
            if len(rows) < page_size:
                complete = False
                break
            if offset >= 2000:
                complete = False
                break
            pause(1)
        except (OSError, ValueError, TypeError, KeyError):
            if not summaries:
                raise
            complete = False
            break

    if total is None or offset < total or len(summaries) < min(offset, maximum):
        complete = False

    jobs = []
    for i, (external, entry) in enumerate(summaries):
        listing_url = f"{board.origin}/{board.locale}/{board.site}{external}"
        detail_url = board.api + external
        title = entry.get("title") if isinstance(entry.get("title"), str) else ""
        location = entry.get("locationsText") if isinstance(entry.get("locationsText"), str) else ""
        doc = {}
        verification = "unverified"
        if robots.can_fetch(USER_AGENT, detail_url):
            try:
                pause(1)
                result = fetch_json("GET", detail_url, None, board)
                info = result.get("jobPostingInfo")
                if isinstance(info, dict) and isinstance(info.get("jobDescription"), str):
                    doc = info
                    verification = "structured"
                else:
                    complete = False
            except (OSError, ValueError, TypeError, KeyError):
                complete = False
        else:
            complete = False

        # Stable within a board across collection runs; no user data in keys.
        identity = hashlib.sha256((board.api + external).encode("utf-8")).hexdigest()[:24]
        jobs.append({
            "id": "workday:" + identity,
            "source": "workday", "company": company.strip(),
            "title": str(doc.get("title") or title),
            "location": str(doc.get("location") or location),
            "url": listing_url,
            "description": str(doc.get("jobDescription") or ""),
            "published_at": str(doc.get("startDate") or ""),
            "workplace": "",
            "employment_type": str(doc.get("timeType") or ""),
            "salary": "",
            "verification": verification,
        })

    if audit is not None:
        audit.update(complete=bool(complete and total is not None and offset >= total
                                   and all(x["verification"] == "structured" for x in jobs)),
                     blocked=False, returned=len(jobs), total=total,
                     reason=("all_public_pages_and_details" if complete and total is not None
                             and offset >= total and all(x["verification"] == "structured" for x in jobs)
                             else "bounded_or_incomplete_cxs"))
    return jobs

def select_workday_sources(payload, maximum):
    """Validate and deduplicate an explicit public employer-site source bank.

    No employer URLs are guessed. This selector neither fetches nor connects
    to any career site, and cannot change the saved agent configuration.
    """
    if not isinstance(maximum, int) or not 1 <= maximum <= 50:
        raise ValueError("Select between 1 and 50 public employer boards.")
    if not isinstance(payload, list):
        raise ValueError("Workday sources file must be a JSON list.")
    selected, seen = [], set()
    for candidate in payload:
        if not isinstance(candidate, dict):
            raise ValueError("Each Workday source must be an object.")
        company, url = candidate.get("company"), candidate.get("url")
        if not isinstance(company, str) or not company.strip() or len(company.strip()) > 120:
            raise ValueError("Workday source has an invalid employer name.")
        board = parse_board(url)
        if board.api in seen:
            continue
        selected.append({"company": company.strip(), "url": url})
        seen.add(board.api)
        if len(selected) >= maximum:
            break
    return selected
