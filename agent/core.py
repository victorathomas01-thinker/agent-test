import csv, hashlib, html, json, re, sqlite3, urllib.request, urllib.parse
from tempfile import NamedTemporaryFile
from datetime import datetime, timezone
from pathlib import Path

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
    con.commit()
    return con

def utc_now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def http_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'PersonalJobAgent/0.1 (personal job discovery)', 'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=18) as r:
        return json.load(r)

def plain(s):
    s = re.sub(r'<[^>]+>', ' ', html.unescape(s or ''))
    return re.sub(r'\s+', ' ', s).strip()

def discover(cfg):
    all_jobs=[]; errors=[]
    for board in cfg['discovery']['greenhouse_boards']:
        try:
            data=http_json('https://boards-api.greenhouse.io/v1/boards/'+urllib.parse.quote(board, safe='')+'/jobs?content=true')
            for item in data.get('jobs',[])[:cfg['discovery']['max_per_source']]:
                all_jobs.append(dict(id=f'greenhouse:{board}:{item["id"]}',source='greenhouse',company=board,
                  title=item.get('title',''), location=item.get('location',{}).get('name',''),
                  url=item.get('absolute_url',''),description=plain(item.get('content',''))))
        except Exception as e: errors.append(f'Greenhouse {board}: {str(e)}')
    for site in cfg['discovery']['lever_sites']:
        try:
            data=http_json('https://api.lever.co/v0/postings/'+urllib.parse.quote(site,safe='')+'?mode=json')
            for item in data[:cfg['discovery']['max_per_source']]:
                all_jobs.append(dict(id=f'lever:{site}:{item["id"]}',source='lever',company=site,
                 title=item.get('text',''), location=lever_location(item),
                 url=item.get('applyUrl') or item.get('hostedUrl',''),
                 description=plain(item.get('descriptionPlain') or item.get('description') or '')))
        except Exception as e: errors.append(f'Lever {site}: {str(e)}')
    return all_jobs,errors

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
    hits = sum(bool(re.search(r'(?<!\w)' + re.escape(key.lower()) + r'(?!\w)', title))
               for key in p['keywords'] if key)
    score=hits*25
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
           VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
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


def add_attempt(job_id,outcome,details):
    con=connect();con.execute('INSERT INTO attempts(job_id,at,outcome,details) VALUES (?,?,?,?)',(job_id,utc_now(),outcome,details))
    status={'submitted':'submitted','needs_review':'needs_review','prepared':'prepared','failed':'failed'}.get(outcome,outcome)
    con.execute('UPDATE jobs SET status=?, notes=?, submitted_at=CASE WHEN ?="submitted" THEN ? ELSE submitted_at END WHERE id=? AND status != ?',
                (status,details,status,utc_now(),job_id,'submitted'));con.commit();con.close()

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


def normalize_question(label):
    return re.sub(r'\s+', ' ', label.casefold().replace('_', ' ')).strip(' :?*')


def answer_for(label, cfg):
    normalized = normalize_question(label)
    if not normalized:
        return None, None
    if normalized in cfg.get('verified_questions', {}):
        return cfg['verified_questions'][normalized] or None, 'verified question'
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
