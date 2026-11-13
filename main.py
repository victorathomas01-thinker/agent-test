#!/usr/bin/env python3
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import sys

from agent import core
from agent import source_health
from agent import form_diagnostics
from agent import pilot_audit
from agent import local_safety
from agent import posting_freshness
from agent import requirement_benchmark
from agent.browser import resume_file, run_browser
from agent.receipts import read_receipt, record_receipt, scan_receipts
from agent.rehearsal import run_rehearsal
from agent.resume import read_resume, write_preview
from agent.matching import STRATEGIES, fit_signals
from agent.operations import run_record, track_application, write_dashboard
from agent.packages import prepare_package
from agent.sessions import sign_in
from agent.submission import official_job_url, release_submission, review_submission
from agent.dashboard import serve
from agent.careers import discover_sites
from agent.workday import select_workday_sources
from agent.facts import effective_answers, revoke_fact, store_fact, sync_config_facts
from agent.live_workbench import available_jobs, review_tabs


def positive_integer(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('Enter a positive integer.')
    return number


def discover_jobs(cfg, summary=None):
    started = core.utc_now()
    coverage, source_checks = [], []
    jobs, errors = core.discover(cfg, coverage, source_checks)
    new = core.store_jobs(jobs, cfg)
    expired = core.expire_unlisted(coverage, jobs, started)
    audit_id = source_health.record(source_checks, started)
    employers = len({job['id'].rsplit(':', 1)[0] for job in jobs})
    statuses = {status: sum(row['status'] == status for row in source_checks)
                for status in sorted({row['status'] for row in source_checks})}
    if summary is not None:
        summary.update(postings=len(jobs), new=new, boards=employers, expired=expired,
                       source_errors=errors, source_coverage=statuses, coverage_run=audit_id)
    print(f'Fetched {len(jobs)} listings from {employers} employer boards, {new} new.')
    print(f'Source audit #{audit_id}: '
          + ', '.join(f'{key}={count}' for key, count in statuses.items())
          + '. Run coverage for details.')
    if expired:
        print(f'{expired} listings are no longer shown on complete public boards.')
    for error in errors:
        print('SOURCE ERROR', error)
    if errors and not jobs:
        raise SystemExit(1)


def dry_run(job, cfg):
    outcome, details = run_browser(dict(job), cfg)
    print(f'{job["id"]} | {outcome} | {details}')
    return outcome


def package_for(con, job, cfg, cover=False):
    folder, version = prepare_package(resume_file(cfg), dict(job), cover=cover)
    with con:
        con.execute('INSERT OR IGNORE INTO packages VALUES (?, ?, ?, ?)',
                    (job['id'], version, core.utc_now(), str(folder.relative_to(core.ROOT))))
    return folder


def run_batch(cfg, limit, fresh_since, summary=None):
    outcomes = {'prepared': 0, 'needs_review': 0, 'expired': 0, 'failed': 0}
    if summary is not None:
        summary['outcomes'] = outcomes
        summary['packages'] = 0
    daily_limit = positive_integer(cfg['preferences']['max_previews_per_day'])
    with closing(core.connect()) as con:
        core.refresh_eligibility(con, cfg)
        for _ in range(limit):
            job = core.claim_preview(con, daily_limit, fresh_since)
            if job is None:
                break
            preview_cfg = cfg
            if summary is not None:
                try:
                    folder = package_for(con, job, cfg)
                    master = folder / ('master' + resume_file(cfg).suffix.lower())
                    preview_cfg = {**cfg, 'profile': {**cfg['profile'], 'resume_path': str(master)}}
                except (OSError, ValueError) as error:
                    details = 'Application package needs review (' + type(error).__name__ + ').'
                    core.add_attempt(job['id'], 'needs_review', details)
                    print(f'{job["id"]} | needs_review | {details}')
                    outcomes['needs_review'] += 1
                    continue
                summary['packages'] += 1
            outcomes[dry_run(job, preview_cfg)] += 1
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
    doctor = commands.add_parser('doctor', help='Inspect local schema and config without migrating.')
    doctor.add_argument('--database', type=Path, default=core.DB)
    doctor.add_argument('--backup', action='store_true',
                        help='Create a verified SQLite snapshot under gitignored private/backups.')
    for name in ('discover', 'status', 'answers'):
        commands.add_parser(name)
    facts = commands.add_parser('facts', help='Inspect or revoke verified facts.')
    facts.add_argument('--revoke')
    logs = commands.add_parser('logs')
    logs.add_argument('--limit', type=positive_integer, default=20)
    receipt = commands.add_parser('receipt', help='Record a locally saved employer confirmation.')
    receipt.add_argument('job_id')
    receipt.add_argument('confirmation', type=Path, help='A UTF-8 confirmation or an exported .eml receipt.')
    commands.add_parser('scan-receipts', help='Match files from the local receipt inbox to pending jobs.')
    queue = commands.add_parser('queue', help='Show previews and submissions that need your review.')
    queue.add_argument('--limit', type=positive_integer, default=20)
    coverage_cmd = commands.add_parser('coverage', help='Inspect the last local discovery source audit.')
    coverage_cmd.add_argument('--limit', type=positive_integer, default=50)
    form_audit = commands.add_parser('form-audit', help='Summarize unresolved offline form blockers.')
    form_audit.add_argument('--limit', type=positive_integer, default=500)
    commands.add_parser('posting-audit', help='Summarize deadlines and stale sources without applicant details.')
    historical = commands.add_parser('pilot-audit',
        help='Analyze historical offline attempts from an existing local database, read-only.')
    historical.add_argument('--database', type=Path, default=core.DB)
    historical.add_argument('--since', metavar='YYYY-MM-DD')
    historical.add_argument('--through', metavar='YYYY-MM-DD')
    historical.add_argument('--limit', type=positive_integer, default=20)
    historical.add_argument('--expected', type=positive_integer, default=20)
    historical.add_argument('--offline-only', action='store_true',
                            help='Reconstruct detached previews, ignoring later non-preview attempts.')
    commands.add_parser('benchmark-requirements',
        help='Run source-linked fictional-profile eligibility regression checks.')
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
    listings.add_argument('--strategy', choices=STRATEGIES)
    commands.add_parser('import').add_argument('csv', type=Path)
    apply = commands.add_parser('apply')
    apply.add_argument('job_id')
    apply.add_argument('--resume', type=Path, help='Use a reviewed local resume for this dry run.')
    apply.add_argument('--live', action='store_true', help=argparse.SUPPRESS)
    tailor = commands.add_parser('tailor', help='Create a local role-specific resume preview.')
    tailor.add_argument('job_id')
    package = commands.add_parser('package', help='Build a private versioned application package.')
    package.add_argument('job_id')
    package.add_argument('--cover-letter', action='store_true')
    explain = commands.add_parser('explain', help='Show eligibility and ranking signals for a listing.')
    explain.add_argument('job_id')
    explain.add_argument('--strategy', choices=STRATEGIES)
    commands.add_parser('dashboard', help='Generate a local review dashboard.')
    web = commands.add_parser('discover-web', help='Discover jobs on configured public employer websites.')
    web.add_argument('--sources', type=Path, default=core.ROOT / 'examples' / 'careers.json')
    web.add_argument('--budget', type=positive_integer, default=10)
    workday = commands.add_parser('discover-workday',
        help='Read a bounded, opt-in public Workday employer source bank.')
    workday.add_argument('--sources', type=Path,
        default=core.ROOT / 'examples' / 'charlotte_workday_sites.json')
    workday.add_argument('--max-sites', type=positive_integer, default=3)
    workday.add_argument('--per-site', type=positive_integer, default=15)
    dashboard = commands.add_parser('serve', help='Open the interactive local dashboard server.')
    dashboard.add_argument('--port', type=int, default=0)
    tabs = commands.add_parser('review-selected', help='Open a specifically approved batch in Microsoft Edge.')
    tabs.add_argument('--limit', type=positive_integer, default=5)
    tabs.add_argument('--attach-master', action='store_true')
    commands.add_parser('health', help='Check the local database and master resume.')
    track = commands.add_parser('track', help='Record an outcome or follow-up for a confirmed application.')
    track.add_argument('job_id')
    track.add_argument('--status', choices=('assessment', 'interview', 'offer', 'rejected', 'withdrawn'))
    track.add_argument('--followup', metavar='YYYY-MM-DD')
    batch = commands.add_parser('batch')
    batch.add_argument('--limit', type=positive_integer)
    batch.add_argument('--live', action='store_true', help=argparse.SUPPRESS)
    unattended = commands.add_parser('run', help='Discover jobs and preview eligible new listings.')
    unattended.add_argument('--limit', type=positive_integer)
    unattended.add_argument('--strategy', choices=STRATEGIES)
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

    if args.command == 'doctor':
        result = local_safety.inspect(args.database)
        saved = None
        if args.backup:
            if result['database'] not in ('ready', 'upgradeable'):
                parser.error('Existing database is missing, incompatible or failed integrity checks.')
            try:
                saved = local_safety.backup_local(args.database)
            except (OSError, ValueError, sqlite3.Error):
                parser.error('Unable to create a verified private SQLite backup.')
        local_safety.report(result, saved)
        if result['database'] not in ('ready', 'upgradeable') or result['config'] != 'valid':
            raise SystemExit(2)
        return

    if args.command == 'posting-audit':
        # Read-only like pilot-audit: never invoke core.connect() or
        # effective_answers(), both of which can update the local schema/facts.
        try:
            with closing(pilot_audit.open_readonly(core.DB)) as con:
                totals = posting_freshness.aggregate(con)
        except (OSError, ValueError, sqlite3.Error):
            parser.error('Posting audit requires an existing compatible local database. Run doctor first.')
        print('Unsubmitted job records:', totals['active_or_unconfirmed'])
        print('Explicitly passed deadline, recheck required:', totals['passed_deadline'])
        print('Source not seen in over 14 days:', totals['stale_source'])
        print('Conflicting explicit closing dates:', totals['conflicting_deadline'])
        print('Public records with no dated observation:', totals['missing_source_timestamp'])
        print('These are review warnings, not independently verified job closures.')
        return

    if args.command == 'pilot-audit':
        try:
            with closing(pilot_audit.open_readonly(args.database)) as con:
                rows = pilot_audit.selected_attempts(con, args.since, args.through,
                                                    args.limit, offline_only=args.offline_only)
                report = pilot_audit.summarize(rows, args.expected)
            pilot_audit.render(report, args.since, args.through,
                               offline_only=args.offline_only)
        except (OSError, ValueError) as error:
            parser.error('Pilot audit unavailable (' + type(error).__name__ +
                         '). Check database path and date range.')
        return
    if args.command == 'benchmark-requirements':
        raise SystemExit(requirement_benchmark.main())
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
    if getattr(args, 'strategy', None):
        cfg['preferences']['strategy'] = args.strategy
    if args.command in {'discover', 'discover-web', 'discover-workday', 'run', 'list', 'batch', 'queue', 'dashboard', 'serve', 'explain'}:
        evidence = cfg.get('_candidate_profile', {})
        cfg['_candidate_evidence'] = ' '.join(evidence.get('skills', []) + evidence.get('projects', []))
        source = resume_file(cfg)
        if source:
            try:
                cfg['_candidate_evidence'] += '\n' + read_resume(source)
            except (OSError, ValueError):
                print('Master resume could not be read for ranking. Using posting-based ranking.')
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
        if args.key in cfg['verified_answers']:
            with closing(core.connect()) as con, con:
                store_fact(con, args.key, cfg['verified_answers'][args.key], 'applicant confirmation')
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
        with closing(core.connect()) as con, con:
            store_fact(con, 'question:' + question, args.answer.strip() or None, 'applicant confirmation')
        print('Verified question memory updated.')
        return
    if args.command == 'facts':
        sync_config_facts(cfg)
        with closing(core.connect()) as con, con:
            if args.revoke:
                if not revoke_fact(con, args.revoke):
                    parser.error('No active fact with that key.')
                print('Fact revoked.')
            else:
                for row in con.execute('SELECT * FROM verified_facts ORDER BY key'):
                    status = row['value'] if row['active'] else 'revoked'
                    print(f'{row["key"]} | {status} | {row["scope"]} | {row["source"]} | {row["verified_at"]}')
        return
    cfg = effective_answers(cfg)
    if args.command == 'answers':
        for key, value in cfg['verified_answers'].items():
            print(f'{key} | {value if value is not None else "NOT SET"}')
        print(f'{len(cfg["verified_questions"])} exact questions remembered.')
        return
    if args.command == 'discover':
        discover_jobs(cfg)
        return
    if args.command == 'coverage':
        source_health.print_latest(min(args.limit, 500))
        return
    if args.command == 'form-audit':
        form_diagnostics.print_report(min(args.limit, 5000))
        return
    if args.command == 'discover-workday':
        if args.max_sites > 50 or args.per_site > 60:
            parser.error('At most 50 Workday sites and 60 listings per site are supported.')
        try:
            sources = json.loads(args.sources.read_text(encoding='utf-8-sig'))
            sites = select_workday_sources(sources, args.max_sites)
        except (OSError, ValueError) as error:
            parser.error('Could not load validated Workday sources (' + type(error).__name__ + ').')
        if not sites:
            print('No Workday career sites selected; no requests made.')
            return
        print(f'Read-only public Workday discovery: {len(sites)} sources, '
              f'up to {args.per_site} stored listings per source.')
        selected_discovery = {
            **cfg['discovery'],
            'greenhouse_boards': [], 'lever_sites': [], 'ashby_boards': [],
            'smartrecruiters_companies': [], 'employer_feeds': [],
            'career_sites': [], 'max_discovered_boards': 0,
            'workday_sites': sites,
            'max_workday_per_site': args.per_site,
        }
        discover_jobs({**cfg, 'discovery': selected_discovery})
        return
    if args.command == 'discover-web':
        seeds = json.loads(args.sources.read_text(encoding='utf-8-sig'))
        checks = []
        started = core.utc_now()
        jobs, errors = discover_sites(seeds, min(args.budget, 100), core.plain, report=checks)
        new = core.store_jobs(jobs, cfg)
        audit_id = source_health.record(checks, started)
        print(f'Employer site discovery | {len(jobs)} listings | {new} new | source audit #{audit_id}')
        for error in errors:
            print(f'SOURCE ERROR {error}')
        if errors and not jobs:
            raise SystemExit(1)
        return
    if args.command == 'serve':
        if not 0 <= args.port <= 65535:
            parser.error('Port must be between 0 and 65535.')
        with closing(core.connect()) as con:
            core.refresh_eligibility(con, cfg)
        serve(cfg, args.port)
        return
    if args.command == 'review-selected':
        if cfg['automation'].get('allow_live_submit') is not True or not sys.stdin.isatty():
            parser.error('Enable attended mode locally and use an interactive terminal.')
        with closing(core.connect()) as con:
            core.refresh_eligibility(con, cfg)
            jobs = available_jobs(con, min(args.limit, 10))
        if not jobs:
            parser.error('Prepare selected supported listings offline first.')
        for job in jobs:
            print(f'{job["title"]} | {job["company"]} | {job["url"]}')
        print('Edge will enter your saved contact and verified answers on these employer pages.')
        if args.attach_master:
            print('The approved package master resume may upload before you click Submit.')
        if input('Type PREPARE to approve exactly these postings: ') != 'PREPARE':
            parser.error('Batch approval was not entered.')
        review_tabs(jobs, cfg, args.attach_master)
        return
    if args.command in {'batch', 'run'}:
        maximum = positive_integer(cfg['preferences']['max_applications_per_run'])
        limit = min(args.limit or maximum, maximum)
        if args.command == 'run':
            with run_record() as summary:
                with closing(core.connect()) as con:
                    scan_local_receipts(con)
                fresh_since = core.utc_now()
                discover_jobs(cfg, summary)
                cfg['automation']['headless'] = True
                run_batch(cfg, limit, fresh_since, summary)
        else:
            run_batch(cfg, limit, None)
        return
    if args.command == 'import':
        print(f'Imported {core.import_urls(args.csv, cfg)} new jobs.')
        return

    with closing(core.connect()) as con:
        if args.command == 'explain':
            row = con.execute("""SELECT j.*, COALESCE(d.workplace,'') AS workplace,
                                 COALESCE(d.employment_type,'') AS employment_type, d.salary, d.published_at
                                 , COALESCE(w.deadline,'') AS deadline, w.verification
                                 FROM jobs j LEFT JOIN job_details d ON d.job_id=j.id
                                 LEFT JOIN web_checks w ON w.job_id=j.id WHERE j.id=?""",
                              (args.job_id,)).fetchone()
            if row is None:
                parser.error('Job ID not found.')
            job = dict(row)
            score, eligible, blockers = core.evaluate(job, cfg)
            _, reasons = fit_signals(job, cfg)
            print(f'{job["title"]} | {"eligible" if eligible else "review or excluded"} | priority {score}')
            for reason in [blockers, *reasons, job['salary'] or '']:
                if reason:
                    print(f'- {reason}')
            return
        if args.command == 'track':
            if not args.status and not args.followup:
                parser.error('Provide a status or follow-up date.')
            try:
                track_application(con, args.job_id, args.status, args.followup)
            except ValueError as error:
                parser.error(str(error))
            print('Application tracking updated.')
            return
        if args.command == 'health':
            integrity = con.execute('PRAGMA quick_check').fetchone()[0]
            print(f'Database | {integrity}')
            print(f'Master resume | {"available" if resume_file(cfg) else "missing"}')
            if integrity != 'ok' or not resume_file(cfg):
                raise SystemExit(1)
            return
        if args.command == 'dashboard':
            core.refresh_eligibility(con, cfg)
            print(write_dashboard(con, cfg))
            return
        if args.command == 'package':
            job = con.execute("""SELECT j.*, COALESCE(w.deadline,'') AS deadline
                                 FROM jobs j LEFT JOIN web_checks w ON w.job_id=j.id
                                 WHERE j.id=?""", (args.job_id,)).fetchone()
            if job is None:
                parser.error('Job ID not found.')
            source_unverified = (job['source'] in {'greenhouse', 'lever'}
                                 and posting_freshness.observation_day(job['last_seen']) is None)
            if job['status'] == 'expired' or source_unverified or posting_freshness.risk_reasons(dict(job)):
                parser.error('Posting deadline or freshness needs verification before creating a new package.')
            try:
                print(package_for(con, job, cfg, args.cover_letter))
            except (OSError, ValueError) as error:
                parser.error(str(error))
            return
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
            if job['submitted_at'] or job['status'] in {'submitted', 'submission_pending'}:
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
            if job['submitted_at'] or job['status'] == 'submitted':
                parser.error('This job was previously submitted.')
            if job['status'] == 'submission_pending':
                parser.error('This job has an unresolved submission. Check the employer first.')
            if not job['eligible']:
                parser.error(job['reason'])
    if dry_run(job, cfg) == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
