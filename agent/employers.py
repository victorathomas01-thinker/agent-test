"""Find public hiring boards from early-career job feeds."""

import re
from urllib.parse import urlsplit


def board_from_url(url):
    if not isinstance(url, str):
        return None
    try:
        address = urlsplit(url)
    except ValueError:
        return None
    if address.scheme != 'https' or address.username is not None:
        return None
    if address.netloc in {'job-boards.greenhouse.io', 'boards.greenhouse.io'}:
        match = re.fullmatch(r'/([a-zA-Z0-9_-]+)/jobs/\d+/?', address.path)
        return ('greenhouse', match[1].lower()) if match else None
    if address.netloc == 'jobs.lever.co':
        match = re.fullmatch(
            r'/([a-zA-Z0-9_-]+)/[a-fA-F0-9-]{36}(?:/apply)?/?', address.path
        )
        return ('lever', match[1].lower()) if match else None
    return None


def find_boards(feeds, known_boards, limit, fetch, score_listing):
    if not limit:
        return [], []
    candidates = {}
    errors = []
    for feed in feeds:
        try:
            listings = fetch(feed)
            if not isinstance(listings, list):
                raise ValueError('Expected a list of job records.')
            for listing in listings:
                if not isinstance(listing, dict) or listing.get('active') is not True:
                    continue
                board = board_from_url(listing.get('url'))
                if board is None or board in known_boards:
                    continue
                timestamp = listing.get('date_posted')
                rank = (score_listing(listing), timestamp if isinstance(timestamp, int) else 0)
                if board not in candidates or rank > candidates[board]:
                    candidates[board] = rank
        except (OSError, ValueError) as error:
            errors.append(f'Employer discovery feed {feed}: {error}')
    ranked = sorted(candidates, key=lambda board: (candidates[board], board), reverse=True)
    return ranked[:limit], errors
