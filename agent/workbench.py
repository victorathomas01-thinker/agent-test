"""Persistent dashboard selections and recoverable offline preparation."""

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone

from . import core
from .browser import resume_file, run_browser
from .packages import prepare_package
from .priority import classify, rank_job
from .posting_freshness import risk_reasons, observation_day
from .official_recheck import target_for
from .form_diagnostics import readiness_for_attempt

UNCERTAIN = {
    'Location missing — review', 'Location outside preferred area — review',
    'May require completed degree — manually review', 'Below match threshold',
    'Prior internship experience required — confirm verified evidence',
    'Graduation relative to internship end — confirm dates',
    'Continued enrollment after internship — verify dates',
    'Restricted to prior company interns — verify status',
    'Mixed required/preferred GPA language — manually review',
    'Mixed required/preferred graduation language — manually review',
}


def can_override(job):
    return bool(job['reason']) and not job['eligible'] and set(job['reason'].split('; ')) <= UNCERTAIN


def override_job(job_id, enabled):
    with closing(core.connect()) as con, con:
        row = con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None or (enabled and not can_override(row)):
            raise ValueError('Only uncertain eligibility classifications can be overridden.')
        if enabled:
            con.execute('INSERT OR REPLACE INTO eligibility_overrides VALUES (?, ?)', (job_id, core.utc_now()))
        else:
            con.execute('DELETE FROM eligibility_overrides WHERE job_id=?', (job_id,))

def select_jobs(ids, selected):
    with closing(core.connect()) as con, con:
        for job_id in ids:
            if selected:
                con.execute("""INSERT OR IGNORE INTO selections(job_id,status,updated_at)
                               SELECT id,'selected',? FROM jobs WHERE id=?""", (core.utc_now(), job_id))
            else:
                con.execute("DELETE FROM selections WHERE job_id=? AND status!='preparing'", (job_id,))


def claim_selected(con):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec='seconds')
    with con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("""UPDATE selections SET status=CASE WHEN attempts<2 THEN 'queued' ELSE 'needs_attention' END,
                       blocker='Previous preparation was interrupted.', updated_at=?
                       WHERE status='preparing' AND updated_at<?""", (core.utc_now(), cutoff))
        job = con.execute("""SELECT j.* FROM selections s JOIN jobs j ON j.id=s.job_id
                             WHERE s.status='queued' ORDER BY j.score DESC, j.id LIMIT 1""").fetchone()
        if job:
            con.execute("""UPDATE selections SET status='preparing', attempts=attempts+1, updated_at=?
                           WHERE job_id=?""", (core.utc_now(), job['id']))
        return job


def queue_selected():
    with closing(core.connect()) as con, con:
        con.execute("""UPDATE selections SET status='queued', updated_at=?, attempts=0
                       WHERE status IN ('selected','needs_attention')""", (core.utc_now(),))


def preview_freshness_blocker(con, job):
    """Require source review before packaging a previously selected listing.

    Selection/eligibility can predate a later deadline or a stale source.
    This performs no employer requests and never claims a listing is closed.
    """
    metadata = con.execute(
        "SELECT deadline FROM web_checks WHERE job_id=?", (job['id'],)
    ).fetchone()
    candidate = dict(job)
    candidate['deadline'] = metadata['deadline'] if metadata else ''
    reasons = risk_reasons(candidate)
    if (candidate.get('source') not in (None, '', 'manual')
            and observation_day(candidate.get('last_seen')) is None):
        reasons.append('Missing dated source observation — verify employer posting')
    return '; '.join(reasons)


def prepare_selected(cfg):
    with closing(core.connect()) as con:
        while (job := claim_selected(con)) is not None:
            blocker, version, status = '', '', 'needs_attention'
            try:
                if job['submitted_at'] or job['status'] in {'submitted','submission_pending','expired','rejected','withdrawn'}:
                    blocker = 'This listing is closed, submitted, or has an unresolved submission.'
                elif not job['eligible'] and not (
                    can_override(job) and con.execute('SELECT 1 FROM eligibility_overrides WHERE job_id=?',
                                                     (job['id'],)).fetchone()
                ):
                    blocker = job['reason'] or 'Eligibility needs review.'
                elif (freshness_blocker := preview_freshness_blocker(con, job)):
                    blocker = 'Source recheck required before preview: ' + freshness_blocker
                else:
                    folder, version = prepare_package(resume_file(cfg), dict(job))
                    master = folder / ('master' + resume_file(cfg).suffix.lower())
                    preview_cfg = {**cfg, 'profile': {**cfg['profile'], 'resume_path': str(master)},
                                   'automation': {**cfg['automation'], 'headless': True}}
                    with con:
                        con.execute('INSERT OR IGNORE INTO packages VALUES (?, ?, ?, ?)',
                                    (job['id'], version, core.utc_now(), str(folder.relative_to(core.ROOT))))
                    outcome, details = run_browser(dict(job), preview_cfg)
                    if outcome == 'prepared':
                        status = 'offline_preview'
                    else:
                        blocker = 'Review required fields or site access.' if outcome == 'needs_review' else outcome
                        if details == 'Sign-in needed.':
                            blocker = details
            except Exception as error:
                blocker = f'Preparation failed ({type(error).__name__}).'
            with con:
                con.execute("""UPDATE selections SET status=?, blocker=?, version=?, updated_at=?
                               WHERE job_id=?""", (status, blocker, version, core.utc_now(), job['id']))


