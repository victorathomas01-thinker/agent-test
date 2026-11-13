# Job Market Intelligence — first data-engineering milestone

**Status: a tested, local, read-only export pipeline; NOT a finished Power BI dashboard, hosted data service, or calibrated labor-market survey.**

The Job Agent is the primary product. This module begins a separate analytical view of the public job records the collector has actually encountered over time, without reusing application-history or applicant-private tables.

## Why this exists

A single current SQLite jobs table cannot show when the agent first encountered a posting, and a job's application status cannot tell us whether the employer still has a vacancy. This milestone adds an append-only observation warehouse so later Power BI reports can distinguish:

- **Stored posting records:** Everything previously collected and retained in the agent database, including stale entries.
- **Seen in the last 7 days:** The source record's `last_seen` timestamp is recent relative to the snapshot. Still not proof that a posting is open now.
- **New to our collector:** The first local snapshot containing an ID. **Not** the employer's posting date or an estimate of newly created vacancies.
- **Salary disclosed:** The source record has a nonblank salary field. **Not** an actual wage, normalized wage, or a validated average.
- **Source verification:** API listing vs employer-site structured extraction vs unverified page. Keep these distinct.

These categories must not be renamed to "jobs available", "jobs added by employer", "competition", or "typical salary" without independently sourced evidence.

## Commands

Use the **consolidated development branch** containing the existing source SQLite schema. This analytics feature is stacked as a separate review PR; it does not change scheduled discovery, submitted applications, browser scripts, or other agent behavior.

After a discovery run has populated the local `agent.sqlite3` file:

```powershell
python -m agent.market_intelligence snapshot
```

Each invocation reads the source database in SQLite read-only mode and appends one observation of its public posting metadata to the separate, gitignored `private/market/market.sqlite3` warehouse. It also updates CSV files inside `private/market/powerbi/`.

To re-export the existing warehouse without another snapshot:

```powershell
python -m agent.market_intelligence export
```

The commands **do not run discovery themselves** and **do not submit or prepare applications**. Run a snapshot after a completed discovery to establish a useful observation cadence. Initially, old records in the source database will still appear as old in the exports. The CLI refuses to export real records outside `private/` by default, to reduce accidental GitHub commits.

## SQL and Power BI model

Source tables (read-only): `jobs`, `job_details`, `web_checks`. Application metadata, applicant answers, notes, the resume and local configuration are deliberately not selected.

Warehouse files:
- `market/market.sqlite3` — relational warehouse containing `market_snapshots` and `market_observations`, plus SQL views `market_category_summary` and `market_first_collected`.
- `market/powerbi/market_snapshots.csv` — one row per recorded snapshot.
- `market/powerbi/market_postings.csv` — one record per posting **per snapshot**, with a stable hashed key and explicit caveat columns.
- `market/powerbi/market_by_category_source.csv` — SQL-grouped counts and disclosure/freshness totals.

Power BI Desktop can import these three CSVs. Use one-to-many relation `market_snapshots[snapshot_id]` → `market_postings[snapshot_id]`. The category/source aggregate is a validation/reporting table: do **not** relate it to postings for additive reporting without carefully defining measure behavior.

Suggested first dashboard pages:

1. **Collector coverage:** number of stored public records by collection source, category, geography, with source quality and freshness controls.
2. **Observed movement:** count of IDs first recorded by the collector between snapshots; repeated vs not-recently-seen; a clear warning about collection coverage changes.
3. **Pay transparency:** share of records with an explicit salary field by source, category, and month. Do not calculate dollar pay medians until unit, currency, range, pay period, and job type have been validated.

One benchmark to add later is the Bureau of Labor Statistics Charlotte regional occupational employment/wages dataset. Its occupational wages are not directly comparable to individual posting salary offers without classification, period and sampling notes.

For source-controlled Power BI work, save a Power BI Desktop project in `.pbip` / PBIR and commit its definitions only after opening and visually validating it. **No `.pbip` or actual report is included in this milestone.**

## Privacy and reproducibility

All production-derived market exports stay local and ignored by Git. Raw descriptions, URLs, application statuses, submitted dates, eligibility reasons, applicant profiles, application attempts and facts are excluded. Scraped text fields are CSV formula-neutralized to prevent common spreadsheet injection.

The only CI data is synthetic and lives in `tests/test_market_intelligence.py`; tests verify no applicant data appears in exports, older snapshots stay available, read-only source access, schema rejection, and that the exported metrics are labeled conservatively. No genuine job data, profile, browser session, or application receipt is committed.

## Broader agent gaps (next milestones)

| Priority | Workstream | Honest acceptance criterion |
| --- | --- | --- |
| P0 | Employer discovery | Broaden direct-ATS coverage and show source-level success/failure/coverage; not "exhaustive" from one aggregator feed |
| P0 | Eligibility accuracy | Independently label a set of real postings for mandatory graduation/experience/location/sponsorship constraints; measure false exclusions |
| P0 | Live form readiness | Convert the 20/20 unresolved offline previews into clear field-level issue categories. Prove one full attended flow with human-operated final submit; no false completion |
| P1 | Salary and work schedule | Parse normalized compensation only when period/currency/units are explicit, and make unknowns visible |
| P1 | Historical data | Make snapshotting part of the successful discovery lifecycle with an opt-in local setting and atomic snapshots |
| P1 | Analytics UI | Build Power BI visuals and optional PostgreSQL analytical views using real observed, quality-gated records |
| P1 | Application package quality | Templates/resumes/cover letters matched against evidence; independently verify attachment and field correctness before live use |
| P2 | Productionization | Versioned data migration, packaging, rollback, permission/terms review and a genuine user-facing setup experience |

**Non-goals for this milestone:** real application submission, credentials, monitoring emails, paid services, web crawling or deployment.
