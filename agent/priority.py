"""Explainable candidate priorities from the Product Bible."""

import re

CATEGORIES = (
    ('IT/application support', ('help desk', 'service desk', 'it support', 'application support', 'desktop support')),
    ('Healthcare technology', ('clinical systems', 'clinical application', 'healthcare it', 'ehr', 'epic analyst', 'hospital it')),
    ('Business systems/implementation', ('business systems', 'systems analyst', 'implementation', 'technical onboarding')),
    ('Software development', ('software engineer', 'software engineering', 'developer', 'web development')),
    ('Data/analytics', ('data analyst', 'data analytics', 'business intelligence', 'reporting analyst', 'bi intern')),
    ('University/education IT', ('student it', 'classroom technology', 'educational technology', 'campus it')),
    ('Quality assurance', ('quality assurance', 'software tester', 'qa analyst', 'test engineer', 'uat')),
    ('Technical consulting/customer success', ('technical consultant', 'solutions engineer', 'technical customer success')),
    ('Infrastructure/operations', ('noc technician', 'network support', 'systems administrator', 'technical operations')),
    ('AI/automation', ('automation analyst', 'ai operations', 'automation engineer')),
    ('Product/project operations', ('technical coordinator', 'product operations', 'project coordinator')),
    ('Entertainment/sports technology', ('venue it', 'broadcast technology', 'game qa')),
)
BRIDGE_TERMS = ('patient access', 'customer support', 'student assistant', 'event operations', 'administrative assistant')
WEIGHTS = {'competitiveness': 30, 'career_value': 25, 'schedule': 20, 'compensation': 15, 'interests': 10}


def classify(title):
    title = (title or '').casefold()
    matches = [(len(phrase), index, label) for index, (label, phrases) in enumerate(CATEGORIES, 1)
               for phrase in phrases if phrase in title]
    if matches:
        _, rank, name = max(matches, key=lambda item: (item[0], -item[1]))
        return name, rank
    if any(term in title for term in BRIDGE_TERMS):
        return 'Bridge employment', len(CATEGORIES) + 1
    return 'Other', len(CATEGORIES) + 2


def weighted_score(scores):
    return round(sum(scores[key] * weight for key, weight in WEIGHTS.items()) / 100, 2)


def rank_job(job, evidence=''):
    from .matching import SKILLS, contains

    title = (job.get('title') or '').casefold()
    text = title + ' ' + (job.get('description') or '').casefold()
    location = (job.get('location') or '').casefold()
    salary = job.get('salary') or ''
    category, priority = classify(title)
    bridge = category == 'Bridge employment'
    skills = [skill for skill in SKILLS if contains(evidence.casefold(), skill) and contains(text, skill)]
    part_time = bool(re.search(r'\bpart[ -]time\b', text)) or (job.get('employment_type') or '').casefold() == 'parttime'
    summer = bool(re.search(r'\bsummer\s+2027\b', text) and re.search(r'\bintern', text))
    full_time = bool(re.search(r'\bfull[ -]time\b', text)) or (job.get('employment_type') or '').casefold() == 'fulltime'
    hybrid = 'hybrid' in location or (job.get('workplace') or '').casefold() == 'hybrid'
    early = bool(re.search(r'\b(intern\w*|junior|entry[ -]level|trainee|apprentice)\b', title))
    reasons = {
        'competitiveness': ['Resume evidence: ' + ', '.join(skills)] if skills else ['No verified skill overlap extracted'],
        'career_value': ['Technical career category: ' + category] if priority <= len(CATEGORIES) else ['Career alignment needs review'],
        'schedule': ['Part-time or summer internship signal'] if part_time or summer else
                    ['Check compatibility with classes' if full_time else 'Schedule unspecified'],
        'compensation': ['Published compensation: ' + salary] if salary else ['Published compensation unavailable'],
        'interests': ['Charlotte area'] if 'charlotte' in location else ['Location preference needs review'],
    }
    if hybrid:
        reasons['interests'].append('Hybrid work arrangement')
    scores = {
        'competitiveness': min(45 + 5 * len(skills) + (12 if early else 0), 90),
        'career_value': 76 if priority <= len(CATEGORIES) else 42,
        'schedule': 82 if part_time or summer else (35 if full_time else 40),
        'compensation': 65 if salary else 35,
        'interests': min(38 + (34 if 'charlotte' in location else 0) + (15 if hybrid else 0), 100),
    }
    hourly = re.search(r'\$\s*(\d{2})(?:\.\d{2})?\s*(?:per hour|/hr|hourly)', salary + ' ' + text)
    hours = re.search(r'\b(1[5-9]|2[0-5])\s*(?:hours|hrs)\s*(?:per|a|/)\s*week', text)
    bridge_score = (25 + (25 if part_time else 0) + (25 if hours else 0)
                    + (25 if hourly and 18 <= int(hourly[1]) <= 25 else 0)) if bridge else None
    return {'score': weighted_score(scores), 'dimensions': scores, 'reasons': reasons,
            'category': category, 'priority': priority, 'bridge_score': bridge_score,
            'confidence': 'medium' if salary and (part_time or summer or full_time) and skills else 'low',
            'schedule': 'Part-time' if part_time else ('Summer internship' if summer else ('Full-time' if full_time else 'Unknown'))}
