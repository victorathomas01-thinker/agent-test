import json
import re
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from .core import ROOT, add_attempt, answer_for
from .sessions import requires_sign_in

FIELDS = 'input, textarea, select, [role="combobox"], [role="listbox"], [role="textbox"]'
SUPPORTED = {'text', 'email', 'tel', 'url', 'number', 'textarea', 'select-one'}
IDENTITY_FIELDS = (
    'input[type=email], input[autocomplete=email], input[name*=email i], input[id=email i], '
    'input[autocomplete=given-name], input[name=first_name i], input[name=firstName i]'
)


def field_metadata(scope):
    return scope.locator(FIELDS).evaluate_all("""elements => elements.map((e, index) => {
      const labelText = node => node?.textContent.trim() || '';
      const ariaName = node => (node?.getAttribute('aria-labelledby') || '').split(/\\s+/)
        .map(id => labelText(document.getElementById(id))).filter(Boolean).join(' ')
        || node?.getAttribute('aria-label') || '';
      const label = [...(e.labels || [])].map(labelText).join(' ');
      const role = e.getAttribute('role');
      const custom = ['combobox', 'listbox', 'textbox'].includes(role) && e.tagName !== 'SELECT';
      const group = ['radio', 'checkbox'].includes(e.type) &&
        e.closest('fieldset, [role="radiogroup"], [role="group"]');
      const listbox = document.getElementById(e.getAttribute('aria-controls') || '');
      const options = e.tagName === 'SELECT' ? [...e.options].filter(o => !o.matches(':disabled'))
        .map(o => ({text: o.text, value: o.value})) :
        [...(listbox || e).querySelectorAll('[role="option"]:not([aria-disabled="true"])')]
          .map(o => ({text: labelText(o), value: labelText(o)}));
      return {
        index, type: custom ? 'custom' : e.type, role, name: e.name || '', id: e.id,
        label: ariaName(e) || label || e.placeholder || '',
        group: group ? elements.findIndex(node => group.contains(node)) : -1,
        question: group ? ariaName(group) || labelText(group.querySelector(':scope > legend')) : '',
        required: e.required || !!e.closest('[aria-required="true"]')
          || /\\*\\s*$/.test(ariaName(e) || label)
          || !!group && /\\*\\s*$/.test(labelText(group.querySelector(':scope > legend'))),
        visible: !!e.getClientRects().length && getComputedStyle(e).visibility === 'visible'
          && !e.closest('[aria-hidden="true"]'),
        disabled: e.matches(':disabled, [aria-disabled="true"]') || e.readOnly,
        options,
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


def is_resume_field(field):
    label = f'{field["label"]} {field["name"]} {field["id"]}'
    return field['type'] == 'file' and bool(
        re.search(r'\b(resume|résumé|cv)\b', re.sub(r'[_-]', ' ', label), re.I)
    )


def grouped_choices(page, groups, cfg, filled, unresolved):
    for fields in groups.values():
        first = fields[0]
        question = first['question'].strip().rstrip('*').strip()
        required = any(field['required'] for field in fields)
        reason = 'requires manual input'
        if first['type'] == 'radio' and question:
            answer, key = answer_for(question, cfg)
            matches = [field for field in fields if answer is not None and
                       answer.strip().casefold() == field['label'].strip().casefold()]
            if len(matches) == 1:
                try:
                    page.locator(FIELDS).nth(matches[0]['index']).check(timeout=3000)
                    filled.append(key)
                    continue
                except Exception:
                    reason = 'browser could not select radio option'
            else:
                reason = 'no unique radio option for a verified answer'
        unresolved.append({'field': (question or first['name'] or first['label'])[:160],
                           'required': required, 'reason': reason})


def has_later_step(page):
    controls = page.get_by_role(
        'button', name=re.compile(
            r'^(?:next(?: step| page)?|(?:save and )?continue(?: to .+)?)\s*[›→]?$', re.I
        )
    )
    return any(button.is_visible() and button.evaluate(
        "element => !!element.closest('form, [role=form]')"
    ) for button in controls.all())


def apply_to_page(page, cfg, live=False):
    if live:
        return 'needs_review', 'Live submission is disabled.'

    filled, unresolved, groups = [], [], {}
    for field in field_metadata(page):
        kind = field['type']
        if field['disabled'] or kind in {'hidden', 'submit', 'button', 'reset', 'image'}:
            continue
        label = field['label'].strip().rstrip('*').strip()
        identifier = field['name'] or field['id']
        name = (label or identifier or f'field {field["index"] + 1}')[:160]
        is_resume = is_resume_field(field)
        if not field['visible'] and not is_resume:
            continue
        if kind in {'radio', 'checkbox'} and field['group'] >= 0:
            group_key = (kind, field['group'], field['name'] if kind == 'radio' else '')
            groups.setdefault(group_key, []).append(field)
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
            elif kind == 'custom':
                answer, key = answer_for(label or identifier, cfg)
                option = choose_option(field['options'], answer) if answer is not None else None
                reason = ('verified choice available, selection requires manual input' if option
                          else 'custom control requires manual input')
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
                        if node.evaluate('(e) => e.validity.valid'):
                            filled.append(key)
                            continue
                        reason = 'value does not satisfy field validation'
                else:
                    reason = 'no verified answer'
        except Exception:
            reason = 'browser could not fill field'
        unresolved.append({'field': name, 'required': field['required'], 'reason': reason})

    grouped_choices(page, groups, cfg, filled, unresolved)
    if has_later_step(page):
        unresolved.append({'field': 'later application steps', 'required': True,
                           'reason': 'preview covers the current step only'})
    if 'email' not in filled or not {'first_name', 'full_name', 'resume'}.intersection(filled):
        unresolved.append({'field': 'application form', 'required': True,
                           'reason': 'could not identify and fill applicant name or resume and email'})
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
    from playwright.sync_api import sync_playwright

    address = urlsplit(url)
    if address.scheme != 'https' or not address.hostname or address.username is not None:
        return 'needs_review', 'An HTTPS application URL without credentials is required.'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=cfg['automation'].get('headless', True))
        try:
            source = browser.new_context(accept_downloads=False, service_workers='block')
            page = source.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            if requires_sign_in(page):
                return 'needs_review', 'Sign-in needed.'
            if response is None or not response.ok:
                return 'needs_review', 'Application page was unavailable.'
            frame = find_form_frame(page)
            if frame is None:
                if requires_sign_in(page):
                    return 'needs_review', 'Sign-in needed.'
                return 'needs_review', 'Could not locate an application form on the page.'
            snapshot = frame.content()
            source.close()
            return preview_snapshot(browser, snapshot, cfg)
        finally:
            browser.close()


def find_form_frame(page):
    from playwright.sync_api import Error as PlaywrightError

    deadline = monotonic() + 7
    while monotonic() < deadline:
        for frame in page.frames:
            try:
                if frame.locator(f':is({IDENTITY_FIELDS}):visible').count():
                    return frame
            except PlaywrightError:
                # Some frames detach while an application page is loading.
                continue
        page.wait_for_timeout(150)
    return None


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
