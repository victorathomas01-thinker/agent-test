"""Deterministic qualification and preference checks."""

import calendar
import re
from datetime import date

MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTH = '|'.join(MONTHS)
MONTH_YEAR = rf'({MONTH})\s+(20\d{{2}})'
WINDOW = re.compile(rf'\b(?:graduat\w*|graduation date)[^.;]{{0,45}}?\bbetween\s+{MONTH_YEAR}\s+and\s+{MONTH_YEAR}\b')
GPA = re.compile(r'\b(?:minimum|required|at least)\s+(?:cumulative\s+)?gpa(?:\s+of|:)?\s*(\d(?:\.\d+)?)'
                 r'|\bgpa(?:\s+of|:)?\s*(\d(?:\.\d+)?)\s*(?:minimum|required|or higher)\b')
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
    description = description.casefold()
    graduation = re.fullmatch(MONTH_YEAR, str(profile.get('graduation') or '').strip().casefold())
    actual = date(int(graduation[2]), MONTHS[graduation[1]], 1) if graduation else None
    blockers = []
    for sentence in re.split(r'(?<=[.!?])\s+|[\n;]', description):
        if re.search(r'\b(?:preferred|nice to have|desirable)\b', sentence):
            continue
        for match in GPA.finditer(sentence):
            minimum = float(next(part for part in match.groups() if part is not None))
            if minimum <= 4 and (gpa is None or minimum > gpa):
                blockers.append(f'Review hard minimum GPA of {minimum:g}')
        if actual:
            for match in WINDOW.finditer(sentence):
                start = date(int(match[2]), MONTHS[match[1]], 1)
                end = date(int(match[4]), MONTHS[match[3]], 1)
                if start <= end and not start <= actual <= end:
                    blockers.append(f'Graduation outside required window ({match[1]} {match[2]} to {match[3]} {match[4]})')
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
