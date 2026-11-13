"""Persistent run summaries and a local, read-only review report."""

import html
import json
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import core
from .matching import fit_signals

TRACKING = {
    'submitted': {'assessment', 'interview', 'offer', 'rejected', 'withdrawn'},
    'assessment': {'interview', 'offer', 'rejected', 'withdrawn'},
    'interview': {'assessment', 'offer', 'rejected', 'withdrawn'},
    'offer': {'withdrawn'},
}


def track_application(con, job_id, status=None, followup=None):
    with con:
        con.execute('BEGIN IMMEDIATE')
        job = con.execute('SELECT status, submitted_at FROM jobs WHERE id=?', (job_id,)).fetchone()
        if job is None or not job['submitted_at']:
            raise ValueError('A confirmed submission is required before tracking later outcomes.')
        if status and status != job['status']:
            if status not in TRACKING.get(job['status'], ()):
                raise ValueError(f'Cannot move from {job["status"]} to {status}.')
            con.execute('UPDATE jobs SET status=? WHERE id=?', (status, job_id))
            con.execute('INSERT INTO attempts(job_id,at,outcome,details) VALUES (?, ?, ?, ?)',
                        (job_id, core.utc_now(), status, 'Applicant recorded the outcome.'))
        if followup:
            day = date.fromisoformat(followup).isoformat()
            con.execute('INSERT OR REPLACE INTO followups(job_id,due_on) VALUES (?, ?)', (job_id, day))
        if status in {'rejected', 'withdrawn'}:
            con.execute('DELETE FROM followups WHERE job_id=?', (job_id,))


@contextmanager
def run_record():
    with closing(core.connect()) as con, con:
        run_id = con.execute("INSERT INTO runs(started_at,status) VALUES (?,'running')",
                             (core.utc_now(),)).lastrowid
    details = {}
    status = 'complete'
    try:
        yield details
        if details.get('source_errors'):
            status = 'partial'
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        status = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed'
        details['failure'] = type(error).__name__
        raise
    finally:
        with closing(core.connect()) as con, con:
            con.execute('UPDATE runs SET finished_at=?, status=?, details=? WHERE id=?',
                        (core.utc_now(), status, json.dumps(details), run_id))


def write_dashboard(con, cfg):
    esc = lambda value: html.escape(str(value or ''), quote=True)
    jobs = con.execute("""SELECT j.*, d.salary, f.due_on, COALESCE(d.workplace, '') AS workplace,
                                (SELECT version FROM packages WHERE job_id=j.id
                                 ORDER BY created_at DESC, rowid DESC LIMIT 1) AS package
                         FROM jobs j LEFT JOIN job_details d ON d.job_id=j.id
                         LEFT JOIN followups f ON f.job_id=j.id
                         WHERE j.status IN ('submitted','submission_pending','interview','assessment',
                                            'offer','rejected','withdrawn')
                            OR (j.eligible=1 AND j.status!='expired')
                         ORDER BY CASE j.status WHEN 'submission_pending' THEN 0 WHEN 'prepared' THEN 1
                                  WHEN 'needs_review' THEN 2 ELSE 3 END, j.score DESC LIMIT 80""")
    cards = []
    for row in jobs:
        job = dict(row)
        _, signals = fit_signals(job, cfg)
        link = (f'<a href="{esc(job["url"])}">Employer posting</a>'
                if core.valid_application_url(job['url'] or '') else '')
        details = ' · '.join(filter(None, [job['location'], job['workplace'], job['salary']]))
        if job['due_on']:
            details += ' · Follow-up ' + job['due_on']
        package = job['package']
        package_link = (f' · <a href="packages/{esc(package)}/manifest.json">Package manifest</a>'
                        if package and all(ch in '0123456789abcdef' for ch in package) else '')
        cards.append(f'<article><h2>{esc(job["title"])}</h2><p>{esc(job["company"])} · '
                     f'{esc(job["status"])} · Score {job["score"]}</p><p>{esc(details)}</p>'
                     f'<p>{esc(job["reason"] or " · ".join(signals))}</p><p>{link}{package_link}</p></article>')
    counts = con.execute('SELECT status, COUNT(*) AS total FROM jobs GROUP BY status ORDER BY status')
    totals = ' · '.join(f'{esc(row["status"])} {row["total"]}' for row in counts)
    latest = con.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone()
    run = (f'{esc(latest["status"])} · {esc(latest["started_at"])} · {esc(latest["details"])}'
           if latest else 'No recorded run.')
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Personal Job Agent</title><style>
body{{font:16px system-ui;margin:2rem auto;padding:0 1rem;max-width:56rem;color:#17233a;background:#f6f8fb}}
article{{background:white;border:1px solid #d6deea;border-radius:.5rem;padding:1rem;margin:.75rem 0}}
h2{{font-size:1.1rem;margin:0}} p{{margin:.55rem 0}} a{{color:#144893}}
</style><h1>Personal Job Agent</h1><p>{totals}</p><h2>Latest run</h2><p>{run}</p>
<h2>Review queue and opportunities</h2>{''.join(cards)}</html>'''
    folder = core.ROOT / 'private'
    folder.mkdir(exist_ok=True)
    target = folder / 'dashboard.html'
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                            suffix='.tmp', delete=False) as temporary:
        temporary.write(document)
    stage = Path(temporary.name)
    try:
        stage.replace(target)
    finally:
        stage.unlink(missing_ok=True)
    return target
