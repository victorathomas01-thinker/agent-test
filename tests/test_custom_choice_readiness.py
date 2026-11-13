"""Synthetic custom-dropdown readiness: no external page, click, or submission."""
import json
import unittest

from playwright.sync_api import sync_playwright

from agent.browser import apply_to_page, custom_choice_reason
from agent.form_diagnostics import classify, BLOCKER_ACTIONS

QUESTION = "Preferred fictional shift"
CFG = {
    "profile": {"first_name": "Example", "email": "example@example.invalid"},
    "verified_answers": {},
    "verified_questions": {"preferred fictional shift": "Evening"},
    "automation": {"allow_live_submit": False},
}


class CustomChoiceReadinessTests(unittest.TestCase):
    def test_static_option_states_are_distinguished(self):
        field = {"role": "combobox", "options": [
            {"text": "Morning", "value": "am"},
            {"text": "Evening", "value": "pm"},
        ]}
        self.assertEqual(custom_choice_reason(field, "Evening"),
                         "verified choice available, selection requires manual input")
        self.assertEqual(custom_choice_reason(field, "Overnight"),
                         "verified answer absent from custom dropdown options")
        self.assertEqual(custom_choice_reason({**field, "options": []}, "Evening"),
                         "custom dropdown options unavailable offline")
        self.assertEqual(custom_choice_reason({**field, "options": [
            {"text": "Evening", "value": "pm"},
            {"text": "Evening", "value": "evening"},
        ]}, "Evening"), "multiple matching custom dropdown options")
        self.assertEqual(custom_choice_reason(field, None),
                         "custom control requires manual input")
        self.assertEqual(custom_choice_reason({**field, "role": "checkbox"}, "Evening"),
                         "custom control requires manual input")

    def test_privacy_safe_categories_and_actions(self):
        cases = {
            "custom dropdown options unavailable offline": "custom_options_not_in_snapshot",
            "multiple matching custom dropdown options": "custom_choice_ambiguous",
            "verified answer absent from custom dropdown options": "custom_choice_unmatched",
        }
        for reason, category in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(classify(reason), category)
                self.assertIn(category, BLOCKER_ACTIONS)
                self.assertNotIn("Evening", BLOCKER_ACTIONS[category])

    @classmethod
    def setUpClass(cls):
        cls.engine = sync_playwright().start()
        cls.addClassCleanup(cls.engine.stop)
        cls.browser = cls.engine.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def test_detached_aria_dropdown_with_static_options_does_not_fill(self):
        html = """<form>
            <label>First Name<input name="first_name" required></label>
            <label>Email<input type="email" name="email" required></label>
            <div role="combobox" aria-label="Preferred fictional shift"
                 aria-required="true" aria-controls="fictional-options"
                 aria-expanded="true" tabindex="0"></div>
            <div id="fictional-options" role="listbox">
                <div role="option">Morning</div>
                <div role="option">Evening</div>
            </div>
            </form>"""
        page = self.browser.new_page(java_script_enabled=False, offline=True)
        try:
            page.set_content(html)
            result, details = apply_to_page(page, CFG)
            self.assertEqual(result, "needs_review")
            unresolved = json.loads(details)["unresolved"]
            self.assertTrue(any(
                item["required"] and
                item["reason"] == "verified choice available, selection requires manual input"
                for item in unresolved
            ))
            self.assertEqual(page.locator('[role="option"][aria-selected="true"]').count(), 0)
            self.assertNotIn("Evening", details)
            self.assertNotIn("example@example.invalid", details)
        finally:
            page.close()

    def test_missing_dynamic_options_are_not_assumed(self):
        html = """<form>
            <label>First Name<input name="first_name" required></label>
            <label>Email<input type="email" name="email" required></label>
            <div role="combobox" aria-label="Preferred fictional shift"
                 aria-controls="dynamic-options" aria-required="true"></div>
            </form>"""
        page = self.browser.new_page(java_script_enabled=False, offline=True)
        try:
            page.set_content(html)
            outcome, details = apply_to_page(page, CFG)
            self.assertEqual(outcome, "needs_review")
            self.assertTrue(any(
                x["reason"] == "custom dropdown options unavailable offline"
                for x in json.loads(details)["unresolved"]
            ))
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
