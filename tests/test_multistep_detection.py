"""Synthetic offline wizard detection, with no live sites or submission."""
import json
import unittest

from playwright.sync_api import sync_playwright

from agent.browser import apply_to_page, has_later_step

CFG = {
    "profile": {"first_name": "Test", "last_name": "Applicant",
                "email": "test@example.invalid", "resume_path": ""},
    "verified_answers": {},
    "automation": {"allow_live_submit": False},
}

IDENTITY = """<form id="apply">
  <label>First Name<input name="first_name" required></label>
  <label>Email<input type="email" name="email" required></label>
  {control}
</form>"""


class WizardDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = sync_playwright().start()
        cls.addClassCleanup(cls.engine.stop)
        cls.browser = cls.engine.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def check_case(self, html, expected):
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content(html)
            self.assertEqual(has_later_step(page), expected)
            status, payload = apply_to_page(page, CFG)
            later = [x for x in json.loads(payload)["unresolved"]
                     if x["reason"] == "preview covers the current step only"]
            self.assertEqual(bool(later), expected)
            if expected:
                self.assertEqual(status, "needs_review")
        finally:
            page.close()

    def test_native_button_next_and_save_continue(self):
        for name in ("Next", "Next step →", "Save and Continue", "Continue to review",
                     "Review application"):
            with self.subTest(name=name):
                self.check_case(IDENTITY.format(control=f'<button>{name}</button>'), True)

    def test_associated_outside_button(self):
        self.check_case(IDENTITY.format(control='') +
                        '<button form="apply" type="submit">Continue</button>', True)

    def test_submit_input_and_link_within_form(self):
        self.check_case(IDENTITY.format(
            control='<input type="submit" value="Next page">'), True)
        self.check_case(IDENTITY.format(
            control='<a href="#stage-two">Continue</a>'), True)
        self.check_case(IDENTITY.format(
            control='<div role="button" aria-label="Next section">›</div>'), True)

    def test_final_submit_and_signin_not_flagged(self):
        for text in ("Submit Application", "Apply Now", "Continue with Google"):
            with self.subTest(text=text):
                self.check_case(IDENTITY.format(control=f'<button>{text}</button>'), False)

    def test_hidden_disabled_and_unrelated_navigation_not_flagged(self):
        self.check_case(IDENTITY.format(
            control='<button hidden>Next</button><button disabled>Continue</button>'),
            False)
        self.check_case(IDENTITY.format(control='') +
                        '<nav><a href="/elsewhere">Continue</a></nav>', False)


if __name__ == "__main__":
    unittest.main()
