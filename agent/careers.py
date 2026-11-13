"""Bounded read-only discovery on explicitly configured employer career origins."""

import hashlib
import json
import re
import socket
from html.parser import HTMLParser
from ipaddress import ip_address
from time import sleep
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

USER_AGENT = 'PersonalJobAgent'
POSTING_PATH = re.compile(r'/(?:jobs?|postings?|careers?|jobdetail|positions?)/[^/?#]+', re.I)


class CareerHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.schemas = []
        self.links = []
        self.script = None
        self.link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.script = []
        elif tag == 'a' and attrs.get('href'):
            self.link = (attrs['href'], [])

    def handle_data(self, text):
        if self.script is not None:
            self.script.append(text)
        if self.link is not None:
            self.link[1].append(text)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            try:
                self.schemas.append(json.loads(''.join(self.script)))
            except (ValueError, RecursionError):
                pass
            self.script = None
        elif tag == 'a' and self.link is not None:
            self.links.append((self.link[0], ' '.join(' '.join(self.link[1]).split())))
            self.link = None


def origin(url):
    value = urlsplit(url)
    if value.scheme != 'https' or value.username is not None or value.port not in (None, 443):
        return None
    return value.hostname


def same_origin(url, host):
    try:
        return host is not None and origin(url) == host
    except ValueError:
        return False


def public_host(host):
    if not host or '.' not in host:
        return False
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        return bool(addresses) and all(ip_address(address).is_global for address in addresses)
    except (OSError, ValueError):
        return False


def read_public(url, host):
    class SameOriginRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not same_origin(newurl, host):
                raise ValueError('Career page redirected outside its configured origin.')
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    if not same_origin(url, host):
        raise ValueError('Unsupported career URL.')
    with build_opener(SameOriginRedirect()).open(
            Request(url, headers={'User-Agent': USER_AGENT}), timeout=12) as response:
        return response.read(2_000_000).decode(response.headers.get_content_charset() or 'utf-8', errors='replace')


def posting_objects(node, depth=0):
    if depth > 12:
        return
    if isinstance(node, list):
        for item in node:
            yield from posting_objects(item, depth + 1)
    elif isinstance(node, dict):
        types = node.get('@type', [])
        if 'JobPosting' in ([types] if isinstance(types, str) else types or []):
            yield node
        for key in ('@graph', 'itemListElement', 'item', 'mainEntity'):
            if key in node:
                yield from posting_objects(node[key], depth + 1)


def extract(html, page, company, plain):
    parser = CareerHTML()
    parser.feed(html)
    host = origin(page)
    jobs = []
    for schema in parser.schemas:
        for item in posting_objects(schema):
            title = item.get('title') or item.get('name')
            url = urljoin(page, item.get('url') or page)
            if not isinstance(title, str) or not same_origin(url, host):
                continue
            locations = item.get('jobLocation') or []
            if isinstance(locations, dict):
                locations = [locations]
            places = []
            for place in locations:
                address = place.get('address') if isinstance(place, dict) else None
                if isinstance(address, dict):
                    places.append(', '.join(str(address.get(key)) for key in ('addressLocality', 'addressRegion')
                                            if address.get(key)))
            description = item.get('description') or ''
            jobs.append(posting(url, company, title, '; '.join(filter(None, places)),
                                plain(description) if isinstance(description, str) else '',
                                published_at=item.get('datePosted') or '', deadline=item.get('validThrough') or '',
                                employment_type=str(item.get('employmentType') or ''),
                                workplace=str(item.get('jobLocationType') or ''), verification='structured'))
    links = {}
    for href, label in parser.links:
        url = urljoin(page, href).split('#', 1)[0]
        if (same_origin(url, host) and POSTING_PATH.search(urlsplit(url).path)
                and len(label) >= 5 and label.casefold() not in {'view job', 'search jobs', 'all jobs', 'apply now', 'learn more'}):
            links.setdefault(url, label)
    return jobs, links


def posting(url, company, title, location='', description='', **metadata):
    identity = hashlib.sha256(url.split('#', 1)[0].encode()).hexdigest()[:24]
    return dict(id=f'careers:{identity}', source='careers', company=company, title=title,
                location=location, url=url, description=description, **metadata)


