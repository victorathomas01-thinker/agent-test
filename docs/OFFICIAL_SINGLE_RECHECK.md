# Verify an individual saved posting against its official ATS

**Review-only.** This development branch adds a narrowly scoped, explicit public job check. It is a **read-only employer API request** and, if a fully matching job is returned, a guarded **local SQLite refresh**. It is not a guaranteed real-time hiring-availability confirmation, employer application-form test, login, or application submission.

## How to use after review

```powershell
python main.py doctor
python main.py recheck-job greenhouse:example:123
# Or for a saved official Lever UUID posting:
python main.py recheck-job lever:example:a1111111-2222-4333-8444-b55555555555
```

The values above are **synthetic examples**, not actual open vacancies. Use an exact job ID already displayed in `python main.py list --all`.

The `recheck-job` command is **manual and opt-in only**. It is not added to background discovery, a scheduler, or an application flow. The program first checks the existing database and locally disabled-submission config without modifying them. It constructs the public GET URL from the saved job's **provider, board identifier and posting ID**; a stored arbitrary URL is never directly fetched.

This first version supports exact official **Greenhouse** and **Lever** postings (including an explicitly approved company-hosted Greenhouse careers URL). It uses each provider's public **single-posting GET** endpoint, without collecting a full company board or hitting an application submission endpoint. Workday, SmartRecruiters, Ashby, manual imports, custom employer sites, login-gated and unknown sources are deliberately **unsupported until independently implemented and tested**.

Official reference documentation:

- [Greenhouse public Job Board API: Retrieve a Job](https://docs.greenhouse.io/job-board) — `GET /v1/boards/{board_token}/jobs/{job_id}`
- [Lever public postings API: Get a Specific Job Posting](https://github.com/lever/postings-api/blob/master/README.md) — `GET /v0/postings/{site}/{posting-id}`

## What the result means

| Result | Interpretation and database behavior |
| --- | --- |
| `verified_listed` | Official public API returned the **same posting ID, approved employer board and exact canonical URL**, with usable structured data. The saved description/location/title and observation timestamp refresh locally, and the eligibility rules are recalculated with existing local configuration. Prior notes, attempt history, submission records and employer status are preserved. |
| `not_found_unconfirmed` | Official API returned HTTP 404 or 410. **Not proof the vacancy is definitely closed**; region, access or system changes are possible. No saved data is modified. |
| `access_denied` / `rate_limited` | Official API returned 401/403 or 429. Do not retry or bypass restrictions automatically. No saved data is modified. |
| `source_unavailable` | Timeout, server error, redirect, non-JSON, or malformed HTTP result. No saved data is modified. |
| `listing_identity_or_metadata_mismatch` | Returned ID, career URL, board, or required listing fields do not match the saved job. No data is modified. |
| `listing_changed_during_recheck` | Local job changed while the public request was in flight. Do not overwrite more recent state. |
| `unsupported_or_unsafe_source`, `already_tracked_or_closed`, `not_in_local_database` | Unsupported system, already completed/closed application state, invalid source or unknown saved record. **No network request or mutation.** |

The request has an explicit HTTPS-only official-host allowlist, exact API path, GET-only method, 15-second timeout, 2 MB response maximum, nonredirecting handler and JSON response check. No applicant email, GPA, résumé, verified questions, cookies, tokens or contact details are sent to the employer API. Evaluation of eligibility happens **locally after a positive matched response**.

The recheck is intentionally conservative. A matching public API response only proves the endpoint still exposes that posting at the time of the read. It does **not** prove the employer is still accepting applications, that a form can be completed or that the applicant meets every requirement. A stated application deadline can still block eligibility even when the posting is visible.

## Safeguards

- No lost applications: previously submitted, pending, rejected, withdrawn, interviewed, offered or formally expired records cannot be refreshed or silently resurrected.
- No false deletions: failures and missing API responses do not mark a job expired or replace its saved description.
- No stale-write races: a successful fetch is only applied if saved URL, status, last-seen timestamp, description and deadline are unchanged inside a SQLite write transaction.
- Custom Greenhouse URLs are accepted only if their exact hostname is already allowlisted in local configuration and their path/posted ID match the official board response.
- Local data is never posted to the API. The recheck itself produces sanitized result codes, not raw exception text, HTTP headers, private fields or full employer response bodies.

## Bounded live-source evidence

[One-time GitHub Actions source verification, November 13, 2026](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43378162276) **passed**. A disposable synthetic SQLite database was initialized; the runner read a small public Greenhouse board listing for Duolingo, selected one URL whose employer posting identity passed the strict allowlist, then made exactly one **public single-job GET** to Greenhouse. The API returned the same posting ID/URL and the local synthetic record's observation timestamp refreshed. No application flow was requested, no job titles or details were logged, and no applicant profile or private data were present.

The one-time workflow is explicitly path-gated to its review branch, has no schedule and does **not** run on normal pushes or pull requests. The result validates **one** real Greenhouse posting and the guarded SQLite refresh; it does not validate Lever availability or all jobs at Duolingo.

## Validation limitations

All unit tests use **fictional records and injected HTTP responses** to prove that successes update only the intended local record while 404, 410, rate limits, blocked access, invalid returned URLs, mismatches, malformed data and concurrent edits do not write to the database. Windows CI also tests the full existing offline application-rehearsal suite.

The original 20-posting form pilot records remain unavailable to GitHub. This recheck feature does **not** diagnose their form failures, nor does it turn the agent into a reliable unattended job-application system.

The next source acceptance should repeat a similarly bounded check against a supported Lever posting and verify actual employer-form availability separately, with user-operated final Submit only. Do not infer a general job availability percentage from a successful one-posting recheck.
