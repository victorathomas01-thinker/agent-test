# Optional Workday public career-site discovery

**Stage:** review-only; tested against offline responses, **not** verified live coverage of any employer. Workday's public-facing CXS JSON endpoint is used by its careers UI but is not an officially supported, stable public job-board API. Employers can change or block it.

This is job **discovery only**. It never signs in, opens an authenticated application flow, enters applicant details, uploads a résumé, or submits an application.

## Why it helps

A number of Charlotte-area employers have public Workday career sites. The repository includes an [opt-in source bank](../examples/charlotte_workday_sites.json) with Workday board roots inferred from publicly visible employer job postings. Those job postings were observed at different times and **some example roles have already closed**; inclusion does not establish current vacancies, site accessibility, eligibility or interest.

The source-bank employers include Protiviti, Wells Fargo, TIAA, Truist, The Hartford, Intapp, AIG and Deriva Energy. Sources are independent public career boards, not remote accounts.

## No-install usage after this branch is reviewed and checked out

Inspect the predefined public-source file first, then run:

```powershell
python main.py discover-workday --max-sites 3 --per-site 15
python main.py coverage
python main.py list --all
```

This one-time command selects up to three employers from the source bank and reads **up to** 15 public listings per employer. It leaves `config.json` unchanged. If an employer has more listings, this run is partial by design. It records the result in the local agent SQLite database only.

To use your own **explicit** official career-site list:

```powershell
python main.py discover-workday --sources examples/charlotte_workday_sites.json --max-sites 5 --per-site 20
```

For future scheduled discoveries, you can voluntarily add a subset to the ignored `config.json` field `discovery.workday_sites`, and set `discovery.max_workday_per_site` to a sensible bound (default 40, hard cap 60). The default list is empty so this change **does not increase traffic** from existing normal discovery runs.

## What this adapter actually does

1. Accepts only explicit, strictly validated HTTPS public root URLs matching `{tenant}.wd{number}.myworkdayjobs.com/{site}` (optional locale).
2. Checks the public `robots.txt` policy before fetching CXS job lists. If access is disallowed or a listing request is blocked, **stop**, record blocked/error and do not work around it.
3. Sends bounded JSON `POST` requests to `/wday/cxs/{tenant}/{site}/jobs` to **read** listing pages (20 per page). This POST is a public listings query, **not** an application submission.
4. Uses the site's first-page `total` field, with an upper bound and duplicate detection; retains only same-board `/job/...` paths.
5. Performs same-origin `GET` requests for individual job detail descriptions, with request delays, strict redirect controls and bounded response sizes.
6. Keeps details as plain text and records any unavailable detail as `unverified`, which cannot enter the recommended preparation queue.
7. Records completeness and blocks/errors in the local `python main.py coverage` report. A full CXS listing response is not proof every employer vacancy is public or that a job is still open.

An **experimental Workday scan never expires** any previously collected listing. The endpoint can return partial data, and its behavior may vary by tenant.

## Source and test provenance

The optional source-bank URL patterns were inferred from publicly accessible career pages, including:

- [Protiviti / Robert Half](https://roberthalf.wd1.myworkdayjobs.com/en-US/ProtivitiNA)
- [Wells Fargo](https://wf.wd1.myworkdayjobs.com/en-US/WellsFargoJobs)
- [TIAA](https://tiaa.wd1.myworkdayjobs.com/en-US/Search)
- [Truist](https://truist.wd1.myworkdayjobs.com/en-US/Careers)
- [The Hartford](https://thehartford.wd5.myworkdayjobs.com/en-US/careers_external)

The broad protocol and cautions are described in [Workday's career-site documentation](https://doc.workday.com/workday-education/en-us/course-manuals/recruiting-for-administrators/career-sites.html), and the independently documented [CXS endpoint behavior](https://lepidata.com/guides/workday-job-listings/). The latter is unofficial and may change.

Tests use synthetic posting JSON only: domain/tenant/path rejection, robots policy, cross-origin defense, pagination past 20, capped results, invalid details, missing total, source-bank validation and explicit no-applicant-data behavior. **No real Workday employer requests were made as part of CI.**

## Release gates still open

- Run a voluntary, read-only smoke check against a handful of *currently authorized public* Workday boards and review the returned URLs, numbers and metadata without storing credentials.
- Confirm final eligibility handling on independently reviewed real public job descriptions, especially hard GPA and graduation rules, mandatory experience and paid student-hour eligibility.
- Keep public job collection separate from the secure, human-operated application workflow. Workday's login/application wizard is **not** supported by this adapter.
- Validate the local Power BI data counts from actual observed collection, not from mock or stale records.

Do not activate this in `main` or scheduled production without separate release review.
