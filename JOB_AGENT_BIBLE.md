# Personal Job Agent — Product Bible

**Version:** 1.0 — November 2026
**Repository:** `victorathomas01-thinker/agent-test`
**Primary objective:** Secure paid, relevant employment as soon as realistically possible while completing the verified degree.

## 1. Product mission

Build a reliable, highly autonomous personal job-search assistant that discovers employment opportunities, evaluates their suitability, ranks them according to the candidate's actual priorities, prepares application materials, completes repetitive application steps, and tracks outcomes.

The agent must drastically reduce the manual effort required to search for and apply to jobs.

Its primary workflow should be:

**Discover → Evaluate → Rank → Select → Prepare → Fill → Validate → Review → Submit → Track**

The candidate should spend time making decisions and pursuing opportunities, not repeatedly entering information or searching individual company websites.

The agent must prioritize working functionality over feature count, architectural sophistication, or impressive-looking dashboards.

## 2. Candidate profile

The agent must maintain the complete verified candidate profile locally. The private copy of this guide, stored at `private/JOB_AGENT_BIBLE.md` in the configured checkout, contains the original applicant-specific profile. Load verified degree, institution, concentration, graduation, GPA, employment and project evidence, skills, strengths, authorization, and application email from the local profile and résumé. Preserve the verified values. Do not infer additional personal information or commit it to Git.

Strategic preferences are Charlotte-area employment, hybrid preferred, with onsite and remote acceptable. Prefer direct-hire W-2 roles, internships, campus jobs, part-time and eligible full-time work. Exclude contract, contract-to-hire, 1099 and freelance arrangements. Keep personal information, browser sessions, and application history private.

## 3. Career priorities

Use the following ordering as the candidate's default strategic preference, not as an unconditional override of job quality.

| Priority | Career category | Examples |
|---|---|---|
| 1 | IT/application support | Help Desk, IT Support, Application Support |
| 2 | Healthcare technology | Hospital IT, Clinical Applications, EHR Support |
| 3 | Business systems/implementation | Systems Analyst, Implementation, Technical Onboarding |
| 4 | Software development | Software Engineer Intern, Junior Developer, Web Developer |
| 5 | Data/analytics | Data Analyst, BI Intern, Reporting |
| 6 | University/education IT | Student IT Assistant, Classroom Technology |
| 7 | Quality assurance | Software Tester, QA Analyst, UAT |
| 8 | Technical consulting/customer success | Solutions Engineering, Technical Customer Success |
| 9 | Infrastructure/operations | NOC Technician, Network Support, IT Operations |
| 10 | AI/automation | Automation Analyst, AI Operations |
| 11 | Product/project operations | Technical Coordinator, Product Operations |
| 12 | Entertainment/sports technology | Venue IT, Broadcast Technology, Game QA |

The search should cover the entire range, not just the first few categories.

Explore adjacent positions when skills and eligibility plausibly match, even if their titles are unfamiliar.

## 4. Employment eligibility

Separate every job's requirements into three groups:

**Hard disqualifiers:** Verified requirements the candidate cannot satisfy, such as mandatory completed bachelor's degrees before graduation, hard GPA minimums above the verified GPA, incompatible location or schedules, mandatory professional experience without accepted equivalents, and prohibited employment arrangements.

**Soft disadvantages:** Preferred skills, previous internships, recommended certifications, advanced technical knowledge, or other qualifications that are not mandatory.

**Unknowns:** Missing or ambiguous requirements that require verification.

A missing GPA requirement is not evidence of easy competitiveness.

Never reject jobs solely because a preferred qualification is missing.

For the following opportunities, evaluate student schedule compatibility:

- 15–25-hour part-time jobs during semesters
- Summer 2027 full-time internships
- Flexible academic-year internships
- Campus jobs
- Full-time permanent roles with feasible class arrangements

Permanent full-time employment is not categorically excluded, but schedule conflicts should be explicitly flagged.

Paid work is the default priority. Unpaid opportunities should not enter the main recommended queue.

## 5. Ranking model

Rank suitable jobs using these weighted criteria:

| Dimension | Weight |
|---|---:|
| Estimated hiring competitiveness | 30% |
| Career development and résumé value | 25% |
| Student schedule compatibility | 20% |
| Compensation and income stability | 15% |
| Personal interests and work environment | 10% |

Each dimension receives a transparent 0–100 score.

Final score = 0.30 × competitiveness + 0.25 × career value + 0.20 × schedule compatibility + 0.15 × compensation + 0.10 × interests.

