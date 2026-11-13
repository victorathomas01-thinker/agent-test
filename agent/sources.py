"""Adapters for public posting APIs with distinct discovery workflows."""

import re
from urllib.parse import quote, urlsplit


def smartrecruiters_jobs(slug, company, maximum, fetch, plain, audit=None):
    """Read public US listings through documented offset/limit/totalFound paging.

    If a detail fetch or page fails after previous pages, preserve collected
    rows but never declare the board complete or expire older listings.
    """
    if not isinstance(maximum, int) or maximum < 1:
        raise ValueError("Positive SmartRecruiters posting cap required.")
    token = quote(slug, safe="")
    base = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    offset, found, complete, total_found, has_total = 0, [], True, None, False
    seen_ids = set()
    while offset < maximum:
        limit = min(100, maximum - offset)
        try:
            listing = fetch(f"{base}?offset={offset}&limit={limit}&country=us&destination=PUBLIC")
            entries = listing["content"]
            if not isinstance(entries, list):
                raise ValueError("Malformed SmartRecruiters list.")
            total = listing.get("totalFound")
            if isinstance(total, int) and total >= 0:
                if total_found is not None and total != total_found:
                    complete = False
                total_found = total
                has_total = True
            else:
                complete = False
        except (OSError, ValueError, KeyError, TypeError):
            if offset == 0:
                raise
            complete = False
            break

        if not entries:
            if total_found is None or offset < total_found:
                complete = False
            break
        offset += len(entries)
        for posting in entries:
            identifier = str(posting.get("id", "")) if isinstance(posting, dict) else ""
            if not re.fullmatch(r"\d+", identifier) or identifier in seen_ids:
                complete = False
                continue
            seen_ids.add(identifier)
            try:
                details = fetch(f"{base}/{identifier}")
                if not isinstance(details, dict):
                    raise ValueError("Malformed SmartRecruiters details.")
                url = details.get("postingUrl") or ""
                address = urlsplit(url)
                if (address.scheme != "https" or address.hostname != "jobs.smartrecruiters.com"
                        or address.username is not None
                        or not address.path.casefold().startswith(f"/{slug.lower()}/{identifier}-")):
                    complete = False
                    continue
                sections = (details.get("jobAd") or {}).get("sections") or {}
                description = " ".join(plain((sections.get(key) or {}).get("text"))
                                       for key in ("jobDescription", "qualifications", "additionalInformation"))
                location = details.get("location") or posting.get("location") or {}
                region = ", ".join(str(location[key]) for key in ("city", "region") if location.get(key))
                if location.get("remote") and str(location.get("country", "")).casefold() == "us":
                    region = "Remote US"
                found.append({
                    "id": f"smartrecruiters:{slug}:{identifier}",
                    "source": "smartrecruiters", "company": company,
                    "title": details.get("name") or posting.get("name") or "",
                    "location": region, "url": url, "description": description,
                    "published_at": details.get("releasedDate") or "",
                    "workplace": location.get("locationType") or "",
                    "employment_type": (details.get("typeOfEmployment") or {}).get("label") or "",
                })
            except (OSError, ValueError, KeyError, TypeError):
                complete = False
                continue

        if total_found is not None and offset >= total_found:
            break
        if not has_total or len(entries) < limit:
            complete = False
            break

    complete = bool(complete and has_total and total_found is not None
                    and offset >= total_found and len(found) == len(seen_ids))
    if audit is not None:
        audit.update(complete=complete, returned=len(found), total=total_found,
                     reason="all_public_pages" if complete else "partial_or_unknown_pagination")
    return found