def all_jobs(con, cfg=None):
    """Build the local dashboard model without making any employer requests."""
    cfg = cfg if cfg is not None else core.with_defaults({})
    rows = con.execute("""SELECT j.id,j.title,j.company,j.location,j.url,j.score,j.eligible,j.reason,
                               j.status,j.source,j.last_seen,j.submitted_at,j.description,
                               d.salary,d.published_at,d.workplace,d.employment_type,
                               w.deadline,w.verification,
                               s.status AS preparation,s.blocker,s.version,o.job_id AS override_id
                        FROM jobs j LEFT JOIN job_details d ON j.id=d.job_id
                        LEFT JOIN web_checks w ON w.job_id=j.id
                        LEFT JOIN selections s ON s.job_id=j.id
                        LEFT JOIN eligibility_overrides o ON o.job_id=j.id
                        ORDER BY j.score DESC,j.id""")
    # One latest historical attempt per job. Read-only, no applicant data or
    # employer requests; score only the detached preview's current step.
    attempts = {
        row['job_id']: readiness_for_attempt(row['outcome'], row['details'])
        for row in con.execute("""SELECT a.job_id, a.outcome, a.details
            FROM attempts a JOIN (
                SELECT job_id, MAX(id) AS latest_id FROM attempts GROUP BY job_id
            ) recent ON a.id=recent.latest_id
            WHERE a.outcome IN ('prepared','needs_review','failed','expired')""")
    }
    jobs = []
    for row in rows:
        job = dict(row)
        job['offline_readiness'] = attempts.get(job['id'], {
            'score': None, 'tier': 'not_assessed',
            'manual_fields': None, 'high_effort_fields': None,
        })
        job['category'], job['category_priority'] = classify(job['title'])
        job['can_override'] = can_override(job)
        job['override'] = bool(job.pop('override_id')) and job['can_override']
        job['bridge_score'] = rank_job(job)['bridge_score'] if job['category'] == 'Bridge employment' else None
        closed = job['status'] in {
            'expired', 'submitted', 'submission_pending', 'assessment', 'interview',
            'offer', 'rejected', 'withdrawn'
        } or bool(job['submitted_at'])
        reasons = risk_reasons(job) if not closed else []
        if (not closed and job['source'] in {'greenhouse', 'lever'}
                and observation_day(job['last_seen']) is None):
            reasons.append('Missing dated ATS observation — recheck source')
        job['recheck_reasons'] = reasons
        job['recheck_status'] = ('not_applicable' if closed else
                                 'needs_recheck' if reasons else 'recent_observation')
        job['can_recheck'] = bool(not closed and target_for(job, cfg))
        job.pop('description')
        job['url'] = job['url'] if core.valid_application_url(job['url'] or '') else ''
        jobs.append(job)
    return jobs


def explain_job(con, job_id, cfg):
    row = con.execute("""SELECT j.*, d.salary,d.workplace,d.employment_type
                         FROM jobs j LEFT JOIN job_details d ON j.id=d.job_id WHERE j.id=?""",
                      (job_id,)).fetchone()
    if row is None:
        return None
    job = dict(row)
    ranking = rank_job(job, cfg.get('_candidate_evidence', ''))
    ranking['eligibility'] = job['reason'] or 'No blocker identified.'
    ranking['review'] = []
    try:
        notes = json.loads(job['notes'])
        ranking['review'] = [item['field'] for item in notes.get('unresolved', [])
                             if item.get('required') and isinstance(item.get('field'), str)]
    except (ValueError, TypeError, AttributeError):
        pass
    return ranking
