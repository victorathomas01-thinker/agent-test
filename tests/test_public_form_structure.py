"""Synthetic, network-free tests for the one-off form metadata reporter."""
import unittest

from scripts.probe_public_form import classify_fields


class PublicFormStructureTests(unittest.TestCase):
    def test_aggregate_field_types_without_employer_questions(self):
        fields = [
            {"type": "email", "visible": True, "disabled": False,
             "required": True, "label": "PRIVATE_EMAIL_LABEL", "name": "private_email"},
            {"type": "text", "visible": True, "disabled": False,
             "required": True, "label": "PRIVATE_FIRST_NAME_LABEL"},
            {"type": "custom", "visible": True, "disabled": False,
             "required": True, "label": "PRIVATE_CUSTOM_QUESTION"},
            {"type": "select-one", "visible": True, "disabled": False,
             "required": True, "label": "PRIVATE_DROPDOWN_QUESTION"},
            {"type": "textarea", "visible": True, "disabled": False,
             "required": False},
            {"type": "checkbox", "visible": True, "disabled": True,
             "required": True},
            {"type": "text", "visible": False, "disabled": False,
             "required": True},
            {"type": "submit", "visible": True, "disabled": False,
             "required": True},
        ]
        result = classify_fields(fields)
        self.assertEqual(result["visible_fields"], 5)
        self.assertEqual(result["required_fields"], 4)
        self.assertEqual(result["required_custom_or_unknown"], 1)
        self.assertEqual(result["required_types"]["custom"], 1)
        self.assertEqual(result["required_types"]["select-one"], 1)
        self.assertNotIn("PRIVATE_", repr(result))

    def test_unknown_required_control_requires_review(self):
        fields = [{"type": "novel-widget", "visible": True,
                   "disabled": False, "required": True}]
        result = classify_fields(fields)
        self.assertEqual(result["types"], {"other": 1})
        self.assertEqual(result["required_custom_or_unknown"], 1)

    def test_no_visible_controls_is_not_a_prepared_application(self):
        self.assertEqual(classify_fields([])["visible_fields"], 0)
        hidden = [{"type": "text", "visible": False, "required": True}]
        self.assertEqual(classify_fields(hidden)["required_fields"], 0)


if __name__ == "__main__":
    unittest.main()
