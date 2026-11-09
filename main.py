#!/usr/bin/env python3
import argparse
from contextlib import closing
import json
from pathlib import Path

from agent import core
from agent.browser import run_browser


def positive_integer(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('Enter a positive integer.')
    return number


def main():
    parser = argparse.ArgumentParser(description='Personal job application agent (dry run only)')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--from-mvp', type=Path, metavar='CONFIG')
    for name in ('discover', 'status', 'answers'):
        commands.add_parser(name)
    logs = commands.add_parser('logs')
    logs.add_argument('--limit', type=positive_integer, default=20)
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
    apply.add_argument('--live', action='store_true', help=argparse.SUPPRESS)
    batch = commands.add_parser('batch')
    batch.add_argument('--limit', type=positive_integer)
    batch.add_argument('--live', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if getattr(args, 'live', False):
        parser.error('Live submission is disabled.')

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
        jobs, errors = core.discover(cfg)
        new = core.store_jobs(jobs, cfg)
        employers = len({job['id'].rsplit(':', 1)[0] for job in jobs})
        print(f'Fetched {len(jobs)} listings from {employers} employer boards, {new} new.')
        for error in errors:
            print('SOURCE ERROR', error)
        if errors and not jobs:
            raise SystemExit(1)
        return
    if args.command == 'import':
        print(f'Imported {core.import_urls(args.csv, cfg)} new jobs.')
        return

    with closing(core.connect()) as con:
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
            job = con.execute('SELECT * FROM jobs WHERE id=?', (args.job_id,)).fetchone()
            if job is None:
                parser.error('Job ID not found.')
            if job['status'] == 'submitted':
                parser.error('This job was previously submitted.')
            if not job['eligible']:
                parser.error(job['reason'])
            jobs = [job]
        else:
            maximum = positive_integer(cfg['preferences']['max_applications_per_run'])
            limit = min(args.limit or maximum, maximum)
            jobs = list(con.execute(
                "SELECT * FROM jobs WHERE eligible=1 AND status='found' ORDER BY score DESC, id LIMIT ?",
                (limit,),
            ))

    print(f'Processing {len(jobs)} job(s) in dry-run mode.')
    failed = False
    for job in jobs:
        outcome, details = run_browser(dict(job), cfg)
        print(f'{job["id"]} | {outcome} | {details}')
        failed |= outcome == 'failed'
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
