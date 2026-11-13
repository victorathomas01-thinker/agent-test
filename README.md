# Personal Job Agent

The [Product Bible](JOB_AGENT_BIBLE.md) defines the project. The [implementation ledger](PROGRESS.md) tracks current coverage, test evidence, and open acceptance work.

**Official one-job public recheck (review-only):** [Usage, restrictions and outcomes](docs/OFFICIAL_SINGLE_RECHECK.md). `python main.py recheck-job <saved-official-job-id>` checks one saved Greenhouse/Lever posting through its own public GET endpoint. Only an exact matching official result can refresh local metadata and eligibility. A 404, access denial, redirect or ID mismatch never marks the posting closed or modifies the saved record.

**Posting deadline/source freshness (review-only):** [Stale listing and deadline safeguards](docs/POSTING_FRESHNESS.md) add `python main.py posting-audit`, stricter saved-job eligibility checks and a second attended-submission reservation guard. Old source timestamps are review warnings, not claims that a vacancy has closed.

**Read-only installation check (review-only):** [Local preflight and protected SQLite snapshots](docs/LOCAL_PREFLIGHT_AND_BACKUP.md) adds `python main.py doctor` before any migration and opt-in `python main.py doctor --backup` to a gitignored private local folder. No real database has been migrated, and the backup covers SQLite only, not other profile files.

**Historical pilot and public requirement evaluation (review-only):** [Method and source links](docs/PILOT_AND_REQUIREMENT_EVALUATION.md). `python main.py pilot-audit --limit 20` analyzes historical offline attempts from the existing **local read-only** database without printing private field labels, employer names or applicant facts. `python main.py benchmark-requirements` checks 28 manually annotated cases derived from nine public postings against fictional applicants; this is not an independent eligibility accuracy estimate.

**One real form, read-only (review-only):** [Lever/Zoox form structure observation](docs/LIVE_FORM_STRUCTURE_2026-11-12.md) measured 34 visible and 13 required controls, including 8 required checkboxes. The run entered no answers and submitted nothing; new checkbox diagnostics keep those choices for explicit review.

**Live public-source results (review-only):** [November 12 source check](docs/LIVE_SOURCE_CHECK_2026-11-12.md) covers real Workday, Lever and Greenhouse API behavior, with tightly capped public reads and no application submissions. It also explains the approved Duolingo custom careers-host rule. This is not proof that any posting remains open.

**Public-posting requirement checks (review-only):** [Source-derived qualification wording regression](docs/PUBLIC_REQUIREMENT_WORDING.md) covers hard GPA, preferred graduation dates, internship-history requirements, and relative date windows. These examples are not representative employer eligibility accuracy measurements.

**New optional Workday provider (review-only):** [Public Workday discovery guide](docs/WORKDAY_PUBLIC_DISCOVERY.md). A curated, opt-in Charlotte-area employer source bank can be explored with `python main.py discover-workday --max-sites 3 --per-site 15`. It does not enable live applications, change scheduled scans, or imply any posting is still open.

**Offline form diagnostics (review branch):** [Form Readiness report](docs/FORM_AUDIT.md) adds `python main.py form-audit` and a local dashboard view grouping unresolved required fields. It does not submit applications or expose applicant answers.

**Eligibility language (review branch):** [Explicit GPA and graduation constraint calibration](docs/ELIGIBILITY_CALIBRATION.md) adds more conservative parsing of mandatory student hiring rules. It does not establish full employer eligibility.

**Discovery audit (review branch):** [Source coverage and public ATS paging](docs/DISCOVERY_COVERAGE.md) adds `python main.py coverage`, source-level checks, and paginated SmartRecruiters reads. A failed or capped source is never evidence that its older vacancies have closed.

**New review-only data work:** [Job Market Intelligence](docs/JOB_MARKET_INTELLIGENCE.md) adds read-only SQLite snapshots and private, Power BI-ready CSV exports. It has no live Power BI report yet, does not change application submission, and does not export applicant information.

## Interactive workbench

Run `main.py serve` and open the printed local URL in Edge. **All Jobs** includes excluded, expired, and unverified records. Filter and export the collection, inspect score explanations, select listings across pages, and click **Prepare selected offline**. A generated offline preview does not transfer entered values into an employer tab.

For attended preparation, enable the local attended setting and run `main.py review-selected --attach-master` in an interactive terminal. Check the exact list of postings and type `PREPARE`. Supported Greenhouse and Lever forms open in a controlled Edge session. Keep that terminal open while reviewing. If you advance tab 2 manually, type `next 2` to prepare its next supported step. You click Submit in Edge. Press Enter in the terminal to check receipts and close the session.

`main.py discover-web --budget 2` runs the example public employer sources. Set `discovery.career_sites` in the ignored local config to include approved career URLs in scheduled discovery. Each entry supplies a company, HTTPS URL, and optional `render` flag. Read-only crawling respects robots rules and confines requests to the configured origin. Unsupported or unverified links can still be reviewed from All Jobs.

`main.py facts` shows locally verified facts and their source. Use `facts --revoke KEY` to stop using a fact. Reconfirm with `set` or `remember`. Ordinary work authorization and unrestricted status are treated as distinct scopes.

