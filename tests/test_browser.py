import json
from contextlib import closing, redirect_stdout
from io import StringIO
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import core
from agent.browser import apply_to_page, find_form_frame, preview_snapshot
from agent.rehearsal import rehearse_submission
from agent import sessions
from agent.submission import (
    attach_reviewed_resume, official_job_url, prefill_contact, prefill_verified_fields,
    release_submission, reserve_submission, review_page,
)

FIXTURE = Path(__file__).with_name('mock_form.html')
CFG = {
    'profile': {'first_name': 'Test', 'last_name': 'Applicant', 'email': 'test@example.invalid'},
    'verified_answers': {'work_authorized_us': True},
    'automation': {'headless': True},
}


class BrowserTest(unittest.TestCase):
    def test_synthetic_discovery_to_dashboard_pipeline(self):
        import main
        from agent.operations import run_record, write_dashboard

        cfg = core.with_defaults({'profile': CFG['profile'], 'verified_answers': CFG['verified_answers']})
        job = {'id': 'greenhouse:example:123', 'source': 'greenhouse', 'company': 'Example',
               'title': 'Software Engineer Intern', 'location': 'Charlotte',
               'url': 'https://job-boards.greenhouse.io/example/jobs/123', 'description': 'Python testing'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            resume = root / 'resume.txt'
            resume.write_text('Synthetic Applicant\n\nSkills\nPython testing\n\nProjects\nBuilt a testing tool\n', encoding='utf-8')
            cfg['profile']['resume_path'] = str(resume)

            def mock_browser(listing, profile):
                outcome, details = preview_snapshot(self.browser, FIXTURE.read_text(encoding='utf-8'), profile)
                core.add_attempt(listing['id'], outcome, details)
                return outcome, details

            with (patch.object(core, 'ROOT', root), patch.object(core, 'DB', root / 'agent.sqlite3'),
                  patch.object(core, 'discover', return_value=([job], [])),
                  patch.object(main, 'run_browser', side_effect=mock_browser), redirect_stdout(StringIO())):
                with run_record() as summary:
                    main.discover_jobs(cfg, summary)
                    main.run_batch(cfg, 1, '2000-01-01', summary)
                with closing(core.connect()) as con:
                    self.assertEqual(con.execute('SELECT status FROM jobs').fetchone()[0], 'prepared')
                    self.assertEqual(con.execute('SELECT status FROM runs').fetchone()[0], 'complete')
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM packages').fetchone()[0], 1)
                    self.assertIn('Software Engineer Intern', write_dashboard(con, cfg).read_text(encoding='utf-8'))

    def test_profile_persists_only_within_its_scope(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sessions, 'ROOT', Path(folder)):
            chromium = self.playwright.chromium
            profile = sessions.open_profile(chromium, 'indeed', headless=True, channel=None)
            try:
                profile.add_cookies([{
                    'name': 'mock_session', 'value': 'synthetic',
                    'url': 'https://example.invalid', 'expires': int(time.time()) + 3600,
                }])
            finally:
                profile.close()
            for scope, expected in [('indeed', ['mock_session']), ('lever--example', [])]:
                profile = sessions.open_profile(chromium, scope, headless=True, channel=None)
                try:
                    self.assertEqual([cookie['name'] for cookie in profile.cookies()], expected)
                finally:
                    profile.close()

    def test_visible_login_page_is_detected(self):
        page = self.browser.new_page()
        try:
            page.set_content('<h1>Sign in to continue</h1><input type="password">')
            self.assertTrue(sessions.requires_sign_in(page))
            page.set_content('<h1>Apply</h1><input type="password" hidden>')
            self.assertFalse(sessions.requires_sign_in(page))
        finally:
            page.close()
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        cls.playwright = playwright
        cls.addClassCleanup(playwright.stop)
        cls.browser = playwright.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def test_mock_dry_run_fills_answers_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            resume = Path(folder) / 'sample.txt'
            resume.write_text('Synthetic resume', encoding='utf-8')
            cfg = {**CFG, 'profile': {**CFG['profile'], 'resume_path': str(resume)}}
            page = self.browser.new_page()
            try:
                page.goto(FIXTURE.resolve().as_uri())
                outcome, details = apply_to_page(page, cfg)
                self.assertEqual(outcome, 'prepared', details)
                self.assertEqual(page.locator('#first').input_value(), 'Test')
                self.assertEqual(page.locator('#auth').input_value(), 'Yes')
                self.assertEqual(page.locator('#resume').evaluate('e => e.files[0].name'), 'sample.txt')
                self.assertEqual(page.locator('form').count(), 1)
                self.assertNotIn('test@example.invalid', details)
                self.assertNotIn('sample.txt', details)
            finally:
                page.close()

    def test_detached_snapshot_disables_site_scripts_and_network(self):
        snapshot = FIXTURE.read_text(encoding='utf-8').replace('type="file" required', 'type="file"')
        snapshot += """
          <script>document.querySelector('form').remove()</script>
          <iframe src="https://example.invalid/probe"></iframe>
        """
        from agent import browser

        original = browser.apply_to_page

        def check_offline(page, cfg):
            self.assertEqual(page.locator('form').count(), 1)
            self.assertEqual(page.frames[1].url, 'chrome-error://chromewebdata/')
            return original(page, cfg)

        with patch.object(browser, 'apply_to_page', side_effect=check_offline):
            outcome, details = preview_snapshot(self.browser, snapshot, CFG)
        self.assertEqual(outcome, 'prepared', details)

    def test_missing_verified_answer_and_resume_need_review(self):
        outcome, details = preview_snapshot(self.browser, FIXTURE.read_text(encoding='utf-8'),
                                            {**CFG, 'verified_answers': {}})
        self.assertEqual(outcome, 'needs_review')
        reasons = {item['reason'] for item in json.loads(details)['unresolved']}
        self.assertIn('no verified answer', reasons)
        self.assertIn('resume file missing or unsupported', reasons)

    def test_live_is_blocked_even_when_config_enabled(self):
        cfg = {**CFG, 'automation': {'allow_live_submit': True}}
        self.assertEqual(apply_to_page(None, cfg, live=True)[0], 'needs_review')

    def test_verified_radio_group_fills_only_unique_match(self):
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content("""
              <form>
                <label>First Name<input required></label>
                <label>Email<input type="email" required></label>
                <fieldset><legend>Are you legally authorized to work in the United States? *</legend>
                  <label><input type="radio" name="authorization" required>Yes</label>
                  <label><input type="radio" name="authorization">No</label>
                </fieldset>
              </form>
            """)
            outcome, details = apply_to_page(page, CFG)
            self.assertEqual(outcome, 'prepared', details)
            self.assertTrue(page.get_by_role('radio', name='Yes').is_checked())
            self.assertFalse(page.get_by_role('radio', name='No').is_checked())
        finally:
            page.close()

    def test_custom_control_and_later_step_are_reported_by_label(self):
        snapshot = """
          <form>
            <label>First Name<input required></label>
            <label>Email<input type="email" required></label>
            <label id="question">Are you willing to relocate?</label>
            <input role="combobox" aria-labelledby="question" aria-controls="choices"
                   aria-required="true">
            <ul id="choices" role="listbox" hidden><li role="option">Yes</li></ul>
            <button type="submit">Continue to next page</button>
          </form>
        """
        cfg = {**CFG, 'verified_answers': {'willing_to_relocate': True}}
        outcome, details = preview_snapshot(self.browser, snapshot, cfg)
        self.assertEqual(outcome, 'needs_review')
        review = {item['field']: item['reason'] for item in json.loads(details)['unresolved']}
        self.assertIn('verified choice available', review['Are you willing to relocate?'])
        self.assertIn('later application steps', review)
        self.assertNotIn('willing_to_relocate', json.loads(details)['filled'])

    def test_embedded_form_can_be_copied_and_filled_offline(self):
        page = self.browser.new_page()
        try:
            page.set_content("""
              <iframe srcdoc='<form><label>First Name<input required></label>
                <label>Email<input type="email" required></label></form>'></iframe>
            """)
            frame = find_form_frame(page)
            self.assertIsNotNone(frame)
            self.assertIsNot(frame, page.main_frame)
            outcome, details = preview_snapshot(self.browser, frame.content(), CFG)
            self.assertEqual(outcome, 'prepared', details)
            self.assertEqual(frame.locator('input[type=email]').input_value(), '')
        finally:
            page.close()

    def test_rehearsal_confirms_exactly_one_synthetic_post(self):
        status, detail = rehearse_submission(self.browser)
        self.assertEqual(status, 'confirmed', detail)
        self.assertIn('exactly one', detail)

    def test_rehearsal_requires_both_http_success_and_receipt(self):
        for mode, expected in [('rejected', 'rejected'), ('missing_receipt', 'unconfirmed')]:
            with self.subTest(mode=mode):
                status, detail = rehearse_submission(self.browser, response_mode=mode)
                self.assertEqual(status, expected, detail)

    def test_rehearsal_blocks_when_required_field_is_missing(self):
        status, detail = rehearse_submission(self.browser, config={'profile': {}, 'verified_answers': {}})
        self.assertEqual(status, 'blocked', detail)
        self.assertIn('No simulated POST', detail)

    def test_attended_submission_tracks_only_confirmed_employer_response(self):
        url = 'https://job-boards.greenhouse.io/example/jobs/123'
        job = dict(id='greenhouse:example:123', url=url, eligible=1,
                   title='Software Engineer', company='Example')
        self.assertTrue(official_job_url(job))
        self.assertFalse(official_job_url({**job, 'url': url.replace('/123', '/456')}))
        for mode in ('named', 'job_specific', 'generic_wrong_route', 'ambiguous'):
            confirmed = mode in {'named', 'job_specific'}
            action = url + '/confirmation' if mode == 'job_specific' else 'https://job-boards.greenhouse.io/mock-submit'
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                with patch.object(core, 'DB', Path(folder) / 'agent.sqlite3'), closing(core.connect()) as con:
                    with con:
                        con.execute(
                            'INSERT INTO jobs(id,url,eligible,title,company) VALUES(:id,:url,:eligible,:title,:company)',
                            job,
                        )
                    reserve_submission(con, job)
                    with self.assertRaisesRegex(ValueError, 'unresolved submission'):
                        reserve_submission(con, job)
                    context = self.browser.new_context(offline=True)
                    try:
                        def respond(route):
                            request = route.request
                            if request.url == url and request.method == 'GET':
                                route.fulfill(content_type='text/html', body=
                                    f'<form method="post" action="{action}"><button>Submit</button></form>')
                            elif request.url == action and request.method == 'POST':
                                text = {
                                    'named': 'Thank you for applying to Example for the Software Engineer role.',
                                    'job_specific': 'Thank you for applying',
                                    'generic_wrong_route': 'Thank you for applying',
                                    'ambiguous': 'Your application status is unavailable.',
                                }[mode]
                                route.fulfill(content_type='text/html', body=f'<title>{text}</title><h1>{text}</h1>')
                            else:
                                route.abort()

                        context.route('**/*', respond)
                        page = context.new_page()
                        result = review_page(con, job, page, lambda _: page.get_by_role('button').click())
                    finally:
                        context.close()
                    self.assertEqual(result, 'submitted' if confirmed else 'submission_pending')
                    core.add_attempt(job['id'], 'needs_review', 'Late preview result.')
                    self.assertEqual(con.execute('SELECT status FROM jobs').fetchone()[0], result)
                    if not confirmed:
                        release_submission(con, job['id'])
                        self.assertEqual(con.execute('SELECT status FROM jobs').fetchone()[0], 'needs_review')

    def test_attended_prefill_only_sets_unambiguous_blank_contact_fields(self):
        url = 'https://job-boards.greenhouse.io/example/jobs/123'
        job = {'id': 'greenhouse:example:123', 'url': url}
        context = self.browser.new_context(offline=True)
        try:
            page = context.new_page()
            requests = []
            html = """
              <form>
                <label>First Name<input id="first"></label>
                <label>Email<input id="email" name="email"></label>
                <label>Phone<input id="phone" type="tel" value="000-000-0000"></label>
                <label>LinkedIn<input id="link-one" type="url"></label>
                <label>LinkedIn<input id="link-two" type="url"></label>
                <label>Are you willing to relocate?<input id="relocate"></label>
                <label>Resume<input id="resume" type="file"></label>
                <button type="submit">Submit</button>
              </form>
              <label>Email<input id="outside" type="email"></label>
            """

            def route_request(route):
                requests.append(route.request.method)
                if route.request.url == url and route.request.method == 'GET':
                    route.fulfill(content_type='text/html', body=html)
                else:
                    route.abort()

            context.route('**/*', route_request)
            page.goto(url)
            cfg = {**CFG, 'profile': {**CFG['profile'], 'phone': '111-111-1111',
                                      'linkedin': 'https://example.invalid/profile'},
                   'verified_answers': {'willing_to_relocate': True}}
            self.assertEqual(prefill_contact(page, job, cfg), ['first_name', 'email'])
            self.assertEqual(page.locator('#first').input_value(), 'Test')
            self.assertEqual(page.locator('#email').input_value(), 'test@example.invalid')
            self.assertEqual(page.locator('#phone').input_value(), '000-000-0000')
            for field in ('link-one', 'link-two', 'relocate', 'resume', 'outside'):
                self.assertEqual(page.locator(f'#{field}').input_value(), '')
            self.assertEqual(requests, ['GET'])
        finally:
            context.close()

    def test_attended_preparation_selects_verified_choice_and_reviewed_file(self):
        url = 'https://job-boards.greenhouse.io/example/jobs/123'
        job = {'id': 'greenhouse:example:123', 'url': url}
        html = """
          <form>
            <label>Email<input name="email"></label>
            <label for="auth">Are you legally authorized to work in the United States?</label>
            <input id="auth" role="combobox" aria-controls="options" aria-expanded="false"
                   onclick="document.querySelector('#options').hidden=false; this.setAttribute('aria-expanded','true')">
            <ul id="options" role="listbox" hidden>
              <li role="option" onclick="document.querySelector('#auth').value='Yes'">Yes</li>
              <li role="option">No</li>
            </ul>
            <label>Resume<input type="file" name="resume" accept=".txt"></label>
            <label>Cover Letter<input type="file" name="cover_letter"></label>
            <label>How did you hear about us?
              <select name="referral"><option value="">Choose</option><option>Yes</option></select>
            </label>
          </form>
        """
        context = self.browser.new_context(offline=True)
        try:
            requests = []

            def respond(route):
                requests.append(route.request.method)
                if route.request.method == 'GET' and route.request.url == url:
                    route.fulfill(content_type='text/html', body=html)
                else:
                    route.abort()

            context.route('**/*', respond)
            page = context.new_page()
            page.goto(url)
            self.assertEqual(prefill_verified_fields(page, job, CFG), ['work_authorized_us'])
            self.assertEqual(page.locator('#auth').input_value(), 'Yes')
            self.assertEqual(page.locator('[name=referral]').input_value(), '')
            with tempfile.TemporaryDirectory() as folder:
                pdf = Path(folder) / 'sample.pdf'
                pdf.write_bytes(b'%PDF-1.0 synthetic')
                text = Path(folder) / 'sample.txt'
                text.write_text('Synthetic resume', encoding='utf-8')
                self.assertFalse(attach_reviewed_resume(page, job, pdf))
                self.assertTrue(attach_reviewed_resume(page, job, text))
                self.assertFalse(attach_reviewed_resume(page, job, text))
            self.assertEqual(page.locator('[name=resume]').evaluate('e => e.files[0].name'), 'sample.txt')
            self.assertEqual(page.locator('[name=cover_letter]').input_value(), '')
            self.assertEqual(requests, ['GET'])
        finally:
            context.close()

    def test_attended_dropdowns_use_explicit_personal_choices_and_distinct_sponsorship_answers(self):
        url = 'https://job-boards.greenhouse.io/example/jobs/123'
        job = {'id': 'greenhouse:example:123', 'url': url}
        questions = {
            'now': 'Do you require immigration sponsorship to work for Example in the United States?',
            'later': 'Will you require immigration sponsorship at any point in the future to maintain authorization to work in the United States?',
            'gender': 'How do you identify? (gender identity)',
            'pronouns': 'Pronouns',
            'race': 'Please indicate your race or ethnicity',
            'ethnicity': 'Are you Hispanic/Latino?',
            'employment': 'Have you previously been employed at Example for any length of time?',
            'referral': 'Were you referred by an employee?',
            'source': 'How did you first learn about Example as an employer?',
            'policy': 'Do you accept our privacy policy?',
        }
        choices = ('<option value="">Choose</option><option value="value-1">No</option>'
                   '<option value="value-2">Prefer not to answer</option>'
                   '<option value="value-3">Black or African American (Not Hispanic or Latino)</option>'
                   '<option value="value-4">Company Website</option><option value="value-5">Job Board</option>')
        markup = '<form><label>Email<input name="email"></label>' + ''.join(
            f'<label for="{key}">{question}</label><select id="{key}">{choices}</select>'
            for key, question in questions.items()
        ) + '</form>'
        context = self.browser.new_context(offline=True)
        try:
            context.route(url, lambda route: route.fulfill(content_type='text/html', body=markup))
            page = context.new_page()
            page.goto(url)
            cfg = {**CFG, 'verified_answers': {'needs_sponsorship_now_or_future': False,
                                              'has_employment_history': False, 'was_referred': False},
                   'automation': {'prefill_job_board_source': True},
                   'verified_questions': {'pronouns': 'Prefer not to answer',
                                          'please indicate your race or ethnicity': 'Black',
                                          'are you hispanic/latino': 'No',
                                          'do you accept our privacy policy': 'No'}}
            self.assertEqual(prefill_verified_fields(page, job, cfg),
                             ['needs_sponsorship_now_or_future', 'needs_sponsorship_now_or_future',
                              'pronouns', 'race', 'hispanic_latino', 'has_employment_history',
                              'was_referred', 'application_source'])
            self.assertEqual(page.locator('#now').input_value(), 'value-1')
            self.assertEqual(page.locator('#later').input_value(), 'value-1')
            self.assertEqual(page.locator('#pronouns').input_value(), 'value-2')
            self.assertEqual(page.locator('#race').input_value(), 'value-3')
            self.assertEqual(page.locator('#ethnicity').input_value(), 'value-1')
            self.assertEqual(page.locator('#employment').input_value(), 'value-1')
            self.assertEqual(page.locator('#referral').input_value(), 'value-1')
            self.assertEqual(page.locator('#source').input_value(), 'value-5')
            self.assertEqual(page.locator('#gender').input_value(), '')
            self.assertEqual(page.locator('#policy').input_value(), '')
        finally:
            context.close()

    def test_attended_next_step_prepares_delayed_dropdown_and_reviews_validation(self):
        url = 'https://job-boards.greenhouse.io/example/jobs/123'
        step = url + '/steps/details'
        receipt = url + '/confirmation'
        job = dict(id='greenhouse:example:123', url=url, eligible=1,
                   title='Software Engineer', company='Example')
        first_page = f'<form><label>Email<input type="email" value="invalid"></label><a href="{step}">Next</a></form>'
        next_page = f"""
            <form method="post" action="{receipt}">
              <label for="pronouns">Pronouns</label>
              <input id="pronouns" role="combobox" aria-expanded="false"
                     onclick="setTimeout(() => {{ this.setAttribute('aria-controls','choices');
                       this.setAttribute('aria-expanded','true');
                       document.querySelector('#choices').hidden=false; }}, 50)">
              <ul id="choices" role="listbox" hidden>
                <li role="option" onclick="document.querySelector('#pronouns').value='He/him/his'">He/him/his</li>
              </ul>
              <button>Submit application</button>
            </form>
        """
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'DB', Path(folder) / 'agent.sqlite3'):
            with closing(core.connect()) as con:
                with con:
                    con.execute('INSERT INTO jobs(id,url,eligible,title,company) VALUES(:id,:url,:eligible,:title,:company)', job)
                reserve_submission(con, job)
                context = self.browser.new_context(offline=True)
                try:
                    def respond(route):
                        target = (route.request.method, route.request.url)
                        pages = {
                            ('GET', url): first_page, ('GET', step): next_page,
                            ('POST', receipt): '<title>Thank you for applying</title><h1>Thank you for applying</h1>',
                        }
                        if target in pages:
                            route.fulfill(content_type='text/html', body=pages[target])
                        else:
                            route.abort()

                    context.route('**/*', respond)
                    page = context.new_page()

                    def applicant(_):
                        if page.url == url:
                            page.get_by_role('link', name='Next').click()
                            return 'next'
                        self.assertEqual(page.locator('#pronouns').input_value(), 'He/him/his')
                        page.get_by_role('button', name='Submit application').click()
                        return ''

                    cfg = {**CFG, 'verified_questions': {'pronouns': 'He/Him'}}
                    output = StringIO()
                    with redirect_stdout(output):
                        outcome = review_page(con, job, page, applicant, verified=cfg)
                    self.assertEqual(outcome, 'submitted')
                    self.assertIn('Invalid entry | Email', output.getvalue())
                    self.assertIn('Prefilled verified answers: pronouns', output.getvalue())
                    self.assertNotIn('He/him/his', output.getvalue())
                finally:
                    context.close()
