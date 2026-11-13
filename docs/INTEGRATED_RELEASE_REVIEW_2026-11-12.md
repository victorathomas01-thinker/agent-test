# Integrated Job Agent review candidate — November 12, 2026

**Status: REVIEW ONLY.** This branch collects the earlier isolated draft PRs into one candidate for review against `main`. It has NOT been merged, deployed to the user's device, scheduled, or used to submit any real applications.

## Scope of the integrated work

- Foundation and private local applicant configuration, guarded browser workbench, explicit submission review and receipt verification (earlier draft PR #3).
- Local-only SQLite market snapshots and Power BI-ready CSV exports (PR #5). **No finished Power BI report yet.**
- Per-source discovery status reporting, SmartRecruiters pagination and conservative stale-posting protection (PR #7).
- Explicit GPA/graduation parsing and read-only local form-readiness breakdown (PR #8).
- Optional robots-aware Workday public listings with per-board caps and conservative verification (PR #9).
- Source-linked public posting requirement regression examples and parsing improvements (PR #10).
- Bounded real public-source checks, fixed Workday robots header, and safe Duolingo Greenhouse custom-host handling (PR #11).
- One real public Lever form *structure* observation and manual checkbox/attestation blockers (PR #12).
- A read-only historical pilot audit and 28 paraphrased, hand-annotated requirements cases from nine actual public postings (PR #13).

## Verified evidence

- Current integrated candidate was verified by Windows GitHub Actions (119 tests passing on commit `0013e437`): https://github.com/victorathomas01-thinker/agent-test/actions/runs/43363212793
- Two structured Workday descriptions each were read from public Protiviti and Wells Fargo sources after a fix, in intentionally partial discovery checks: https://github.com/victorathomas01-thinker/agent-test/actions/runs/43360677416
- Four Duolingo public Greenhouse and four Zoox public Lever HTTPS posting URLs were accepted in a separate intentionally partial source check: https://github.com/victorathomas01-thinker/agent-test/actions/runs/43360979050
- One Zoox/Lever public form was inspected without entering applicant information: 34 visible controls, 13 required, eight required checkboxes: https://github.com/victorathomas01-thinker/agent-test/actions/runs/43361435744

These source runs did not verify that any sampled job is still open, or that an employer would accept an application. The read-only form inspection did not test an actual submitted form.

## Known release blockers

1. **No original private pilot data in this repository.** The earlier documented pilot reached 20 forms, but every detached offline preview still needed manual attention. It cannot be re-diagnosed without the user's original local SQLite database, and the new `pilot-audit` cannot infer those records from their aggregate summary.
2. **No independently reviewed, representative eligibility holdout.** The 28 cases from nine postings are authored paraphrases with fictional applicant profiles, not a blind statistical validation. Eligibility errors, especially experience equivalency and nuanced student requirements, remain possible.
3. **The Workday CXS integration is experimental.** It uses public-facing sites, respects robots rules, and defaults off; sites may change or refuse access. Do not enable a scheduled Workday crawl by default.
4. **No real application readiness rate.** Existing data shows no verified live-ready form from the original 20. Synthetic form tests and the single no-input inspection do not change that.
5. **No actual Power BI report or real longitudinal data collection cadence.** The SQL warehouse and exports are development infrastructure rather than a production dashboard.
6. **Do not claim all target employers are covered.** Current source-bank coverage is incomplete, and some published public posting examples are expired.

## Safe next review sequence

- Validate config/example schema and data migration against a disposable SQLite copy, with all credentials and personal data excluded.
- Run `python main.py benchmark-requirements` and the full synthetic suite on a Windows machine.
- Open the local app only against a dedicated test profile until historical audit and backup/restore checks pass.
- If the existing local SQLite pilot database is still available, run `python main.py pilot-audit` with the original known pilot date window, and inspect the aggregate blocker distribution **locally only**.
- Build a separate blind requirements evaluation on recent open public postings; do not treat author-labeled fixtures as hiring-accuracy estimates.
- Keep live form submission user-operated only, with original posting identity, reviewed résumé package and explicit approval. Do not activate unattended submission or automated application traffic.

The integration is reviewable as a single codebase. No merge or production activation is inferred from a successful CI run.
