"""Conservative source freshness and explicitly stated application deadlines.

No network access. A stale listing is NOT classified as a closed vacancy; it
requires another verified source read before unattended prep or attended review.
"""
import calendar
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MONTHS = '|'.join(calendar.month_name[1:]) + '|' + '|'.join(calendar.month_abbr[1:])
ENGLISH_DATE = rf'(?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+20\d{{2}}'
ISO_DATE = r'20\d{2}-\d{2}-\d{2}'
DATE_TOKEN = rf'(?:{ISO_DATE}|{ENGLISH_DATE})'
LABEL = re.compile(
    rf'\b(?:applications?\s+(?:close|closes|closing|deadline|due|end|ends)'
    rf'|apply\s+by|deadline\s+to\s+apply|posting\s+(?:closes|close|ends)'
    rf'|last\s+day\s+to\s+apply)\b'
    rf'\s*(?:(?::|is|are|on|at|by)\s*)?'
    rf'({DATE_TOKEN})(?!\d)',
    re.IGNORECASE
)


def parse_day(value):
    """Accept only an unambiguous absolute day, never ambiguous slash dates."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or len(raw) > 100:
        return None
    if re.fullmatch(ISO_DATE, raw):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    # Structured ATS metadata sometimes includes a full timestamp.
    if re.fullmatch(r'20\d{2}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', raw, re.I):
        try:
            return datetime.fromisoformat(raw.replace('Z', '+00:00')).date()
        except ValueError:
            return None
    match = re.fullmatch(
        rf'({MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})',
        raw, re.I
    )
    if not match:
        return None
    try:
        month = datetime.strptime(match[1].rstrip('.')[:3].title(), '%b').month
        return date(int(match[3]), month, int(match[2]))
    except ValueError:
        return None


def explicit_text_deadline(description):
    """Return (date, ambiguous) for narrowly labeled employer closing dates.

    Multiple distinct dates or malformed matching labels must not be turned
    into a confident 'closed' fact. We also avoid expiry decisions on a date
    mentioned only in qualifications, start dates, or unrelated history.
    """
    if not isinstance(description, str) or not description:
        return None, False
    dates = {parsed for match in LABEL.finditer(description)
             if (parsed := parse_day(match[1])) is not None}
    if len(dates) > 1:
        return None, True
    return (next(iter(dates)), False) if dates else (None, False)


def observation_day(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        observed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if observed.tzinfo is None:
            return None
        return observed.astimezone(timezone.utc).date()
    except ValueError:
        return None


def risk_reasons(job, *, today=None, stale_after_days=14):
    """Return reasons to verify the job, not claims that it has closed."""
    if today is None:
        today = datetime.now(ZoneInfo('America/New_York')).date()
    if not isinstance(today, date) or isinstance(today, datetime):
        raise ValueError("Expected a calendar date.")
    if not isinstance(stale_after_days, int) or stale_after_days < 1:
        raise ValueError("Freshness interval must be a positive day count.")
    raw = job.get('deadline')
    stated = parse_day(raw)
    from_text, conflicting = explicit_text_deadline(job.get('description', ''))
    reasons = []
    if stated and from_text and stated != from_text:
        conflicting = True
    if conflicting:
        reasons.append("Conflicting explicit application deadlines — verify employer posting")
    else:
        deadline = stated or from_text
        if deadline is not None:
            # Do not mark a calendar-day deadline closed until the following
            # calendar day; employer time zones may differ from ours.
            if today > deadline + timedelta(days=1):
                reasons.append("Explicit application deadline passed — verify employer posting")
    if job.get('source') not in {None, '', 'manual'}:
        seen = observation_day(job.get('last_seen'))
        if seen is not None and today > seen + timedelta(days=stale_after_days):
            reasons.append("Listing last observed over 14 days ago — recheck source")
    return reasons


def aggregate(con, *, today=None):
    """Summarize stored source confidence without exposing personal data."""
    rows = con.execute("""SELECT j.source, j.last_seen, j.description,
                                 COALESCE(w.deadline,'') AS deadline,
                                 j.status
                          FROM jobs j LEFT JOIN web_checks w ON w.job_id=j.id
                          WHERE j.status NOT IN
                              ('submitted','submission_pending','assessment',
                               'interview','offer','rejected','withdrawn')""")
    stats = {'active_or_unconfirmed': 0, 'passed_deadline': 0,
             'stale_source': 0, 'conflicting_deadline': 0}
    for row in rows:
        stats['active_or_unconfirmed'] += 1
        signals = risk_reasons(dict(row), today=today)
        if any('deadline passed' in reason for reason in signals):
            stats['passed_deadline'] += 1
        if any('last observed' in reason for reason in signals):
            stats['stale_source'] += 1
        if any('Conflicting' in reason for reason in signals):
            stats['conflicting_deadline'] += 1
    return stats
