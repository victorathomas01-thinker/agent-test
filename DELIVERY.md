# Preparation upgrade

| Area | Before | This branch |
| --- | --- | --- |
| Discovery | Greenhouse, Lever, and community leads | Adds public Ashby and SmartRecruiters adapters, metadata, bounded transient retries, and tracking-link normalization |
| Eligibility | Title rules and basic GPA matching | Checks explicit GPA minimums and month-to-month graduation windows, with preferred GPA language separated |
| Ranking | One keyword score | Adds resume-text overlap, local and hybrid preferences, configurable strategies, and an explanation command |
| Materials | Reordered text preview | Stores a versioned package with validated resume text, original file, content hashes, and optional evidence-based cover-letter draft |
| Preparation | Discover and preview | Scheduled entry point builds and validates a package before each preview, then records its outcomes locally |
| Tracking | Preview attempts, holds, and receipts | Adds run history, package history, confirmed outcome transitions, and follow-up dates |
| Review | Terminal queue | Adds an escaped, local-only HTML report with status, score, fit evidence, run history, and package links |
| Testing | Local synthetic tests | Adds Windows CI, public adapter smoke checks, and a synthetic discovery-to-dashboard test |

## Remaining boundaries

- Form rehearsal uses an isolated browser copy. Attended prefill and confirmation checks cover supported direct Greenhouse and Lever workflows. Ashby and SmartRecruiters are discovery sources with generic offline preview where a form is accessible. Workday, iCIMS, and Indeed-hosted form adapters still need implementation and permission checks.
- Discovery deduplicates canonical links. Similar roles with distinct posting IDs remain separate. HTTP 404 and 410 mark a previewed job expired. Complete board scans also reconcile removed listings and preserve submitted or pending records. Repost detection, incremental provider synchronization, and wider regional coverage remain follow-up work.
- Ranking uses deterministic signals and resume-text overlap. It needs broader qualification extraction, more geographic policies, and calibrated user feedback before it can replace review. A score describes priority, not hiring probability.
- Packages preserve source text and copy the original resume. Tailored PDF and DOCX layout generation, structured project evidence, richer variant authoring, and grounded written application responses remain open. Cover letters are local review drafts.
- Windows Task Scheduler registration is optional. The script passed syntax checking and a Windows `-WhatIf` preview. The existing Codex schedule remains the current scheduler. A crashed run may leave a running row for investigation. The shared preview quota prevents immediate duplicate attempts.
- The dashboard is a generated local report. It has no authenticated web service, account-connected mailbox, or resume conversion statistics. Receipt exports and interview tracking work locally.
- No production submission path was enabled or tested. The attended workflow still requires the applicant to approve the exact posting and click Submit. A future unattended mode would need provider-specific success tests, revocable per-job authorization, an independently enforced submission boundary, rate limits, and persistent idempotency before any activation. A quota alone grants no permission.
