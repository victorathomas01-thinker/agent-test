"""Open a single official application for attended submission and receipt review."""

from collections import Counter
from mimetypes import guess_type
import re
from urllib.parse import urlsplit

from .browser import FIELDS, IDENTITY_FIELDS, choose_option, field_metadata, find_form_frame, is_resume_field
from .core import answer_for, record_attempt
from .employers import board_from_url
from .receipts import receipt_fingerprint, record_receipt
from .sessions import EDGE_CHANNEL, open_profile, posting_scope, requires_sign_in

CONTACT_FIELDS = {
    'first_name': {'text'}, 'last_name': {'text'}, 'full_name': {'text'},
    'email': {'text', 'email'}, 'phone': {'text', 'tel'},
    'linkedin': {'text', 'url'}, 'github': {'text', 'url'}, 'portfolio': {'text', 'url'},
}
VERIFIED_FIELDS = {'work_authorized_us', 'needs_sponsorship_now_or_future', 'over_18', 'willing_to_relocate'}


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


def contact_form(page, job):
    original_url = page.url
    if not official_job_url({**dict(job), 'url': original_url}):
        return None
    if find_form_frame(page) is not page.main_frame or page.url != original_url:
        return None
    forms = page.locator('form:visible').filter(
        has=page.locator(':is(input[type=email], input[autocomplete=email], input[name=email i], input[id=email i]):visible')
    )
    return forms.first if forms.count() == 1 else None


def prefill_contact(page, job, cfg):
    from playwright.sync_api import Error as PlaywrightError

    original_url = page.url
    form = contact_form(page, job)
    if form is None:
        return []
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


def attach_reviewed_resume(page, job, path):
    from playwright.sync_api import Error as PlaywrightError

    original_url = page.url
    form = contact_form(page, job)
    if form is None:
        return False
    fields = [field for field in field_metadata(form)
              if not field['disabled'] and is_resume_field(field)]
    if len(fields) != 1:
        return False
    try:
        field = form.locator(FIELDS).nth(fields[0]['index']).element_handle(timeout=1500)
        accepted = (field.get_attribute('accept') or '').casefold().strip()
        mime = guess_type(path)[0] or 'application/octet-stream'
        formats = {part.strip() for part in accepted.split(',') if part.strip()}
        compatible = {mime, mime.split('/')[0] + '/*', path.suffix.casefold(), '*/*'}
        if (formats and not formats.intersection(compatible)
                or field.evaluate('input => input.files.length') or page.url != original_url):
            return False
        field.set_input_files(str(path), timeout=3000)
        return True
    except PlaywrightError:
        return False


def prefill_verified_fields(page, job, cfg):
    from playwright.sync_api import Error as PlaywrightError

    original_url = page.url
    form = contact_form(page, job)
    if form is None:
        return []
    verified_cfg = {'profile': {}, 'verified_answers': cfg['verified_answers']}
    candidates = []
    for field in field_metadata(form):
        if not field['visible'] or field['disabled']:
            continue
        answer, key = answer_for(field['label'].strip().rstrip('*'), verified_cfg)
        if answer is not None and key in VERIFIED_FIELDS:
            candidates.append((field, key, answer))
    keys = Counter(key for _, key, _ in candidates)
    inputs = [(form.locator(FIELDS).nth(field['index']).element_handle(timeout=1500),
               field, key, answer) for field, key, answer in candidates if keys[key] == 1]
    filled = []
    for node, field, key, answer in inputs:
        if page.url != original_url:
            break
        try:
            if field['type'] == 'select-one' and not node.input_value():
                value = choose_option(field['options'], answer)
                if value is not None:
                    node.select_option(value=value, timeout=1500)
                    filled.append(key)
            elif field['type'] == 'custom' and field['role'] == 'combobox':
                if select_verified_combobox(page, node, answer, original_url):
                    filled.append(key)
        except PlaywrightError:
            continue
    return filled


def select_verified_combobox(page, node, answer, original_url):
    # Leave existing selections and non-input widgets for the applicant.
    if not node.evaluate("node => node.tagName === 'INPUT' && !node.value"):
        return False
    if node.get_attribute('aria-expanded') != 'true':
        node.click(timeout=1500)
    control = node.get_attribute('aria-controls')
    if not control or page.url != original_url:
        return False
    list_id = page.evaluate('id => CSS.escape(id)', control)
    listbox = page.locator(f'#{list_id}[role="listbox"]:visible')
    if (listbox.count() != 1 or listbox.get_attribute('aria-multiselectable') == 'true'
            or listbox.get_by_role('option', selected=True).count()):
        return False
    options = listbox.get_by_role(
        'option', name=re.compile(r'^' + re.escape(answer) + r'$', re.I)
    )
    if options.count() != 1 or not options.first.is_enabled():
        return False
    options.first.click(timeout=1500)
    return page.url == original_url


def review_page(con, job, page, wait, prefill=None, attachment=None, verified=None, reuse_session=False):
    response = page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
    if reuse_session and requires_sign_in(page):
        wait('Sign in in Microsoft Edge, then press Enter here to reopen the approved posting. ')
        response = page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
    if requires_sign_in(page):
        raise ValueError('Sign-in needed. The submission remains on hold.')
    if response is None or not response.ok or not official_job_url({**dict(job), 'url': page.url}):
        raise ValueError('The official posting could not be opened. The submission remains on hold.')
    if prefill is not None:
        filled = prefill_contact(page, job, prefill)
        print('Prefilled contact fields: ' + ', '.join(filled) if filled
              else 'Contact fields need manual entry on this form.')
    if verified is not None:
        filled = prefill_verified_fields(page, job, verified)
        print('Prefilled verified answers: ' + ', '.join(filled) if filled
              else 'Verified questions need manual entry on this form.')
    if attachment is not None:
        attached = attach_reviewed_resume(page, job, attachment)
        print('Reviewed resume attached.' if attached else 'Attach your resume manually on this form.')
    if not official_job_url({**dict(job), 'url': page.url}):
        raise ValueError('The posting changed during preparation. The submission remains on hold.')
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
    wait('Complete and submit the application yourself in Microsoft Edge. Press Enter here to check for a receipt. ')
    text = check_confirmation(page, job, initial_url, initial)
    if text is None or not successful_posts:
        return 'submission_pending'
    record_receipt(con, job['id'], text, details='Matched the confirmation shown in the attended browser.')
    return 'submitted'


def review_submission(con, job, prefill=None, attachment=None, verified=None, reuse_session=False):
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    reserve_submission(con, job)
    try:
        with sync_playwright() as playwright:
            if reuse_session:
                context = open_profile(playwright.chromium, posting_scope(job['url']))
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    return review_page(con, job, page, input, prefill, attachment, verified, True)
                finally:
                    context.close()
            browser = playwright.chromium.launch(channel=EDGE_CHANNEL, headless=False)
            try:
                context = browser.new_context(accept_downloads=False, service_workers='block')
                return review_page(con, job, context.new_page(), input, prefill, attachment, verified)
            finally:
                browser.close()
    except (EOFError, KeyboardInterrupt, PlaywrightError):
        return 'submission_pending'
