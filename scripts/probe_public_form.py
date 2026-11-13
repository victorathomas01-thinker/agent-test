"""Inspect one public application form's structure without entering information.

One-off public read-only diagnostic. No applicant profile, credentials, uploads,
form filling, clicking, submission or private database writes.
"""
import sys
from collections import Counter
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from agent import core
from agent.browser import SUPPORTED, field_metadata, find_form_frame
from agent.sessions import requires_sign_in
from agent.submission import official_job_url

USER_AGENT = "PersonalJobAgent/0.1 (read-only application-form structure check)"
ORIGIN = "https://jobs.lever.co"
PUBLIC_BOARD = ("lever", "zoox")


def robots_permits(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "jobs.lever.co"
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)):
        raise ValueError("Only validated public Lever application pages can be inspected.")
    path = ORIGIN + "/robots.txt"
    request = Request(path, headers={"User-Agent": USER_AGENT,
                                     "Accept": "text/plain, */*"})
    try:
        with urlopen(request, timeout=15) as response:
            if response.geturl() != path:
                raise ValueError("Robots policy redirected to an unapproved URL.")
            raw = response.read(100_001)
            if len(raw) > 100_000:
                raise ValueError("Robots policy exceeded bounded size.")
    except HTTPError as error:
        if error.code != 404:
            raise
        raw = b""
    parser = RobotFileParser()
    parser.parse(raw.decode("utf-8", errors="replace").splitlines())
    return parser.can_fetch(USER_AGENT, url)


def classify_fields(fields):
    """Aggregate form types only: no questions, IDs, labels or answers."""
    counts, required = Counter(), Counter()
    visible = 0
    unsupported = 0
    for row in fields:
        if not row.get("visible") or row.get("disabled"):
            continue
        kind = str(row.get("type") or "unknown")
        if kind.startswith("custom"):
            kind = "custom"
        # Group names intentionally omit all employer field labels.
        if kind not in SUPPORTED and kind not in {
            "radio", "checkbox", "file", "hidden", "submit", "button",
            "reset", "image", "custom",
        }:
            kind = "other"
        if kind in {"hidden", "submit", "button", "reset", "image"}:
            continue
        visible += 1
        counts[kind] += 1
        if row.get("required") is True:
            required[kind] += 1
            if kind in {"custom", "other"}:
                unsupported += 1
    return {
        "visible_fields": visible,
        "required_fields": sum(required.values()),
        "required_custom_or_unknown": unsupported,
        "types": dict(sorted(counts.items())),
        "required_types": dict(sorted(required.items())),
    }


def probe():
    """Observe a single publicly listed direct Lever apply page, no interaction."""
    from playwright.sync_api import sync_playwright

    provider, slug = PUBLIC_BOARD
    jobs = core.fetch_board(provider, slug, slug, 1)
    approved = [job for job in jobs if official_job_url(job)]
    if not approved:
        return {"status": "no_direct_public_apply_url", "field_summary": None}
    url = approved[0]["url"]
    if not robots_permits(url):
        return {"status": "robots_denied", "field_summary": None}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block", accept_downloads=False)
            # GET/HEAD requests to an exact approved public ATS host only.
            # In particular, block every POST, PUT, DELETE and non-official
            # host request, even if the employer page tries one via JS.
            context.route("**/*", lambda route: (
                route.continue_() if route.request.method in ("GET", "HEAD")
                and urlsplit(route.request.url).scheme == "https"
                and urlsplit(route.request.url).hostname == "jobs.lever.co"
                else route.abort()
            ))
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            if response is None or not response.ok:
                return {"status": "page_unavailable", "field_summary": None}
            if page.url != url:
                return {"status": "unexpected_redirect", "field_summary": None}
            if requires_sign_in(page):
                return {"status": "login_required", "field_summary": None}
            frame = find_form_frame(page)
            if frame is None:
                return {"status": "form_not_found", "field_summary": None}
            fields = field_metadata(frame)
            summary = classify_fields(fields)
            return {"status": "form_observed" if summary["visible_fields"] else "form_not_found",
                    "field_summary": summary}
        finally:
            browser.close()


def main():
    try:
        result = probe()
    except Exception as error:
        # Do not print exceptions; their messages may contain job URLs/tokens.
        print("Public form read-only probe failed:", type(error).__name__,
              "HTTP_" + str(error.code) if isinstance(error, HTTPError) else "")
        return 2
    print("PUBLIC FORM STRUCTURE PROBE — 1 official Lever posting, no applicant data")
    print("Source: Lever / Zoox. Status:", result["status"])
    summary = result.get("field_summary")
    if summary is not None:
        print("Visible controls:", summary["visible_fields"])
        print("Required controls:", summary["required_fields"])
        print("Required custom/unknown:", summary["required_custom_or_unknown"])
        print("Field types:", summary["types"])
        print("Required types:", summary["required_types"])
    print("No input, upload, click, or form submission occurred.")
    return 0 if result["status"] == "form_observed" else 2


if __name__ == "__main__":
    sys.exit(main())
