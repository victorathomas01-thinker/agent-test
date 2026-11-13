"""Open a single official application for attended submission and receipt review."""

from collections import Counter
from mimetypes import guess_type
import re
from urllib.parse import parse_qs, urlsplit

from .browser import FIELDS, IDENTITY_FIELDS, field_metadata, find_form_frame, is_resume_field
from .core import answer_for, canonical_url, normalize_question, record_attempt
from .posting_freshness import risk_reasons, observation_day
from .employers import board_from_url
from .receipts import receipt_fingerprint, record_receipt
from .sessions import EDGE_CHANNEL, open_profile, posting_scope, requires_sign_in

CONTACT_FIELDS = {
    'first_name': {'text'}, 'last_name': {'text'}, 'full_name': {'text'}, 'preferred_name': {'text'},
    'email': {'text', 'email'}, 'phone': {'text', 'tel'},
    'linkedin': {'text', 'url'}, 'github': {'text', 'url'}, 'portfolio': {'text', 'url'},
}
VERIFIED_FIELDS = {'work_authorized_us', 'needs_sponsorship_now_or_future', 'over_18', 'willing_to_relocate',
                   'has_employment_history', 'was_referred'}
SOURCE_QUESTION = re.compile(
    r'(?:(?:how|where) did you (?:first )?(?:hear|learn|find out) about '
    r'(?:us|this (?:job|role|position|opening|opportunity)|[a-z0-9 .&’\x27-]+ as an employer)'
    r'|(?:how|where) did you find this (?:job|role|position|opening|opportunity))'
)
SOURCE_LABELS = ('job board', 'online job board', 'job posting site', 'company careers site',
                 'company career site', 'company website', 'careers website')
PERSONAL_DROPDOWNS = {
    'gender': {'gender', 'gender identity', 'which gender do you identify as',
               'what is your gender identity', 'how do you identify? (gender identity)'},
    'pronouns': {'pronouns', 'preferred pronouns', 'what are your pronouns', 'what pronouns do you use'},
    'race': {'race', 'race/ethnicity', 'race or ethnicity', 'please indicate your race or ethnicity',
             'how do you identify? (race/ethnicity)'},
    'hispanic_latino': {'are you hispanic/latino', 'are you hispanic or latino',
                       'hispanic/latino', 'hispanic or latino'},
    'residence_state': {'state of residence', 'which u.s. state or canadian province do you reside in'},
    'residence_country': {'country of residence', 'which country do you currently reside in'},
}
DROPDOWN_EQUIVALENTS = {
    'pronouns': ({'he/him', 'he/him/his'}, {'she/her', 'she/her/hers'}, {'they/them', 'they/them/theirs'}),
    'race': ({'black', 'black or african american', 'black / african american', 'black/african american'},),
    'hispanic_latino': ({'no', 'not hispanic or latino', 'no, not hispanic or latino'},),
    'was_referred': ({'no', 'not referred', 'no employee referral'},),
    'residence_state': ({'north carolina', 'nc'},),
    'residence_country': ({'united states', 'united states of america', 'usa', 'u.s.'},),
}


def official_job_url(job):
    url = job['url']
    board = board_from_url(url)
    if board is None or board[0] not in {'greenhouse', 'lever'}:
        return False
    posting = urlsplit(url).path.rstrip('/').removesuffix('/apply').rsplit('/', 1)[-1]
    return job['id'].lower() == ':'.join((*board, posting.lower()))


