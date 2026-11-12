"""Build versioned local review packages from the applicant's source resume."""

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from . import core
from .resume import keywords, read_resume, tailor_text

CATEGORIES = {
    'support': ('support', 'help desk', 'technician', 'clinical', 'healthcare', 'implementation'),
    'analytics': ('analytics', 'analyst', 'data', 'reporting', 'business intelligence'),
}


def prepare_package(source, job, *, cover=False):
    if not source or not source.is_file():
        raise ValueError('A readable master resume is required.')
    original = source.read_bytes()
    resume = read_resume(source)
    if source.read_bytes() != original:
        raise ValueError('The master resume changed during preparation.')
    if not resume.strip():
        raise ValueError('The master resume contains no readable text.')
    tailored, order = tailor_text(resume, job)
    if Counter(line for line in tailored.splitlines() if line.strip()) != Counter(
            line for line in resume.splitlines() if line.strip()):
        raise ValueError('Tailored resume did not preserve all source lines.')

    title = job['title'].casefold()
    category = next((key for key, signals in CATEGORIES.items() if any(s in title for s in signals)), 'development')
    terms = keywords(job['title'] + ' ' + job['description'])
    evidence = sorted(keywords(resume) & terms)
    posting_hash = sha256(job['description'].encode()).hexdigest()
    manifest = {
        'job_id': job['id'], 'title': job['title'], 'employer': job['company'],
        'posting_url': job['url'], 'posting_sha256': posting_hash,
        'source_sha256': sha256(original).hexdigest(), 'category': category,
        'source_extension': source.suffix.lower(), 'section_order': order,
        'overlapping_terms': evidence, 'resume_format': 'text',
        'cover_letter': 'none',
    }
    letter = None
    if cover:
        lines = [line.strip() for line in resume.splitlines()
                 if len(line.strip()) >= 45 and line.strip().startswith(('•', '-', '–'))]
        strongest = max(lines, key=lambda line: len(keywords(line) & terms), default='')
        if strongest and keywords(strongest) & terms:
            employer = ' '.join(job['company'].split())
            role = ' '.join(job['title'].split())
            letter = (f'Dear {employer} hiring team,\n\n'
                      f'I am applying for the {role} position. One relevant example from my resume is:\n\n'
                      f'{strongest}\n\nThank you for considering my application.\n')
            manifest['cover_letter'] = 'draft_requires_review'
    serialized = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
    version = sha256((serialized + tailored + (letter or '')).encode()).hexdigest()[:20]
    parent = core.ROOT / 'private' / 'packages'
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / version
    if not destination.is_dir():
        with TemporaryDirectory(dir=parent) as temporary:
            stage = Path(temporary) / 'package'
            stage.mkdir()
            (stage / 'resume.txt').write_text(tailored, encoding='utf-8')
            (stage / ('master' + source.suffix.lower())).write_bytes(original)
            (stage / 'manifest.json').write_text(serialized + '\n', encoding='utf-8')
            if letter:
                (stage / 'cover-letter-draft.txt').write_text(letter, encoding='utf-8')
            try:
                stage.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
    if ((destination / 'resume.txt').read_text(encoding='utf-8') != tailored
            or (destination / 'manifest.json').read_text(encoding='utf-8') != serialized + '\n'
            or (destination / ('master' + source.suffix.lower())).read_bytes() != original
            or (letter and (destination / 'cover-letter-draft.txt').read_text(encoding='utf-8') != letter)):
        raise ValueError('Stored package failed its integrity check.')
    return destination, version
