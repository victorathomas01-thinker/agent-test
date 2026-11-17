"""Run one synthetic job through review, rehearsal, and receipt in a temporary database."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from .core import evaluate, record_attempt, with_defaults
from .dashboard import is_review_job, load_jobs
from .receipts import record_receipt
from .rehearsal import FORM, MOCK_COMPANY, MOCK_TITLE, rehearse_submission
from .storage import connect

JOB_ID = 'demo:software-intern'


def run_demo(browser, observe):
    fixture = {'title': MOCK_TITLE, 'location': 'Charlotte, NC', 'url': FORM,
               'description': 'Build and test an internal web tool.'}
    score, eligible, reason = evaluate(fixture, with_defaults({}))

    with TemporaryDirectory(prefix='job-agent-demo-') as directory:
        database = Path(directory) / 'demo.sqlite3'
        with closing(connect(database)) as con:
            with con:
                con.execute('''INSERT INTO jobs
                    (id, source, company, title, location, url, description, score, eligible, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (JOB_ID, 'demo', MOCK_COMPANY, MOCK_TITLE, fixture['location'], FORM,
                     fixture['description'], score, int(eligible), reason))
            observe('discovery', database)

            with con:
                record_attempt(con, JOB_ID, 'needs_review', 'Synthetic listing ready for an isolated rehearsal.')
            observe('review', database)

            receipts = []
            state, detail = rehearse_submission(browser, on_receipt=receipts.append)
            if state != 'confirmed' or len(receipts) != 1:
                raise RuntimeError(detail)
            observe('mock confirmation', database)

            if not record_receipt(con, JOB_ID, receipts[0], details='Matched the isolated mock employer receipt.'):
                raise RuntimeError('The synthetic receipt was already recorded.')
            observe('receipt', database)


def print_stage(stage, database):
    row, = load_jobs(database, include_id=True)
    job_id, title, company, _, score, eligible, status, _ = row
    queue = 'in review queue' if is_review_job(eligible, status) else 'outside review queue'
    print(f'{stage} | {job_id} | {title} at {company} | score {score} | {status} | {queue}')


def main():
    from playwright.sync_api import sync_playwright

    print('Synthetic walkthrough. All application and receipt records are temporary.', flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            run_demo(browser, print_stage)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
