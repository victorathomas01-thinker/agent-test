"""One-time public Greenhouse application-form structure check, no input.

Uses one bounded board listing GET and a fresh, read-only Chromium context.
The browser allows GET/HEAD only to exact Greenhouse public-host names;
blocks POST, upload, cookies from user profiles, analytics and external hosts.
Only aggregate control counts leave the process. No form labels are logged.
"""
import json
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from urllib.robotparser import RobotFileParser

from agent.browser import field_metadata, find_form_frame
from agent.employers import board_from_url
from agent.official_recheck import DenyRedirects, MAX_BYTES
from agent.sessions import requires_sign_in
from scripts.probe_public_form import classify_fields

BOARD = "canonical"
GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
API = f"https://boards-api.greenhouse.io/v1/boards/{BOARD}/jobs?content=false"
USER_AGENT = "PersonalJobAgent/0.1 (one-time read-only public Greenhouse form structure)"


def public_candidate():
    """Select one strictly validated public board listing, no raw job data logs."""
    request = Request(API, method="GET", headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
    })
    with build_opener(DenyRedirects()).open(request, timeout=15) as response:
        if "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("Official Greenhouse listing was not JSON.")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("Official board exceeded bounded response size.")
        payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError("Unexpected public Greenhouse board response.")
    for job in payload["jobs"][:50]:
        if not isinstance(job, dict) or not re.fullmatch(r"[0-9]{1,20}", str(job.get("id", ""))):
            continue
        url = job.get("absolute_url")
        if board_from_url(url) != ("greenhouse", BOARD):
            continue
        parsed = urlsplit(url)
        if parsed.hostname not in GREENHOUSE_HOSTS or parsed.query or parsed.fragment:
            continue
        if parsed.path.rstrip("/").rsplit("/", 1)[-1] != str(job["id"]):
            continue
        return url
    return None


def robots_allows(host, url):
    """Fail closed for unreachable, redirected or explicitly denied policies."""
    if host not in GREENHOUSE_HOSTS or urlsplit(url).hostname != host:
        raise ValueError("Unapproved source for robots decision.")
    robots = f"https://{host}/robots.txt"
    request = Request(robots, method="GET", headers={
        "User-Agent": USER_AGENT, "Accept": "text/plain, */*",
    })
    try:
        with build_opener(DenyRedirects()).open(request, timeout=15) as response:
            body = response.read(100_001)
        if len(body) > 100_000:
            raise ValueError("Robots rules exceeded safe limit.")
        parser = RobotFileParser()
        parser.parse(body.decode("utf-8", errors="replace").splitlines())
        return parser.can_fetch(USER_AGENT, url)
    except HTTPError as error:
        # Missing robots.txt means ordinary public GET is permitted.
        return error.code == 404


def probe():
    from playwright.sync_api import sync_playwright

    url = public_candidate()
    if not url:
        return {"status": "no_strict_public_listing", "field_summary": None}
    parsed = urlsplit(url)
    if not robots_allows(parsed.hostname, url):
        return {"status": "robots_denied", "field_summary": None}
    # A canonical Greenhouse board may redirect between these two official
    # aliases, so require both hosts' robots rules before navigation.
    other = next(name for name in GREENHOUSE_HOSTS if name != parsed.hostname)
    alt = url.replace(parsed.hostname, other, 1)
    if not robots_allows(other, alt):
        return {"status": "robots_denied_alias", "field_summary": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(service_workers="block", accept_downloads=False)
            ctx.route("**/*", lambda route: route.continue_()
                      if route.request.method in {"GET", "HEAD"}
                      and urlsplit(route.request.url).scheme == "https"
                      and urlsplit(route.request.url).hostname in GREENHOUSE_HOSTS
                      and urlsplit(route.request.url).username is None
                      else route.abort())
            page = ctx.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            if response is None or not response.ok:
                return {"status": "page_unavailable", "field_summary": None}
            target = urlsplit(page.url)
            if (board_from_url(page.url) != ("greenhouse", BOARD)
                    or target.path.rstrip("/").rsplit("/", 1)[-1] != parsed.path.rstrip("/").rsplit("/", 1)[-1]):
                return {"status": "unexpected_page", "field_summary": None}
            if requires_sign_in(page):
                return {"status": "login_required", "field_summary": None}
            form = find_form_frame(page)
            if form is None:
                return {"status": "form_not_found", "field_summary": None}
            summary = classify_fields(field_metadata(form))
            return {"status": "form_observed" if summary["visible_fields"] else "form_not_found",
                    "field_summary": summary}
        finally:
            browser.close()


def main():
    try:
        result = probe()
    except Exception as error:
        print("One-time Greenhouse form structure unavailable:", type(error).__name__)
        return 2
    print("ONE OFFICIAL PUBLIC GREENHOUSE FORM — read-only metadata, no applicant data")
    print("Status:", result["status"])
    if result["field_summary"] is not None:
        info = result["field_summary"]
        print("Visible fields:", info["visible_fields"])
        print("Required fields:", info["required_fields"])
        print("Required checkbox attestations/choices:",
              info["required_checkbox_attestations_or_choices"])
        print("Required custom/unknown:", info["required_custom_or_unknown"])
        print("Types:", info["types"])
        print("Required types:", info["required_types"])
        print("Observed step needs human/verified choices:",
              info["requires_human_decisions_on_observed_step"])
    print("Zero inputs, uploads, clicks, submissions, browser profile sharing.")
    print("No individual questions or posting identity were logged.")
    return 0 if result["status"] == "form_observed" else 2


if __name__ == "__main__":
    sys.exit(main())
