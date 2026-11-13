# Review queue + explicit official-source recheck — November 13, 2026

**Draft only.** This change connects the existing explicit, read-only **Greenhouse and Lever per-job GET** to the local review experience. It does **not** enable automatic employer polling, live application filling, resume uploading or final application submission.

## Real public Lever evidence

The one-time [Lever/Zoox public-source check](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43379477548) **passed**. Using a disposable SQLite database with entirely fictional values, GitHub Actions performed two bounded public GET requests: a small Zoox listing sample (at most five entries) and the precise Lever API detail endpoint for one matching public job ID. The returned job ID and official URL matched the stored synthetic record. Only its public metadata, last-seen timestamp and local eligibility were refreshed, while the job's identity and tracking status remained unchanged.

This extends the earlier [Greenhouse/Duolingo single-job success](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43378162276). **Neither result proves a job application is currently open** or confirms the user meets every employer requirement. No employer form or applicant data was involved.

## In the review queue

The **local dashboard** now has a **Needs Recheck** view. A saved job appears here if it has an explicitly passed application deadline, contradictory deadline information, an employer-source observation more than 14 days old, or (for the supported direct ATS sources) no dated observation. These are review signals, not declarations that the employer closed hiring.

Every affected job stays visible, even when a new freshness restriction makes `eligible=0`. The existing `python main.py queue` command also keeps previously prepared or selected ineligible jobs visible, with a specific manual instruction when a supported official recheck can help:

```powershell
python main.py queue
python main.py recheck-job <saved-job-id>
```

The local dashboard shows **Recheck this public posting** for a recheckable saved Greenhouse/Lever listing that needs re-verification. The action is **not performed until the user clicks**. The dashboard performs one local preflight, verifies its normal same-origin session token, and calls the exact-ID official public GET already validated in [single-posting recheck](OFFICIAL_SINGLE_RECHECK.md). A successful matched response refreshes the saved public fields and eligibility locally; source errors leave saved records unchanged and report an outcome. The user must review the updated eligibility and employer form separately.

For Workday, SmartRecruiters, Ashby, arbitrary company careers sites and manually imported URLs, the dashboard says to **verify directly on the employer's website**. It never silently falls back to a speculative scraper or arbitrary URL.

## Safety checks

- Opening the dashboard or switching tabs does **not** fetch any employer pages. The normal `GET /api/jobs` just loads local SQLite.
- `POST /api/recheck` is a user-click-only action guarded by the existing local-only Host, Origin and per-session token checks. Invalid requests return 403 without a source request.
- The existing local `doctor` preflight must report a compatible database and valid settings with live submission disabled. Unsafe local settings return 409 without a source request.
- Supported rechecks are restricted to validated official Greenhouse/Lever public JSON endpoints. Their original strict host/path, response-size, identity, redirect and concurrency rules remain in effect.
- No background scheduling, auto-refresh network rechecks, applicant answers, credentials, resumes or application submission calls were introduced.
- Local job tracking states already submitted/pending/interviewed/offered/rejected/withdrawn/expired never offer a recheck action. The user checks receipt or the employer website instead.

## Acceptance evidence and limits

Synthetic tests exercise the dashboard model, selected/previously prepared stale jobs, the CLI queue, lack of employer requests on page load, user-click authentication, and fail-closed database preflight. The full Windows test suite and disposable-installation check are the integration gates.

The saved original 20 application-preview attempts are still private and unavailable in the GitHub workspace. This work does not claim their actual blockers were resolved. The dashboard is a **locally hosted application** that runs on the user's own machine; these changes have **not been installed or deployed**. The latest integration must be reviewed and merged before the user can use it locally.

## Future work

- Independently check the employer's application page for real open/closed status; an API listing alone can remain indexed after recruitment ends.
- Audit the original 20 offline previews when their private local SQLite data is available.
- Build a larger independent, held-out requirements benchmark and validate graduated qualifications/experience wording for Charlotte, remote and hybrid roles.
- Keep final Submit attended and user-operated. Do not use the green tests as permission to turn on unattended applications.

See [live source checks](LIVE_SOURCE_CHECK_2026-11-12.md), [posting freshness](POSTING_FRESHNESS.md), [single official recheck](OFFICIAL_SINGLE_RECHECK.md) and [local backup guidance](LOCAL_PREFLIGHT_AND_BACKUP.md).