def reserve_submission(con, job):
    if not official_job_url(job) or not job['eligible']:
        raise ValueError('Attended submission requires an eligible, direct Greenhouse or Lever listing.')
    with con:
        con.execute('BEGIN IMMEDIATE')
        current = con.execute("""SELECT j.*, COALESCE(w.deadline,'') AS deadline
                                 FROM jobs j LEFT JOIN web_checks w ON w.job_id=j.id
                                 WHERE j.id=?""", (job['id'],)).fetchone()
        if current is None or current['url'] != job['url'] or not current['eligible']:
            raise ValueError('The listing changed. Review it again before proceeding.')
        if current['status'] in {'expired','rejected','withdrawn','offer','assessment','interview'}:
            raise ValueError('This record is closed or already tracked. Do not reopen the application.')
        if current['submitted_at'] or current['status'] in {'submitted', 'submission_pending'}:
            raise ValueError('This job was submitted or has an unresolved submission. Check the employer first.')
        if current['source'] in {'greenhouse', 'lever'} and observation_day(current['last_seen']) is None:
            raise ValueError('Listing has no dated public-source observation. Rediscover it first.')
        if risk_reasons(dict(current)):
            raise ValueError('Application deadline or listing freshness needs employer re-verification.')
        identity = canonical_url(job['url'])
        prior = con.execute("""SELECT url FROM jobs WHERE id!=?
                            AND (submitted_at IS NOT NULL OR status IN ('submitted', 'submission_pending'))""",
                            (job['id'],))
        if identity and any(canonical_url(row['url']) == identity for row in prior):
            raise ValueError('Another record for this posting has a submission or unresolved attempt.')
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


def greenhouse_confirmation(page, job, initial_url):
    if not job['id'].startswith('greenhouse:'):
        return False
    expected = urlsplit(initial_url)
    current = urlsplit(page.url)
    if (current.scheme, current.netloc, current.path.rstrip('/')) != (
        expected.scheme, expected.netloc, expected.path.rstrip('/') + '/confirmation'
    ):
        return False
    acknowledgment = re.compile(r'^thank you for applying[.!]?$', re.I)
    return bool(acknowledgment.fullmatch(page.title().strip())) or (
        page.get_by_role('heading', name=acknowledgment).count() == 1
    )


def allowed_step(job, url):
    if not official_job_url(job):
        return False
    expected, current = urlsplit(job['url']), urlsplit(url)
    if (current.scheme, current.netloc) != (expected.scheme, expected.netloc):
        return False
    root = expected.path.rstrip('/').removesuffix('/apply')
    path = current.path.rstrip('/')
    if path in {root, root + '/apply', root + '/application'}:
        return True
    return bool(re.fullmatch(re.escape(root) + r'/(?:apply/|application/)?steps?/[a-zA-Z0-9_-]+', path))


def allowed_form_frame(job, url):
    if not official_job_url(job):
        return False
    if allowed_step(job, url):
        return True
    current, expected = urlsplit(url), urlsplit(job['url'])
    return (
        job['id'].startswith('greenhouse:')
        and (current.scheme, current.netloc, current.path.rstrip('/')) ==
            (expected.scheme, expected.netloc, '/embed/job_app')
        and parse_qs(current.query).get('token') == [job['id'].rsplit(':', 1)[-1]]
    )


def contact_form(page, job, later_step=False):
    original_url = page.url
    if not allowed_step(job, original_url):
        return None
    if later_step:
        forms = page.locator('form:visible, [role=form]:visible')
        return forms.first if forms.count() == 1 else None
    if not official_job_url({**dict(job), 'url': original_url}):
        return None
    frame = find_form_frame(page)
    if frame is None or page.url != original_url or not allowed_form_frame(job, frame.url):
        return None
    forms = frame.locator('form:visible, [role=form]:visible').filter(
        has=frame.locator(':is(input[type=email], input[autocomplete=email], input[name=email i], input[id=email i]):visible')
    )
    return forms.first if forms.count() == 1 else None


def prefill_contact(page, job, cfg, later_step=False):
    from playwright.sync_api import Error as PlaywrightError

    original_url = page.url
    form = contact_form(page, job, later_step)
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
    if not later_step and (not {'first_name', 'full_name'}.intersection(keys) or keys['email'] != 1):
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


def attach_reviewed_resume(page, job, path, later_step=False):
    from playwright.sync_api import Error as PlaywrightError

    original_url = page.url
    form = contact_form(page, job, later_step)
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


