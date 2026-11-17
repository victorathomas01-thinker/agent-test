# Personal Job Agent release handoff

## Demonstrate without an applicant profile

Use Python 3.11 or later. On Windows run `pwsh -File setup.ps1 -DemoOnly`. On other platforms create a virtual environment, install `requirements.txt`, and run `python -m playwright install chromium`.

Run `python -m agent.web_dashboard`, then open http://127.0.0.1:8765 for synthetic listings. Run `python -m agent.portfolio_demo` separately to follow one temporary job through review, an isolated form submission, and receipt matching.

The dashboard sample and temporary walkthrough have different data. The walkthrough checks its job's state through the same dashboard API implementation at each stage.

## Release contents

- Python CLI, FastAPI dashboard, SQLite schema upgrade, provider adapters, and browser rehearsal.
- Synthetic examples and ranking fixtures with overall and eligible-only evaluation.
- Setup instructions and a [two-minute script](DEMO.md).
- Windows CI for the application and isolated browser fixtures.

## Delivery record

Review and merge the draft PR, then record its merge revision and successful CI run in the published release notes. The commands above reproduce the synthetic demonstration. Follow the README to initialize a real local profile.

The ranking fixtures are small synthetic samples. Preserve their sample descriptions when presenting benchmark results.
