"""Open a single official application for attended submission and receipt review."""

from urllib.parse import urlsplit

from .browser import IDENTITY_FIELDS
from .core import record_attempt
from .employers import board_from_url
from .receipts import receipt_fingerprint, record_receipt


def official_job_url(job):
    url = job['url']
    board = board_from_url(url)
    if board is None:
        return False
    posting = urlsplit(url).path.rstrip('/').removesuffix('/apply').rsplit('/', 1)[-1]
    return job['id'].lower() == ':'.join((*board, posting.lower()))


def reserve_submission(con, job):
    if not official_job_url(job) or not job['eligible']:
        raise ValueError('Attended submission requires an eligible, direct Greenhouse or Lever listing.')
    with con:
        con.execute('BEGIN IMMEDIATE')
        current = con.execute('SELECT status, url, eligible FROM jobs WHERE id=?', (job['id'],)).fetchone()
        if current is None or current['url'] != job['url'] or not current['eligible']:
            raise ValueError('The listing changed. Review it again before proceeding.')
        if current['status'] in {'submitted', 'submission_pending'}:
            raise ValueError('This job was submitted or has an unresolved submission. Check the employer first.')
        record_attempt(con, job['id'], 'submission_pending', 'Reserved for attended submission.')


def release_submission(con, job_id):
    with con:
        con.execute('BEGIN IMMEDIATE')
        changed = con.execute(
            "UPDATE jobs SET status='needs_review' WHERE id=? AND status='submission_pending'",
            (job_id,),
        ).rowcount
        if not changed:
            raise ValueError('This job has no pending submission to release.')
        record_attempt(con, job_id, 'needs_review', 'Applicant verified that no submission occurred.')


def check_confirmation(page, job, initial_url, original_text):
    address = urlsplit(page.url)
    expected = urlsplit(initial_url)
    if (address.scheme, address.netloc) != (expected.scheme, expected.netloc):
        return None
    if page.locator(f':is({IDENTITY_FIELDS}):visible').count():
        return None
    text = page.locator('body').inner_text(timeout=5000)
    if text == original_text:
        return None
    try:
        receipt_fingerprint(text, job)
    except ValueError:
        return None
    return text


def review_page(con, job, page, wait):
    response = page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
    if response is None or not response.ok or not official_job_url({**dict(job), 'url': page.url}):
        raise ValueError('The official posting could not be opened. The submission remains on hold.')
    initial = page.locator('body').inner_text(timeout=5000)
    initial_url = page.url
    origin = urlsplit(initial_url).netloc
    successful_posts = []

    def observe(response):
        address = urlsplit(response.url)
        if (response.request.method == 'POST' and address.scheme == 'https'
                and address.netloc == origin and (response.ok or response.status == 303)):
            successful_posts.append(True)

    page.on('response', observe)
    wait('Complete and submit the application yourself in Chromium. Press Enter here to check for a receipt. ')
    text = check_confirmation(page, job, initial_url, initial)
    if text is None or not successful_posts:
        return 'submission_pending'
    record_receipt(con, job['id'], text, details='Matched the confirmation shown in the attended browser.')
    return 'submitted'


def review_submission(con, job):
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    reserve_submission(con, job)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                context = browser.new_context(accept_downloads=False, service_workers='block')
                return review_page(con, job, context.new_page(), input)
            finally:
                browser.close()
    except (EOFError, KeyboardInterrupt, PlaywrightError):
        return 'submission_pending'
