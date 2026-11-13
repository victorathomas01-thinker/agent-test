"""Deterministic qualification and preference checks."""

import calendar
import re
from datetime import date

MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTH = '|'.join(MONTHS)
MONTH_YEAR = rf'({MONTH})\s+(20\d{{2}})'
WINDOW = re.compile(rf'\b(?:graduat\w*|graduation date)[^.;]{{0,45}}?\bbetween\s+{MONTH_YEAR}\s+and\s+{MONTH_YEAR}\b')
GRADUATE_BY = re.compile(
    rf'\b(?:applicants\s+)?(?:must|are\s+required\s+to)\s+(?:(?:have|be)\s+)?'
    rf'graduat(?:e|ed|ing)\s+(?:by|no\s+later\s+than|on\s+or\s+before)\s+{MONTH_YEAR}\b'
)
GRADUATE_AFTER = re.compile(
    rf'\b(?:applicants\s+)?(?:must|are\s+required\s+to)\s+(?:(?:have|be)\s+)?'
    rf'graduat(?:e|ed|ing)\s+(?:no\s+earlier\s+than|on\s+or\s+after)\s+{MONTH_YEAR}\b'
)
GPA = re.compile(
    r'\b(?:minimum|required|at least)\s+(?:cumulative\s+)?gpa(?:\s+of|:)?\s*(\d(?:\.\d+)?)'
    r'|\bgpa(?:\s+of|:)?\s*(\d(?:\.\d+)?)\s*(?:minimum|required|or higher)\b'
    r'|\b(?:minimum|at least)\s+(\d(?:\.\d+)?)\s+(?:cumulative\s+)?gpa\b'
    r'|\b(\d(?:\.\d+)?)\s+(?:cumulative\s+)?gpa\s*(?:minimum|required)\b'
    r'|\b(?:cumulative\s+)?gpa\s*(?:>=|≥)\s*(\d(?:\.\d+)?)'
    r'|\b(?:cumulative\s+)?gpa\s+(?:of\s+)?at\s+least\s+(\d(?:\.\d+)?)'
    r'|\b(?:minimum|required)\s+(?:cumulative\s+)?gpa\s+(?:is|must\s+be)\s+(\d(?:\.\d+)?)'
    r'|\b(?:cumulative\s+)?gpa(?:\s+of|:)?\s*(\d(?:\.\d+)?)\s*\+'
)
SKILLS = ('python', 'javascript', 'typescript', 'java', 'sql', 'postgresql', 'linux', 'git',
          'react', 'node.js', 'html', 'css', 'excel', 'power bi', 'tableau', 'azure', 'aws',
          'technical support', 'troubleshooting', 'testing', 'rest api', 'epic', 'c++', 'c#')
STRATEGIES = ('fit', 'internship', 'healthcare', 'bridge', 'entry', 'stretch')
ADJACENT_ROLES = {
    'web development', 'application developer', 'software developer', 'qa analyst', 'test engineer',
    'desktop support', 'service desk', 'systems administrator', 'systems administration',
    'business systems analyst', 'clinical systems', 'epic analyst', 'hospital information systems',
    'implementation specialist', 'integration analyst', 'technical consultant', 'solutions engineer',
    'business intelligence', 'reporting analyst', 'database support', 'technical operations',
    'technology rotational', 'technology apprentice',
}


def qualifications(description, profile, gpa):
    """Conservative, explicit GPA and graduation filters for public job text.

    Ambiguous dates, absent applicant GPA, and optional requirements are flagged
    for review or left alone; this is not an applicant eligibility guarantee.
    """
    description = str(description or '').casefold()
    graduation = re.fullmatch(MONTH_YEAR, str(profile.get('graduation') or '').strip().casefold())
    actual = date(int(graduation[2]), MONTHS[graduation[1]], 1) if graduation else None
    try:
        actual_gpa = float(gpa) if gpa is not None else None
        if actual_gpa is not None and not 0 <= actual_gpa <= 4:
            actual_gpa = None
    except (TypeError, ValueError):
        actual_gpa = None

    blockers = []
    for sentence in re.split(r'(?<=[.!?])\s+|[\n;]', description):
        optional = bool(re.search(r'\b(?:preferred|nice to have|desirable|a plus)\b', sentence))
        mandatory = bool(re.search(r'\b(?:must|requires?|required)\b', sentence))
        # Pure preferred clauses never block a candidate. Mixed-language
        # clauses can be contradictory; mark them for human review.
        if optional and not mandatory:
            continue
        for match in GPA.finditer(sentence):
            minimum = float(next(part for part in match.groups() if part is not None))
            if minimum > 4:
                continue
            if optional and mandatory:
                blockers.append('Mixed required/preferred GPA language — manually review')
            elif actual_gpa is None or minimum > actual_gpa:
                blockers.append(f'Review hard minimum GPA of {minimum:g}')
        if actual:
            for match in WINDOW.finditer(sentence):
                start = date(int(match[2]), MONTHS[match[1]], 1)
                end = date(int(match[4]), MONTHS[match[3]], 1)
                if start <= end and not start <= actual <= end:
                    blockers.append(f'Graduation outside required window ({match[1]} {match[2]} to {match[3]} {match[4]})')
            for match in GRADUATE_BY.finditer(sentence):
                cutoff = date(int(match[2]), MONTHS[match[1]], 1)
                if actual > cutoff:
                    blockers.append(f'Graduation later than required cutoff ({match[1]} {match[2]})')
            for match in GRADUATE_AFTER.finditer(sentence):
                earliest = date(int(match[2]), MONTHS[match[1]], 1)
                if actual < earliest:
                    blockers.append(f'Graduation earlier than required start ({match[1]} {match[2]})')
    return list(dict.fromkeys(blockers))


def contains(text, phrase):
    return bool(re.search(r'(?<![\w+#])' + re.escape(phrase) + r'(?![\w+#])', text))


def fit_signals(job, cfg):
    title = (job['title'] or '').casefold()
    description = (job['description'] or '').casefold()
    location = (job['location'] or '').casefold()
    evidence = cfg.get('_candidate_evidence', '').casefold()
    matches = [skill for skill in SKILLS if contains(evidence, skill) and contains(title + ' ' + description, skill)]
    score = min(len(matches) * 4, 24)
    reasons = ['Resume text overlaps: ' + ', '.join(matches)] if matches else []
    if 'charlotte' in location:
        score += 12
        reasons.append('Charlotte location')
    if ('hybrid' in location or job.get('workplace', '').casefold() == 'hybrid') and 'charlotte' in location:
        score += 6
        reasons.append('Charlotte hybrid preference')
    strategy = cfg['preferences'].get('strategy', 'fit')
    strategy_terms = {
        'internship': ('intern', 'co-op', 'apprentice'),
        'healthcare': ('clinical', 'healthcare', 'epic', 'hospital'),
        'bridge': ('support', 'technician', 'help desk', 'implementation'),
        'entry': ('entry', 'junior', 'associate', 'trainee'),
        'stretch': ('engineer ii', 'specialist ii'),
    }
    if any(term in title for term in strategy_terms.get(strategy, ())):
        score += 12
        reasons.append(f'{strategy.title()} strategy priority')
    return score, reasons
