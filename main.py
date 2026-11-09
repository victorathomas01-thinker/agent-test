#!/usr/bin/env python3
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sys

from agent import core
from agent.browser import resume_file, run_browser
from agent.receipts import read_receipt, record_receipt, scan_receipts
from agent.rehearsal import run_rehearsal
from agent.resume import write_preview
from agent.sessions import sign_in
from agent.submission import official_job_url, release_submission, review_submission


def positive_integer(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('Enter a positive integer.')
    return number


def discover_jobs(cfg):
    jobs, errors = core.discover(cfg)
    new = core.store_jobs(jobs, cfg)
    employers = len({job['id'].rsplit(':', 1)[0] for job in jobs})
    print(f'Fetched {len(jobs)} listings from {employers} employer boards, {new} new.')
    for error in errors:
        print('SOURCE ERROR', error)
    if errors and not jobs:
        raise SystemExit(1)


def dry_run(job, cfg):
    outcome, details = run_browser(dict(job), cfg)
    print(f'{job["id"]} | {outcome} | {details}')
    return outcome


def run_batch(cfg, limit, fresh_since):
    outcomes = {'prepared': 0, 'needs_review': 0, 'failed': 0}
    daily_limit = positive_integer(cfg['preferences']['max_previews_per_day'])
    with closing(core.connect()) as con:
        core.refresh_eligibility(con, cfg)
        for _ in range(limit):
            job = core.claim_preview(con, daily_limit, fresh_since)
            if job is None:
                break
            outcomes[dry_run(job, cfg)] += 1
    print(f'Batch complete | {sum(outcomes.values())} previews | '
          + ' | '.join(f'{status}: {count}' for status, count in outcomes.items()))
    if not any(outcomes.values()):
        print('No eligible unprocessed listings available within today’s preview quota.')
    if outcomes['failed']:
        raise SystemExit(1)


def scan_local_receipts(con):
    summary = scan_receipts(con, core.ROOT / 'private' / 'receipts')
    print('Receipt scan | ' + ' | '.join(f'{status}: {count}' for status, count in summary.items()))


def print_review_queue(con, limit):
    jobs = con.execute("""SELECT * FROM jobs
        WHERE status='submission_pending'
           OR (eligible=1 AND status IN ('needs_review', 'prepared', 'failed'))
        ORDER BY CASE status WHEN 'submission_pending' THEN 0 WHEN 'prepared' THEN 1
                             WHEN 'needs_review' THEN 2 ELSE 3 END, score DESC, id LIMIT ?""",
                       (limit,)).fetchall()
    if not jobs:
        print('No applications are waiting for review.')
    for job in jobs:
        print(f'{job["id"]} | {job["status"]} | {job["title"]} | {job["company"]}')
        print(f'  {job["url"]}')
        if job['status'] == 'submission_pending':
            print('  Verify the employer receipt before trying this application again.')
        elif job['status'] == 'needs_review':
            if job['notes'] == 'Sign-in needed.':
                print('  Sign-in needed.')
                continue
            try:
                items = json.loads(job['notes']).get('unresolved', [])
            except (ValueError, AttributeError, TypeError):
                items = []
            if not isinstance(items, list):
                items = []
            labels = dict.fromkeys(
                ''.join(char for char in item['field'] if char.isprintable())
                for item in items if isinstance(item, dict) and item.get('required')
                and isinstance(item.get('field'), str)
            )
            if labels:
                print('  Required review')
                for label in labels:
                    print(f'  - {label}')
            else:
                print('  Review the form or see the dry-run log for details.')


def main():
    parser = argparse.ArgumentParser(description='Personal job application agent')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--from-mvp', type=Path, metavar='CONFIG')
    for name in ('discover', 'status', 'answers'):
        commands.add_parser(name)
    logs = commands.add_parser('logs')
    logs.add_argument('--limit', type=positive_integer, default=20)
    receipt = commands.add_parser('receipt', help='Record a locally saved employer confirmation.')
    receipt.add_argument('job_id')
    receipt.add_argument('confirmation', type=Path, help='A UTF-8 confirmation or an exported .eml receipt.')
    commands.add_parser('scan-receipts', help='Match files from the local receipt inbox to pending jobs.')
    queue = commands.add_parser('queue', help='Show previews and submissions that need your review.')
    queue.add_argument('--limit', type=positive_integer, default=20)
    commands.add_parser('rehearse-submit', help='Test submission against an isolated mock employer.')
    login = commands.add_parser('sign-in', help='Open a dedicated Indeed browser profile for manual sign-in.')
    login.add_argument('portal', choices=['indeed'])
    login.add_argument('--job-key', help='Open a specific Indeed listing after signing in.')
    review = commands.add_parser('review-submit', help='Open one official form for attended submission.')
    review.add_argument('job_id')
    review.add_argument('--reuse-session', action='store_true',
                        help='Use a private browser profile for this employer board.')
    review.add_argument('--prefill', action='store_true',
                        help='Enter saved contact details on the live form after you approve the posting.')
    review.add_argument('--attach-resume', type=Path,
                        help='Attach this reviewed local resume on the employer page.')
    review.add_argument('--prefill-verified', action='store_true',
                        help='Select verified eligibility and explicitly saved personal dropdown choices.')
    release = commands.add_parser('release-submit', help='Clear a hold after verifying no submission occurred.')
    release.add_argument('job_id')
    setting = commands.add_parser('set')
    setting.add_argument('key')
    setting.add_argument('value')
    memory = commands.add_parser('remember')
    memory.add_argument('question')
    memory.add_argument('answer', help='An applicant-confirmed answer, or an empty string to clear it.')
    listings = commands.add_parser('list')
    listings.add_argument('--all', action='store_true')
    listings.add_argument('--limit', type=positive_integer, default=30)
    commands.add_parser('import').add_argument('csv', type=Path)
    apply = commands.add_parser('apply')
    apply.add_argument('job_id')
    apply.add_argument('--resume', type=Path, help='Use a reviewed local resume for this dry run.')
    apply.add_argument('--live', action='store_true', help=argparse.SUPPRESS)
    tailor = commands.add_parser('tailor', help='Create a local role-specific resume preview.')
    tailor.add_argument('job_id')
    batch = commands.add_parser('batch')
    batch.add_argument('--limit', type=positive_integer)
    batch.add_argument('--live', action='store_true', help=argparse.SUPPRESS)
    unattended = commands.add_parser('run', help='Discover jobs and preview eligible new listings.')
    unattended.add_argument('--limit', type=positive_integer)
    args = parser.parse_args()
    if getattr(args, 'live', False):
        parser.error('Live submission is disabled.')

    if args.command == 'sign-in':
        from playwright.sync_api import Error as PlaywrightError

        if not sys.stdin.isatty():
            parser.error('Sign-in requires an interactive terminal.')
        if args.job_key and not re.fullmatch(r'[0-9a-f]{16}', args.job_key, re.I):
            parser.error('Enter a valid Indeed job key.')
        url = 'https://www.indeed.com/'
        if args.job_key:
            url += f'viewjob?jk={args.job_key}'
        try:
            sign_in(args.portal, url)
        except (EOFError, KeyboardInterrupt, PlaywrightError):
            parser.error('Sign-in session closed or unavailable. Close any existing profile window and try again.')
        print('Profile closed. Browser session data stays on this computer.')
        return

    if args.command == 'rehearse-submit':
        status, detail = run_rehearsal()
        print(f'{status} | {detail}')
        if status != 'confirmed':
            raise SystemExit(1)
        return

    if args.command == 'init':
        if not core.CONFIG.exists():
            saved = json.loads(args.from_mvp.read_text(encoding='utf-8-sig')) if args.from_mvp else {}
            if args.from_mvp:
                resume = saved.get('profile', {}).get('resume_path')
                if resume and not Path(resume).expanduser().is_absolute():
                    saved['profile']['resume_path'] = str(args.from_mvp.parent / resume)
                discovery = saved.get('discovery', {})
                if not discovery.get('greenhouse_boards') and not discovery.get('lever_sites'):
                    saved.pop('discovery', None)
            cfg = core.with_defaults(saved)
            cfg['automation']['allow_live_submit'] = False
            core.save_config(cfg)
        core.connect().close()
        print('Local profile and application log are ready.')
        return

    if not core.CONFIG.exists():
        parser.error('Run python main.py init first.')
    cfg = core.load_config()
    if args.command == 'set':
        if args.key in cfg['verified_answers']:
            value = args.value.lower()
            choices = {'yes': True, 'true': True, 'no': False, 'false': False, 'unknown': None}
            if value not in choices:
                parser.error('Verified answers accept yes, no, or unknown.')
            cfg['verified_answers'][args.key] = choices[value]
        elif args.key in cfg['profile']:
            cfg['profile'][args.key] = args.value
        else:
            parser.error('Unknown profile or answer key.')
        core.save_config(cfg)
        print(f'Saved {args.key}.')
        return
    if args.command == 'remember':
        question = core.normalize_question(args.question)
        if not question:
            parser.error('Enter the full question.')
        if args.answer.strip():
            cfg['verified_questions'][question] = args.answer.strip()
        else:
            cfg['verified_questions'].pop(question, None)
        core.save_config(cfg)
        print('Verified question memory updated.')
        return
    if args.command == 'answers':
        for key, value in cfg['verified_answers'].items():
            print(f'{key} | {value if value is not None else "NOT SET"}')
        print(f'{len(cfg["verified_questions"])} exact questions remembered.')
        return
    if args.command == 'discover':
        discover_jobs(cfg)
        return
    if args.command in {'batch', 'run'}:
        maximum = positive_integer(cfg['preferences']['max_applications_per_run'])
        fresh_since = None
        if args.command == 'run':
            with closing(core.connect()) as con:
                scan_local_receipts(con)
            fresh_since = core.utc_now()
            discover_jobs(cfg)
            cfg['automation']['headless'] = True
        run_batch(cfg, min(args.limit or maximum, maximum), fresh_since)
        return
    if args.command == 'import':
        print(f'Imported {core.import_urls(args.csv, cfg)} new jobs.')
        return

    with closing(core.connect()) as con:
        if args.command == 'scan-receipts':
            scan_local_receipts(con)
            return
        if args.command == 'queue':
            core.refresh_eligibility(con, cfg)
            print_review_queue(con, args.limit)
            return
        if args.command in {'review-submit', 'release-submit'}:
            if args.command == 'review-submit' and cfg['automation'].get('allow_live_submit') is not True:
                parser.error('Attended submission is disabled in the local configuration.')
            if not sys.stdin.isatty():
                parser.error('Attended submission commands require an interactive terminal.')
            if args.command == 'release-submit':
                if input('Close any open application and verify that nothing was submitted. Type the job ID to release: ') != args.job_id:
                    parser.error('Job ID did not match.')
                try:
                    release_submission(con, args.job_id)
                except ValueError as error:
                    parser.error(str(error))
                print('Submission hold released.')
                return

            core.refresh_eligibility(con, cfg)
            job = con.execute('SELECT * FROM jobs WHERE id=?', (args.job_id,)).fetchone()
            if job is None or not job['eligible'] or not official_job_url(job):
                parser.error('Select an eligible, direct Greenhouse or Lever listing.')
            if job['status'] in {'submitted', 'submission_pending'}:
                parser.error('This listing is already submitted or pending confirmation.')
            print(f'{job["title"]} | {job["company"]} | {job["url"]}')
            if args.prefill:
                print('Prefill will enter saved contact details on this employer’s live page.')
            if args.prefill_verified:
                print('Prefill will select matching verified eligibility and explicitly saved personal choices on this employer’s live page.')
            attachment = None
            if args.attach_resume is not None:
                attachment = resume_file({'profile': {'resume_path': str(args.attach_resume.resolve())}})
                if attachment is None:
                    parser.error('Select an existing resume file in a supported format.')
                print(f'Attaching {attachment.name} may upload the file before you click Submit.')
            if input('Type the job ID to open this form for manual submission: ') != args.job_id:
                parser.error('Job ID did not match.')
            try:
                outcome = review_submission(con, job, cfg if args.prefill else None, attachment,
                                            cfg if args.prefill_verified else None, args.reuse_session)
            except ValueError as error:
                parser.error(str(error))
            print('Employer receipt recorded.' if outcome == 'submitted' else
                  'Submission unconfirmed. The job is on hold until you verify the result.')
            return
        if args.command == 'receipt':
            try:
                confirmation, _ = read_receipt(args.confirmation)
                created = record_receipt(con, args.job_id, confirmation)
            except (OSError, ValueError) as error:
                parser.error(str(error))
            print('Employer receipt recorded.' if created else 'This receipt is already recorded.')
            return
        if args.command == 'tailor':
            job = con.execute('SELECT * FROM jobs WHERE id=?', (args.job_id,)).fetchone()
            if job is None:
                parser.error('Job ID not found.')
            source = resume_file(cfg)
            if source is None:
                parser.error('Set a valid local resume path first.')
            try:
                destination, order = write_preview(source, job)
            except (OSError, ValueError) as error:
                parser.error(str(error))
            print(f'Local preview: {destination}')
            print('Section order: ' + ', '.join(order))
            return
        if args.command == 'status':
            for row in con.execute('SELECT status, COUNT(*) AS count FROM jobs GROUP BY status'):
                print(f'{row["status"]} | {row["count"]}')
            return
        if args.command == 'logs':
            for row in con.execute('SELECT * FROM attempts ORDER BY id DESC LIMIT ?', (args.limit,)):
                print(f'{row["at"]} | {row["job_id"]} | {row["outcome"]} | {row["details"]}')
            return

        core.refresh_eligibility(con, cfg)
        if args.command == 'list':
            filters = '' if args.all else 'WHERE eligible=1'
            sql = f'SELECT * FROM jobs {filters} ORDER BY score DESC, id LIMIT ?'
            for row in con.execute(sql, (args.limit,)):
                print(f'{row["id"]} | {row["score"]} | {row["status"]} | '
                      f'{row["title"]} | {row["company"]} | {row["location"]} | {row["reason"]}')
            return
        if args.command == 'apply':
            if args.resume is not None:
                cfg['profile']['resume_path'] = str(args.resume.resolve())
                if resume_file(cfg) is None:
                    parser.error('Select an existing resume file in a supported format.')
            job = con.execute('SELECT * FROM jobs WHERE id=?', (args.job_id,)).fetchone()
            if job is None:
                parser.error('Job ID not found.')
            if job['status'] == 'submitted':
                parser.error('This job was previously submitted.')
            if job['status'] == 'submission_pending':
                parser.error('This job has an unresolved submission. Check the employer first.')
            if not job['eligible']:
                parser.error(job['reason'])
    if dry_run(job, cfg) == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
