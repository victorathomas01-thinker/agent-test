# Personal Job Agent

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

## Sign-in profiles

Run `main.py sign-in indeed` in an interactive terminal to open Indeed in a dedicated browser profile. An optional `--job-key` opens a specific listing. Sign in and complete verification in Microsoft Edge, then press Enter in the terminal to close the profile cleanly. Reopening the profile can reuse sessions that Indeed keeps valid. This command opens the listing for manual use.

For a supported employer posting, add `--reuse-session` to `review-submit`. Each employer board has its own local Edge profile. Use your existing account when prompted. Create an account only when needed and handle verification yourself. Dedicated profiles start separately from your everyday Edge profile. If the agent detects a sign-in page, it pauses before prefilling so you can sign in yourself. Keep `private/browser-profiles` on this computer. It contains browser session data and is ignored by Git. Scheduled runs use a fresh browser and flag detected login pages for review.