Discover jobs from public Greenhouse and Lever boards, filter and rank them, and rehearse filling application forms locally. Automatic submission is disabled. In a dry run the agent opens the posting without applicant data, then fills a disconnected copy with site scripts disabled.

## Windows setup

With Python 3.11 or later installed, run `pwsh -File setup.ps1` in the repository folder. This installs Playwright and Chromium, creates the local profile and database, and runs the tests. Setup imports the existing MVP configuration from Downloads when present. For an MVP installed elsewhere, run `python main.py init --from-mvp PATH_TO_CONFIG` before setup.

On other platforms, run `python -m pip install -r requirements.txt`, `python -m playwright install chromium`, and `python main.py init`. Run `python -m unittest discover -s tests -v` to verify the install.

## Workflow

```powershell
.\.venv\Scripts\python.exe main.py discover
.\.venv\Scripts\python.exe main.py list
.\.venv\Scripts\python.exe main.py apply JOB_ID
.\.venv\Scripts\python.exe main.py logs
```

- **Discovery.** Each run checks the preset boards and finds up to 25 additional employers using SimplifyJobs' internship and new-grad feeds. The agent ranks board leads using your job and location preferences and imports openings from the employer's public Greenhouse or Lever board. Listings from other hiring platforms and links without a board identifier are skipped. Adjust `max_discovered_boards` in the ignored local `config.json` to change the cap, or set it to zero to use only configured boards. To import jobs, use `main.py import YOUR_JOBS.csv` with the columns in `examples/jobs.csv`.
- **Eligibility.** Discovered and imported jobs use the same title, location, contract, seniority, GPA, work authorization, and sponsorship rules. Use `list --all` to see exclusions and their reasons. The rules are heuristic and can miss requirements.
- **Verified answers.** Use `main.py set work_authorized_us yes` for a confirmed built-in answer or `main.py remember "Do you speak French?" "Yes"` for a confirmed answer tied to the exact question wording. Remember only reusable answers. A labeled radio group can use a verified answer when exactly one option matches. Checkbox groups, unknown questions, and ambiguous choices go to review.
- **Resume.** Set the local master file with `main.py set resume_path PATH_TO_RESUME`. Use `main.py tailor JOB_ID` to create a plain-text preview from a text-based PDF or UTF-8 text resume. The agent ranks whole skills, project, and experience sections by their overlap with the posting while keeping each section's contents in order. Review the result in the ignored `private/resumes` folder, then pass it to one dry run with `main.py apply JOB_ID --resume PATH_TO_PREVIEW`. Normal dry runs use the configured master file. Plain-text previews omit PDF styling and embedded hyperlinks. Some application forms may reject text files.
- **Dry runs.** `apply JOB_ID` rehearses a single listing. `batch --limit 5` rehearses up to five eligible, unprocessed listings within the configured limit. The local application log records `prepared`, `needs_review`, or `failed`. The agent can preview a form embedded in a frame and reports labeled custom controls that need manual input. When it detects a Next or Continue button, it reports that later steps still need review. It previews only the current step. Login, CAPTCHA, and JavaScript-driven choices require manual handling.

Keep the local config, database, and resumes out of Git. The tracked example has blank applicant fields. Attempt details store field labels, answer keys, and outcomes. They omit filled values and resume paths.

