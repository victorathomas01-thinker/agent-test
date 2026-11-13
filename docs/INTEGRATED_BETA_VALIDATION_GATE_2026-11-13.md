# Integrated Job Agent beta — release validation gate

**Status:** review-only candidate. No user-device installation, live application submission, scheduler activation, or merging to `main` is authorized by this document.

This branch incorporates the beta release candidate and subsequent selected-preview freshness, wizard detection, question-label parsing, custom-choice diagnostics, and offline-readiness scoring. The readiness score estimates **effort on the inspected detached step**. It is **not** a probability of a successful application, a verified employer acceptance, or a hiring prediction.

## 1. Immutable review reference

Before release, record the exact tested commit SHA and GitHub Actions run URL here in the review notes. Do not rely on a green check from an earlier commit or a different branch.

### Automated checks
- [ ] Full Windows unit suite green **at candidate HEAD**
- [ ] `python -m scripts.integration_acceptance` green in disposable environment
- [ ] `pwsh -File .\\setup.ps1 -PreflightOnly` is nonmutating in disposable Windows environment
- [ ] New regression tests pass for posting freshness, wizard progression, verified-question label extraction, custom dropdown states, and readiness effort
- [ ] Git diff reviewed for any new startup triggers, automatic employer POST, live-submit enablement, or applicant data logs

### Device-specific gates (cannot be proven by GitHub Actions)
- [ ] On the candidate's real Windows machine, run **preflight first**, identify whether `agent.sqlite3` already exists, and record safe aggregate output only
- [ ] If a database exists, verify schema compatibility and make an explicit tested backup before migration; never overwrite the previous MVP history
- [ ] Verify local resume path and contact fields privately; never commit `config.json`, resumes, database files, screenshots with private answers, or browser profiles
- [ ] Open the dashboard without launching discovery, previews, employer requests, or a scheduled task merely by loading it
- [ ] Confirm `allow_live_submit=false` and no unattended employer traffic

## 2. Ten-job human validation sample

Select **ten distinct currently open listings** from official employer sites: at least three Charlotte-area/hybrid, three remote-compatible US, and four additional eligible roles across application support/healthcare IT, IT support, data/BI, and software development. Include only postings matching the user's December 2027 graduation window; exclude hard 3.0+ GPA requirements where established. Do not pad the sample with duplicates or knowingly ineligible postings.

Record **only non-sensitive operational observations** in a private local worksheet, not the GitHub repository:
- Official employer URL, ATS provider, read date, listing still open (confirmed/unconfirmed), eligibility outcome and manually checked rationale
- Whether the application is one step or multiple; any login, CAPTCHA, sensitive verification, or inaccessible source
- Detached preview status, readiness effort score/tier, number of unresolved required questions, type of blockers
- Minutes of manual work needed to finish **reviewing/preparing**, not submitting; whether the preview actually saved time
- Whether a required field was missed or an incorrect answer was suggested; stop and record a defect if so

Use the applicant's own normal process to validate any permitted employer form **only with explicit attended consent**. Never advance forms automatically, bypass bot challenges, upload private documents to a live site from automated testing, or submit an application as part of this gate.

## 3. Evaluation and stop conditions

Calculate sample counts with denominators: e.g. `6/10 inspected`, `4/6 current steps prepared`, `0/6 incorrect verified-answer selections`. Keep "could not inspect" distinct from "blocked on inspected form." Do not call current-step preparedness "application-ready."

**Release is blocked** if any of these occur:
- A preview writes personal data to an employer site, submits an application, or sends an unintended POST.
- A form is marked `prepared` despite an identified required unanswered field or an identified later step.
- Duplicate or wrong-job application identity/receipt is recorded, eligibility disqualifiers are silently overridden, or the wrong user database is modified.
- Resume/profile information appears in diagnostic exports, CI output, public issues, or the Git repository.
- A source failure/404 is treated as definitive closure or a stale posting is prepared without the required review.

Any scoring thresholds should be recalibrated *after* this pilot. Until then, use readiness only to triage manual work, **not** to authorize automatic sending.

## 4. Decision

After automated checks, device preflight, and the attended ten-job review, write down which gates passed, which failed, exact counts, unresolved defects, and the reviewed commit SHA. Only then consider a deliberate beta merge or a limited local install. Live submissions remain a separate later decision and should never be enabled by this checklist.
