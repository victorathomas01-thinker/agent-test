"""Local browser profiles for user-managed sign-in sessions."""

import re
from urllib.parse import urlsplit

from .core import ROOT
from .employers import board_from_url

EDGE_CHANNEL = 'msedge'


def session_dir(scope):
    if not re.fullmatch(r'[a-z0-9_-]+', scope):
        raise ValueError('Invalid browser profile name.')
    return ROOT / 'private' / 'browser-profiles' / 'edge' / scope


def posting_scope(url):
    board = board_from_url(url)
    if board is None:
        raise ValueError('A direct Greenhouse or Lever posting is required.')
    return '--'.join(board)


def open_profile(chromium, scope, *, headless=False, channel=EDGE_CHANNEL):
    return chromium.launch_persistent_context(
        session_dir(scope), channel=channel, headless=headless,
        accept_downloads=False, service_workers='block',
    )


def sign_in(scope, url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = open_profile(playwright.chromium, scope)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            input('Sign in in Microsoft Edge and complete any verification yourself. Press Enter here when done. ')
        finally:
            context.close()


def requires_sign_in(page):
    address = urlsplit(page.url)
    if address.hostname == 'secure.indeed.com' and address.path.startswith('/auth'):
        return True
    if page.locator('input[type=password]:visible').count():
        return True
    heading = page.get_by_role('heading', name=re.compile(r'^(sign in|log in)(?: to (?:apply|continue))?$', re.I))
    return bool(heading.count())
