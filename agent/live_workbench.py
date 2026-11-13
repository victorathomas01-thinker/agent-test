"""Attended Edge tabs for an explicitly approved batch of official postings."""

import json
from contextlib import ExitStack, closing
from hashlib import sha256

from . import core
from .sessions import EDGE_CHANNEL, requires_sign_in
from .submission import (allowed_step, browser_outcome, contact_form, observe_submission, official_job_url,
                         prepare_step, reserve_submission)


def available_jobs(con, limit):
    rows = con.execute("""SELECT j.*,s.version FROM selections s JOIN jobs j ON j.id=s.job_id
                         WHERE s.status IN ('offline_preview','needs_attention')
                           AND j.eligible=1 AND j.submitted_at IS NULL
                           AND j.status NOT IN ('submission_pending','expired','submitted')
                         ORDER BY j.score DESC,j.id""")
    return [dict(row) for row in rows if official_job_url(row)][:limit]


def reviewed_master(job):
    version = job['version']
    if len(version) != 20 or any(char not in '0123456789abcdef' for char in version):
        return None
    directory = core.ROOT / 'private' / 'packages' / version
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    suffix = manifest['source_extension']
    if manifest['job_id'] != job['id'] or suffix not in {'.pdf', '.txt'}:
        return None
    path = directory / ('master' + suffix)
    return path if sha256(path.read_bytes()).hexdigest() == manifest['source_sha256'] else None


def set_tab_state(con, job, status, reason=''):
    with con:
        con.execute('UPDATE selections SET status=?, blocker=?, updated_at=? WHERE job_id=?',
                    (status, reason, core.utc_now(), job['id']))


def review_tabs(jobs, cfg, attach=False, wait=input, context=None):
    from playwright.sync_api import Error as BrowserError, sync_playwright

    if cfg['automation'].get('allow_live_submit') is not True:
        raise ValueError('Attended submission is disabled in the local configuration.')
    with closing(core.connect()) as con, ExitStack() as resources:
        if context is None:
            playwright = resources.enter_context(sync_playwright())
            browser = playwright.chromium.launch(channel=EDGE_CHANNEL, headless=False)
            resources.callback(browser.close)
            context = browser.new_context(accept_downloads=False, service_workers='block')
        tabs = []
        try:
            for original in jobs:
                page = context.new_page()
                try:
                    response = page.goto(original['url'], wait_until='domcontentloaded', timeout=25000)
                    if requires_sign_in(page):
                        raise ValueError('Sign-in needed. Use the single-job session reuse flow.')
                    job = {**original, 'url': page.url}
                    if not response or not response.ok or not official_job_url(job):
                        raise ValueError('The official form could not be verified.')
                    if contact_form(page, job) is None:
                        raise ValueError('A supported application form was not found.')
                    resume = reviewed_master(job) if attach else None
                    if attach and resume is None:
                        raise ValueError('The approved package could not be verified.')
                    reserve_submission(con, original)
                    initial_url = page.url
                    print(f'[{len(tabs) + 1}] {job["title"]} at {job["company"]}')
                    remaining = prepare_step(page, job, cfg, resume, cfg)
                    initial = page.locator('body').inner_text(timeout=5000)
                    posts = observe_submission(page, initial_url)
                    tabs.append((job, page, initial_url, initial, posts, remaining))
                    set_tab_state(con, job, 'live_review', 'Review required fields and validation in Edge.')
                except (OSError, ValueError, KeyError, BrowserError) as error:
                    message = str(error) if isinstance(error, ValueError) else f'Form blocked ({type(error).__name__}).'
                    set_tab_state(con, original, 'needs_attention', message)
                    page.close()

            if tabs:
                while True:
                    command = wait('Review the Edge tabs and submit manually. Type next N after advancing tab N, '
                                   'or press Enter to check receipts and close: ').strip()
                    if not command:
                        break
                    verb, _, number = command.partition(' ')
                    if verb != 'next' or not number.isdigit() or not 1 <= int(number) <= len(tabs):
                        print('Use next N with the numbered application tab, or press Enter.')
                        continue
                    index = int(number) - 1
                    job, page, initial_url, initial, posts, remaining = tabs[index]
                    if page.is_closed() or not allowed_step(job, page.url):
                        print('This tab is outside its approved application steps.')
                        continue
                    remaining = prepare_step(page, job, cfg, remaining, cfg, later_step=True)
                    posts.clear()
                    tabs[index] = (job, page, initial_url, initial, posts, remaining)
                for job, page, initial_url, initial, posts, _ in tabs:
                    try:
                        outcome = ('submission_pending' if page.is_closed() else
                                   browser_outcome(con, job, page, initial_url, initial, posts))
                        set_tab_state(con, job, 'confirmed' if outcome == 'submitted' else 'needs_attention',
                                      '' if outcome == 'submitted' else 'Check the employer receipt before retrying.')
                        print(f'{job["id"]} | {outcome}')
                    except (ValueError, BrowserError):
                        set_tab_state(con, job, 'needs_attention', 'Receipt could not be verified.')
        finally:
            for job, *_ in tabs:
                with con:
                    con.execute("""UPDATE selections SET status='needs_attention',
                                   blocker='The Edge session closed. Check the employer before retrying.',
                                   updated_at=? WHERE job_id=? AND status='live_review'""",
                                (core.utc_now(), job['id']))
