"""Deterministic qualification and preference checks."""

import calendar
import re
from datetime import date

MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTH = '|'.join(MONTHS)
MONTH_YEAR = rf'({MONTH})\s+(20\d{{2}})'
WINDOW = re.compile(
    rf'\b(?:graduat\w*|graduation date)[^.;]{{0,70}}?'
    rf'\b(?:between|from|of)\s+{MONTH_YEAR}\s*(?:and|through|to|[-–—])\s*{MONTH_YEAR}\b'
)
GRADUATE_BY = re.compile(
    rf'\b(?:applicants\s+)?(?:must|are\s+required\s+to)\s+(?:(?:have|be)\s+)?'
    rf'graduat(?:e|ed|ing)\s+(?:by|no\s+later\s+than|on\s+or\s+before)\s+{MONTH_YEAR}\b'
)
GRADUATE_AFTER = re.compile(
    rf'\b(?:applicants\s+)?(?:must|are\s+required\s+to)\s+(?:(?:have|be)\s+)?'
    rf'graduat(?:e|ed|ing)\s+(?:no\s+earlier\s+than|on\s+or\s+after)\s+{MONTH_YEAR}\b'
)
NOT_GRADUATING_BEFORE = re.compile(
    rf'\b(?:must\s+)?not\s+graduat(?:e|ing)\s+before\s+{MONTH_YEAR}\b'
)
GRADUATE_OR_LATER = re.compile(
    rf'\bmust\s+graduat(?:e|ing)\s+(?:in|on)?\s*{MONTH_YEAR}\s+or\s+later\b'
)
GPA = re.compile(
    r'\b(?:minimum|required|at least)\s+(?:overall\s+|cumulative\s+)?gpa(?:\s+of|:)?\s*(\d(?:\.\d+)?)'
    r'|\b(?:overall\s+|cumulative\s+)?gpa(?:\s+of|:)?\s*(\d(?:\.\d+)?)\s*(?:minimum|required|or higher|or above)\b'
    r'|\b(?:minimum|at least)\s+(\d(?:\.\d+)?)\s+(?:overall\s+|cumulative\s+)?gpa\b'
    r'|\b(\d(?:\.\d+)?)\s+(?:overall\s+|cumulative\s+)?gpa\s*(?:minimum|required|and higher|or above)\b'
    r'|\b(?:overall\s+|cumulative\s+)?gpa\s*(?:>=|≥)\s*(\d(?:\.\d+)?)'
    r'|\b(?:overall\s+|cumulative\s+)?gpa\s+(?:of\s+)?at\s+least\s+(\d(?:\.\d+)?)'
    r'|\b(?:minimum|required)\s+(?:overall\s+|cumulative\s+)?gpa\s+(?:is|must\s+be)\s+(\d(?:\.\d+)?)'
    r'|\b(?:overall\s+|cumulative\s+)?gpa(?:\s+of|:)?\s*(\d(?:\.\d+)?)\s*\+'
)
SCOPE_HEADING = re.compile(
    r'\b(required qualifications?|minimum qualifications?|basic(?:/required)? qualifications?|'
    r'desired qualifications?|preferred qualifications?|'
    r'additional requirements?|eligibility requirements?|'
    r'job expectations?|educational requirements?|'
    r'job responsibilities?|key responsibilities?|what makes you successful|'
    r'about this role|skills and experience|benefits)\s*:',
    flags=re.I,
)


def requirement_sections(text):
    """Keep employer headings meaningful even when HTML flattening removes line breaks."""
    cursor, scope = 0, "unspecified"
    for match in SCOPE_HEADING.finditer(text):
        if match.start() > cursor:
            yield scope, text[cursor:match.start()]
        heading = match.group(1).casefold()
        scope = ("optional" if heading.startswith(("desired", "preferred")) else
                 "required" if heading.startswith(("required", "minimum",
                                                    "basic", "additional",
                                                    "eligibility")) else "unspecified")
        cursor = match.end()
    if cursor < len(text):
        yield scope, text[cursor:]


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
    """Conservatively flag explicit hiring requirements, retaining section scope.

    The result blocks unattended preparation, not applications themselves.
    No prediction of employer decisions is made.
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
    for scope, section in requirement_sections(description):
        for sentence in re.split(r'(?<=[.!?])\s+|[\n;]', section):
            optional = (scope == "optional" or bool(
                re.search(r'\b(?:preferred|nice to have|desirable|desired|a plus)\b',
                          sentence)))
            mandatory = bool(re.search(r'\b(?:must|requires?|required|minimum)\b', sentence))
            if optional and not mandatory:
                continue
            mixed = optional and mandatory

            if re.search(r'\b(?:previous|prior)\s+(?:relevant\s+)?internship experience\s+(?:is\s+)?required\b', sentence):
                blockers.append('Prior internship experience required — confirm verified evidence')
            if re.search(r'\bgraduat(?:e|ion)\s+within\s+\d{1,2}\s+months?\s+after\s+'
                         r'(?:the\s+)?(?:completion|conclusion|end)\s+of\s+(?:the\s+)?internship\b', sentence):
                blockers.append('Graduation relative to internship end — confirm dates')
            if re.search(r'\bmust\s+continue\s+enrollment\b', sentence):
                blockers.append('Continued enrollment after internship — verify dates')
            if re.search(r'\b(?:this\s+requisition\s+is\s+)?open\s+to\s+\d{4}\s+'
                         r'[a-z0-9 .&-]{1,70}\s+interns?\s+only\b', sentence):
                blockers.append('Restricted to prior company interns — verify status')

            matches = list(GPA.finditer(sentence))
            for match in matches:
                minimum = float(next(part for part in match.groups() if part is not None))
                if minimum > 4:
                    continue
                if mixed:
                    blockers.append('Mixed required/preferred GPA language — manually review')
                elif actual_gpa is None or minimum > actual_gpa:
                    blockers.append(f'Review hard minimum GPA of {minimum:g}')

            if actual:
                windows = list(WINDOW.finditer(sentence))
                bys = list(GRADUATE_BY.finditer(sentence))
                afters = list(GRADUATE_AFTER.finditer(sentence))
                earliest = list(NOT_GRADUATING_BEFORE.finditer(sentence))
                later = list(GRADUATE_OR_LATER.finditer(sentence))
                if mixed and (windows or bys or afters or earliest or later):
                    blockers.append('Mixed required/preferred graduation language — manually review')
                    continue
                for match in windows:
                    start = date(int(match[2]), MONTHS[match[1]], 1)
                    end = date(int(match[4]), MONTHS[match[3]], 1)
                    if start <= end and not start <= actual <= end:
                        blockers.append(f'Graduation outside required window ({match[1]} {match[2]} to {match[3]} {match[4]})')
                for match in bys:
                    cutoff = date(int(match[2]), MONTHS[match[1]], 1)
                    if actual > cutoff:
                        blockers.append(f'Graduation later than required cutoff ({match[1]} {match[2]})')
                for match in afters:
                    first = date(int(match[2]), MONTHS[match[1]], 1)
                    if actual < first:
                        blockers.append(f'Graduation earlier than required start ({match[1]} {match[2]})')
                for match in earliest + later:
                    first = date(int(match[2]), MONTHS[match[1]], 1)
                    if actual < first:
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
