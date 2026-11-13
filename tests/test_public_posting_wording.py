"""Small public-source-derived requirement wording checks (not a hiring benchmark).

The short, limited excerpts below are cited to public Workday job descriptions
observed in October–November 2026. They are NOT current-open-job assertions,
not entire descriptions, not user-specific applicant data, and not a held-out
representative sample of employer requirements.
"""
import unittest

from agent import core
from agent.matching import qualifications
from agent.workbench import can_override


class PublicPostingWordingTests(unittest.TestCase):
    def test_aig_explicit_hard_gpa_and_prior_internship(self):
        # AIG early careers Technology internship, job JR2603638.
        # https://aig.wd1.myworkdayjobs.com/en-US/aig/job/XMLNAME-2027-Early-Careers--Summer-Intern--Technology---United-States--Charlotte--NC--Houston--TX----Jersey-City--NJ_JR2603638-1
        source_excerpt = ("Minimum cumulative GPA of 3.4 or higher. "
                          "Previous internship experience is required.")
        synthetic_applicant = {"graduation": "December 2027"}
        flags = qualifications(source_excerpt, synthetic_applicant, 2.6)
        self.assertTrue(any("3.4" in flag for flag in flags))
        self.assertIn("Prior internship experience required — confirm verified evidence", flags)
        self.assertFalse(can_override({"reason": "; ".join(flags), "eligible": 0}),
                         "An explicit hard GPA requirement must not be overrideable as mere uncertainty.")

    def test_wells_fargo_desired_graduation_is_not_hard_disqualifier(self):
        # Wells Fargo Data Engineering internship, job R-583066.
        # https://wf.wd1.myworkdayjobs.com/en-US/WellsFargoJobs/job/CHARLOTTE-NC/XMLNAME-2027-Technology-Summer-Internship---Early-Careers--Data-Engineering-_R-583066
        # Rephrased and shortened to test the *Desired Qualifications* scope.
        source_excerpt = ("Desired Qualifications: Currently pursuing a degree "
                          "with expected graduation between December 2027 and June 2028.")
        flags = qualifications(source_excerpt, {"graduation": "August 2029"}, 3.8)
        self.assertEqual(flags, [], "A preferred graduation window cannot be a hard blocker.")
        cfg = core.with_defaults({"profile": {"graduation": "August 2029"}})
        _, eligible, reason = core.evaluate({
            "title": "Data Analyst Intern", "location": "Charlotte",
            "description": source_excerpt, "url": "https://example.invalid/jobs/1",
        }, cfg)
        self.assertNotIn("Graduation outside required window", reason)

    def test_protiviti_relative_graduation_is_manual_review(self):
        # Protiviti Charlotte Technology Consulting Intern 2027, job JR-258879.
        # https://roberthalf.wd1.myworkdayjobs.com/en-US/ProtivitiNA/job/Charlotte-Technology-Consulting-Intern---2027_JR-258879
        source_excerpt = ("Graduation status: Expected to graduate within 12 months "
                          "after completion of the internship.")
        flags = qualifications(source_excerpt, {"graduation": "December 2027"}, 3.2)
        self.assertEqual(flags, ["Graduation relative to internship end — confirm dates"])
        self.assertTrue(can_override({"reason": flags[0], "eligible": 0}),
                        "The applicant may confirm internship-specific dates.")

    def test_truist_soft_academic_performance_not_fabricated_gpa(self):
        # Truist Technology Data and Operations Internship, job R0118061.
        # https://truist.wd1.myworkdayjobs.com/en-US/Careers/job/XMLNAME-2027-Technology--Data--and--Operations-Internship_R0118061
        self.assertEqual(qualifications("Demonstrated strong academic performance.",
                                        {"graduation": "December 2027"}, 2.6), [])

    def test_wells_fargo_equivalent_experience_not_auto_excluded(self):
        # Wells Fargo R-583066 permits education/training as experience equivalents.
        source_excerpt = ("Six months of work experience or equivalent through "
                          "work, education, training, or military service.")
        self.assertEqual(qualifications(source_excerpt,
                                        {"graduation": "December 2027"}, 2.6), [])

    def test_ordinary_mandatory_graduation_range_still_hard_review(self):
        # This is a synthetic requirement counterexample, not a real posting.
        flags = qualifications("Applicants must graduate between May 2027 and December 2027.",
                               {"graduation": "May 2029"}, 3.4)
        self.assertTrue(any("Graduation outside required window" in flag for flag in flags))


if __name__ == "__main__":
    unittest.main()
