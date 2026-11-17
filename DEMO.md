# Personal Job Agent walkthrough

## Two-minute demo

1. Install the requirements, then run `python -m agent.web_dashboard`. Open [the local dashboard](http://127.0.0.1:8765). Show the ranked listings, the excluded listing's reason, and the Review queue. This default mode uses synthetic data.
2. Run `python -m agent.portfolio_demo`. Follow one synthetic job ID through discovery, the review queue, an offline browser rehearsal, and receipt matching. The test suite verifies that the dashboard API shows the same job before and after the receipt. This walkthrough uses a temporary database and synthetic applicant data.
3. Run `python -m agent.evaluation --fixture examples/ranking-holdout.json --cutoff 5`. Explain nDCG as a measure of how high the manually labeled relevant jobs appear. Review the eligibility mismatch list separately.

## Verify a real local workflow

Use `python main.py init` to initialize your local profile and database. Use `python main.py discover` or import an authorized CSV, then open the dashboard with `python -m agent.web_dashboard --live`. Use the displayed job ID with `python main.py apply JOB_ID` to rehearse and `python main.py queue` to review. The dashboard is read-only. Use the attended submission and receipt instructions in the README when ready to handle a real application yourself.

## Evaluation evidence

The baseline and holdout are small, independently authored sets of synthetic listings for the same example preferences. The holdout was added after the ranker was implemented, and the scoring rules were kept fixed. Treat the scores as reproducible fixture results. Real provider distribution, job quality, and ranking utility still need evaluation on a larger authorized sample.

## Presentation notes

Keep the browser at a readable zoom and show one workflow at a time. Explain the result before opening source files. Use the documented synthetic demo for applicant or campaign examples. Give viewers the README link so setup instructions and evidence remain available after the walkthrough.
