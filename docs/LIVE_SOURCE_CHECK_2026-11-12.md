# Live public-source validation — November 12, 2026

**Status:** bounded public discovery demonstrated on two Workday sources and two official structured ATS APIs. This is a source access check, **not a comprehensive current job search, eligibility adjudication, or application-submission test**.

No credentials, applicant profile, browser session, application data, stored candidate database or resume were accessed. The GitHub Actions probes queried public career-board endpoints only and deliberately retained no raw job descriptions or application forms.

## Verified observations

| Check | Source(s) | Direct observed result | What it establishes |
| --- | --- | --- | --- |
| [First Workday check](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43360198019) | Protiviti + Wells Fargo | Both failed before listing data with HTTP errors | Did **not** establish Workday accessibility |
| [HTTP-code and official ATS check](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43360457446) | Protiviti + Wells Fargo | Both returned **HTTP 406 on robots.txt** | Revealed invalid JSON-only `Accept` header for text robots policy |
| Same run | Greenhouse / Duolingo | Official board returned **61 source records**, but **0 accepted** | Its API returned links on `careers.duolingo.com`, which the original board-only allowlist dropped |
| Same run | Lever / Zoox | **4 accepted** sample jobs from a source with **237 rows** | Public Lever API access and basic HTTPS link validation; not live application readiness |
| [Corrected Workday source check](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43360677416) | Protiviti + Wells Fargo | **2 structured detail records each; 4 total** | Correct content negotiation permits public Workday listing/detail reads at both tested employers |
| [Greenhouse allowlist check](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43360979050) | Greenhouse / Duolingo | **4 accepted** public API jobs out of **61 source rows** | Official custom-host link handling works on actual response data |
| Same run | Lever / Zoox | **4 accepted** sample jobs out of **237 source rows** | Continues to provide a successful independent structured ATS baseline |

The source sizes were observed through live GitHub Actions on this date. They are **not** an exhaustive inventory of eligible Charlotte positions. All smoke runs deliberately requested only four ATS or two Workday detail records per source. A capped sample is classified `partial`, never `complete`. Validated HTTPS URLs may still lead to closed application pages.

## Engineering fixes based on actual failures

1. **Workday 406:** `robots.txt` is requested as `text/plain, */*`, while CXS list/detail API requests still use `application/json`. The adapter still enforces robots rules and does not retry denied origins or bypass access restrictions.
2. **Greenhouse company-hosted postings:** An *explicit, exact-host* allowlist permits the `duolingo` board's official company careers URL `careers.duolingo.com/jobs/{job_id}` only when it is consistent with the job ID returned by Greenhouse's own board API. URLs with other domains, userinfo, HTTP, unexpected job IDs or conflicting `gh_jid` values remain rejected. Approved custom-host links are marked `api_listing` rather than declaring the landing page independently verified.
3. **Application boundary stays closed:** Custom-hosted Greenhouse links are allowed into **discovery**, not the existing direct Greenhouse/Lever attended submission flow. In code, `official_job_url` still rejects these custom-domain links. Real employer forms remain human-reviewed.
4. **Minimal logs:** Smoke checks report provider/employer names, counts, status/error class and HTTP code/phase only. No personal data, descriptions or raw HTML is recorded.

The one-time GitHub Actions workflow in `.github/workflows/one-time-public-source-smoke.yml` is path-gated to this review branch and has **no schedule**. Normal code pushes and pull requests do not call real employers. Its final version uses one controlled official ATS check. Workday's earlier successful evidence remains in the linked prior run.

## What is not proven

- Whether any of the sampled jobs is currently open, eligible for a particular student, or suitable for their work schedule.
- That Workday CXS is an officially supported stable API or that all Workday tenants allow equivalent reads.
- That all 61 Duolingo or 237 Zoox records are accessible by the collector, or that all their external link destinations work.
- That the synthetic/isolated form-preparation suite can complete a real employer application. No employer forms were filled, and **nothing was submitted**.
- That the local SQL snapshots represent the whole Charlotte labor market. The Power BI report still requires a clean real-data collection history.

## Next acceptance steps

1. Run read-only discovery on a curated Charlotte/hybrid/remote employer bank, then verify actual landing-page availability and explicit deadlines for a representative sample without applicant details.
2. Extend the source-coverage report to capture employers verified on their own websites, unreachable, robots-denied, incomplete, and deprecated. Never infer that absence from a partial scan means the vacancy closed.
3. Label a held-out set of recent public jobs for mandatory versus preferred GPA, graduation, experience and sponsorship conditions. Measure false exclusions and unknowns.
4. Use the existing private `form-audit` output to identify common unresolved fields. Continue synthetic fixture fixes and **do not** enable unattended final submission.

The draft chain remains [agent foundation PR #3](https://github.com/victorathomas01-thinker/agent-test/pull/3) → [analytics PR #5](https://github.com/victorathomas01-thinker/agent-test/pull/5) → [source coverage PR #7](https://github.com/victorathomas01-thinker/agent-test/pull/7) → [eligibility/form diagnostics PR #8](https://github.com/victorathomas01-thinker/agent-test/pull/8) → [Workday PR #9](https://github.com/victorathomas01-thinker/agent-test/pull/9) → [public posting examples PR #10](https://github.com/victorathomas01-thinker/agent-test/pull/10). This milestone is stacked on PR #10. No production merge or activation is authorized by these public tests.
