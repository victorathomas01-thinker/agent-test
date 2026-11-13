from concurrent.futures import ThreadPoolExecutor
import csv, hashlib, html, json, re, sqlite3, urllib.request, urllib.parse
from ipaddress import ip_address
from urllib.error import HTTPError, URLError
from time import sleep
from contextlib import closing
from tempfile import NamedTemporaryFile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .employers import board_from_url, find_boards
from .matching import ADJACENT_ROLES, fit_signals, qualifications
from .priority import rank_job
from .careers import discover_sites
from .sources import smartrecruiters_jobs

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'agent.sqlite3'
CONFIG = ROOT / 'config.json'

def load_config():
    if not CONFIG.exists():
        raise RuntimeError('config.json missing. Run python main.py init first.')
    cfg = with_defaults(json.loads(CONFIG.read_text(encoding='utf-8-sig')))
    candidate = ROOT / 'private' / 'candidate-profile.json'
    if candidate.is_file():
        cfg['_candidate_profile'] = json.loads(candidate.read_text(encoding='utf-8-sig'))
    return cfg


def with_defaults(saved):
    defaults = json.loads((ROOT / 'config.example.json').read_text(encoding='utf-8'))
    for section, values in defaults.items():
        values.update(saved.get(section, {}))
    return defaults

def save_config(cfg):
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=ROOT, prefix='config.',
                            suffix='.local.json', delete=False) as temporary:
        json.dump({key: value for key, value in cfg.items() if not key.startswith('_')},
                  temporary, indent=2, ensure_ascii=False)
        temporary.write('\n')
    path = Path(temporary.name)
    try:
        path.replace(CONFIG)
    finally:
        path.unlink(missing_ok=True)

