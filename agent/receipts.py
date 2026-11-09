"""Match user-supplied confirmation text to a job without retaining the text."""

import re
import unicodedata
from collections import Counter
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from hashlib import sha256
from urllib.parse import urlsplit

from .core import record_attempt, utc_now

CONFIRMATION = re.compile(
    r'(?:^|[.!?]\s+|\n)\s*(?:'
    r'(?:thank you|thanks) for applying\b|'
    r'(?:we (?:have |successfully )?received|we[’\x27]ve received) your application\b|'
    r'your application (?:has been |was )(?:successfully )?(?:received|submitted)\b'
    r')',
    re.IGNORECASE,
)
MAX_RECEIPT_BYTES = 1_000_000


def read_receipt(path):
    with path.open('rb') as file:
        raw = file.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError('Receipt is too large.')
    if path.suffix.casefold() != '.eml':
        return raw.decode('utf-8-sig'), None
    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = message.get_body(preferencelist=('plain',))
    if body is None:
        raise ValueError('Use a receipt with a plain-text message body.')
    lines = []
    for line in body.get_content().splitlines():
        if line.startswith(('-----Original Message-----', '---------- Forwarded message ---------')):
            break
        if not line.lstrip().startswith('>'):
            lines.append(line)
    try:
        sent = parsedate_to_datetime(str(message['Date']))
    except (TypeError, ValueError, OverflowError):
        sent = None
    return '\n'.join(lines), sent


def normalized(text):
    words = re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold())
    return ' '.join(words)


def contains_name(text, name):
    return bool(name) and f' {name} ' in f' {text} '


def mentions_posting(text, url):
    try:
        address = urlsplit(url or '')
    except ValueError:
        return False
    if not address.scheme or not address.netloc or not address.path:
        return False
    expected = address.scheme, address.netloc.casefold(), address.path.rstrip('/')
    for link in re.findall(r'https?://[^\s<>()\[\]"]+', text, re.IGNORECASE):
        try:
            candidate = urlsplit(link.rstrip('.,;'))
        except ValueError:
            continue
        if (candidate.scheme, candidate.netloc.casefold(), candidate.path.rstrip('/')) == expected:
            return True
    return False


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


def record_receipt(con, job_id, text, *, details='Matched a user-provided employer receipt.',
                   pending_attempt=None):
    with con:
        con.execute('BEGIN IMMEDIATE')
        job = con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if job is None:
            raise ValueError('Job ID not found.')
        if pending_attempt is not None:
            latest = con.execute(
                "SELECT MAX(id) FROM attempts WHERE job_id=? AND outcome='submission_pending'",
                (job_id,),
            ).fetchone()[0]
            if job['status'] != 'submission_pending' or latest != pending_attempt:
                raise ValueError('This application hold changed before the receipt could be recorded.')
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


def scan_receipts(con, folder):
    summary = {'matched': 0, 'unmatched': 0, 'ambiguous': 0, 'unreadable': 0}
    if not folder.is_dir():
        return summary
    jobs = con.execute("""SELECT j.*, a.id AS hold_id, a.at AS held_at
        FROM jobs j JOIN attempts a ON a.id=(
            SELECT MAX(id) FROM attempts WHERE job_id=j.id AND outcome='submission_pending'
        )
        WHERE j.status='submission_pending'""").fetchall()
    if not jobs:
        return summary
    known_roles = Counter(
        (normalized(job['company'] or ''), normalized(job['title'] or ''))
        for job in con.execute('SELECT company, title FROM jobs')
    )

    for path in sorted(folder.glob('*.eml')):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text, sent = read_receipt(path)
        except (OSError, ValueError, LookupError):
            summary['unreadable'] += 1
            continue
        matches = []
        for job in jobs:
            if sent is None or sent.utcoffset() is None or sent < datetime.fromisoformat(job['held_at']):
                continue
            try:
                receipt_fingerprint(text, job)
            except ValueError:
                continue
            matches.append(job)
        unique = []
        for job in matches:
            role = normalized(job['company'] or ''), normalized(job['title'] or '')
            if known_roles[role] == 1 or mentions_posting(text, job['url']):
                unique.append(job)
        if len(unique) != 1:
            summary['ambiguous' if matches else 'unmatched'] += 1
            continue
        job = unique[0]
        try:
            created = record_receipt(con, job['id'], text, pending_attempt=job['hold_id'],
                                     details='Matched a confirmation from the local receipt inbox.')
        except ValueError:
            summary['unmatched'] += 1
            continue
        summary['matched'] += int(created)
    return summary
