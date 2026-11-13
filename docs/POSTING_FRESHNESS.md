# Posting freshness and explicit application-deadline checks

**Status:** Draft review. This change adds safeguards to the local Job Agent; it is not an employer-confirmed live availability service and does not submit an application.

## Why

A real employer listing may remain indexed or saved in the agent long after its application window closes. The existing `web_checks.deadline` field was not reliably carried into regular eligibility recalculation. Old saved listings could also be selected from a queue without making clear when the board was last read.

The agent now uses two separate warning signals:

1. **Explicit application deadline**: Strictly parse a date from structured `web_checks.deadline` metadata or unmistakably labeled wording such as `Application deadline: October 26, 2026`, `Apply by 2026-10-26`, or `Applications close November 5, 2026`. Dates mentioned only as graduation, starting dates, or historical events are ignored. Unparseable/ambiguous slash dates are not guessed. Conflicting explicit dates are flagged for manual verification instead of treating either as ground truth.
2. **Age of the last source observation**: Nonmanual public postings last collected more than **14 calendar days** ago are flagged for another employer-source check. This means the collector has not re-observed the listing, **not** that the vacancy has definitely closed.

To avoid wrongly excluding an employer still accepting applications on its deadline date in another time zone, the explicit deadline warning starts **after one whole additional calendar day**. Source timestamps are stored in UTC; the check uses the UTC calendar date for portability.

## How to inspect locally

On the reviewed development branch:

```powershell
python main.py posting-audit
python main.py list --all
python main.py explain <official-job-id>
```

The `posting-audit` summary prints only the number of unsubmitted/unconfirmed records, clearly passed deadlines, old source observations, conflicting closing dates and missing source timestamps. It prints **no** employer names, job IDs, application contents, applicant information or stored credentials. The `list --all` and `explain` commands are intentionally more detailed; keep their output private.

- **New discoveries**: An explicitly passed deadline found in the public description prevents a newly discovered posting from entering the automatic eligibility queue.
- **Existing local jobs**: `refresh_eligibility` now joins saved `web_checks.deadline` and reevaluates deadline and source age. These jobs stay visible when listing all jobs but cannot be automatically prepared until re-observed or manually reviewed.
- **Manual `package`**: Rejects already expired records and records with a passed deadline or aged-out source. Direct official Greenhouse and Lever postings with **no dated public-source observation** also require re-discovery before a new package.
- **Attended submission**: `reserve_submission` independently rechecks the current job's saved status, public-source timestamp, and deadline under the same database transaction. It will not reserve a job already marked expired, in a closed/tracked state, stale, lacking a dated direct ATS observation, or past a clear deadline—even if a cached `eligible=1` value was left in the database.
- **No status forgery**: An uncertain deadline or stale source adds an eligibility-review reason; it does **not** mutate the stored job status to `expired`. That status is reserved for explicit complete-board disappearance reconciliation or other independently recorded reasons.

## Evidence and limitations

The new synthetic suite checks exact and abbreviated English dates, ISO dates and time zones, unparseable or conflicting dates, a one-day deadline grace period, stale-source thresholds, manual imports, saved database deadline joins, preserved unsubmitted status, independently guarded attended-submission reservations, and private aggregate counts. The disposable end-to-end integration test also verifies the `posting-audit` CLI with one synthetic expired deadline.

The **dates, not the employer's actual application status**, are validated here. A posting can be taken down before its advertised deadline, remain open past an estimated closing date, or require checking the company site for location-specific application rules. No network recheck is performed by this change. For real openings, reconfirm the official employer page before any final application preparation or human-operated Submit.

A 14-day observation threshold is a deliberate conservative engineering default, not a claim about employers' hiring cycles or job closure rates.

For the original 20-form pilot, source records remain private and unavailable to GitHub. This change does not resolve their field-level failures or establish real application completion readiness. Do not merge or turn on unattended submission solely because these safety tests pass.

See [integrated review](INTEGRATED_RELEASE_REVIEW_2026-11-12.md), [local preflight](LOCAL_PREFLIGHT_AND_BACKUP.md), and [historical pilot audit](PILOT_AND_REQUIREMENT_EVALUATION.md).
