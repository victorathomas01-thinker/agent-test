import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.browser import apply_to_page, find_form_frame, preview_snapshot
from agent.rehearsal import rehearse_submission

FIXTURE = Path(__file__).with_name('mock_form.html')
CFG = {
    'profile': {'first_name': 'Test', 'last_name': 'Applicant', 'email': 'test@example.invalid'},
    'verified_answers': {'work_authorized_us': True},
    'automation': {'headless': True},
}


class BrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
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