def rendered_html(page, url, host, permits):
    page.route('**/*', lambda route: route.continue_()
               if same_origin(route.request.url, host) and permits(route.request.url)
               and route.request.method == 'GET' else route.abort())
    response = page.goto(url, wait_until='domcontentloaded', timeout=12000)
    if not response or not response.ok or not same_origin(page.url, host):
        raise ValueError('Career page did not return a permitted public response.')
    from playwright.sync_api import TimeoutError as BrowserTimeout

    try:
        page.locator('script[type="application/ld+json"], a[href*="/jobs/"], a[href*="/postings/"]').first.wait_for(
            state='attached', timeout=2500)
    except BrowserTimeout:
        pass
    return page.content()


def crawl_careers(seed, budget, plain, fetch=read_public, render=None):
    url = seed['url']
    company = seed['company']
    host = origin(url)
    if not public_host(host):
        raise ValueError('Career origin must resolve only to public HTTPS addresses.')
    robots = RobotFileParser()
    try:
        robots.parse(fetch(f'https://{host}/robots.txt', host).splitlines())
    except OSError as error:
        if getattr(error, 'code', None) != 404:
            raise
        robots.parse([])
    permits = lambda link: robots.can_fetch(USER_AGENT, link)
    if not permits(url):
        raise ValueError('The career page is disallowed by robots.txt.')

    found, links = extract(fetch(url, host), url, company, plain)
    if seed.get('render') and not found and not links and render:
        found, links = extract(render(url, host, permits), url, company, plain)
    jobs = {job['url']: job for job in found if permits(job['url'])}
    for link, label in list(links.items())[:budget]:
        if link in jobs or not permits(link):
            continue
        sleep(max(0.5, robots.crawl_delay(USER_AGENT) or 0))
        try:
            details, _ = extract(fetch(link, host), link, company, plain)
            if not details and seed.get('render') and render:
                details, _ = extract(render(link, host, permits), link, company, plain)
        except (OSError, ValueError):
            details = []
        if details:
            jobs.update({job['url']: job for job in details if permits(job['url'])})
        else:
            jobs[link] = posting(link, company, label, verification='unverified')
    return list(jobs.values())


def discover_sites(seeds, budget, plain, report=None):
    from contextlib import ExitStack
    from playwright.sync_api import Error as BrowserError, sync_playwright

    jobs, errors = [], []
    with ExitStack() as resources:
        browser = None
        if any(seed.get('render') for seed in seeds):
            try:
                playwright = resources.enter_context(sync_playwright())
                browser = playwright.chromium.launch(headless=True)
                resources.callback(browser.close)
            except BrowserError:
                errors.append('Career renderer unavailable. Static extraction will still run.')

        def render(url, host, permits):
            page = browser.new_page(service_workers='block', accept_downloads=False)
            try:
                return rendered_html(page, url, host, permits)
            finally:
                page.close()

        for seed in seeds:
            raw_url = seed.get('url', '') if isinstance(seed, dict) else ''
            key = 'site:' + hashlib.sha256(str(raw_url).encode('utf-8')).hexdigest()[:16]
            try:
                postings = crawl_careers(seed, budget, plain, render=render if browser else None)
                jobs.extend(postings)
                if not postings:
                    status, detail = 'empty', 'no_extractable_postings; not_verified_empty_market'
                    errors.append(f'{seed["company"]}: no postings could be extracted from the configured page.')
                else:
                    status = 'partial'
                    detail = ('unverified_posting_links' if any(
                        job.get('verification') != 'structured' for job in postings)
                        else 'bounded_crawl; no_completeness_proof')
                if report is not None:
                    report.append(dict(kind='employer_site', key=key, status=status,
                                       records=len(postings), detail=detail))
            except (OSError, ValueError, KeyError, TypeError, BrowserError) as error:
                if report is not None:
                    message = str(error).casefold()
                    blocked = ('robots.txt' in message or 'http error 403' in message
                               or 'disallowed' in message)
                    report.append(dict(kind='employer_site', key=key,
                                       status='blocked' if blocked else 'error',
                                       records=0, detail=type(error).__name__))
                label = seed.get('company', 'Career site') if isinstance(seed, dict) else 'Career site'
                errors.append(f'{label}: {error}')
    return jobs, errors
