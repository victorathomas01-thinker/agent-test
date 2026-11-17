from io import BytesIO
import unittest
from unittest.mock import call, patch
from urllib.error import HTTPError

from agent import core, provider_http


def http_error(status, headers=None):
    return HTTPError('https://example.invalid', status, 'test response', headers or {}, BytesIO())


class ProviderHttpTest(unittest.TestCase):
    def test_transient_responses_retry_with_bounded_backoff(self):
        with patch.object(provider_http, 'urlopen', side_effect=[
            http_error(503), http_error(429, {'Retry-After': '3'}), BytesIO(b'{"ok":true}')
        ]) as request, patch.object(provider_http, 'sleep') as sleep:
            self.assertEqual(provider_http.http_json('https://example.invalid'), {'ok': True})
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(3)])

    def test_permanent_failure_and_long_retry_after_surface_immediately(self):
        for error in (http_error(404), http_error(429, {'Retry-After': '60'})):
            with patch.object(provider_http, 'urlopen', side_effect=error) as request, \
                    patch.object(provider_http, 'sleep') as sleep:
                with self.assertRaises(HTTPError):
                    provider_http.http_json('https://example.invalid')
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()

    def test_discovery_keeps_other_boards_after_retries_are_exhausted(self):
        config = core.with_defaults({'discovery': {
            'greenhouse_boards': ['studio', 'outage'],
            'lever_sites': ['example'], 'employer_feeds': [],
        }})

        def respond(request, *, timeout):
            url = request.full_url
            if '/outage/' in url:
                raise http_error(503)
            if '/studio/' in url:
                return BytesIO(b'{"jobs":[{"id":42,"title":"Developer",'
                               b'"location":{"name":"Charlotte, NC"},'
                               b'"absolute_url":"https://boards.greenhouse.io/studio/jobs/42",'
                               b'"content":"<p>Build &amp; test</p>"}]}')
            return BytesIO(b'[{"id":"abc","text":"Data Analyst",'
                           b'"categories":{"allLocations":["Charlotte, NC","Remote"]},'
                           b'"applyUrl":"https://jobs.lever.co/example/abc/apply",'
                           b'"descriptionPlain":"Analyze results"}]')

        with patch.object(provider_http, 'urlopen', side_effect=respond) as request, \
                patch.object(provider_http, 'sleep'):
            jobs, errors = core.discover(config)
        self.assertEqual(request.call_count, 5)
        self.assertEqual([job['id'] for job in jobs], ['greenhouse:studio:42', 'lever:example:abc'])
        self.assertEqual(jobs[0]['description'], 'Build & test')
        self.assertEqual(jobs[1]['location'], 'Charlotte, NC, Remote')
        self.assertEqual(len(errors), 1)
        self.assertIn('greenhouse outage', errors[0])