def connect():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT,
        location TEXT, url TEXT, description TEXT, score INTEGER DEFAULT 0, eligible INTEGER DEFAULT 1,
        reason TEXT DEFAULT '', status TEXT DEFAULT 'found', last_seen TEXT, submitted_at TEXT, notes TEXT DEFAULT '')''')
    con.execute('''CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT,
       at TEXT, outcome TEXT, details TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS preview_claims (
       day TEXT NOT NULL, job_id TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (day, job_id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS receipts (
       job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, recorded_at TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS job_details (
       job_id TEXT PRIMARY KEY, published_at TEXT, workplace TEXT, employment_type TEXT, salary TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS runs (
       id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
       details TEXT NOT NULL DEFAULT '')''')
    con.execute('''CREATE TABLE IF NOT EXISTS packages (
       job_id TEXT NOT NULL, version TEXT NOT NULL, created_at TEXT NOT NULL,
       folder TEXT NOT NULL, PRIMARY KEY (job_id, version))''')
    con.execute('''CREATE TABLE IF NOT EXISTS followups (
       job_id TEXT PRIMARY KEY, due_on TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS selections (
       job_id TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL,
       attempts INTEGER NOT NULL DEFAULT 0, blocker TEXT NOT NULL DEFAULT '', version TEXT NOT NULL DEFAULT '')''')
    con.execute('''CREATE TABLE IF NOT EXISTS web_checks (
       job_id TEXT PRIMARY KEY, verification TEXT NOT NULL, deadline TEXT NOT NULL DEFAULT '')''')
    con.execute('''CREATE TABLE IF NOT EXISTS verified_facts (
       key TEXT PRIMARY KEY, value TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
       verified_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)''')
    con.execute('''CREATE TABLE IF NOT EXISTS eligibility_overrides (
       job_id TEXT PRIMARY KEY, created_at TEXT NOT NULL)''')
    con.commit()
    return con

def utc_now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')


def claim_preview(con, daily_limit, fresh_since=None):
    """Reserve a batch slot before opening the browser so overlapping runs share the cap."""
    with con:
        con.execute('BEGIN IMMEDIATE')
        day = date.today().isoformat()
        used = con.execute('SELECT COUNT(*) FROM preview_claims WHERE day=?', (day,)).fetchone()[0]
        if used >= daily_limit:
            return None

        recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec='seconds')
        job = con.execute('''SELECT * FROM jobs AS j
            WHERE eligible=1 AND status='found'
              AND (? IS NULL OR (source!='manual' AND last_seen>=?))
              AND NOT EXISTS (SELECT 1 FROM preview_claims AS c
                              WHERE c.job_id=j.id AND (c.day=? OR c.at>=?))
            ORDER BY score DESC, id LIMIT 1''',
                          (fresh_since, fresh_since, day, recent)).fetchone()
        if job is not None:
            con.execute('INSERT INTO preview_claims(day, job_id, at) VALUES (?, ?, ?)',
                        (day, job['id'], utc_now()))
        return job


def http_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'PersonalJobAgent/0.1 (personal job discovery)', 'Accept':'application/json'})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req,timeout=18) as response:
                return json.load(response)
        except HTTPError as error:
            if attempt or error.code not in {429, 500, 502, 503, 504}:
                raise
            wait = error.headers.get('Retry-After', '')
            if wait and (not wait.isdigit() or int(wait) > 10):
                raise
            sleep(max(1, int(wait)) if wait else 1)
        except (TimeoutError, URLError):
            if attempt:
                raise
            sleep(1)

def plain(s):
    s = re.sub(r'<[^>]+>', ' ', html.unescape(s or ''))
    return re.sub(r'\s+', ' ', s).strip()

def fetch_board(provider, slug, company, maximum, discovered=False, coverage=None, audit=None):
    if not isinstance(maximum, int) or maximum < 1:
        raise ValueError('Posting cap must be positive.')
    if provider == 'smartrecruiters':
        jobs = smartrecruiters_jobs(slug, company, maximum, http_json, plain, audit)
        if coverage is not None and audit is not None and audit.get('complete'):
            coverage.append((provider, slug))
        return jobs
    token = urllib.parse.quote(slug, safe='')
    if provider == 'greenhouse':
        data = http_json(f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true')
        postings = data['jobs']
    elif provider == 'lever':
        postings = http_json(f'https://api.lever.co/v0/postings/{token}?mode=json')
    elif provider == 'ashby':
        postings = http_json(f'https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true')['jobs']
    else:
        raise ValueError('Unknown posting provider.')

    if not isinstance(postings, list):
        raise ValueError('Posting API did not return a list.')
    jobs = []
    complete = len(postings) < maximum
    for posting in postings[:maximum]:
        if not isinstance(posting, dict):
            complete = False
            continue
        details = {}
        if provider == 'greenhouse':
            title = posting.get('title', '')
            location = (posting.get('location') or {}).get('name', '')
            url = posting.get('absolute_url', '')
            description = posting.get('content', '')
        elif provider == 'lever':
            title = posting.get('text', '')
            location = lever_location(posting)
            url = posting.get('applyUrl') or posting.get('hostedUrl', '')
            description = posting.get('descriptionPlain') or posting.get('description')
            details = {'workplace': posting.get('workplaceType'), 'salary': posting.get('salaryDescriptionPlain'),
                       'employment_type': (posting.get('categories') or {}).get('commitment')}
        else:
            if posting.get('isListed') is not True:
                continue
            title = posting.get('title')
            location = posting.get('location')
            url = posting.get('applyUrl') or posting.get('jobUrl')
            description = posting.get('descriptionPlain') or posting.get('descriptionHtml')
            details = {'published_at': posting.get('publishedAt'), 'workplace': posting.get('workplaceType'),
                       'employment_type': posting.get('employmentType'),
                       'salary': (posting.get('compensation') or {}).get('scrapeableCompensationSalarySummary')}
        if board_from_url(url) != (provider, slug.lower()):
            # Never import another organization's posting or assert completeness
            # when the source could not be verified.
            complete = False
            continue
        identifier = (urllib.parse.urlsplit(url).path.rstrip('/').removesuffix('/application').rsplit('/', 1)[-1]
                      if provider == 'ashby' else posting['id'])
        jobs.append({
            'id': f'{provider}:{slug}:{identifier}',
            'source': provider,
            'company': company,
            'title': title or '',
            'location': location or '',
            'url': url or '',
            'description': plain(description),
            **{key: value or '' for key, value in details.items()},
        })
    if audit is not None:
        audit.update(complete=complete, returned=len(jobs), total=len(postings),
                     reason='all_public_listings' if complete else 'capped_or_invalid_listing')
    if coverage is not None and complete:
        coverage.append((provider, slug))
    return jobs


def discovery_rank(listing, cfg):
    locations = listing.get('locations')
    if not isinstance(locations, list):
        locations = []
    title = listing.get('title')
    if not isinstance(title, str):
        title = ''
    # A clue can contain multiple locations. Give the board credit for its best match.
    def match(location):
        score, eligible, _ = evaluate({
            'title': title, 'location': str(location), 'description': '', 'url': listing['url'],
        }, cfg)
        return eligible, score

    return max(map(match, locations or ['']))


def discover(cfg, coverage=None, source_checks=None):
    discovery = cfg['discovery']
    configured = [
        ('greenhouse', slug, slug) for slug in discovery['greenhouse_boards']
    ] + [
        ('lever', slug, slug) for slug in discovery['lever_sites']
    ] + [
        ('ashby', slug, slug) for slug in discovery.get('ashby_boards', [])
    ] + [
        ('smartrecruiters', slug, slug) for slug in discovery.get('smartrecruiters_companies', [])
    ]
    known = {(provider, slug.lower()) for provider, slug, _ in configured}
    found, errors = find_boards(
        discovery.get('employer_feeds', []),
        known,
        max(0, discovery.get('max_discovered_boards', 0)),
        http_json,
        lambda listing: discovery_rank(listing, cfg),
        source_checks,
    )
    sources = list(dict.fromkeys(configured)) + [(provider, slug, slug) for provider, slug in found]
    discovered = set(found)

    def fetch(source):
        provider, slug, company = source
        completed, audit = [], {}
        key = f'{provider}:{slug}'
        try:
            postings = fetch_board(provider, slug, company, discovery['max_per_source'],
                                   (provider, slug) in discovered, completed, audit)
            status = ('empty' if not postings else 'complete') if audit.get('complete') else 'partial'
            source_check = dict(kind='ats', key=key, status=status, records=len(postings),
                                detail=audit.get('reason', 'coverage_unknown'))
            return postings, None, completed, source_check
        except (OSError, ValueError, KeyError, TypeError) as error:
            source_check = dict(kind='ats', key=key, status='error', records=0,
                                detail=type(error).__name__)
            return [], f'{provider} {slug}: {error}', [], source_check

    jobs = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for postings, error, completed, source_check in pool.map(fetch, sources):
            jobs.extend(postings)
            if coverage is not None:
                coverage.extend(completed)
            if source_checks is not None:
                source_checks.append(source_check)
            if error:
                errors.append(error)
    if discovery.get('career_sites'):
        postings, problems = discover_sites(discovery['career_sites'],
                                            discovery.get('career_page_budget', 10),
                                            plain, report=source_checks)
        jobs.extend(postings)
        errors.extend(problems)
    return jobs, errors


def expire_unlisted(coverage, observed, started):
    """Only reconcile boards successfully read without a posting cap."""
    active_ids = {job['id'] for job in observed}
    with closing(connect()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        missing = []
        for provider, slug in set(coverage):
            prefix = f'{provider}:{slug}:'
            rows = con.execute("""SELECT id FROM jobs WHERE substr(id,1,?)=? AND last_seen<?
                                  AND status IN ('found','prepared','needs_review','failed')""",
                               (len(prefix), prefix, started))
            missing.extend((row['id'],) for row in rows if row['id'] not in active_ids)
        con.executemany("""UPDATE jobs SET status='expired', notes='No longer listed on the public board.'
                           WHERE id=?""", missing)
        return len(missing)

def lever_location(item):
    categories = item.get('categories') or {}
    locations = categories.get('allLocations') or [categories.get('location') or '']
    if item.get('workplaceType') == 'remote' and not any(locations):
        locations = [*locations, 'Remote']
    return ', '.join(locations)


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
    if job.get('verification') == 'unverified':
        reasons.append('Posting availability could not be verified')
    if re.search(r'\bunpaid\s+(?:internship|role|position|opportunity)\b', title + ' ' + description):
        reasons.append('Unpaid opportunity')
    if p['exclude_contract'] and ((job.get('employment_type') or '').casefold() in
            {'contract', 'temporary', 'contracttohire', 'contract to hire', 'contract-to-hire', 'freelance'}
            or re.search(r'\b(contract(or)?|1099|freelance)\b', title)
            or re.search(r'\b(contract position|contract role|1099 position)\b', description[:1500])):
        reasons.append('Contract work')
    if p['exclude_senior'] and re.search(r'\b(senior|sr\.?|principal|staff|lead|director|manager|architect|iii|iv)\b',title):
        reasons.append('Senior-level title')
    candidate = cfg.get('_candidate_profile', {})
    reasons.extend(qualifications(description, {**cfg.get('profile', {}), **candidate},
                                  candidate.get('gpa', p['exclude_hard_gpa_over'])))
    verified = cfg.get('verified_answers', {})
    if re.search(r'\b(no (?:visa )?sponsorship|(?:cannot|unable to|will not) sponsor)\b', description) and verified.get('needs_sponsorship_now_or_future') is not False:
        reasons.append('Review sponsorship restriction')
    if re.search(r'\b(?:must be|must already be) (?:legally )?authorized to work in the (?:u\.?s\.?|united states)\b', description) and verified.get('work_authorized_us') is not True:
        reasons.append('Review US work authorization requirement')
    degree = re.search(r'\b(?:must have|must hold|requires?)\s+(?:a\s+)?(?:completed\s+)?'
                       r'(?:bachelor.?s|master.?s|phd)\s+degree\b[^.!?]*', description)
    if degree and not re.search(r'\b(?:equivalent|preferred|in progress)\b', degree[0]):
        if 'completed' in degree[0] or not re.search(r'\bintern(ship)?\b', title):
            reasons.append('May require completed degree — manually review')
    search_title = re.sub(r'\bsoftware engineering\b', 'software engineer', title)
    keywords = {key.lower() for key in p['keywords'] if key}
    if p.get('include_adjacent_roles'):
        keywords |= ADJACENT_ROLES
    fields = keywords - {'intern', 'internship', 'co-op', 'junior', 'entry level'}
    hits = {key for key in keywords
            if re.search(r'(?<!\w)' + re.escape(key) + r'(?!\w)', search_title)}
    priority = rank_job(job, cfg.get('_candidate_evidence', ''))
    if fields and not fields.intersection(hits):
        if priority['category'] == 'Other':
            reasons.append('No matching job field')
    score = len(hits) * 25
    if not hits and priority['category'] != 'Other':
        score += 25
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
    return priority['score'], not reasons, '; '.join(reasons)


def valid_application_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or '.' not in host or parsed.username is not None or parsed.port not in (None, 443):
            return False
        try:
            return ip_address(host).is_global
        except ValueError:
            return not host.endswith(('.localhost', '.local', '.internal'))
    except ValueError:
        return False

def canonical_url(url):
    if not url or not valid_application_url(url):
        return ''
    parsed = urllib.parse.urlsplit(url)
    board = board_from_url(url)
    if board:
        path = parsed.path.rstrip('/').removesuffix('/apply').removesuffix('/application')
        return f'{board[0]}:{path.casefold()}'
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query
             if not key.casefold().startswith('utm_') and key.casefold() not in {'gclid', 'fbclid'}]
    return urllib.parse.urlunsplit(('https', parsed.hostname, parsed.path.rstrip('/') or '/',
                                    urllib.parse.urlencode(sorted(query)), ''))


def store_jobs(jobs, cfg):
    new = 0
    with closing(connect()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        existing = {row['id']: row['source'] for row in con.execute('SELECT id, source FROM jobs')}
        known_urls = {canonical_url(row['url']): row['id'] for row in con.execute(
            "SELECT id,url FROM jobs WHERE url IS NOT NULL ORDER BY (status='submitted')"
        )}
        for job in jobs:
            identity = canonical_url(job['url'])
            if identity and identity in known_urls and job['id'] not in existing:
                if job['source'] == 'manual' or existing[known_urls[identity]] != 'manual':
                    continue
            score, eligible, reason = evaluate(job, cfg)
            new += int(job['id'] not in existing)
            con.execute('''INSERT INTO jobs (id,source,company,title,location,url,description,score,eligible,reason,last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, company=excluded.company,
           location=excluded.location,url=excluded.url,description=excluded.description,score=excluded.score,
           eligible=excluded.eligible,reason=excluded.reason,last_seen=excluded.last_seen,
           status=CASE WHEN jobs.status='expired' AND excluded.source!='manual' THEN 'found' ELSE jobs.status END''',
                        (job['id'], job['source'], job['company'], job['title'], job['location'], job['url'],
                         job['description'], score, int(eligible), reason, utc_now()))
            if job['source'] != 'manual':
                con.execute('INSERT OR REPLACE INTO job_details VALUES (?, ?, ?, ?, ?)',
                            (job['id'], *(job.get(key, '') for key in
                             ('published_at', 'workplace', 'employment_type', 'salary'))))
            if job.get('verification'):
                con.execute('INSERT OR REPLACE INTO web_checks VALUES (?, ?, ?)',
                            (job['id'], job['verification'], str(job.get('deadline') or '')))
            existing[job['id']] = job['source']
            if identity:
                known_urls[identity] = job['id']
    return new

def import_urls(path, cfg):
    jobs = []
    with open(path, encoding='utf-8-sig', newline='') as file:
        rows = csv.DictReader(file)
        if 'url' not in (rows.fieldnames or []):
            raise ValueError('CSV requires a url column.')
        for row in rows:
            url = (row.get('url') or '').strip()
            if not valid_application_url(url):
                continue
            identifier = 'manual:' + hashlib.sha256(url.encode()).hexdigest()[:24]
            jobs.append(dict(id=identifier, source='manual', url=url, **{
                key: row.get(key) or '' for key in ('company', 'title', 'location', 'description')
            }))
    return store_jobs(jobs, cfg)


def refresh_eligibility(con, cfg):
    updates = []
    for job in con.execute("""SELECT j.*, COALESCE(d.workplace, '') AS workplace,
                                     COALESCE(d.employment_type, '') AS employment_type,
                                     COALESCE(d.salary, '') AS salary, w.verification
                              FROM jobs j LEFT JOIN job_details d ON j.id=d.job_id
                              LEFT JOIN web_checks w ON j.id=w.job_id"""):
        score, eligible, reason = evaluate(dict(job), cfg)
        updates.append((score, int(eligible), reason, job['id']))
    with con:
        con.executemany('UPDATE jobs SET score=?, eligible=?, reason=? WHERE id=?', updates)


def record_attempt(con, job_id, outcome, details):
    now = utc_now()
    con.execute('INSERT INTO attempts(job_id, at, outcome, details) VALUES (?, ?, ?, ?)',
                (job_id, now, outcome, details))
    con.execute("""UPDATE jobs SET status=?, notes=?,
                   submitted_at=CASE WHEN ?='submitted' THEN ? ELSE submitted_at END
                   WHERE id=? AND submitted_at IS NULL
                     AND status NOT IN ('submitted','assessment','interview','offer','rejected','withdrawn')
                     AND (status!='submission_pending' OR ?='submitted')""",
                (outcome, details, outcome, now, job_id, outcome))


def add_attempt(job_id, outcome, details):
    with closing(connect()) as con, con:
        record_attempt(con, job_id, outcome, details)

PROFILE_LABELS = {
    'first_name': ('first name', 'firstname', 'given name', 'legal first name'),
    'last_name': ('last name', 'lastname', 'surname', 'family name', 'legal last name'),
    'full_name': ('full name', 'fullname', 'name'),
    'preferred_name': ('preferred name', 'preferred first name'),
    'email': ('email', 'email address', 'e-mail'),
    'phone': ('phone', 'phone number', 'mobile', 'telephone'),
    'city': ('city',), 'state': ('state', 'province'),
    'school': ('university', 'school', 'college'),
    'degree': ('degree',), 'major': ('major', 'field of study'),
    'graduation': ('graduation', 'graduation date', 'expected graduation', 'expected graduation date'),
    'linkedin': ('linkedin', 'linkedin profile', 'linkedin profile url', 'linkedin url'),
    'github': ('github', 'github url', 'github profile'),
    'portfolio': ('portfolio', 'portfolio url', 'personal website', 'website'),
}

VERIFIED_PATTERNS = {
    'work_authorized_us': (
        r'(?:are you (?:legally )?(?:authorized|eligible|permitted) to work in (?:the )?'
        r'(?:united states|u\.?s\.?a?\.?)'
        r'|do you have (?:legal )?(?:work authorization|authorization to work) in (?:the )?'
        r'(?:united states|u\.?s\.?a?\.?)'
        r'|are you (?:legally )?(?:authorized|eligible|permitted) to work in the united states of america)'
    ),
    'needs_sponsorship_now_or_future': r'(?:do|will) you (?:now or in the future )?(?:require|need) (?:visa |employment )?sponsorship(?: now or in the future)?',
    'over_18': r'are you (?:at least 18(?: years old| years of age)?|18 years of age or older)',
    'willing_to_relocate': r'are you willing to relocate',
    'has_employment_history': (
        r'(?:have you (?:ever |previously )?(?:been employed|worked here(?: before)?)'
        r'|have you (?:ever |previously )?(?:worked for|worked at|been employed by|been employed at) '
        r'(?:us|this company|[a-z0-9 .&’\x27-]+)(?: before| for any length of time)?'
        r'|are you (?:a )?(?:current or former|former or current) employee(?: of [a-z0-9 .&’\x27-]+)?)'
    ),
    'was_referred': (
        r'(?:(?:were|have) you (?:been )?referred(?: to (?:this (?:job|role|position)|us))?'
        r'(?: by (?:an? )?(?:employee|current employee|someone)(?: of [a-z0-9 .&’\x27-]+)?)?'
        r'|did someone refer you)'
    ),
}
NARROW_US_SPONSORSHIP = re.compile(
    r"(?:do you require immigration sponsorship to work for [a-z0-9 .&'\-]+ in the united states"
    r"|will you require immigration sponsorship at any point in the future to maintain authorization to work in the united states)"
)


def normalize_question(label):
    return re.sub(r'\s+', ' ', label.casefold().replace('_', ' ')).strip(' :?*')


def answer_for(label, cfg):
    normalized = normalize_question(label)
    if not normalized:
        return None, None
    if normalized in cfg.get('verified_questions', {}):
        return cfg['verified_questions'][normalized] or None, 'verified question'
    if NARROW_US_SPONSORSHIP.fullmatch(normalized):
        key = 'needs_sponsorship_now_or_future'
        # A combined No answers each timeframe. A combined Yes does not say which one.
        return ('No' if cfg['verified_answers'].get(key) is False else None), key
    for key, pattern in VERIFIED_PATTERNS.items():
        if re.fullmatch(pattern, normalized):
            value = cfg['verified_answers'].get(key)
            if key in {'has_employment_history', 'was_referred'} and value is not False:
                return None, key
            return ('Yes' if value else 'No', key) if isinstance(value, bool) else (None, key)
    profile = cfg['profile']
    for key, aliases in PROFILE_LABELS.items():
        if normalized in aliases:
            if key == 'full_name':
                first, last = profile.get('first_name'), profile.get('last_name')
                return (f'{first} {last}' if first and last else None), key
            return profile.get(key) or None, key
    return None, None
