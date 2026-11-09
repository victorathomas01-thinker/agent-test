"""Adapters for public posting APIs with distinct discovery workflows."""

import re
from urllib.parse import quote, urlsplit


def smartrecruiters_jobs(slug, company, maximum, fetch, plain):
    token = quote(slug, safe='')
    base = f'https://api.smartrecruiters.com/v1/companies/{token}/postings'
    limit = min(maximum, 12)
    listing = fetch(f'{base}?limit={limit}&country=us&destination=PUBLIC')
    for posting in listing['content'][:limit]:
        identifier = str(posting.get('id', ''))
        if not re.fullmatch(r'\d+', identifier):
            continue
        details = fetch(f'{base}/{identifier}')
        url = details.get('postingUrl') or ''
        address = urlsplit(url)
        if (address.scheme != 'https' or address.netloc != 'jobs.smartrecruiters.com'
                or not address.path.casefold().startswith(f'/{slug.lower()}/{identifier}-')):
            continue
        sections = (details.get('jobAd') or {}).get('sections') or {}
        description = ' '.join(plain((sections.get(key) or {}).get('text'))
                               for key in ('jobDescription', 'qualifications', 'additionalInformation'))
        location = details.get('location') or posting.get('location') or {}
        region = ', '.join(str(location[key]) for key in ('city', 'region') if location.get(key))
        if location.get('remote') and str(location.get('country', '')).casefold() == 'us':
            region = 'Remote US'
        yield {
            'id': f'smartrecruiters:{slug}:{identifier}', 'source': 'smartrecruiters', 'company': company,
            'title': details.get('name') or posting.get('name') or '', 'location': region,
            'url': url, 'description': description, 'published_at': details.get('releasedDate') or '',
            'workplace': location.get('locationType') or '',
            'employment_type': (details.get('typeOfEmployment') or {}).get('label') or '',
        }
