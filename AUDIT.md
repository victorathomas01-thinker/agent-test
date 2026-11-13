# Personal Job Agent audit

Baseline is commit `11af6a2`. The existing workflow uses public Greenhouse and Lever feeds, a local SQLite log, isolated form previews, and an attended Edge workflow. The local master resume was readable and the existing database contained 4,320 rows at audit time. Neither the resume nor the database is part of this repository.

## Verified defects

| Priority | Finding | Impact |
| --- | --- | --- |
| P0 | CSV import hashes the full URL and does not reconcile with ATS rows. | Tracking links and repeated imports can produce parallel records for one posting. |
| P1 | Eligibility uses title keywords and a single GPA match. | Hard graduation windows are missed, and preferred requirements can be confused with exclusions. |
| P1 | Discovery only fetches Greenhouse and Lever boards and has no retry policy. | Relevant roles on other boards are missed and transient errors reduce coverage. |
| P1 | The scheduled workflow does not save a run record or build a versioned application package. | Recovery and investigation depend on terminal output. |
| P2 | Ranking exposes a single score and exclusion message. | It is difficult to tell which part of the posting drove the order. |

## Design limitations

- The browser rehearsal isolates applicant data. Attended Edge automation supports a subset of direct Greenhouse and Lever forms and the applicant clicks Submit. Login, CAPTCHA, unsupported widgets, and uncertain receipts need review.
- Resume tailoring reorders source text. It has no package manifest, evidence index, cover letter, or formatted resume export.
- The CLI queue and local receipt inbox do not provide a consolidated dashboard or account-connected email tracking.
- The Windows setup script installs the runtime and tests. A separate Codex automation currently invokes the dry-run command.

## Implementation priority

Preserve existing records and submission protections first. Add source and eligibility coverage, explainable ranking, package provenance, run records, and a local review interface. Use synthetic tests for browser and submission changes. Leave unattended live submission disabled.
