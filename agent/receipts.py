"""Match user-supplied confirmation text to a job without retaining the text."""

import re
import unicodedata
from hashlib import sha256

from .core import record_attempt, utc_now

CONFIRMATION = re.compile(
    r'(?:^|[.!?]\s+|\n)\s*(?:'
    r'(?:thank you|thanks) for applying\b|'
    r'(?:we (?:have |successfully )?received|we[’\x27]ve received) your application\b|'
    r'your application (?:has been |was )(?:successfully )?(?:received|submitted)\b'
    r')',
    re.IGNORECASE,
)


def normalized(text):
    words = re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold())
    return ' '.join(words)


def contains_name(text, name):
    return bool(name) and f' {name} ' in f' {text} '


def receipt_fingerprint(text, job):
    if not CONFIRMATION.search(text):
        raise ValueError('The receipt needs an explicit acknowledgment of a received application.')
    searchable = normalized(text)
    company = normalized(job['company'] or '')
    title = normalized(job['title'] or '')
    if not contains_name(searchable, title) or not contains_name(searchable, company):
        raise ValueError('The receipt needs the same employer and job title as the stored listing.')
    canonical = ' '.join(unicodedata.normalize('NFKC', text).casefold().split())
    return sha256(canonical.encode()).hexdigest()


def record_receipt(con, job_id, text, *, details='Matched a user-provided employer receipt.'):
    with con:
        con.execute('BEGIN IMMEDIATE')
        job = con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if job is None:
            raise ValueError('Job ID not found.')
        fingerprint = receipt_fingerprint(text, job)
        existing = con.execute(
            'SELECT job_id, fingerprint FROM receipts WHERE job_id=? OR fingerprint=?',
            (job_id, fingerprint),
        ).fetchall()
        if existing:
            if len(existing) == 1 and (existing[0]['job_id'], existing[0]['fingerprint']) == (job_id, fingerprint):
                return False
            raise ValueError('A receipt is already associated with this job or another listing.')
        if job['status'] == 'submitted':
            raise ValueError('This listing is already marked submitted.')
        recorded_at = utc_now()
        con.execute('INSERT INTO receipts(job_id, fingerprint, recorded_at) VALUES (?, ?, ?)',
                    (job_id, fingerprint, recorded_at))
        record_attempt(con, job_id, 'submitted', details)
        return True
