# First live public form-structure observation — November 12, 2026

**Status:** one bounded, read-only observation of a directly listed **Lever / Zoox** public apply page. This is a form structure sample, **not** a form-filling or submission test, and not a representative survey of employer forms.

The [GitHub Actions read-only form run](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43361435744) succeeded. It fetched at most one direct Lever apply URL returned by Zoox's public posting API, checked robots policy, launched a fresh Chromium browser, and only read visible form metadata. The browser **blocked every non-GET/HEAD request** and disallowed requests outside the exact public Lever host. No applicant data was loaded, no control was selected, no file was attached, and no application was submitted.

## Actual observations

| Metric | Result |
| --- | ---: |
| Visible controls | 34 |
| Required controls | 13 |
| Required custom/unknown controls | 0 |
| Required checkboxes | 8 |
| Required email fields | 1 |
| Required single-select dropdowns | 1 |
| Required text fields | 2 |
| Required long-form text fields | 1 |

Across all visible controls, including optional ones, the form also had 19 checkboxes, four single-select dropdowns, seven text fields, two textareas and one file input. **This is a single source sample, not a rate for all Zoox or Lever applications.** The source-specific page and any raw form question labels were deliberately not written into the CI log.

The most actionable engineering signal is the concentration of **eight required checkboxes**. Checkboxes can represent legal acknowledgments, screening answers, demographic disclosures or multi-select questions. A form automation system must not select them just to achieve a green validation state. Even an applicant who has given a general answer must review the employer-specific wording before any legal attestation or sensitive disclosure.

## Engineering improvement made

This PR makes the local disconnected form preview explain these blockers more precisely:

- A standalone checkbox left unanswered is categorized `checkbox_attestation_or_choice`.
- A grouped checkbox question is categorized `checkbox_group_manual_review`.
- Neither is checked automatically. The existing `needs_review` gate remains in force, and the private `python main.py form-audit` view can now count these categories separately.
- Synthetic Chromium tests confirm both checkbox types remain unchecked after offline preparation and required fields stay unresolved.

The public form read tool itself reports aggregate field types only, never raw labels, applicant answers, uploads, browser profiles, recruiter communications, or form contents. The optional one-time GitHub Actions workflow has no schedule and is path-gated to this review branch.

## What this does not establish

- The application was not filled or submitted. Nothing in this test establishes a usable completed application.
- The prior 20 employer forms have **not** been automatically retested, so their original unresolved-field count remains the baseline.
- One application form cannot establish overall Lever/Greenhouse/Workday readiness or whether employer validation requires JavaScript, multiple steps, CAPTCHA, consent or account creation.
- Counts reflect controls visible on the inspected step, not conditional controls or later application steps.
- The test browser blocked cross-origin resources; it may not render every dynamic field that a normal applicant would encounter. A complete live form validation requires an explicitly attended, human-operated review.

## Next actions

1. Use the existing **private** `python main.py form-audit` results to determine how common checkbox, dropdown, resume, custom widget and later-step issues are in the user's *actual local* attempts.
2. Add isolated synthetic fixture coverage for the dominant legitimate field types, while refusing to infer missing facts or select attestations.
3. On a later explicitly attended application, verify field-level correctness in the employer's own page before any final user-operated Submit.
4. Keep Workday/custom employer portals discovery-only until an actual safe application flow has been independently validated.

This change stacks on [source validation PR #11](https://github.com/victorathomas01-thinker/agent-test/pull/11) and earlier unmerged development PRs. No merge, live submission, or scheduled employer traffic is authorized.
