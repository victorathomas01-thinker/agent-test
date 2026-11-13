"""Synthetic employer-question label tests. No employer traffic or submission."""
import json
import unittest

from playwright.sync_api import sync_playwright

from agent.browser import apply_to_page, field_metadata
from agent.core import normalize_question

QUESTION = "Can you work the required evening schedule?"
CFG = {
    "profile": {"first_name": "Sample", "email": "sample@example.invalid"},
    "verified_answers": {},
    "verified_questions": {normalize_question(QUESTION): "Yes"},
    "automation": {"allow_live_submit": False},
}
FORM = """<form>
<label>First Name<input name="first_name" required></label>
<label>Email<input type="email" name="email" required></label>
<label>{question}<select id="schedule" required>
  <option value="">Choose an answer</option>
  <option value="yes">Yes</option>
  <option value="no">No</option>
</select></label>
</form>"""


class EmployerQuestionLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = sync_playwright().start()
        cls.addClassCleanup(cls.engine.stop)
        cls.browser = cls.engine.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def test_nested_select_uses_question_without_option_text(self):
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content(FORM.format(question=QUESTION))
            fields = field_metadata(page)
            select = next(item for item in fields if item["id"] == "schedule")
            self.assertEqual(select["label"], QUESTION)
            self.assertEqual(len(select["options"]), 3)
            status, details = apply_to_page(page, CFG)
            self.assertEqual(status, "prepared", details)
            self.assertEqual(page.locator("#schedule").input_value(), "yes")
            self.assertNotIn("sample@example.invalid", details)
        finally:
            page.close()

    def test_unknown_question_is_not_guessed(self):
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content(FORM.format(question="Can you work overnight?"))
            status, details = apply_to_page(page, CFG)
            self.assertEqual(status, "needs_review")
            self.assertEqual(page.locator("#schedule").input_value(), "")
            unresolved = json.loads(details)["unresolved"]
            self.assertTrue(any(item["reason"] == "no verified answer" and item["required"]
                                for item in unresolved))
        finally:
            page.close()

    def test_radio_choice_labels_survive_cleaning(self):
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content("""<fieldset>
              <legend>Choose one</legend>
              <label><input type="radio" name="choice" value="yes">Yes</label>
              <label><input type="radio" name="choice" value="no">No</label>
            </fieldset>""")
            choices = [f for f in field_metadata(page) if f["type"] == "radio"]
            self.assertEqual([f["label"] for f in choices], ["Yes", "No"])
        finally:
            page.close()

    def test_explicit_for_label_remains_usable(self):
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content("""<label for="answer">Can you work the required evening schedule?</label>
              <select id="answer"><option value="yes">Yes</option></select>""")
            self.assertEqual(field_metadata(page)[0]["label"], QUESTION)
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
