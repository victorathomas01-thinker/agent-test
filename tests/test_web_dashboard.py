from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from agent.storage import connect
from agent.web_dashboard import create_app


class WebDashboardTest(unittest.TestCase):
    def test_live_review_filters_and_escapes_job_titles(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'agent.sqlite3'
            connection = connect(database)
            with connection:
                connection.executemany(
                    'INSERT INTO jobs (id, title, score, eligible, status, notes) VALUES (?, ?, ?, ?, ?, ?)',
                    [('one', '<Sample>', 60, 1, 'prepared', 'private note'),
                     ('two', 'Another', 40, 1, 'found', 'private note'),
                     ('pending', 'Pending', 10, 0, 'submission_pending', 'private note')],
                )
            connection.close()
            with TestClient(create_app(database), base_url='http://127.0.0.1') as client:
                html = client.get('/?view=review')
                self.assertIn('&lt;Sample&gt;', html.text)
                self.assertNotIn('Another', html.text)
                self.assertEqual(html.headers['Cache-Control'], 'no-store')
                jobs = client.get('/api/jobs?view=review').json()
                self.assertEqual([job['id'] for job in jobs], ['pending', 'one'])
                limited = client.get('/api/jobs?view=review&limit=1').json()
                self.assertEqual([job['id'] for job in limited], ['pending'])
                self.assertNotIn('notes', jobs[0])
                self.assertEqual(client.post('/api/jobs').status_code, 405)

    def test_demo_is_default_and_rejects_non_loopback_hosts(self):
        with TestClient(create_app(), base_url='http://localhost') as client:
            self.assertEqual(len(client.get('/api/jobs').json()), 4)
            self.assertEqual(client.get('/', headers={'Host': 'example.invalid'}).status_code, 400)