**Competitiveness is an estimate, not a statistically calibrated probability of receiving an offer.**

Evaluate competitiveness using verified evidence such as required experience, education, location constraints, relevant projects, transferable experience, certifications, and hiring-program eligibility.

Do not invent applicant counts, hiring probabilities, or employer preferences.

Assign a confidence level to uncertain assessments. Missing information should never silently become a favorable assumption.

Evaluate category priority separately as a strategic sorting or tie-breaking preference. Do not let a low-quality IT position automatically outrank an excellent software internship.

Allow filtering by career category, location, pay, schedule, eligibility, and ranking score.

Maintain a distinct bridge-employment ranking when the immediate objective is earning income.

## 6. Discovery — exhaustive visibility

The agent must find opportunities through multiple complementary discovery methods.

**A. Structured job feeds**

Use existing Greenhouse, Lever, Ashby, and SmartRecruiters integrations where available.

**B. Direct company careers websites**

Navigate employer websites, locate careers pages, identify search functionality, follow job listings, extract details, and discover application destinations.

Support websites that render jobs dynamically with JavaScript.

**C. Additional ATS systems**

Investigate and implement permitted browser workflows for Workday, iCIMS, Oracle Recruiting, SuccessFactors, and other commonly encountered systems.

**D. Campus and educational employment**

Search UNC Charlotte departmental and student employment channels, university technology teams, UPIP, and related employment programs.

**E. Local employer targeting**

Maintain and expand a directory of Charlotte-area hospitals, healthcare systems, insurers, banks, universities, schools, manufacturers, nonprofits, entertainment venues, and smaller employers.

**F. Aggregators and web search**

Use permitted job-board sources, search engines, and open-source discovery tools to identify candidates for employer-site verification.

### Important discovery rules

- No arbitrary 25-employer discovery ceiling.
- Use configurable crawling budgets and rate limits rather than a permanently tiny list.
- Preserve every discovered job record, including low-ranking jobs, exclusions, and unverifiable records.
- Do not silently discard jobs because they lack an application adapter.
- Deduplicate across tracking URLs, employers, ATS systems, and canonical posting IDs.
- Track posting freshness, availability, and verification attempts.
- Preserve source provenance and the last successful fetch time.
- Do not report that a search found zero jobs when its sources failed.
- Never present unverifiable listings as confirmed open positions.
- Respect site access controls and applicable restrictions.

**Every discovered job must be visible in the dashboard.**

The candidate should be able to view, search, filter, and export the complete collection, including excluded, expired, and low-ranked listings.

## 7. Dashboard requirements

The dashboard is the main user interface, not an optional reporting accessory.

Required views:

**All Jobs:** Every discovered listing, with sorting, filtering, search, pagination, and export.

**Top Matches:** The highest-ranked eligible jobs, accompanied by clear scoring explanations.

**Selected:** Jobs the candidate has chosen to prepare.

**Ready to Review:** Applications filled as far as possible and awaiting final inspection.

**Needs Attention:** Blocked applications, grouped by the specific problem.

**Applications:** Submitted applications and their subsequent outcomes.

**History:** Discovery runs, application attempts, source errors, and changes in status.

For each listing, display:

- Role, employer, category and location
- Score and score explanation
- Eligibility and confidence
- Salary and schedule, when known
- Direct application link
- Posting date and deadline, if published
- Source and last verification time
- Preparation status
- Application status
- Relevant requirements and missing qualifications
- Available application documents

Support bulk selection and batch preparation.

The system must distinguish all discovered jobs from the curated top recommendations.

The candidate must be able to inspect why an excluded job was excluded and override an uncertain classification.

## 8. Core user interactions

The agent must support simple user commands or equivalent dashboard controls.

Examples:

- "Show me all the jobs you found this week."
- "Show your top 20 jobs."
- "Why is this job ranked above that one?"
- "Show only Charlotte healthcare IT jobs."
- "Find me part-time jobs paying at least $20 an hour."
- "Apply to jobs 2, 4, 6 and 8."
- "Prepare all selected applications."
- "Open the applications you've prepared."
- "What do you need from me?"
- "Don't recommend this employer again."
- "Which applications have I already submitted?"
- "Show jobs you excluded because of graduation requirements."

The minimum functional interpretation of "apply to these jobs" is: prepare the application packages, fill supported forms, navigate permitted intermediate steps, and make them available for final approval.

Do not interpret "apply" as permission for unattended final submission unless the candidate has separately authorized that capability.

A conversational interface is desirable, but dashboard controls must provide the same essential functionality without an LLM.