def prefill_verified_fields(page, job, cfg, later_step=False):
    from playwright.sync_api import Error as PlaywrightError

    original_url = page.url
    form = contact_form(page, job, later_step)
    if form is None:
        return []
    verified_cfg = {'profile': {}, 'verified_answers': cfg['verified_answers']}
    remembered = cfg.get('verified_questions', {})
    hispanic_answers = {str(remembered[question]).strip().casefold()
                        for question in PERSONAL_DROPDOWNS['hispanic_latino'] if remembered.get(question)}
    candidates = []
    for field in field_metadata(form):
        if (not field['visible'] or field['disabled']
                or not (field['type'] == 'select-one'
                        or (field['type'] == 'custom' and field['role'] == 'combobox'))):
            continue
        question = normalize_question(field['label'])
        answer, key = answer_for(question, verified_cfg)
        if key in VERIFIED_FIELDS:
            answer = remembered.get(question, answer)
        else:
            key = next((name for name, labels in PERSONAL_DROPDOWNS.items() if question in labels), None)
            answer = remembered.get(question) if key else None
            if key is None and cfg.get('automation', {}).get('prefill_job_board_source') is True and SOURCE_QUESTION.fullmatch(question):
                key, answer = 'application_source', 'Job board'
        if isinstance(answer, str) and answer.strip():
            candidates.append((field, question, key, answer.strip()))
    questions = Counter(question for _, question, _, _ in candidates)
    inputs = [(form.locator(FIELDS).nth(field['index']).element_handle(timeout=1500),
               field, key, answer) for field, question, key, answer in candidates if questions[question] == 1]
    filled = []
    for node, field, key, answer in inputs:
        if page.url != original_url:
            break
        try:
            label = answer.casefold()
            labels = next((set(group) for group in DROPDOWN_EQUIVALENTS.get(key, ()) if label in group), {label})
            priority = ()
            if key == 'application_source':
                priority = (job['id'].split(':', 1)[0], *SOURCE_LABELS)
                labels = set(priority)
            if key == 'race' and 'black' in labels and hispanic_answers == {'no'}:
                labels.add('black or african american (not hispanic or latino)')
            if field['type'] == 'select-one' and not node.input_value():
                options = [option for option in field['options'] if option['value']
                           and option['text'].strip().casefold() in labels]
                if priority and options:
                    best = min(priority.index(option['text'].strip().casefold()) for option in options)
                    options = [option for option in options if option['text'].strip().casefold() == priority[best]]
                if len(options) == 1:
                    node.select_option(label=options[0]['text'], timeout=1500)
                    filled.append(key)
            elif field['type'] == 'custom' and field['role'] == 'combobox':
                if select_verified_combobox(page, node, labels, original_url, priority):
                    filled.append(key)
        except PlaywrightError:
            continue
    return filled


def select_verified_combobox(page, node, labels, original_url, priority=()):
    # Leave existing selections and non-input widgets for the applicant.
    if not node.evaluate("node => node.tagName === 'INPUT' && !node.value"):
        return False
    if node.get_attribute('aria-expanded') != 'true':
        node.click(timeout=1500)
    frame = node.owner_frame()
    if frame is None:
        return False
    frame_url = frame.url
    control = frame.wait_for_function(
        "node => node.isConnected && node.getAttribute('aria-controls')",
        arg=node, timeout=1500,
    ).json_value()
    if page.url != original_url or frame.url != frame_url:
        return False
    list_id = frame.evaluate('id => CSS.escape(id)', control)
    listbox = frame.locator(f'#{list_id}[role="listbox"]:visible')
    listbox.wait_for(state='visible', timeout=1500)
    if listbox.get_attribute('aria-multiselectable') == 'true':
        return False
    names = '|'.join(re.escape(label).replace('/', r'\/') for label in sorted(labels))
    options = listbox.get_by_role('option', name=re.compile(r'^(?:' + names + r')$', re.I))
    options.first.wait_for(state='visible', timeout=1500)
    if priority and options.count() > 1:
        for label in priority:
            preferred = listbox.get_by_role('option', name=re.compile(r'^' + re.escape(label) + r'$', re.I))
            if preferred.count():
                options = preferred
                break
    if (listbox.get_by_role('option', selected=True).count() or options.count() != 1
            or not options.first.is_enabled() or page.url != original_url or frame.url != frame_url):
        return False
    options.first.click(timeout=1500)
    return page.url == original_url


