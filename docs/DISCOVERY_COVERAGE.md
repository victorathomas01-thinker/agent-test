# Discovery reliability and source coverage (development branch)

This is the first P0 discovery-hardening milestone. It does **not** turn the Job Agent into an exhaustive job search, a hosted service, or a reliable automatic applicant. The user's application data and submitted jobs are unchanged.

## What changed

- Public SmartRecruiters company postings now use the officially documented `limit`, `offset`, and `totalFound` fields to page beyond the old fixed 12-posting cap, stopping at the configured maximum. Public list entries still require an official same-company job URL; partial or malformed details cannot prove a full scan.
- Greenhouse, Lever, and Ashby scans distinguish complete, capped, and invalid/malformed results. Any scan where the configured cap may have omitted postings is considered partial.
- A completed full ATS scan can support marking previously seen, unsubmitted jobs as no longer shown **on that public board**. A partial, failed, or blocked scan **never** triggers that expiration. This is still not evidence of the employer's final hiring decision.
- Employer career-site crawling is conservatively marked partial even when it extracts structured postings. It cannot prove all pagination, JavaScript, robots restrictions, or external redirects were covered.
- Each discovery run now persists a source audit in two new local SQLite tables: `discovery_coverage_runs` and `discovery_coverage_checks`. Feed URLs and employer URLs are represented by short hashes rather than copying the full URLs, and exception detail is reduced to an error-class name.

## Run and inspect locally

The feature branch is stacked on the broader [Job Agent development PR #3](https://github.com/victorathomas01-thinker/agent-test/pull/3) and the [job market sidecar PR #5](https://github.com/victorathomas01-thinker/agent-test/pull/5). Existing `main` does **not** contain it yet.

```powershell
python main.py discover
python main.py coverage
python main.py coverage --limit 150
```

The scheduled `python main.py run` command also records these checks, but retains its original preview-only behavior. `discover-web` writes an audit for the employer career sites it actually tries.

Coverage statuses:

| Status | What it means | What it does not mean |
| --- | --- | --- |
| `complete` | ATS returned a validated full bounded listing set, or a configured feed was read successfully | All jobs on the internet or at the employer were discovered |
| `partial` | Page cap, invalid detail, incomplete/unknown paging, or bounded career-site crawl | No more jobs exist |
| `empty` | Full ATS response was empty, or a career site yielded no extractable records | An employer has no open jobs |
| `blocked` | A career-site request was restricted by robots/permissions or HTTP 403 | We can bypass restrictions |
| `error` | Source fetch or decoding failed | The source has permanently stopped hiring |

The report retains the *latest* audited discovery's source list. A failed feed is not treated as a successfully scanned employer board, and a short feature-source list is not a representative sample of the whole job market.

## Verification

All sample postings in the regression tests are synthetic. The new tests cover SmartRecruiters paging through over 100 public listings, an intentional cap, missing `totalFound`, failed posting details, malformed links, source-level feed failures, bounded company sites, and retention of previously collected listings when scans were incomplete.

The code does not contact real employer boards during these tests. It also does not submit applications, open authenticated employer sessions, attach a resume, or alter the applicant's verified answers.

Official documentation used for adapter design: [SmartRecruiters pagination](https://developers.smartrecruiters.com/docs/customer-overview), [SmartRecruiters public posting API](https://developers.smartrecruiters.com/reference/v1listpostings), and [Ashby public job board API](https://developers.ashbyhq.com/docs/public-job-posting-api).

## Still missing

- Source adapters and robust discovery for Workday, iCIMS, Oracle, SuccessFactors, and many custom employer career sites.
- A reviewed source list with measurable Charlotte/hybrid/remote coverage, not only tech-heavy aggregator leads.
- Freshness and employer-page existence checks before applying.
- Independently labeled eligibility evaluations (graduation, degree, work history, GPA, schedule and sponsorship).
- Safe, attended real employer form-readiness checks. The earlier 20-form pilot did not show unattended submission readiness.
- A Power BI dashboard. The separate job-market SQL snapshot/export sidecar is only its data foundation.

Track these in [P0 quality and readiness issue #6](https://github.com/victorathomas01-thinker/agent-test/issues/6).
