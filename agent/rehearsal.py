"""Exercise the submit-and-confirm sequence against a local browser fixture."""

from urllib.parse import parse_qs

from .browser import apply_to_page

ORIGIN = 'https://employer-rehearsal.invalid'
FORM = ORIGIN + '/apply'
SUBMIT = ORIGIN + '/submit'
REFERENCE = 'simulation-001'

SYNTHETIC_PROFILE = {
    'profile': {'first_name': 'Sample', 'email': 'applicant@example.invalid'},
    'verified_answers': {},
}
FORM_HTML = """
<!doctype html>
<title>Mock employer application</title>
<form method="post" action="/submit">
  <label>First Name <input name="first_name" required></label>
  <label>Email <input type="email" name="email" required></label>
  <button type="submit">Submit application</button>
</form>
"""


def rehearse_submission(browser, response_mode='confirmed', config=SYNTHETIC_PROFILE):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    context = browser.new_context(java_script_enabled=False, service_workers='block',
                                  offline=True, accept_downloads=False)
    posted = []

    def mock_employer(route):
        request = route.request
        if request.url == FORM and request.method == 'GET':
            route.fulfill(content_type='text/html', body=FORM_HTML)
        elif request.url == SUBMIT and request.method == 'POST':
            posted.append(parse_qs(request.post_data or ''))
            expected = {'first_name': ['Sample'], 'email': ['applicant@example.invalid']}
            if len(posted) != 1 or posted[0] != expected or response_mode == 'rejected':
                route.fulfill(status=422, content_type='text/html', body='<h1>Application rejected</h1>')
            else:
                body = '<h1>Application received</h1>'
                if response_mode == 'confirmed':
                    body += f'<p data-confirmation-reference="{REFERENCE}">{REFERENCE}</p>'
                route.fulfill(status=200, content_type='text/html', body=body)
        else:
            route.abort()

    try:
        context.route('**/*', mock_employer)
        page = context.new_page()
        page.goto(FORM, timeout=5000)
        state, _ = apply_to_page(page, config)
        if state != 'prepared':
            return 'blocked', 'Required fields were unresolved. No simulated POST was sent.'
        submit = page.get_by_role('button', name='Submit application', exact=True)
        try:
            with page.expect_response(
                lambda response: response.url == SUBMIT and response.request.method == 'POST',
                timeout=5000,
            ) as submission:
                submit.click(timeout=5000)
            response = submission.value
            page.wait_for_url(SUBMIT, wait_until='domcontentloaded', timeout=5000)
        except PlaywrightTimeoutError:
            return 'unconfirmed', 'The simulated attempt returned no usable response. Review before retrying.'

        if not response.ok:
            return 'rejected', f'The mock employer rejected the simulated application (HTTP {response.status}).'
        receipt = page.locator(f'[data-confirmation-reference="{REFERENCE}"]')
        if len(posted) != 1 or receipt.count() != 1 or receipt.inner_text().strip() != REFERENCE:
            return 'unconfirmed', 'The mock employer response lacked a matching confirmation reference.'
        return 'confirmed', f'The mock employer confirmed exactly one simulated application ({REFERENCE}).'
    finally:
        context.close()


def run_rehearsal():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            return rehearse_submission(browser)
        finally:
            browser.close()
