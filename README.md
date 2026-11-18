# Personal Job Agent

[Release instructions](RELEASE.md)

Discover jobs, explain eligibility, review applications, and rehearse forms through a Python workflow with a local web dashboard.

**[Two-minute walkthrough](DEMO.md) · [Setup](#windows-setup) · [Ranking benchmark](#ranking-benchmark)**

| Start here | Command | Result |
| --- | --- | --- |
| See the dashboard | `python -m agent.web_dashboard` | Synthetic jobs at http://127.0.0.1:8765 |
| Follow one job | `python -m agent.portfolio_demo` | Discovery → review → offline rehearsal → matched receipt |
| Inspect ranking | `python -m agent.evaluation --fixture examples/ranking-holdout.json` | Reproducible report for ten synthetic jobs |

Install the dependencies in the setup instructions before running these commands. Both demonstrations work with synthetic applicant data. The dashboard binds to loopback and reads the job database without writing to it.

**Engineering evidence.** 51 local tests and Windows CI passed before this documentation update, including provider failures, database upgrades, and the same-job workflow. The synthetic holdout scored 0.51 nDCG@5 for the agent and 0.48 for title overlap. Eligibility matched all ten fixture labels.

**Workflow boundaries.** Discovery uses public Greenhouse and Lever boards. Dry runs fill disconnected forms. Live submissions use the attended review workflow documented below.

**Architecture.** Provider adapters feed normalized listings into eligibility rules and SQLite. The CLI and FastAPI dashboard share the review-queue query. Browser rehearsal and receipt matching record application outcomes.

## Release status

This branch contains the portfolio release candidate. Use the synthetic dashboard and temporary same-job walkthrough to inspect it before configuring a personal profile.

| Capability | Evidence |
| --- | --- |
| Dashboard and review queue | Local API checks and shared CLI queue ordering |
| Same-job walkthrough | One temporary job moves through review, offline browser rehearsal, and receipt matching |
| Provider recovery and database upgrade | Included in the 51-test suite that passed locally and in Windows CI |
| Ranking evaluation | Ten synthetic holdout jobs, with relevance and eligibility reported separately |

The dashboard sample rows and temporary same-job walkthrough use separate datasets. The walkthrough checks dashboard API state at each transition and prints the result in the terminal.

## Windows setup

### Contributor checks

Install `requirements-dev.txt` for the pinned Ruff tool alongside the runtime dependencies. Run `python -m ruff check .`, `python -m ruff format --check .`, and `python -m unittest discover -s tests -v` before opening a pull request. To apply the formatter, use `python -m ruff format .`. Windows CI runs both lint and formatting checks before the existing test suite. The Python 3.11 target and lint rules are recorded in `pyproject.toml`.

With Python 3.11 or later installed, run `pwsh -File setup.ps1` in the repository folder. This installs Playwright and Chromium, creates the local profile and database, and runs the tests. Setup imports the existing MVP configuration from Downloads when present. For an MVP installed elsewhere, run `python main.py init --from-mvp PATH_TO_CONFIG` before setup.

On other platforms, run `python -m pip install -r requirements.txt`, `python -m playwright install chromium`, and `python main.py init`. Run `python -m unittest discover -s tests -v` to verify the install.

GitHub Actions runs the same unittest command on Windows for pushes and pull requests. CI installs Chromium and uses a clean checkout.

## Portfolio dashboard

See the [two-minute walkthrough](DEMO.md) for the dashboard, an isolated employer rehearsal, and a separate synthetic ranking holdout.

Run `python -m agent.dashboard` and open `private/dashboard/demo.html` for a synthetic walkthrough of scores, eligibility reasons, and the review queue. It works offline without a configured profile.

Run `python -m agent.dashboard --live` to generate an offline snapshot of your initialized SQLite database in `private/dashboard/jobs.html`. Keep this file private. It contains listing and review status data. The dashboard reads SQLite in read-only mode.

## Local web dashboard

Start the synthetic dashboard with `python -m agent.web_dashboard` and open http://127.0.0.1:8765. Pass `--live` to display jobs from your initialized local SQLite database. The review queue uses the same status priority as the CLI. The views show up to 100 jobs by default. Use the displayed job ID with the CLI for rehearsals and receipts. The dashboard reads the database in read-only mode and binds to loopback.

Existing SQLite databases are upgraded when the CLI next opens them. The upgrade preserves existing rows, adds an index for review queries, and records its schema version.

## Provider failures

Run the discovery command to see fetched and newly stored totals plus per-provider board counts, retries, failures, and combined board time. A discovery request retries timeouts, connection errors, and transient HTTP responses up to twice. Rate-limit instructions are honored when the requested delay is within the short retry budget. An exhausted or permanently failed board appears in the discovery summary, while other successful board results are still processed.

## Ranking benchmark

Run `python -m agent.evaluation --cutoff 5` to compare the agent score and title overlap using [labeled synthetic jobs](examples/ranking-benchmark.json). The report includes normalized discounted cumulative gain (nDCG), strong matches in the top five, and eligibility decisions that disagree with the fixture. The benchmark reads no local applicant data. Its small sample is designed for inspection and regression checks.

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
Employer board leads come from [Summer 2027 Internships](https://github.com/SimplifyJobs/Summer2027-Internships) and [New Grad Positions](https://github.com/SimplifyJobs/New-Grad-Positions). The internship feed can be updated in `employer_feeds` when the hiring season changes.

## Unattended dry runs

Use `main.py run` as the entry point for a local scheduled job. It refreshes discovery, previews eligible unprocessed jobs seen in that refresh in a headless browser, and prints a summary. Use `main.py logs` to review attempts.

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

## Data interpretation update

The ranking evaluation includes an eligible_only section. Both rankers use the same jobs approved by the eligibility rules. The cutoff shrinks to the available sample, and eligibility mismatches remain visible in the overall report.
