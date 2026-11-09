"""Build reviewable resume previews from local, existing resume text."""

import re
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from .core import ROOT

MOVABLE = {
    'experience', 'work experience', 'professional experience', 'relevant experience',
    'technical experience', 'projects', 'project experience', 'selected projects',
    'technical projects', 'personal projects', 'academic projects', 'skills', 'technical skills',
}
FIXED = {
    'summary', 'professional summary', 'career summary', 'profile', 'objective', 'education',
    'certifications', 'certifications and training', 'coursework', 'relevant coursework',
    'awards', 'honors', 'honors and awards', 'activities', 'leadership',
    'leadership and activities', 'volunteer experience', 'languages', 'publications',
}
STOP_WORDS = set(
    'about across also and are can company employees for from have help into job join more '
    'our role team than that the their them these this those through use using who will with '
    'work working would you your years experience requirements qualifications skills'.split()
)
TOKEN = re.compile(r'[a-z][a-z0-9]*(?:\+\+|#)?')


def keywords(text):
    tokens = set(TOKEN.findall(text.casefold()))
    return {word for word in tokens if len(word) > 2 or word in {'c++', 'c#', 'ai', 'qa', 'ml', 'ui', 'ux'}} - STOP_WORDS


def read_resume(source):
    if source.suffix.lower() == '.txt':
        return source.read_text(encoding='utf-8-sig')
    if source.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(source)
            if reader.is_encrypted:
                raise ValueError('Use an unlocked PDF or a UTF-8 text resume.')
            return '\n'.join(page.extract_text() for page in reader.pages)
        except PdfReadError as error:
            raise ValueError('Could not read the PDF. Use a readable PDF or UTF-8 text resume.') from error
    raise ValueError('Tailoring supports a text-based PDF or UTF-8 text resume.')


def tailor_text(source, job):
    blocks = [('', [])]
    for line in source.splitlines():
        label = line.strip().rstrip(':').casefold()
        if label in MOVABLE or label in FIXED:
            blocks.append((label, []))
        blocks[-1][1].append(line)

    movable = [index for index, (label, _) in enumerate(blocks) if label in MOVABLE]
    if len(movable) < 2:
        raise ValueError('Could not find two recognizable experience, project, or skills sections.')

    title = keywords(job['title'])
    description = keywords(job['description'])

    def relevance(index):
        terms = keywords('\n'.join(blocks[index][1][1:]))
        return 3 * len(title & terms) + len(description & terms)

    # Reorder entire sections while keeping each role, date, and bullet together.
    ranked = iter(blocks[index] for index in sorted(movable, key=relevance, reverse=True))
    result = [next(ranked) if label in MOVABLE else (label, lines) for label, lines in blocks]
    content = '\n\n'.join('\n'.join(lines).strip('\n') for _, lines in result if lines).strip('\n')
    order = [lines[0].strip() for label, lines in result if label in MOVABLE]
    return content + '\n', order


def write_preview(source, job):
    text = read_resume(source)
    if not text.strip():
        raise ValueError('No text could be extracted. Use a text-based PDF or UTF-8 text resume.')
    preview, order = tailor_text(text, job)
    key = sha256(f'{job["id"]}\n{preview}'.encode()).hexdigest()[:16]
    folder = ROOT / 'private' / 'resumes'
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f'resume-{key}.txt'

    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                            suffix='.tmp', delete=False) as temporary:
        temporary.write(preview)
    path = Path(temporary.name)
    try:
        path.replace(destination)
    finally:
        path.unlink(missing_ok=True)
    return destination, order
