# Personal Job Agent — Windows Beta Candidate

**November 13, 2026 — REVIEW-ONLY CANDIDATE, NOT A FINISHED PRODUCT.**

This branch consolidates the cumulative draft feature work (#14–#19) with a safer local Windows first-run workflow. The goal is **manual job discovery, local ranking and inspection, and detached offline form preparation**. Real employer submissions remain explicitly user-operated and disabled by default. No historical personal database has been accessed, migrated or uploaded by the developers.

## What actually works

- Read official public ATS job records and rank them against local user criteria.
- Show all jobs, including excluded, unverified, expired and previously selected records, in a local review dashboard. Show a separate **Needs Recheck** view for stale public postings.
- On a specific explicit action, recheck a saved Greenhouse or Lever listing against its exact official single-posting public API. A public record's presence does **not** prove its application form accepts submissions.
- Prepare a detached offline preview without entering personal data into the employer's live form. Recognize required native and ARIA-only checkbox/radio/switch/custom controls and keep unsupported or attestation decisions for the person applying.
- Report private aggregated form blocker categories and recommendations.
- Protect an existing compatible local database with a read-only preflight and an **explicitly approved** verified SQLite snapshot before additive migration.

**Not proven:** a high real application-form completion rate, the original 20-form historical pilot's blocker breakdown, correct eligibility judgments across representative jobs, general Workday application flows, reliable submission for real employer systems, or an installed beta on the user's computer.

## First: inspect this candidate safely

Run Windows PowerShell in the **reviewed branch's** root. The commands below do not assume your working GitHub `main` contains these changes. Do not copy private configuration, SQLite databases, CV files, or browser profiles into GitHub.

```powershell
pwsh -File .\setup.ps1 -PreflightOnly
```

This is read-only: it doesn't create any database, install dependencies, access an employer, import a profile or perform a schema migration. It will tell you whether the local install is new, already compatible, or needs an explicitly approved migration.

If the preflight says **fresh_new**, the new-install command is:

```powershell
pwsh -File .\setup.ps1
```

This installs Python dependencies and Chromium in a local virtual environment, initializes a blank local configuration and database and runs the automated tests. It **does not** silently read `Downloads`, import a prior MVP profile, schedule a task or enable live submission.

If you already have an older database, **do not run a new installation over it without inspecting it.** The installer will stop if the older schema needs expansion. Check it first:

```powershell
python main.py doctor
pwsh -File .\setup.ps1 -AllowSchemaUpgrade
```

The second command is **explicit approval** to save a verified SQLite-only backup to Git-ignored `private/backups/` before additive schema updates. Confirm the original database really belongs to this install, and keep the backup safe; ignored SQLite copies are **not encrypted**. If the installer reports a corrupt or incompatible schema, **stop**: it will not attempt an upgrade.

If an old `config.json` exists but the database is missing, the installer **refuses** to create a new database by default. Restore the original first. Only if you intentionally want a separate empty history:

```powershell
pwsh -File .\setup.ps1 -InitializeMissingDatabase
```

If importing a previous MVP profile into an otherwise **entirely new**, empty installation, use the specific file you selected (not an automatic Downloads lookup):

```powershell
pwsh -File .\setup.ps1 -FromMvp 'C:\path\to\previous\config.json'
```

No original history is automatically imported from another directory. The installer fails if the local configuration has enabled live submission; turn it off locally before proceeding.

## Open the local beta dashboard

```powershell
pwsh -File .\start-beta.ps1
```

The launcher checks local database integrity and configuration and prints a read-only beta status overview. Open the exact `127.0.0.1` URL printed by the command in your local browser, then explore **All Jobs**, **Top Matches**, **Needs Recheck**, **Selected**, **Form Readiness** and **Applications**.

Simply loading the dashboard makes **no employer requests**; its one-job `Recheck this public posting` button acts only when you click it. Keep the terminal open while using the dashboard. Press Ctrl+C to stop.

### Configure, find and inspect jobs locally

Using the reviewed beta branch and its virtual environment:

```powershell
.\.venv\Scripts\python.exe main.py set first_name 'FIRST_NAME'
.\.venv\Scripts\python.exe main.py set last_name 'LAST_NAME'
.\.venv\Scripts\python.exe main.py set email 'YOUR_PRIVATE_EMAIL'
.\.venv\Scripts\python.exe main.py set resume_path 'C:\path\to\resume.pdf'
.\.venv\Scripts\python.exe -m scripts.beta_status
.\.venv\Scripts\python.exe main.py discover
.\.venv\Scripts\python.exe main.py list --all
```

These profile values are placeholders; enter and verify your real data **locally**, never in a public GitHub issue or CI log. Discovery reads public employer websites and ATS feeds, but does not apply to jobs. No action is automatically scheduled. Use `main.py explain JOB_ID` to inspect a ranking or `main.py queue` to see outstanding reviews.

Select a **single** relevant, confirmed posting in the dashboard and choose **Prepare selected offline**, or use `main.py apply JOB_ID` for one safe preview. This reads the public posting and fills a detached offline copy with scripts/network disabled. It **does not** transfer those values to the employer's page or constitute an accepted application. An offline `prepared` status is only a current-step signal; the employer might have more steps.

Run `main.py form-audit` or the **Form Readiness** dashboard view for aggregated blocker counts. Only use `main.py recheck-job JOB_ID` when you expressly want to check one official Greenhouse or Lever posting; other ATS systems remain manual-only for the single-job workflow.

## Historical pilot: keep source data private

The original pilot reached **20 real forms**, and none demonstrated full live-ready completion. Its actual historical database is **not** in the GitHub repository. If it is located in the beta install's local `agent.sqlite3`, after safeguarding the original run:

```powershell
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py pilot-audit --offline-only --limit 20 --expected 20
```

This reads aggregate historical **detached preview** blockers locally without exporting personal field labels. If the original SQLite file lives elsewhere, **do not move/overwrite it casually**; first identify a safe copy and review `docs/LOCAL_PREFLIGHT_AND_BACKUP.md`. A new blank database will not reconstruct the 20 previous attempts.

## Beta acceptance scorecard (not yet satisfied)

| Gate | Evidence needed | Current state |
| --- | --- | --- |
| Clean local Windows installation | Actual user-device preflight, install, and dashboard launch | **Pending on-device**; synthetic Windows CI only |
| Historical-data safety | Preflight + protected backup + original 20-form local audit | **Pending original data** |
| Relevant opportunities | Human review of a meaningful sample of currently open Charlotte/hybrid/remote jobs and reasoning | **Pending independent validation** |
| Open job sources | Exact verified public posting identity and human check of live application availability | **Greenhouse and Lever single-job APIs sampled only** |
| Form usability | Measure manual corrections, missing applicant answers, and time saved on multiple real application forms | **Not yet demonstrated** |
| Duplicate/receipt safety | No unintended sends, duplicate submissions or fabricated employer confirmations | **Synthetic cases passed; live not demonstrated** |
| Live submission | Manual reviewed application, final Submit by applicant | **Disabled by default; outside current beta trial** |

Success for the first attended beta is a usable **review-and-prepare workflow**, not a promise of zero-touch mass applications. Do not enable automatic application submissions based on test counts.

## GitHub evidence and next action

The project has previously passed the full synthetic Windows suite and disposable acceptance tests, with limited public real Greenhouse and Lever form/source observations recorded in earlier draft PRs. **Passing unit tests does not establish real application readiness.**

The remaining direct next step is to review the beta branch, install it on the user's own Windows machine with the preflight safeguards, inspect the historical local source if present, and measure a small set of real job/form review outcomes. Do not merge, deploy, enable a schedule or submit any job without a separate deliberate decision.
