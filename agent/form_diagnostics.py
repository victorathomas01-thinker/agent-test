"""Summarize local form-preparation blockers without applicant answers.

This reports aggregate labels only. It never opens employers, writes forms,
submits applications, or copies job descriptions/application records.
"""
from collections import Counter
from contextlib import closing
import json

from . import core

CATEGORIES = {
    "no verified answer": "missing_verified_answer",
    "no unique radio option for a verified answer": "radio_choice_ambiguous",
    "no unique matching dropdown option": "dropdown_choice_ambiguous",
    "requires manual input": "manual_question_or_choice",
    "checkbox requires explicit applicant review": "checkbox_attestation_or_choice",
    "checkbox group requires explicit applicant review": "checkbox_group_manual_review",
    "custom control requires manual input": "unsupported_custom_control",
    "verified choice available, selection requires manual input": "unsupported_custom_control",
    "custom dropdown options unavailable offline": "custom_options_not_in_snapshot",
    "multiple matching custom dropdown options": "custom_choice_ambiguous",
    "verified answer absent from custom dropdown options": "custom_choice_unmatched",
    "resume file missing or unsupported": "resume_not_ready",
    "browser could not fill field": "browser_fill_error",
    "browser could not select radio option": "browser_fill_error",
    "value does not satisfy field validation": "validation_error",
    "preview covers the current step only": "later_step_unchecked",
    "could not identify and fill applicant name or resume and email": "identity_or_resume_unresolved",
}

# Fixed, privacy-safe remediation guidance. Never incorporate employer form
# wording or applicant-supplied answers into these public-facing summaries.
BLOCKER_ACTIONS = {
    "missing_verified_answer": "Confirm the exact answer with the applicant before retrying.",
    "radio_choice_ambiguous": "Compare employer options to an explicitly verified answer; do not guess.",
    "dropdown_choice_ambiguous": "Review the exact employer options and previously verified answer.",
    "manual_question_or_choice": "Requires human review of the actual employer question.",
    "checkbox_attestation_or_choice": "Applicant must review and select any required attestation personally.",
    "checkbox_group_manual_review": "Applicant must inspect the checkbox group; never auto-agree.",
    "unsupported_custom_control": "Requires a tested employer-specific control handler or manual review.",
    "custom_options_not_in_snapshot": "Employer widget options are dynamic or not in the saved HTML; review manually.",
    "custom_choice_ambiguous": "More than one option matches the verified answer; inspect the real choices.",
    "custom_choice_unmatched": "Verified answer does not exactly match an available option; review manually.",
    "resume_not_ready": "Verify that the local résumé file exists and uses an accepted format.",
    "browser_fill_error": "Inspect the form's input behavior in a safe offline fixture.",
    "validation_error": "Review the field's validation and applicant-approved answer.",
    "later_step_unchecked": "Additional employer steps remain unchecked; manual progression required.",
    "identity_or_resume_unresolved": "Confirm contact/resume field recognition in an isolated fixture.",
    "login_required": "Applicant must sign in themselves; do not bypass an account gate.",
    "form_not_found": "Manual employer-page review; do not infer readiness.",
    "page_unavailable": "Recheck the official employer page before attempting preparation.",
    "posting_unavailable": "Verify the official posting is still available before applying.",
    "browser_preview_error": "Investigate local browser failure using a synthetic fixture.",
    "unsupported_url": "Replace with an exact, verified HTTPS employer application URL.",
    "other_manual_review": "Human review needed; do not infer applicant information.",
    "unknown": "Unknown required-field blocker; manual review needed.",
}


NON_JSON = (
    ("Sign-in needed.", "login_required"),
    ("Could not locate an application form", "form_not_found"),
    ("Application page was unavailable", "page_unavailable"),
    ("posting returned HTTP 404 or 410", "posting_unavailable"),
    ("Browser preview failed", "browser_preview_error"),
    ("An HTTPS application URL", "unsupported_url"),
)


def classify(reason):
    if not isinstance(reason, str):
        return "unknown"
    for phrase, category in CATEGORIES.items():
        if reason == phrase:
            return category
    for phrase, category in NON_JSON:
        if phrase.casefold() in reason.casefold():
            return category
    return "other_manual_review"



# These weights estimate human attention on the *detached current step*.
# They are not employer-form completion probabilities or application success.
LOW_EFFORT = frozenset({
    "missing_verified_answer", "radio_choice_ambiguous",
    "dropdown_choice_ambiguous", "checkbox_attestation_or_choice",
    "checkbox_group_manual_review", "custom_choice_unmatched",
})
HIGH_EFFORT = frozenset({
    "unsupported_custom_control", "custom_options_not_in_snapshot",
    "browser_fill_error", "validation_error", "resume_not_ready",
    "identity_or_resume_unresolved", "later_step_unchecked",
})
HARD_CAPS = {
    "later_step_unchecked": 40,
    "identity_or_resume_unresolved": 25,
    "custom_options_not_in_snapshot": 50,
    "browser_fill_error": 45,
}


