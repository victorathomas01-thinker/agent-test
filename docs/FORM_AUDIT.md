# Offline Form Readiness: diagnostic reporting

**Purpose:** Turn the prior 20/20 unresolved synthetic/offline form-preview experience into a measurable engineering backlog without pretending that a detached browser snapshot can complete an employer's live application.

## What the new tooling does

Use `python main.py form-audit` to summarize the latest saved offline form attempt per job, or open the local `python main.py serve` dashboard and select **Form Readiness**. Results are generated from the existing local `attempts` table and describe:

- Number of local job attempts and disconnected dry-run form previews.
- Count of previews that passed **only the currently copied offline form step**.
- Required unresolved fields grouped into categories: missing verified answers, unsupported custom controls, ambiguous radio/dropdown choices, resume/identity fields, validation errors, later steps, login, unavailable pages, and browser errors.
- Counts per category both by unresolved required fields and by affected job, so one complex employer form does not make it look like multiple companies failed.

The report is an **aggregate of locally recorded attempts**, not a newly executed experiment and not a measured result for the previous 20-posting pilot unless those records are actually in the user's current database. A form can appear prepared in an offline snapshot but still fail on the real browser because of JavaScript, hidden fields, conditional choices, account creation, CAPTCHA, attachments, or later steps.

## Privacy and safety

No applicant values, full resumes, emails, or form field labels are included in the summary or dashboard response. Nothing is uploaded or committed. The dashboard remains bound to localhost and uses the existing host/origin protections; the new aggregate endpoint is read-only.

No employer website is visited by this diagnostic tool. It never fills a live form, attaches a file, or changes any submission state. The existing user-operated final Submit boundary remains unchanged.

## How to use the results

Fix the dominant **required** blocker categories first and add corresponding detached-form fixtures. For each proposed fix, confirm that it fills only unambiguous verified facts, leaves sensitive/unknown choices for manual review, and does not send data to a real site during testing. Separate a successful offline preview from a demonstrated attended live final-review step.

The actual previous pilot cannot be reclassified without its locally stored form diagnostics. The code's synthetic tests show the report works, not that the number of unresolved real forms has decreased.

See [P0 engineering issue #6](https://github.com/victorathomas01-thinker/agent-test/issues/6) and [eligibility calibration](ELIGIBILITY_CALIBRATION.md).
