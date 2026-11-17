"""Drive the same synthetic listing through the read-only dashboard and receipt matcher."""

from contextlib import closing
import unittest

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from agent.portfolio_demo import JOB_ID, run_demo
from agent.storage import connect
from agent.web_dashboard import create_app


def dashboard_state(database):
    with TestClient(create_app(database), base_url='http://127.0.0.1') as client:
        main = (client.get('/api/jobs')).json()
        queue = (client.get('/api/jobs?view=review')).json()
    return main, queue


class PortfolioDemoTest(unittest.TestCase):
    def test_same_listing_moves_through_review_and_receipt(self):
        sequence = []
        databases = []

        def observe(stage, database):
            databases.append(database)
            rows, queue = dashboard_state(database)
            job, = rows
            self.assertEqual(job['id'], JOB_ID)
            sequence.append((stage, job['status'], [row['id'] for row in queue]))
            if stage == 'receipt':
                with closing(connect(database)) as con:
                    self.assertEqual(con.execute('SELECT job_id FROM receipts').fetchone()[0], JOB_ID)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                run_demo(browser, observe)
            finally:
                browser.close()

        self.assertEqual(sequence, [
            ('discovery', 'found', []),
            ('review', 'needs_review', [JOB_ID]),
            ('mock confirmation', 'needs_review', [JOB_ID]),
            ('receipt', 'submitted', []),
        ])
        self.assertFalse(databases[0].exists())