def print_step_review(page):
    forms = page.locator('form:visible, [role=form]:visible')
    if forms.count() != 1:
        return
    groups = {'Required and blank': [], 'Invalid entry': [], 'Check required custom choices': []}
    for field in field_metadata(forms.first):
        if not field['visible'] or field['disabled']:
            continue
        label = field['question'] or field['label'] or field['name'] or field['id']
        label = ''.join(char for char in label if char.isprintable()).strip().rstrip('*').strip()
        label = label or 'Unlabeled field'
        if field['type'] == 'custom' and field['required']:
            groups['Check required custom choices'].append(label)
        elif field['missing'] or (field['required'] and field['blank']):
            groups['Required and blank'].append(label)
        elif field['invalid']:
            groups['Invalid entry'].append(label)
    for description, labels in groups.items():
        if labels:
            print(f'{description} | ' + ' | '.join(dict.fromkeys(labels)))


def prepare_step(page, job, prefill, attachment, verified, later_step=False):
    def signature():
        return {(field['type'], field['id'], field['name'], field['label']) for field in field_metadata(page)
                if field['visible'] and not field['disabled']}

    before = signature() if verified is not None else set()
    contact_filled = []
    if prefill is not None:
        contact_filled = prefill_contact(page, job, prefill, later_step)
    if verified is not None:
        filled = prefill_verified_fields(page, job, verified, later_step)
        if allowed_step(job, page.url) and signature() - before:
            if prefill is not None:
                contact_filled.extend(prefill_contact(page, job, prefill, later_step))
            filled.extend(prefill_verified_fields(page, job, verified, later_step))
        print('Prefilled verified answers: ' + ', '.join(filled) if filled
              else 'Verified questions need manual entry on this form.')
    if prefill is not None:
        print('Prefilled contact fields: ' + ', '.join(contact_filled) if contact_filled
              else 'Contact fields need manual entry on this form.')
    if attachment is not None:
        attached = attach_reviewed_resume(page, job, attachment, later_step)
        print('Reviewed resume attached.' if attached else 'Attach your resume manually on this form.')
        if attached:
            attachment = None
    if not allowed_step(job, page.url):
        raise ValueError('The posting changed during preparation. The submission remains on hold.')
    print_step_review(page)
    return attachment


def review_page(con, job, page, wait, prefill=None, attachment=None, verified=None, reuse_session=False):
    response = page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
    if reuse_session and requires_sign_in(page):
        wait('Sign in in Microsoft Edge, then press Enter here to reopen the approved posting. ')
        response = page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
    if requires_sign_in(page):
        raise ValueError('Sign-in needed. The submission remains on hold.')
    if response is None or not response.ok or not official_job_url({**dict(job), 'url': page.url}):
        raise ValueError('The official posting could not be opened. The submission remains on hold.')
    initial_url = page.url
    job = {**dict(job), 'url': initial_url}
    attachment = prepare_step(page, job, prefill, attachment, verified)
    initial = page.locator('body').inner_text(timeout=5000)
    successful_posts = observe_submission(page, initial_url)
    while True:
        choice = wait('Click Next yourself, then type next here to prepare that step. '
                      'After submitting in Edge, press Enter here to check for a receipt. ')
        if not choice:
            break
        if choice.strip().casefold() != 'next':
            print('Type next after advancing the form, or press Enter after submitting.')
            continue
        if not allowed_step(job, page.url):
            print('This page is outside the approved application steps. Review it in Edge.')
            continue
        if page.locator('form:visible, [role=form]:visible').count() != 1:
            print('No single application form was found on this step. Review it in Edge.')
            continue
        attachment = prepare_step(page, job, prefill, attachment, verified, later_step=True)
        successful_posts.clear()
    return browser_outcome(con, job, page, initial_url, initial, successful_posts)


def observe_submission(page, initial_url):
    origin = urlsplit(initial_url).netloc
    successful_posts = []

    def observe(response):
        address = urlsplit(response.url)
        if (response.request.method == 'POST' and address.scheme == 'https'
                and address.netloc == origin and (response.ok or response.status == 303)):
            successful_posts.append(True)

    page.on('response', observe)
    return successful_posts


def browser_outcome(con, job, page, initial_url, initial, successful_posts):
    text = check_confirmation(page, job, initial_url, initial)
    if not successful_posts:
        return 'submission_pending'
    if text is not None:
        record_receipt(con, job['id'], text, details='Matched the confirmation shown in the attended browser.')
    elif greenhouse_confirmation(page, job, initial_url):
        with con:
            record_attempt(con, job['id'], 'submitted', 'Matched the job-specific Greenhouse confirmation page.')
    else:
        return 'submission_pending'
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
