from concurrent.futures import ThreadPoolExecutor
import csv, hashlib, html, json, re, sqlite3, urllib.request, urllib.parse
from contextlib import closing
from tempfile import NamedTemporaryFile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .employers import board_from_url, find_boards

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'agent.sqlite3'
CONFIG = ROOT / 'config.json'

def load_config():
    if not CONFIG.exists():
        raise RuntimeError('config.json missing. Run python main.py init first.')
    return with_defaults(json.loads(CONFIG.read_text(encoding='utf-8-sig')))


def with_defaults(saved):
    defaults = json.loads((ROOT / 'config.example.json').read_text(encoding='utf-8'))
    for section, values in defaults.items():
        values.update(saved.get(section, {}))
    return defaults

def save_config(cfg):
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=ROOT, prefix='config.',
                            suffix='.local.json', delete=False) as temporary:
        json.dump(cfg, temporary, indent=2, ensure_ascii=False)
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
    with urllib.request.urlopen(req,timeout=18) as r:
        return json.load(r)

def plain(s):
    s = re.sub(r'<[^>]+>', ' ', html.unescape(s or ''))
    return re.sub(r'\s+', ' ', s).strip()

def fetch_board(provider, slug, company, maximum, discovered=False):
    token = urllib.parse.quote(slug, safe='')
    if provider == 'greenhouse':
        data = http_json(f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true')
        postings = data['jobs']
    else:
        postings = http_json(f'https://api.lever.co/v0/postings/{token}?mode=json')

    jobs = []
    for posting in postings[:maximum]:
        if provider == 'greenhouse':
            title = posting.get('title', '')
            location = (posting.get('location') or {}).get('name', '')
            url = posting.get('absolute_url', '')
            description = posting.get('content', '')
        else:
            title = posting.get('text', '')
            location = lever_location(posting)
            url = posting.get('applyUrl') or posting.get('hostedUrl', '')
            description = posting.get('descriptionPlain') or posting.get('description')
        if discovered and board_from_url(url) != (provider, slug):
            continue
        jobs.append({
            'id': f'{provider}:{slug}:{posting["id"]}',
            'source': provider,
            'company': company,
            'title': title or '',
            'location': location or '',
            'url': url or '',
            'description': plain(description),
        })
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


def discover(cfg):
    discovery = cfg['discovery']
    configured = [
        ('greenhouse', slug, slug) for slug in discovery['greenhouse_boards']
    ] + [
        ('lever', slug, slug) for slug in discovery['lever_sites']
    ]
    known = {(provider, slug.lower()) for provider, slug, _ in configured}
    found, errors = find_boards(
        discovery.get('employer_feeds', []),
        known,
        max(0, discovery.get('max_discovered_boards', 0)),
        http_json,
        lambda listing: discovery_rank(listing, cfg),
    )
    sources = list(dict.fromkeys(configured)) + [(provider, slug, slug) for provider, slug in found]
    discovered = set(found)

    def fetch(source):
        provider, slug, company = source
        try:
            return fetch_board(provider, slug, company, discovery['max_per_source'],
                               (provider, slug) in discovered), None
        except (OSError, ValueError, KeyError, TypeError) as error:
            return [], f'{provider} {slug}: {error}'

    jobs = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for postings, error in pool.map(fetch, sources):
            jobs.extend(postings)
            if error:
                errors.append(error)
    return jobs, errors

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
        parsed = urllib.parse.urlsplit(url)
        return parsed.scheme == 'https' and bool(parsed.hostname) and parsed.username is None
    except ValueError:
        return False

def store_jobs(jobs,cfg):
    con=connect(); new=0
    for job in jobs:
        score,eligible,reason=evaluate(job,cfg)
        found=con.execute('SELECT status FROM jobs WHERE id=?',(job['id'],)).fetchone()
        if not found:new+=1
        con.execute('''INSERT INTO jobs (id,source,company,title,location,url,description,score,eligible,reason,last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, company=excluded.company,
           location=excluded.location,url=excluded.url,description=excluded.description,score=excluded.score,
           eligible=excluded.eligible,reason=excluded.reason,last_seen=excluded.last_seen''',
           (job['id'],job['source'],job['company'],job['title'],job['location'],job['url'],job['description'],score,int(eligible),reason,utc_now()))
    con.commit();con.close();return new

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
    for job in con.execute('SELECT * FROM jobs'):
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
                   WHERE id=? AND status!='submitted'
                     AND (status!='submission_pending' OR ?='submitted')""",
                (outcome, details, outcome, now, job_id, outcome))


def add_attempt(job_id, outcome, details):
    with closing(connect()) as con, con:
        record_attempt(con, job_id, outcome, details)

PROFILE_LABELS = {
    'first_name': ('first name', 'firstname', 'given name', 'legal first name'),
    'last_name': ('last name', 'lastname', 'surname', 'family name', 'legal last name'),
    'full_name': ('full name', 'fullname', 'name'),
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
    'work_authorized_us': r'are you (?:legally )?(?:authorized|eligible) to work in (?:the )?(?:united states|u\.?s\.?a?\.?)',
    'needs_sponsorship_now_or_future': r'(?:do|will) you (?:now or in the future )?(?:require|need) (?:visa |employment )?sponsorship(?: now or in the future)?',
    'over_18': r'are you (?:at least 18(?: years old| years of age)?|18 years of age or older)',
    'willing_to_relocate': r'are you willing to relocate',
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
            return ('Yes' if value else 'No', key) if isinstance(value, bool) else (None, key)
    profile = cfg['profile']
    for key, aliases in PROFILE_LABELS.items():
        if normalized in aliases:
            if key == 'full_name':
                first, last = profile.get('first_name'), profile.get('last_name')
                return (f'{first} {last}' if first and last else None), key
            return profile.get(key) or None, key
    return None, None
