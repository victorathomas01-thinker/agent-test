import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .core import ROOT, add_attempt, answer_for

FIELDS = 'input, textarea, select'
SUPPORTED = {'text', 'email', 'tel', 'url', 'number', 'textarea', 'select-one'}


def field_metadata(page):
    return page.eval_on_selector_all(FIELDS, """elements => elements.map((e, index) => {
      const label = [...(e.labels || [])].map(n => n.textContent.trim()).join(' ');
      const aria = (e.getAttribute('aria-labelledby') || '').split(/\\s+/)
        .map(id => document.getElementById(id)?.textContent.trim()).filter(Boolean).join(' ');
      return {
        index, type: e.type, name: e.name, id: e.id,
        label: aria || e.getAttribute('aria-label') || label || e.placeholder || '',
        required: e.required || e.getAttribute('aria-required') === 'true'
          || !!e.closest('[aria-required="true"]') || /\\*\\s*$/.test(label),
        visible: !!e.getClientRects().length && getComputedStyle(e).visibility === 'visible',
        disabled: e.matches(':disabled') || e.readOnly,
        options: e.tagName === 'SELECT' ? [...e.options].filter(o => !o.disabled)
          .map(o => ({text: o.text, value: o.value})) : [],
      };
    })""")


def choose_option(options, answer):
    normalized = answer.strip().casefold()
    matches = [o['value'] for o in options if o['value'] and
               normalized in (o['text'].strip().casefold(), o['value'].strip().casefold())]
    return matches[0] if len(matches) == 1 else None


def resume_file(cfg):
    value = cfg['profile'].get('resume_path')
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if path.suffix.lower() in {'.pdf', '.docx', '.doc', '.txt', '.rtf'} and path.is_file():
        return path.resolve()
    return None


def apply_to_page(page, cfg, live=False):
    if live:
        return 'needs_review', 'Live submission is disabled.'

    filled, unresolved = [], []
    for field in field_metadata(page):
        kind = field['type']
        if field['disabled'] or kind in {'hidden', 'submit', 'button', 'reset', 'image'}:
            continue
        label = field['label'].strip().rstrip('*').strip()
        identifier = field['name'] or field['id']
        name = (label or identifier or f'field {field["index"] + 1}')[:160]
        upload_label = re.sub(r'[_-]', ' ', f'{label} {identifier}')
        is_resume = kind == 'file' and re.search(r'\b(resume|résumé|cv)\b', upload_label, re.I)
        if not field['visible'] and not is_resume:
            continue
        node = page.locator(FIELDS).nth(field['index'])
        reason = 'requires manual input'
        try:
            if is_resume:
                resume = resume_file(cfg)
                if resume is not None:
                    node.set_input_files(str(resume), timeout=3000)
                    filled.append('resume')
                    continue
                reason = 'resume file missing or unsupported'
            elif kind in SUPPORTED:
                answer, key = answer_for(label or identifier, cfg)
                if answer is not None:
                    if kind == 'select-one':
                        option = choose_option(field['options'], answer)
                        if option is not None:
                            node.select_option(value=option, timeout=3000)
                            filled.append(key)
                            continue
                        reason = 'no unique matching dropdown option'
                    else:
                        node.fill(answer, timeout=3000)
                        filled.append(key)
                        if node.evaluate('(e) => e.validity.valid'):
                            continue
                        reason = 'value does not satisfy field validation'
                else:
                    reason = 'no verified answer'
        except Exception:
            reason = 'browser could not fill field'
        unresolved.append({'field': name, 'required': field['required'], 'reason': reason})

    if 'email' not in filled or not {'first_name', 'full_name', 'resume'}.intersection(filled):
        unresolved.append({'field': 'application form', 'required': True,
                           'reason': 'could not identify and fill applicant name or resume and email'})
    if page.locator('[role="combobox"][aria-required="true"]:not(input, select):visible').count():
        unresolved.append({'field': 'custom dropdown', 'required': True,
                           'reason': 'requires manual input'})
    outcome = 'prepared' if not any(f['required'] for f in unresolved) else 'needs_review'
    return outcome, json.dumps({'filled': filled, 'unresolved': unresolved, 'mode': 'dry-run'})


def run_browser(job, cfg, live=False):
    if live:
        result = ('needs_review', 'Live submission is disabled.')
    else:
        try:
            result = preview(job['url'], cfg)
        except Exception as error:
            result = ('failed', f'Browser preview failed ({type(error).__name__}).')
    add_attempt(job['id'], *result)
    return result


def preview(url, cfg):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

    address = urlsplit(url)
    if address.scheme != 'https' or not address.hostname or address.username is not None:
        return 'needs_review', 'An HTTPS application URL without credentials is required.'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=cfg['automation'].get('headless', True))
        try:
            source = browser.new_context(accept_downloads=False, service_workers='block')
            page = source.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            if response is None or not response.ok:
                return 'needs_review', 'Application page was unavailable.'
            try:
                page.locator('input[type=email], input[autocomplete=email], input[name*=email i]').first.wait_for(
                    state='attached', timeout=7000
                )
            except PlaywrightTimeoutError:
                return 'needs_review', 'Could not locate an application form on the page.'
            snapshot = page.content()
            source.close()
            return preview_snapshot(browser, snapshot, cfg)
        finally:
            browser.close()


def preview_snapshot(browser, snapshot, cfg):
    # Only the detached copy receives applicant data.
    offline = browser.new_context(java_script_enabled=False, offline=True,
                                  service_workers='block', accept_downloads=False)
    try:
        offline.route('**/*', lambda route: route.abort())
        copy = offline.new_page()
        copy.set_content(snapshot, wait_until='domcontentloaded', timeout=10000)
        return apply_to_page(copy, cfg)
    finally:
        offline.close()