## 9. Persistent, reusable answer memory

Build a verified semantic answer library.

A single confirmed answer should be reusable across differently phrased but equivalent questions.

Examples:

"Are you authorized to work in the United States?"

"Do you have unrestricted U.S. work authorization?"

"Are you legally permitted to work in the United States?"

All may map to a shared work-authorization fact when their meaning and scope are equivalent.

Other common fields include:

- Sponsorship
- Age eligibility
- Relocation
- Education
- Graduation date
- Employment history
- Technical skills
- Years of experience
- Contact information
- Referrals
- Work arrangements
- Start-date availability
- Salary expectations

Use a hybrid approach:

1. Exact matches.
2. Normalized label and known synonym matches.
3. Verified semantic similarity.
4. LLM-assisted interpretation where available.
5. Manual review for uncertainty.

Do not treat textual similarity alone as sufficient evidence of equivalent meaning.

Preserve negation, conditional wording, timeframes, jurisdiction, and employer-specific qualifications.

Store reusable answers as typed facts with provenance, scope, verification date, and confidence rather than just question-and-answer strings.

Keep separate rules for sensitive demographic disclosures, disability, veteran status, background checks, legal declarations, and employment agreements.

Never guess sensitive responses or automatically opt into voluntary disclosures.

Allow the candidate to inspect, correct, and revoke remembered answers.

## 10. Written application answers

Support short-answer and essay-style application questions.

Use only verified personal experience and documented projects.

Generate relevant, natural, concise answers.

Examples:

- Why are you interested in the company?
- Describe a technical project.
- Explain a troubleshooting experience.
- Describe teamwork or customer service.
- Explain relevant coursework.
- Describe a challenge and how you handled it.

Use verified internship experience, actual projects, technical skills, and other verified experiences where relevant.

Do not generate fabricated achievements, invented metrics, or unsupported credentials.

Show a reviewable answer when the response is personal, uncertain, or consequential.

Allow approved answers to be reused as templates, adapted to new employers when appropriate.

## 11. Browser application automation

Use a hybrid browser architecture.

**Deterministic layer:** Stable Playwright selectors, provider-specific form adapters, known field mappings, controlled file uploads, and validation.

**Adaptive layer:** An AI-powered browser agent capable of interpreting unfamiliar layouts, finding interactive elements, and handling dynamic multi-step pages.

**Safety layer:** Independent restrictions on submission, external communications, sensitive data, and untrusted navigation.

Capabilities should include:

- Open official employer applications
- Reuse authenticated sessions where supported
- Fill profile information
- Fill verified answers
- Select dropdown and radio options
- Handle conditional questions
- Upload documents
- Navigate non-submitting intermediate steps
- Detect form validation errors
- Save application progress
- Recover from interrupted preparation
- Handle iframe and dynamic controls
- Identify final submission actions
- Stop when genuine user involvement is required

An intermediate "Continue" button must be checked for possible submission effects before being automated.

Do not blindly click every button named Next or Continue.

Do not bypass CAPTCHA, security challenges, or website access restrictions.

Never infer that a form is complete merely because its visible inputs are populated.

## 12. Browser tabs and final review

The preferred workflow is:

1. Candidate selects jobs.
2. Agent creates or selects application materials.
3. Agent opens each employer application in a controlled browser session.
4. Agent fills known information.
5. Agent navigates supported intermediate steps.
6. Agent validates form completion.
7. Agent saves the state and marks any blockers.
8. Candidate opens the prepared application.
9. Candidate reviews and approves final submission.

Provide batch-opening controls for prepared applications.

Persist browser session references and preparation records.

Recognize that some sites will not preserve unsent form data across tabs or sessions. Prefer live browser tabs when available, and otherwise resume through safe replay with validation.

Never claim an application is submission-ready unless the actual live workflow has been validated.

Record whether the application is prepared, awaiting review, submitted, or submission-unconfirmed.

## 13. Application documents

Maintain verified career evidence and appropriate résumé variants.

Support:

- Development résumé
- IT/application support résumé
- Data/analytics résumé
- Other variants justified by job requirements

Generate ATS-readable PDF/DOCX files when needed.

Tailor emphasis, ordering, descriptions, and wording without inventing facts.

Generate cover letters when required or potentially useful, but do not make unnecessary documents block otherwise ready applications.

Save package versions, source evidence, and corresponding job identifiers.

Automatically attach the right file to the right application field.

## 14. Application tracking and duplicate prevention

Track the complete lifecycle of every selected opportunity.

User-facing statuses:

- Not Started
- Preparing
- Needs Attention
- Ready for Review
- Applied
- Interviewing
- Offered
- Rejected
- Closed

Maintain additional internal statuses for uncertainty, retries, failed verification, and submission holds.

A successful application must be supported by appropriate confirmation evidence.

Never equate pressing Submit with confirmed application receipt.

Preserve application history when a listing is reposted.

Exclude already rejected jobs from default recommendations unless genuinely new circumstances justify reconsideration.

Prevent duplicate submissions and repeated processing.

Allow manual status updates and, if configured, read-only email confirmation monitoring.

## 15. Bridge employment

Maintain a separate search lane for student-compatible W-2 employment providing near-term income.

Examples:

- Campus administration
- Hospital patient access
- Customer support
- Education support
- Entertainment and event operations

Target approximately $18–$25 per hour and 15–25 hours per week when available.

Do not force bridge jobs into the same career-value ranking as technical roles.

Prefer opportunities that preserve time for school, technical skill development, interviews, and verified personal projects.

## 16. Open-source-first development

Before implementing any major subsystem from scratch, investigate existing maintained open-source solutions.

Evaluate candidates according to:

- Functional suitability
- Windows compatibility
- Integration effort
- License compatibility
- Cost and model requirements
- Data privacy
- Reliability
- Maintenance activity
- Testing quality
- Actual time saved

Evaluate Browser Use, Skyvern, Stagehand, Crawl4AI, JobSpy, Resume Matcher, and other relevant projects.

Prefer reusing mature components over duplicating functionality.

Do not integrate libraries merely because they are popular.

Build a working proof of concept before choosing an integration.

## 17. Operating requirements

The system must:

- Work on Windows
- Run on a configurable schedule
- Recover safely from crashes
- Preserve local configuration and history
- Avoid repeated discovery of unchanged records
- Store run logs and clear error messages
- Keep private information out of Git
- Support source-specific retry and rate limiting
- Continue processing other applications when one is blocked
- Provide a local dashboard
- Support realistic, reproducible integration tests

The agent must preserve a durable product roadmap and development status inside the repository so future Codex sessions know what remains.

## 18. Implementation priorities

**P0 — Essential:** All-jobs dashboard, broad company-site discovery, verified eligibility, correct ranking, reusable personal answers, reliable application form filling, multi-step handling, saved preparation state, and user-controlled submission.

**P1 — High value:** AI-powered fallback form handling, batch preparation, formatted tailored résumés, grounded written answers, browser-session recovery, and read-only outcome tracking.

**P2 — Enhancements:** Advanced search personalization, source-performance analytics, interview-outcome feedback, integrations, and more sophisticated job competitiveness estimation.

**P3 — Future autonomy:** A separately authorized, carefully tested unattended submission process.

Do not spend substantial development effort on P2 or P3 while core P0 functionality remains unreliable.

## 19. Acceptance testing

Build end-to-end synthetic tests covering:

- Company careers page discovery without an ATS API
- Dynamic JavaScript job listings
- Canonical URL verification
- All-job visibility
- GPA/graduation filtering
- Ranking calculations
- Semantic question equivalence
- Negated and non-equivalent questions
- Profile prefill
- Document uploads
- Custom dropdowns
- Multi-step forms
- Conditional questions
- Failed validation
- Authentication interruptions
- Session recovery
- Duplicate prevention
- Final submission boundaries
- Application status updates

Conduct a controlled pilot using 20 real, eligible job postings, without submitting them.

Report:

- Number successfully discovered and verified
- Number correctly classified
- Number with complete application packages
- Number of supported applications prepared
- Number requiring manual intervention
- Number with genuine final-review readiness
- Causes of every failed or incomplete preparation

The initial target is at least 80% autonomous preparation on the workflows the agent claims to support. Report actual performance honestly.

## 20. Long-term definition of done

The product is successful when the candidate can:

1. Open one dashboard and see every discovered job.
2. View high-quality, explainable job recommendations.
3. Select opportunities to pursue.
4. Start batch preparation with one action.
5. Have repetitive questions answered from persistent verified information.
6. Have documents generated and uploaded appropriately.
7. Have supported multi-page forms navigated automatically.
8. Open prepared application tabs for final review.
9. Submit with minimal additional work.
10. Track subsequent employer responses and outcomes.

**The central objective is to reduce the candidate's manual workload while improving the quality of their employment search.**

This document is the product's authoritative requirements guide. Future implementation decisions must serve these requirements rather than redefining the mission around whichever features are easiest to build.
