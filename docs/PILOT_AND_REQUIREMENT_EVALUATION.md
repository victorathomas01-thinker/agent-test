# Historical pilot diagnosis and source-linked requirements check

**Status:** Draft engineering validation. The original 20-employer-form pilot is documented in `PROGRESS.md` (20 reached, 20 with unresolved required fields, zero demonstrated live-ready). **Its actual private SQLite record set is not present in GitHub**, so the original per-field failure distribution cannot be claimed without reading that existing database on the user's computer.

## Analyze the saved 20-form pilot without exposing it

After this development branch is reviewed and checked out locally, use:

```powershell
python main.py pilot-audit --offline-only --limit 20 --expected 20
```

If the exact pilot date window is known, specify it to avoid including unrelated later attempts:

```powershell
python main.py pilot-audit --since 2026-10-01 --through 2026-10-31 --offline-only --limit 20 --expected 20
```

*The dates above are illustrative, not a claim about when the original pilot happened.* For an archived local SQLite copy, use `--database C:\\path\\to\\agent.sqlite3`. The tool refuses to create a missing database. It opens the specified file read-only; with `--offline-only` it chooses the most recent **detached preview** for each job rather than letting later login failures replace the original pilot history. Without that flag it reports the latest recorded attempt per job, including non-preview failures. It prints only aggregate totals by ATS provider, blocker category, and the number of affected jobs. It does **not** print posting IDs, employer names, answers, the applicant's GPA, contact information, job descriptions, original questions, or raw error text.

**Crucial:** Getting exactly 20 matching records is not proof they are the same 20 original pilot jobs. The final pilot claim requires comparing its original saved run/date selection. If the existing DB has no detailed detached previews, report unavailable rather than reconstructing them from the prior summary. The reported `offline_current_step_prepared` count does not imply an applicant can submit a real employer form.

The original pilot comprised 14 Canonical, five Affirm and one Shield AI postings according to the recorded development notes. This is the only supported original provider/employer breakdown so far—not a newly calculated diagnosis.

## Evaluate rule behavior against actual public posting styles

The source-linked file `examples/public_requirements_benchmark.json` includes **28 short, manually annotated cases derived from nine public job postings**. Candidate graduation dates and GPAs in these cases are entirely fictional; no user information is in the repository. Descriptions are brief paraphrases, not employer job descriptions copied wholesale. The sample is hand-curated, nonrandom, and labels were created by the project's author, not an independent blind reviewer.

Run:

```powershell
python main.py benchmark-requirements
```

The check compares three conservative preparation classifications: `hard_block`, `manual_review`, and `no_block`, reporting a source-by-source case count and a confusion matrix. A pass demonstrates reproducibility **on these examples** only. It does not measure actual hiring outcomes or accuracy across the labor market.

Examples covered with source links in the fixture:

- [Duke Energy / Telecommunications Internship](https://dukeenergy.wd1.myworkdayjobs.com/search/job/Charlotte-NC/Telecommunications-Internship---Summer-2027_R41225): 2.75 cumulative GPA **required**, 3.0 **desired**, and a minimum graduation month.
- [TIAA Technology Internship](https://tiaa.wd1.myworkdayjobs.com/en-US/Search/job/XMLNAME-2027-Early-Talent-Internship--Technology_R261000111): explicit 3.0 GPA and graduation range, but **posting deadline October 26, 2026**; do not present it as currently open.
- [Wells Fargo Data Engineering Internship](https://wf.wd1.myworkdayjobs.com/en-US/WellsFargoJobs/job/CHARLOTTE-NC/XMLNAME-2027-Technology-Summer-Internship---Early-Careers--Data-Engineering-_R-583066): graduation range under **Desired Qualifications** rather than Required Qualifications.
- [Truist Enterprise Payments Internship](https://truist.wd1.myworkdayjobs.com/en-US/Careers/job/XMLNAME-2027-Enterprise-Payments-Summer-Intern_R0121539): an explicit overall GPA cutoff and graduation range.
- [Honeywell Technologies software/embedded internship](https://hireaniner.charlotte.edu/jobs/df26b8c3f5f9a98734f8d8b0405424e0): minimum GPA, graduate-on-or-after date, and continued enrollment after internship.
- [SAS 2027 software development/testing internship](https://careers-sas.icims.com/jobs/42964/summer-2027---software-development-and-testing-intern/job?mobile=true&needsRedirect=false): graduation not before December 2027.
- [Protiviti Charlotte Technology Consulting](https://roberthalf.wd1.myworkdayjobs.com/en-US/ProtivitiNA/job/Charlotte-Technology-Consulting-Intern---2027_JR-258879): graduation within a period after internship completion that cannot be resolved without dates.
- [AIG Technology Early Careers](https://aig.wd1.myworkdayjobs.com/en-US/aig/job/XMLNAME-2027-Early-Careers--Summer-Intern--Technology---United-States--Charlotte--NC--Houston--TX----Jersey-City--NJ_JR2603638-1): mandatory GPA and prior internship experience.
- [Truist 2027 Intern Conversion](https://notify.careers/postings/72499d6b-2a94-41b7-9440-2d38d5bee327): restricted to a prior internal company internship cohort. A normal external student should not be assumed eligible.

The parser now retains separate **Required Qualifications** and **Desired Qualifications** scope even when the original HTML is flattened into plain text; it also recognizes common `through` and dash-separated graduation ranges, minimum GPA alternatives, and ambiguous prior-intern/continued-enrollment requirements. Preferred GPA phrasing must remain nonblocking even when it contains the word **minimum**.

## Disposable installation and recovery verification

A separate [Windows CI acceptance run](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43364014263) exercised the integrated command-line app in a fresh disposable working directory. It initialized a local SQLite database with live submission disabled, inserted 20 entirely synthetic blocked previews, ran the audit and 28-case requirement fixture, performed SQLite backup/restore, created two SQL market snapshots, and expanded a four-table legacy database without deleting its original job and attempt rows. It never used the user's original pilot records or any live employer form. The smoke test is repeatable with `python -m scripts.integration_acceptance` and runs without network calls.

## Remaining release gates

1. Read an existing local pilot database **without exporting raw records**; verify the correct date window/20 exact jobs and produce its aggregate blocker histogram.
2. Build a separately held-out, independently reviewed sample of recent public postings across employers and systems; measure false exclusions, false approvals and unknowns per mandatory/preferred dimension.
3. Confirm actual application landing pages and deadlines before recommending a job. Indexed expired listings are not proof of vacancy availability.
4. Use the aggregated blocker breakdown to prioritize safe offline form-fixture fixes. Sensitive acknowledgements and final Submit remain human-operated.

No live application was opened, filled or submitted by this audit or benchmark.