def readiness_for_attempt(outcome, details):
    """Return an explainable offline preparation effort estimate, or unknown.

    Only records generated from detached snapshots qualify. No employer
    requests and no source answer/field labels escape into the result.
    """
    try:
        payload = json.loads(details) if isinstance(details, str) else None
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict) or payload.get("mode") != "dry-run":
        return {"score": None, "tier": "not_assessed",
                "manual_fields": None, "high_effort_fields": None}
    items = payload.get("unresolved")
    if not isinstance(items, list) or not isinstance(payload.get("filled"), list):
        return {"score": None, "tier": "not_assessed",
                "manual_fields": None, "high_effort_fields": None}
    required = [classify(item.get("reason")) for item in items
                if isinstance(item, dict) and item.get("required") is True]
    count_low = sum(kind in LOW_EFFORT for kind in required)
    count_high = sum(kind in HIGH_EFFORT for kind in required)
    unknown = len(required) - count_low - count_high
    points = max(0, 100 - 12 * count_low - 28 * count_high - 25 * unknown)
    for category, cap in HARD_CAPS.items():
        if category in required:
            points = min(points, cap)
    if outcome != "prepared" and not required:
        return {"score": None, "tier": "not_assessed",
                "manual_fields": None, "high_effort_fields": None}
    tier = ("current_step_clear" if not required and outcome == "prepared"
            else "light_manual_review" if points >= 70
            else "substantial_manual_review" if points >= 35
            else "major_blockers")
    return {"score": points, "tier": tier,
            "manual_fields": len(required),
            "high_effort_fields": count_high + unknown}

def latest_reviews(con, limit=500):
    if not isinstance(limit, int) or not 1 <= limit <= 5000:
        raise ValueError("Invalid form audit limit.")
    # Latest attempt per job, not every retry; otherwise large applications
    # are overcounted. No JOIN to applicant profile, verified answers, or notes.
    return con.execute(
        """SELECT a.job_id, a.outcome, a.details FROM attempts a
           JOIN (SELECT job_id, MAX(id) AS last_id FROM attempts GROUP BY job_id)
                recent ON a.job_id=recent.job_id AND a.id=recent.last_id
           WHERE a.outcome IN ('prepared','needs_review','failed','expired')
           ORDER BY a.id DESC LIMIT ?""", (limit,),
    ).fetchall()


def summarize(con, limit=500):
    records = latest_reviews(con, limit)
    outcomes = Counter()
    required_field_categories = Counter()
    jobs_with_category = Counter()
    current_step_prepared = 0
    reviewed_jobs = 0
    readiness_tiers = Counter()
    for row in records:
        outcome = row["outcome"]
        readiness_tiers[readiness_for_attempt(outcome, row["details"])["tier"]] += 1
        outcomes[outcome] += 1
        detail = row["details"]
        try:
            payload = json.loads(detail) if detail else None
        except (ValueError, TypeError):
            payload = None
        categories_this_job = set()
        if isinstance(payload, dict) and payload.get("mode") == "dry-run":
            reviewed_jobs += 1
            unresolved = payload.get("unresolved") or []
            if not isinstance(unresolved, list):
                unresolved = []
            for item in unresolved:
                if not isinstance(item, dict) or item.get("required") is not True:
                    continue
                category = classify(item.get("reason"))
                required_field_categories[category] += 1
                categories_this_job.add(category)
            if outcome == "prepared" and not categories_this_job:
                current_step_prepared += 1
        else:
            # Explicit login/404/failure markers are useful but are not
            # genuine detached-snapshot field diagnostics.
            category = classify(detail)
            if outcome in {"failed", "expired", "needs_review"}:
                categories_this_job.add(category)
                required_field_categories[category] += 1
        for category in categories_this_job:
            jobs_with_category[category] += 1

    return {
        "latest_jobs": len(records),
        "dry_run_previews": reviewed_jobs,
        "prepared_current_step_only": current_step_prepared,
        "offline_readiness_tiers": dict(sorted(readiness_tiers.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "required_blockers": dict(sorted(required_field_categories.items())),
        "jobs_affected": dict(sorted(jobs_with_category.items())),
        "recommended_next_actions": {
            category: BLOCKER_ACTIONS.get(category, BLOCKER_ACTIONS["unknown"])
            for category in sorted(required_field_categories)
        },
    }


def print_report(limit=500):
    with closing(core.connect()) as con:
        report = summarize(con, limit)
    print(f"Form readiness audit: {report['latest_jobs']} latest job attempts; "
          f"{report['dry_run_previews']} disconnected dry-run form previews.")
    print(f"Prepared on current detached step: {report['prepared_current_step_only']} "
          "(NOT a verified live final-submit-ready count).")
    if not report["latest_jobs"]:
        print("No preview attempts yet. Run safe offline preparation first.")
        return
    print("Latest outcomes: " + ", ".join(
        f"{key}={value}" for key, value in report["outcomes"].items()))
    print("Unresolved required-field categories (fields / affected jobs):")
    if not report["required_blockers"]:
        print("  No classified required blockers in the latest attempts.")
    for category, count in sorted(report["required_blockers"].items(),
                                  key=lambda item: (-item[1], item[0])):
        print(f"  {category}: {count} fields / {report['jobs_affected'][category]} jobs")
        print(f"    Next: {report['recommended_next_actions'][category]}")
    print("No application was submitted. Category totals reflect stored local "
          "previews, not employer live-form acceptance.")
