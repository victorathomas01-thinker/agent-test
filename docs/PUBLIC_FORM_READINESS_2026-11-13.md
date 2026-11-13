# Real public form structures and conservative offline-readiness checks

**Review-only engineering milestone — November 13, 2026.** These are two individual publicly visible employer-form observations. Neither is a form-submission benchmark or a claim that a job is still accepting applications.

## Two concrete, read-only public form observations

| Observed provider and sample | Visible controls | Required controls | Main manual obstacle | Verification |
| --- | ---: | ---: | --- | --- |
| Lever / Zoox, one public application step (November 12) | 34 | 13 | **8 required native checkboxes** | [One-time public Lever form read](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43361435744) |
| Greenhouse / Canonical, one public application step (November 13) | 28 | 17 | **10 required custom/unsupported controls**, out of 18 custom controls visible | [One-time public Greenhouse form read](https://github.com/victorathomas01-thinker/agent-test/actions/runs/43381042657) |

The Greenhouse observation also showed one required file input, three required plain text inputs and three required textareas. Its full visible type breakdown was 18 custom controls, five text inputs, three textareas, one telephone input and one file input. **These are raw control counts; controls such as ARIA listboxes may contain nested options, and the counts do not prove independent questions or unique blockers.**

Both checks used a fresh browser context with downloads blocked, **GET/HEAD requests only**, and no access to user profiles, résumés, verified answers, browser sessions or applicant credentials. Public pages were selected from official ATS listings and checked for allowed application hosts. The Greenhouse probe checked robots.txt for the two recognized Greenhouse public board aliases and performed no input, click, upload, POST or Submit. The only output was aggregate field types and required-flag counts; individual question labels and source posting identifiers were not logged.

The Greenhouse probe intentionally blocked external scripts and resources, so a fully rendered ordinary browser form could differ. The older Lever probe similarly blocked third-party resources. This is only the currently visible portion of a form and might miss conditional or later-step questions. Form HTML may change without notice.

## Engineering correction

A required custom checkbox implemented as `<div role="checkbox" aria-required="true">` is not a native HTML input, and was previously outside the browser's `FIELDS` selector. The offline analyzer now recognizes ARIA-only checkboxes, radio choices and switches in addition to existing combobox/listbox/textbox controls. It marks **required** custom choices as unresolved manual input and never silently toggles them. Native checkboxes still require explicit applicant review.

The fix deliberately **preserves the previous behavior for input-based ARIA comboboxes**, which can appear in many employer dropdowns. An initial version of the selector incorrectly treated some input comboboxes as ordinary text; existing regression tests detected this and the implementation was corrected before release.

The public-form statistics reporter now counts mandatory checkboxes, native radio choices, file uploads, required custom/unknown controls and the presence of manual/verified decision-making, **without collecting personal application questions**.

## Fictional offline stress tests, not simulated real employer answers

A wholly synthetic 34-control form reproduces only the earlier Lever aggregate shape (19 checkboxes, four selects, seven text inputs, two textareas, one email and one file input, with 13 required). The offline `apply_to_page` result must remain `needs_review` and all eight required native checkboxes must remain unchecked, even when contact information is supplied by a fictional profile.

A separate fictional 28-control form reproduces only the Greenhouse aggregate shape (18 custom, five text, three textarea, one telephone and one file input, with 17 required). The 10 required custom controls cannot be silently resolved, and missing resume information must still appear as a blocker.

A third fixture exercises aria-required custom checkbox, radios and switch controls; the analyzer must see their required status and leave `aria-checked` unchanged. Tests also distinguish optional custom controls from required ones.

None of these synthetic fixtures is an applicant's genuine employer application. Even a synthetic `prepared` result is **only a detached current-step assessment**, not proof that the live employer form is ready to submit.

## Practical next release gates

1. Run `python main.py doctor` and `python main.py pilot-audit --offline-only` on the user's own local historical database *when available*. We still cannot diagnose the original 20 actual form attempts from GitHub summary data alone.
2. Independently test representative live form structures across a broader ATS sample, with read-only robots-respecting access. Do not generalize these two findings into employer-wide rates.
3. Consider safe assisted handling of supported **non-attestation** custom controls on a local detached synthetic form only, with exact verified answers and rigorous DOM tests. Never infer mandatory legal acknowledgements, demographic answers or employer-specific responses to make a score green.
4. Keep real submission **attended and user-operated**; an ATS posting visible over API does not guarantee that its application form remains open.

No changes were installed on a user's machine; `main` remains unchanged and live submission stays disabled in the development workflow.
