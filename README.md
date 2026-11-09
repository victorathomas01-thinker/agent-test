# Personal Job Agent

Discover jobs from public Greenhouse and Lever boards, filter and rank them, and rehearse filling application forms locally. Live submission is disabled. The agent opens the posting without applicant data, then fills a disconnected copy with site scripts disabled.

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

- **Discovery.** The starter feeds cover Canonical, Duolingo, Cloudflare, Affirm, and Zoox. Change the board or site identifiers in the ignored local `config.json` to cover other employers. To import jobs, use `main.py import YOUR_JOBS.csv` with the columns in `examples/jobs.csv`.
- **Eligibility.** Discovered and imported jobs use the same title, location, contract, seniority, GPA, work authorization, and sponsorship rules. Use `list --all` to see exclusions and their reasons. The rules are heuristic and can miss requirements.
- **Verified answers.** Use `main.py set work_authorized_us yes` for a confirmed built-in answer or `main.py remember "Do you speak French?" "Yes"` for a confirmed answer tied to the exact question wording. Remember only reusable answers. Unknown questions and required checkbox or radio controls go to review.
- **Resume.** Set the local file with `main.py set resume_path PATH_TO_RESUME`. The browser attaches the original file to a recognized resume field in the disconnected copy. Resume tailoring is outside this implementation.
- **Dry runs.** `apply JOB_ID` rehearses a single listing. `batch --limit 5` rehearses up to five eligible, unprocessed listings within the configured limit. The local application log records `prepared`, `needs_review`, or `failed`. `prepared` means the agent filled recognized fields and found no unresolved required field it could detect. Multi-step forms, login, CAPTCHA, and custom widgets can require manual review.

Keep the local config, database, and resumes out of Git. The tracked example has blank applicant fields. Attempt details store field labels, answer keys, and outcomes. They omit filled values and resume paths.

Discovery uses the [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html) and [Lever Postings API](https://github.com/lever/postings-api).
