"""Synthetic qualification wording; never tests a real applicant profile."""
import unittest

from agent import core
from agent.matching import qualifications


class EligibilityPrecisionTest(unittest.TestCase):
    PROFILE = {"graduation": "August 2027"}

    def test_explicit_minimum_gpa_word_orders(self):
        positive_cases = (
            "Minimum GPA of 3.5 is required.",
            "At least 3.5 cumulative GPA required.",
            "3.5 GPA minimum.",
            "GPA >= 3.5.",
            "The minimum GPA is 3.5.",
            "GPA 3.5+.",
            "GPA of at least 3.5.",
            "GPA 3.5 or higher required.",
        )
        for text in positive_cases:
            with self.subTest(text=text):
                self.assertIn("3.5", str(qualifications(text, self.PROFILE, "3.40")))
                self.assertEqual(qualifications(text, self.PROFILE, 3.50), [])

    def test_unstated_gpa_stays_review_not_automatic_pass(self):
        self.assertIn("Review hard minimum", str(
            qualifications("Minimum GPA of 3.0 is required.", self.PROFILE, None)))

    def test_preferred_gpa_not_an_exclusion(self):
        for text in (
            "Minimum GPA 3.5 preferred.",
            "GPA of 3.5 or higher preferred.",
            "At least 3.5 GPA desirable.",
            "3.5 GPA minimum is a plus.",
        ):
            with self.subTest(text=text):
                self.assertEqual(qualifications(text, self.PROFILE, 2.9), [])

    def test_mixed_required_and_preferred_needs_review(self):
        text = "Minimum GPA of 3.2 is required but GPA of 3.5 is preferred."
        result = qualifications(text, self.PROFILE, 3.2)
        self.assertIn("Mixed required/preferred GPA language", str(result))

    def test_decimal_gpa_is_not_split_or_rounded(self):
        self.assertIn("3.5", str(qualifications(
            "Minimum GPA of 3.5.", self.PROFILE, 3.49)))
        self.assertEqual(qualifications("Minimum GPA of 3.5.", self.PROFILE, 3.5), [])

    def test_explicit_graduation_latest_cutoff(self):
        result = qualifications("Applicants must graduate by May 2027.", self.PROFILE, 4.0)
        self.assertTrue(any("later than required cutoff" in item for item in result))
        self.assertEqual(qualifications(
            "Applicants must graduate by December 2027.", self.PROFILE, 4.0), [])
        self.assertTrue(qualifications("Must be graduating by May 2027.", self.PROFILE, 4.0))

    def test_explicit_graduation_earliest_date(self):
        result = qualifications("Must graduate no earlier than January 2028.", self.PROFILE, 4.0)
        self.assertTrue(any("earlier than required start" in item for item in result))
        self.assertEqual(qualifications(
            "Must graduate no earlier than January 2027.", self.PROFILE, 4.0), [])

    def test_graduation_windows_and_preferred_ranges(self):
        self.assertTrue(qualifications(
            "Applicants must be graduating between January 2028 and June 2028.",
            self.PROFILE, 4.0))
        self.assertEqual(qualifications(
            "Graduation between January 2028 and June 2028 is preferred.",
            self.PROFILE, 4.0), [])

    def test_malformed_or_unknown_candidate_gpa_stays_conservative(self):
        for gpa in ("unknown", "", "not provided", float("nan")):
            with self.subTest(gpa=repr(gpa)):
                result = qualifications("Minimum GPA 3.0 required.", self.PROFILE, gpa)
                self.assertTrue(result, "Missing evidence cannot satisfy an explicit minimum")

    def test_integration_keeps_unknowns_excluded_from_auto_preparation(self):
        cfg = core.with_defaults({
            "profile": {"graduation": "August 2027"},
            "preferences": {"exclude_hard_gpa_over": None},
            "verified_answers": {"work_authorized_us": True,
                                 "needs_sponsorship_now_or_future": False},
        })
        job = {"title": "Software Engineer Intern",
               "location": "Charlotte, NC",
               "url": "https://example.invalid/jobs/100",
               "description": "Applicants must graduate by May 2027. Minimum GPA of 3.5 required."}
        _, eligible, reason = core.evaluate(job, cfg)
        self.assertFalse(eligible)
        self.assertIn("Graduation later than required cutoff", reason)
        self.assertIn("Review hard minimum GPA", reason)


if __name__ == "__main__":
    unittest.main()
