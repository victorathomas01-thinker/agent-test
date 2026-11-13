"""Source-linked public requirement regression evaluation (synthetic profiles).

This is NOT an independently sampled or externally adjudicated hiring benchmark.
The fixtures contain short paraphrases, never full employer job descriptions
or a real applicant's GPA, employment history, or personal details.
"""
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from .matching import qualifications

DEFAULT_CASES = Path(__file__).resolve().parent.parent / "examples" / "public_requirements_benchmark.json"
LABELS = {"hard_block", "manual_review", "no_block"}
HARD = (
    "Review hard minimum GPA",
    "Graduation outside required window",
    "Graduation later than required cutoff",
    "Graduation earlier than required start",
)


def predicted_class(reasons):
    if any(str(reason).startswith(HARD) for reason in reasons):
        return "hard_block"
    if reasons:
        return "manual_review"
    return "no_block"


def load_cases(filename=DEFAULT_CASES):
    data = json.loads(Path(filename).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("Benchmark fixture must contain an array of cases.")
    unique = set()
    for case in data["cases"]:
        if not isinstance(case, dict):
            raise ValueError("Malformed benchmark case.")
        if not isinstance(case.get("id"), str) or not case["id"] or case["id"] in unique:
            raise ValueError("Benchmark cases require unique identifiers.")
        unique.add(case["id"])
        if case.get("expected") not in LABELS:
            raise ValueError("Benchmark has an invalid expected class.")
        if not isinstance(case.get("requirements"), str) or len(case["requirements"]) > 500:
            raise ValueError("Requirement excerpt must be a short paraphrase.")
        url = urlsplit(case.get("source_url", ""))
        if url.scheme != "https" or not url.hostname or url.username:
            raise ValueError("Benchmark case has no public source URL.")
        profile = case.get("synthetic_profile")
        if (not isinstance(profile, dict)
                or not isinstance(profile.get("graduation"), str)
                or not isinstance(profile.get("gpa"), (int, float))):
            raise ValueError("Benchmark must have an explicit fictional applicant.")
    return data["cases"]


def evaluate_cases(cases):
    rows = []
    for case in cases:
        candidate = case["synthetic_profile"]
        reasons = qualifications(case["requirements"],
                                 {"graduation": candidate["graduation"]},
                                 candidate["gpa"])
        predicted = predicted_class(reasons)
        rows.append({
            "id": case["id"],
            "source": case["source"],
            "expected": case["expected"],
            "predicted": predicted,
            "matches": predicted == case["expected"],
        })
    matrix = Counter((row["expected"], row["predicted"]) for row in rows)
    sources = Counter(row["source"] for row in rows)
    return {
        "cases": len(rows),
        "unique_source_postings": len(sources),
        "matches": sum(row["matches"] for row in rows),
        "mismatched_cases": [row["id"] for row in rows if not row["matches"]],
        "cases_per_posting": dict(sorted(sources.items())),
        "confusion": {
            expected: {predicted: matrix[(expected, predicted)] for predicted in sorted(LABELS)}
            for expected in sorted(LABELS)
        },
    }


def main():
    report = evaluate_cases(load_cases())
    print("PUBLIC-SOURCE WORDING FIXTURE — fictional applicants; curated and nonrepresentative")
    print("Annotated cases:", report["cases"])
    print("Distinct source postings:", report["unique_source_postings"])
    print("Fixture label matches:", report["matches"])
    print("Cases per posting:", report["cases_per_posting"])
    print("Expected x predicted:", report["confusion"])
    print("Mismatched case IDs:", report["mismatched_cases"])
    print("This is a regression match count, NOT real hiring eligibility accuracy.")
    return 0 if not report["mismatched_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
