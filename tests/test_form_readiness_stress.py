"""Detached, synthetic form stress tests based on aggregate public observations.

All content is fictional. Never opens an employer or enters applicant data
on a live application, and never attempts a submission.
"""
import json
import unittest

from playwright.sync_api import sync_playwright

from agent.browser import apply_to_page, field_metadata
from scripts.probe_public_form import classify_fields

PUBLIC_OBSERVATION_SHAPE = {
    "checkbox": 19,
    "email": 1,
    "file": 1,
    "select-one": 4,
    "text": 7,
    "textarea": 2,
}
REQUIRED_SHAPE = {
    "checkbox": 8,
    "email": 1,
    "select-one": 1,
    "text": 2,
    "textarea": 1,
}


def fictional_form_shape():
    html = ["<!doctype html><form>",
            '<label>First Name<input type="text" name="first_name" required></label>',
            '<label>Last Name<input type="text" name="last_name" required></label>',
            '<label>Email<input type="email" name="email" required></label>']
    for index in range(5):
        html.append(f'<label>Optional note {index}<input type="text" name="note_{index}"></label>')
    for index in range(4):
        required = " required" if index == 0 else ""
        html.append(f'<label>Fictional choice {index}<select name="choice_{index}"{required}>'
                    '<option value="">Select</option><option value="a">Choice A</option></select></label>')
    for index in range(2):
        required = " required" if index == 0 else ""
        html.append(f'<label>Fictional free text {index}<textarea name="body_{index}"{required}></textarea></label>')
    html.append('<label>Fictional résumé<input type="file" name="resume"></label>')
    for index in range(19):
        required = " required" if index < 8 else ""
        html.append(f'<label><input type="checkbox" name="attestation_{index}"{required}> '
                    f'Fictional acknowledgment / voluntary preference {index}</label>')
    html.append("</form>")
    return "".join(html)


CFG = {
    "profile": {"first_name": "Sample", "last_name": "Person",
                "email": "sample@example.invalid", "resume_path": ""},
    "verified_answers": {},
    "automation": {"allow_live_submit": False},
}


class FormReadinessStressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = sync_playwright().start()
        cls.addClassCleanup(engine.stop)
        cls.browser = engine.chromium.launch(headless=True)
        cls.addClassCleanup(cls.browser.close)

    def test_public_observation_shape_is_never_reported_prepared(self):
        """A fictional same-count form with eight required attestations is blocked."""
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content(fictional_form_shape())
            metadata = field_metadata(page)
            summary = classify_fields(metadata)
            self.assertEqual(summary["visible_fields"], 34)
            self.assertEqual(summary["required_fields"], 13)
            self.assertEqual(summary["types"], PUBLIC_OBSERVATION_SHAPE)
            self.assertEqual(summary["required_types"], REQUIRED_SHAPE)
            self.assertEqual(summary["required_checkbox_attestations_or_choices"], 8)
            self.assertTrue(summary["requires_human_decisions_on_observed_step"])
            outcome, details = apply_to_page(page, CFG)
            self.assertEqual(outcome, "needs_review")
            unresolved = json.loads(details)["unresolved"]
            required_checkboxes = [f for f in unresolved if f["required"] and
                                   f["reason"] == "checkbox requires explicit applicant review"]
            self.assertEqual(len(required_checkboxes), 8)
            self.assertEqual(page.locator('input[type="checkbox"]:checked').count(), 0)
            self.assertNotIn("sample@example.invalid", details)
        finally:
            page.close()

    def test_required_aria_only_checkbox_radio_and_switch_are_not_omitted(self):
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content("""
            <form>
              <label>First Name<input name="first_name" required></label>
              <label>Email<input type="email" name="email" required></label>
              <div role="checkbox" tabindex="0" aria-required="true"
                   aria-checked="false" aria-label="Fictional certification"></div>
              <div role="radiogroup" aria-required="true" aria-label="Fictional selection">
                <div role="radio" tabindex="0" aria-checked="false"
                     aria-label="One fictional option"></div>
                <div role="radio" tabindex="0" aria-checked="false"
                     aria-label="Another fictional option"></div>
              </div>
              <div role="switch" aria-required="true" aria-checked="false"
                   aria-label="Fictional setting"></div>
            </form>
            """)
            fields = field_metadata(page)
            custom = [f for f in fields if f["type"] == "custom"]
            self.assertEqual(len(custom), 4)
            self.assertTrue(all(f["required"] for f in custom))
            outcome, details = apply_to_page(page, CFG)
            self.assertEqual(outcome, "needs_review", details)
            reasons = json.loads(details)["unresolved"]
            manual = [f for f in reasons if f["required"]
                      and f["reason"] == "custom control requires manual input"]
            self.assertEqual(len(manual), 4)
            self.assertEqual(page.locator('[aria-checked="true"]').count(), 0)
            self.assertEqual(classify_fields(fields)["required_custom_or_unknown"], 4)
        finally:
            page.close()

    def test_synthetic_greenhouse_28_control_shape_requires_manual_custom_review(self):
        # Fictional content matching ONLY the aggregate type counts observed
        # in one real public Greenhouse form. No actual employer questions.
        pieces = ["<form>",
                  '<label>First Name<input type="text" name="first_name" required></label>',
                  '<label>Last Name<input type="text" name="last_name" required></label>',
                  '<label>Email<input type="text" name="email" required></label>']
        for i in range(2):
            pieces.append(f'<label>Optional synthetic text {i}<input type="text"></label>')
        for i in range(18):
            required = ' aria-required="true"' if i < 10 else ''
            pieces.append(
                f'<label>Synthetic combobox {i}<input role="combobox" '
                f'aria-label="Synthetic option {i}"{required}></label>')
        pieces.extend([
            '<label>Optional phone<input type="tel"></label>',
            '<label>Synthetic résumé<input type="file" name="resume" required></label>',
        ])
        for i in range(3):
            pieces.append(f'<label>Required synthetic paragraph {i}<textarea required></textarea></label>')
        pieces.append("</form>")
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content("".join(pieces))
            summary = classify_fields(field_metadata(page))
            self.assertEqual(summary["visible_fields"], 28)
            self.assertEqual(summary["required_fields"], 17)
            self.assertEqual(summary["types"], {
                "custom": 18, "file": 1, "tel": 1, "text": 5, "textarea": 3,
            })
            self.assertEqual(summary["required_types"], {
                "custom": 10, "file": 1, "text": 3, "textarea": 3,
            })
            self.assertTrue(summary["requires_human_decisions_on_observed_step"])
            self.assertEqual(summary["required_custom_or_unknown"], 10)
            outcome, payload = apply_to_page(page, CFG)
            self.assertEqual(outcome, "needs_review")
            unresolved = json.loads(payload)["unresolved"]
            self.assertEqual(sum(f["required"] and
                                 "custom control" in f["reason"] for f in unresolved), 10)
            self.assertEqual(sum(f["required"] and
                                 "resume" in f["reason"] for f in unresolved), 1)
            self.assertNotIn("sample@example.invalid", payload)
        finally:
            page.close()

    def test_optional_aria_only_controls_still_visible_but_not_required(self):
        page = self.browser.new_page(java_script_enabled=False)
        try:
            page.set_content("""
            <form>
              <label>First Name<input name="first_name" required></label>
              <label>Email<input type="email" name="email" required></label>
              <div role="checkbox" aria-checked="false" aria-label="Optional choice"></div>
            </form>
            """)
            fields = field_metadata(page)
            summary = classify_fields(fields)
            self.assertEqual(summary["required_custom_or_unknown"], 0)
            self.assertEqual(summary["types"]["custom"], 1)
            outcome, details = apply_to_page(page, CFG)
            # Optional ARIA controls must not be checked automatically.
            self.assertEqual(outcome, "prepared", details)
            self.assertEqual(page.locator('[aria-checked="true"]').count(), 0)
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
