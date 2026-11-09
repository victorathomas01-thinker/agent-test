"""Open a single official application for attended submission and receipt review."""

from collections import Counter
from urllib.parse import urlsplit

from .browser import FIELDS, IDENTITY_FIELDS, field_metadata, find_form_frame
from .core import answer_for, record_attempt
from .employers import board_from_url
from .receipts import receipt_fingerprint, record_receipt

CONTACT_FIELDS = {
    'first_name': {'text'}, 'last_name': {'text'}, 'full_name': {'text'},
    'email': {'text', 'email'}, 'phone': {'text', 'tel'},
    'linkedin': {'text', 'url'}, 'github': {'text', 'url'}, 'portfolio': {'text', 'url'},
}


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


def prefill_contact(page, job, cfg):
    from playwright.sync_api import Error as PlaywrightError

    original_url = page.url
    if not official_job_url({**dict(job), 'url': original_url}):
        return []
    if find_form_frame(page) is not page.main_frame or page.url != original_url:
        return []
    forms = page.locator('form:visible').filter(
        has=page.locator(':is(input[type=email], input[autocomplete=email], input[name=email i], input[id=email i]):visible')
    )
    if forms.count() != 1:
        return []
    form = forms.first
    candidates = []
    for field in field_metadata(form):
        if not field['visible'] or field['disabled'] or field['type'] not in {'text', 'email', 'tel', 'url'}:
            continue
        label = field['label'].strip().rstrip('*').strip() or field['name'] or field['id']
        answer, key = answer_for(label, {'profile': cfg['profile'], 'verified_answers': {}})
        if answer is not None and field['type'] in CONTACT_FIELDS.get(key, ()):
            candidates.append((field['index'], key, answer))

    keys = Counter(key for _, key, _ in candidates)
    if not {'first_name', 'full_name'}.intersection(keys) or keys['email'] != 1:
        return []
    # Pin elements before filling so a re-render cannot shift an index to another input.
    inputs = [(form.locator(FIELDS).nth(index).element_handle(timeout=1500), key, answer)
              for index, key, answer in candidates if keys[key] == 1]
    filled = []
    for node, key, answer in inputs:
        if page.url != original_url:
            break
        try:
            if not node.input_value():
                node.fill(answer, timeout=1500)
                filled.append(key)
        except PlaywrightError:
            continue
    return filled


def review_page(con, job, page, wait, prefill=None):
    response = page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
    if response is None or not response.ok or not official_job_url({**dict(job), 'url': page.url}):
        raise ValueError('The official posting could not be opened. The submission remains on hold.')
    if prefill is not None:
        filled = prefill_contact(page, job, prefill)
        print('Prefilled contact fields: ' + ', '.join(filled) if filled
              else 'Contact fields need manual entry on this form.')
        if not official_job_url({**dict(job), 'url': page.url}):
            raise ValueError('The posting changed during prefill. The submission remains on hold.')
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


def review_submission(con, job, prefill=None):
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    reserve_submission(con, job)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                context = browser.new_context(accept_downloads=False, service_workers='block')
                return review_page(con, job, context.new_page(), input, prefill)
            finally:
                browser.close()
    except (EOFError, KeyboardInterrupt, PlaywrightError):
        return 'submission_pending'
