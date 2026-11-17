"""Generate an offline dashboard from synthetic data or a local SQLite database."""

import argparse
from contextlib import closing
from html import escape
from pathlib import Path
import sqlite3

from . import core
from .storage import review_jobs

DEMO_JOBS = (
    ('Software engineering intern', 'Sample employer A', 'Charlotte, NC', 68, 1, 'prepared', ''),
    ('Data analyst intern', 'Sample employer B', 'Remote US', 58, 1, 'found', ''),
    ('Senior backend engineer', 'Sample employer C', 'Remote UK', 10, 0, 'found',
     'Senior-level title; Location outside preferred area'),
    ('Implementation associate', 'Sample employer D', 'Charlotte, NC', 65, 1,
     'submission_pending', ''),
)


def is_review_job(eligible, status):
    return status == 'submission_pending' or (
        eligible and status in {'prepared', 'needs_review', 'failed'}
    )


def load_jobs(database, *, include_id=False, review=False, limit=-1):
    fields = ('title', 'company', 'location', 'score', 'eligible', 'status', 'reason')
    if include_id:
        fields = ('id', *fields)
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        if review:
            con.row_factory = sqlite3.Row
            return [tuple(row[field] for field in fields) for row in review_jobs(con, limit)]
        columns = ', '.join(fields)
        return con.execute(f'SELECT {columns} FROM jobs ORDER BY score DESC, id LIMIT ?', (limit,)).fetchall()


def render_dashboard(jobs, *, demo, interactive=False):
    rows = []
    waiting = 0
    for row in jobs:
        job_id = row[0] if interactive else None
        title, company, location, score, eligible, status, reason = row[1:] if interactive else row
        needs_review = is_review_job(eligible, status)
        waiting += bool(needs_review)
        values = (title, company, location, score, 'Eligible' if eligible else 'Review',
                  status, reason or '—', 'Yes' if needs_review else '—')
        if interactive:
            values = (job_id, *values)
        rows.append('<tr>' + ''.join(f'<td>{escape(str(value))}</td>' for value in values) + '</tr>')
    source = 'Synthetic portfolio demo' if demo else 'Private local jobs'
    if not demo and not interactive:
        source += ' snapshot'
    headers = ('Role', 'Company', 'Location', 'Score', 'Eligibility', 'Status', 'Reason', 'Review queue')
    nav = ''
    if interactive:
        headers = ('Job ID', *headers)
        nav = '<nav aria-label="Job views"><a href="/">All jobs</a> · <a href="/?view=review">Review queue</a></nav>\n<p>Use the job ID with <code>main.py apply JOB_ID</code> for a rehearsal or <code>main.py queue</code> for review details and follow-up.</p>'
    header = ''.join(f'<th scope="col">{name}</th>' for name in headers)
    body = ''.join(rows) or f'<tr><td colspan="{len(headers)}">No matching jobs.</td></tr>'
    return f'''<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Personal Job Agent dashboard</title>
<style>
body {{ font: 1rem/1.55 system-ui, sans-serif; margin: 2rem auto; max-width: 74rem; padding: 0 1rem; color: #18253a; }}
section {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ padding: .75rem; border-bottom: 1px solid #ccd5e0; text-align: left; }}
th {{ background: #e9eff6; }}
</style>
<main>
<h1>Personal Job Agent</h1>
<p>{source} · {len(rows)} jobs · {waiting} waiting for review</p>
{nav}
<section aria-label="Ranked jobs">
<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>
</section>
</main>
</html>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Read the local job database.')
    args = parser.parse_args()
    try:
        jobs = load_jobs(core.DB) if args.live else DEMO_JOBS
    except sqlite3.Error as error:
        parser.exit(1, f'Could not read the job database: {error}\n')
    destination = core.ROOT / 'private' / 'dashboard' / ('jobs.html' if args.live else 'demo.html')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_dashboard(jobs, demo=not args.live), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
