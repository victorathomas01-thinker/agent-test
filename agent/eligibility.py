"""Eligibility and scoring rules."""

import re
from urllib.parse import urlsplit


def preferred_location(location, preferences):
    for preference in preferences:
        if preference == 'remote':
            # A bare remote preference must not match "Remote Canada" or "Remote UK".
            region = re.sub(r'[^a-z0-9 ]', ' ', location.lower())
            region = ' '.join(region.split())
            if region in {'remote', 'remote us', 'us remote', 'remote usa', 'usa remote',
                          'remote united states', 'united states remote', 'remote u s', 'u s remote'}:
                return True
        elif preference and re.search(r'(?<!\w)' + re.escape(preference.lower()) + r'(?!\w)', location):
            return True
    return False


def evaluate(job,cfg):
    title=job['title'].lower(); description=job['description'].lower(); location=job['location'].lower()
    p=cfg['preferences']; reasons=[]
    if p['exclude_contract'] and (re.search(r'\b(contract(or)?|1099|freelance)\b',title) or re.search(r'\b(contract position|contract role|1099 position)\b',description[:1500])):
        reasons.append('Contract work')
    if p['exclude_senior'] and re.search(r'\b(senior|sr\.?|principal|staff|lead|director|manager|architect|iii|iv)\b',title):
        reasons.append('Senior-level title')
    hard_gpa=re.search(r'(?:minimum|required|at least|of)\s*(?:cumulative\s*)?gpa\s*(?:of|:)?\s*(\d\.\d+)|gpa\s*(?:of\s*)?(\d\.\d+)\s*(?:minimum|required|or higher)',description)
    gpa = p['exclude_hard_gpa_over']
    if hard_gpa and (gpa is None or max(float(x) for x in hard_gpa.groups() if x) > gpa):
        reasons.append('Review minimum GPA requirement')
    verified = cfg.get('verified_answers', {})
    if re.search(r'\b(no (?:visa )?sponsorship|(?:cannot|unable to|will not) sponsor)\b', description) and verified.get('needs_sponsorship_now_or_future') is not False:
        reasons.append('Review sponsorship restriction')
    if re.search(r'\b(?:must be|must already be) (?:legally )?authorized to work in the (?:u\.?s\.?|united states)\b', description) and verified.get('work_authorized_us') is not True:
        reasons.append('Review US work authorization requirement')
    if re.search(r'\b(?:must have|requires?)\s+(?:a\s+)?(?:completed\s+)?(?:bachelor.?s|master.?s|phd)\s+degree\b',description) and not re.search(r'\bintern(ship)?\b',title):
        reasons.append('May require completed degree — manually review')
    search_title = re.sub(r'\bsoftware engineering\b', 'software engineer', title)
    keywords = {key.lower() for key in p['keywords'] if key}
    fields = keywords - {'intern', 'internship', 'co-op', 'junior', 'entry level'}
    hits = {key for key in keywords
            if re.search(r'(?<!\w)' + re.escape(key) + r'(?!\w)', search_title)}
    if fields and not fields.intersection(hits):
        reasons.append('No matching job field')
    score = len(hits) * 25
    if 'intern' in title or 'co-op' in title or 'entry' in title or 'junior' in title: score+=18
    location_matches = preferred_location(location, p['locations'])
    if location_matches: score+=15
    if not location:
        reasons.append('Location missing — review')
    if '5+ years' in description or '7+ years' in description: score-=15
    if not hits: score-=15
    # Geography is conservative: unknown/nonlocal postings need manual review, not silent rejection.
    if location and not location_matches: reasons.append('Location outside preferred area — review')
    if score < p['minimum_score']: reasons.append('Below match threshold')
    if not valid_application_url(job.get('url', 'https://example.invalid')):
        reasons.append('Application URL missing or invalid')
    return score, not reasons, '; '.join(reasons)


def valid_application_url(url):
    try:
        parsed = urlsplit(url)
        return parsed.scheme == 'https' and bool(parsed.hostname) and parsed.username is None
    except ValueError:
        return False
