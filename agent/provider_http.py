"""Bounded retries for public job board and feed reads."""

from contextvars import ContextVar
import json
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS = (1, 2)
MAX_RETRY_AFTER = 5
retry_count = ContextVar("provider_retry_count", default=0)


def http_json(url):
    request = Request(url, headers={
        'User-Agent': 'PersonalJobAgent/0.1 (personal job discovery)',
        'Accept': 'application/json',
    })
    for attempt in range(len(RETRY_DELAYS) + 1):
        delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else None
        try:
            with urlopen(request, timeout=18) as response:
                return json.load(response)
        except HTTPError as error:
            if delay is None or error.code not in RETRYABLE_STATUS:
                raise
            retry_after = error.headers.get('Retry-After') if error.headers else None
            if retry_after is not None:
                if not retry_after.isascii() or not retry_after.isdecimal() or len(retry_after) > 9:
                    raise
                delay = max(delay, int(retry_after))
                if delay > MAX_RETRY_AFTER:
                    raise
            error.close()
        except (TimeoutError, ConnectionError, URLError) as error:
            reason = error.reason if isinstance(error, URLError) else error
            if delay is None or not isinstance(reason, (TimeoutError, ConnectionError)):
                raise
        retry_count.set(retry_count.get() + 1)
        sleep(delay)
