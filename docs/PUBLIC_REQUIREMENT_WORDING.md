# Public posting wording regression corpus

**Scope:** a handful of source-derived examples, **not** a representative or blind employer eligibility accuracy study. The publicly visible posting pages below were indexed during October–November 2026. Several have since passed their posting deadlines. No example proves a vacancy is currently open or that the synthetic applicant would receive an interview.

## What these tests expose

| Source / posting | Narrow public requirement signal | Expected agent behavior |
| --- | --- | --- |
| [AIG technology summer internship](https://aig.wd1.myworkdayjobs.com/en-US/aig/job/XMLNAME-2027-Early-Careers--Summer-Intern--Technology---United-States--Charlotte--NC--Houston--TX----Jersey-City--NJ_JR2603638-1) | Mandatory high GPA plus prior internship experience | Review hard GPA if verified candidate evidence is below threshold; flag internship requirement until verified |
| [Wells Fargo data-engineering internship](https://wf.wd1.myworkdayjobs.com/en-US/WellsFargoJobs/job/CHARLOTTE-NC/XMLNAME-2027-Technology-Summer-Internship---Early-Careers--Data-Engineering-_R-583066) | Graduation range appears under **Desired Qualifications** | Never reject solely because a preferred date range is not met |
| [Protiviti Charlotte technology-consulting internship](https://roberthalf.wd1.myworkdayjobs.com/en-US/ProtivitiNA/job/Charlotte-Technology-Consulting-Intern---2027_JR-258879) | Requires graduation within a time window relative to the internship's end | Flag as requiring verification of the actual internship-end date; do not infer it |
| [Truist technology/data/operations internship](https://truist.wd1.myworkdayjobs.com/en-US/Careers/job/XMLNAME-2027-Technology--Data--and--Operations-Internship_R0118061) | Broad academic-performance language, no GPA number in the selected excerpt | Do not invent a hard numeric GPA cutoff |
| [Wells Fargo R-583066](https://wf.wd1.myworkdayjobs.com/en-US/WellsFargoJobs/job/CHARLOTTE-NC/XMLNAME-2027-Technology-Summer-Internship---Early-Careers--Data-Engineering-_R-583066) | Prior experience wording permits education/training equivalents | Never treat the *short excerpt* as an unconditional experienced-only requirement |

All test applicant profiles are **synthetic**, intentionally different from the actual user's sensitive or locally verified facts. The fixture excerpts are short and, where appropriate, paraphrased. See `tests/test_public_posting_wording.py`.

The previous requirement detector could mistakenly treat **desired** graduation ranges as hard exclusions. It now recognizes that word as optional, like `preferred`. Explicit prior internship experience and relative-to-internship-end graduation requirements are flagged for manual review because a verified candidate profile and actual program dates are required. The workbench allows an explicit **offline** override of these uncertain requirements, but never overrides an independently confirmed hard GPA failure.

## What the test pass means—and does not mean

If these cases pass, the engine handles these particular examples as annotated. That is useful regression evidence. It is **not** evidence that requirements from hundreds of employers are being interpreted correctly, nor evidence of employer site reachability, application readiness, or an offer probability.

The next quantitative study should use independently reviewed, previously unseen employer postings across Workday, Greenhouse, Lever, Ashby and custom sites. For each posting, label only the qualification dimensions with direct quoted evidence, marking `mandatory`, `preferred` or `ambiguous`, then report false exclusions, false approvals, and unknown rates by source. Do not encode private applicant values in Git.

Other unaddressed requirements include professional experience equivalencies, licenses, active-enrollment requirements, immigration nuances, mandatory certifications and accurate work schedules.

See [P0 issue #6](https://github.com/victorathomas01-thinker/agent-test/issues/6).