Discovery uses the [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html) and [Lever Postings API](https://github.com/lever/postings-api).
The [Ashby public posting API](https://developers.ashbyhq.com/docs/public-job-posting-api) and [SmartRecruiters Posting API](https://developers.smartrecruiters.com/docs/endpoints) are also supported for discovery. Set `ashby_boards` and `smartrecruiters_companies` in the local discovery settings. The default starter boards are Ramp and Bosch Group. SmartRecruiters discovery limits each employer to 12 U.S. detail requests per run. Attended automation remains limited to supported Greenhouse and Lever postings.
Employer board leads come from [Summer 2027 Internships](https://github.com/SimplifyJobs/Summer2027-Internships) and [New Grad Positions](https://github.com/SimplifyJobs/New-Grad-Positions). The internship feed can be updated in `employer_feeds` when the hiring season changes.

## Unattended dry runs

Use `main.py run` as the entry point for a local scheduled job. It refreshes discovery, previews eligible unprocessed jobs seen in that refresh in a headless browser, and prints a summary. Use `main.py logs` to review attempts.

Before previewing, `run` saves a versioned package with the source resume, a validated reordered text resume, and a manifest of source and posting hashes. It attaches the packaged copy of the master resume in the offline browser preview. Run `main.py package JOB_ID --cover-letter` to generate a package on demand and request a cover-letter draft when the resume contains matching evidence. All files go under the ignored `private/packages` directory.

Use `main.py explain JOB_ID` for the eligibility decision and ranking signals. `list` and `run` accept `--strategy fit|internship|healthcare|bridge|entry|stretch`. A strategy changes priority while leaving eligibility rules in place. Use `main.py dashboard` to regenerate the local report, then open the printed HTML path in your browser. Run `main.py health` to check the database and master resume.

On Windows, the existing Codex automation can continue invoking `main.py run`. For a standalone schedule, run `pwsh -File schedule.ps1 -At 09:00 -EveryDays 1` after setup. This installs a local dry-run task that runs while your Windows account is signed in, without an open terminal. Use one scheduler to avoid redundant discovery. Run summaries are kept in SQLite.

After a confirmed submission, use `main.py track JOB_ID --status interview --followup YYYY-MM-DD` to log a later outcome and an optional follow-up date. The tracker does not send follow-up messages.

`run` and `batch` share a default quota of five preview attempts per calendar day on the machine running the agent. Change `max_previews_per_day` in the ignored local config to adjust it. An interrupted or failed attempt uses a slot for that day. A deliberate single-job `apply` preview is separate from the batch quota. All of these commands are dry-run only.

## Record an employer receipt

After submitting an application yourself, save the employer's confirmation page or email text as a UTF-8 file in the ignored `private` folder. Run `main.py receipt JOB_ID private/confirmation.txt`. The text must contain an explicit receipt message and the listing's employer and title. Some generic receipts omit those details and need to be tracked manually. Use only confirmation text from a source you recognize. The agent checks the text locally and cannot authenticate its origin.

A matching receipt marks the listing `submitted` and removes it from future preview batches. The database stores a fingerprint and the recording time. The receipt contents stay in your file. Reusing the same receipt for another listing is blocked.

For automatic matching, place exported `.eml` confirmations you trust in `private/receipts`. The scheduled `run` command scans that folder locally. Use `scan-receipts` to scan immediately. Each email must have a plain-text body and a dated confirmation that matches exactly one pending application. When the same employer and title appear on multiple listings, the receipt must also identify the exact posting link. Ambiguous or undated messages stay unrecorded. The agent reads this folder without connecting to your email account. Use `queue` to see pending submissions, completed previews, and the required fields that still need review.

## Rehearse submission

Run `main.py rehearse-submit` to exercise the submit button, form POST, and receipt check against an isolated mock employer. It uses synthetic applicant details and checks for a matching confirmation reference after a successful response. Rejections and missing receipts are separate outcomes. The rehearsal works without a local applicant profile, does not contact any website, and does not change the application log.

## Attended submission

Attended submission is off by default. To enable it, explicitly set `automation.allow_live_submit` to true in the ignored local config. Run `main.py review-submit JOB_ID` in an interactive terminal and type the exact job ID to open the verified Greenhouse or Lever listing. Optional flags are `--prefill` for saved contact details, `--prefill-verified` for uniquely matched eligibility choices in supported dropdowns, and `--attach-resume PATH` for a reviewed file. These act on the employer's live page and attaching a file can upload it immediately. Existing values and ambiguous fields are left for review. Review, complete, and submit the form yourself in Microsoft Edge, then return to the terminal to check for a receipt. Scheduled runs remain dry-run only.

The agent records a browser receipt when it observes a successful same-host form POST and a matching acknowledgment. Greenhouse can identify the listing through its exact job-specific confirmation URL. Other pages must identify the employer and role in the acknowledgment. An ambiguous result leaves the listing on hold. After checking the employer, use `receipt` to record a saved confirmation or `release-submit JOB_ID` after closing the browser and verifying that nothing was submitted.

For a multi-step form, click **Next** in Edge yourself. After the next step appears, type `next` at the terminal prompt to reuse the approved prefill options. The agent only prepares a single recognizable form within the approved posting. The terminal lists blank required fields, browser validation errors, and custom choices to review. After you submit in Edge, press Enter to check for the receipt.

### Saved dropdown choices

`--prefill-verified` supports verified work authorization and sponsorship answers as well as explicitly saved gender, pronouns, race, ethnicity, and residence answers. To save a personal choice, use `main.py remember "Pronouns" "Prefer not to answer"` with the exact question label and the option you want. The example is a command format. No personal answers are set by default. The agent uses a unique matching option on a supported single-choice dropdown. A combined race and ethnicity option requires both facts to be confirmed. Consent questions, existing choices, and unmatched fields stay for review.

The agent can reuse a confirmed absence of employment history or referrals for equivalent questions. Set `automation.prefill_job_board_source` in the local config to use the known posting source or a generic job-board option on recognized source questions.

## Sign-in profiles

Run `main.py sign-in indeed` in an interactive terminal to open Indeed in a dedicated browser profile. An optional `--job-key` opens a specific listing. Sign in and complete verification in Microsoft Edge, then press Enter in the terminal to close the profile cleanly. Reopening the profile can reuse sessions that Indeed keeps valid. This command opens the listing for manual use.

For a supported employer posting, add `--reuse-session` to `review-submit`. Each employer board has its own local Edge profile. Use your existing account when prompted. Create an account only when needed and handle verification yourself. Dedicated profiles start separately from your everyday Edge profile. If the agent detects a sign-in page, it pauses before prefilling so you can sign in yourself. Keep `private/browser-profiles` on this computer. It contains browser session data and is ignored by Git. Scheduled runs use a fresh browser and flag detected login pages for review.
