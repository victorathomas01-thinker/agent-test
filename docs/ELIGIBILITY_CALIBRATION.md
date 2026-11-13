# Eligibility language: first precision improvements

This is a **small, deterministic improvement** to the candidate-specific evaluation that runs inside the Job Agent. It does not claim to decide full eligibility for real employer postings, and it does not read or publish anyone's local candidate profile.

## Specific changes

The qualification parser now recognizes additional explicit GPA expressions, including:

- `minimum GPA is 3.5`, `3.5 GPA minimum`, `minimum 3.5 cumulative GPA`
- `GPA >= 3.5`, `GPA 3.5+`, `GPA of at least 3.5`
- A numeric applicant GPA stored as text, with safe handling of blank, malformed, out-of-range and nonfinite values

It also identifies narrow *mandatory* graduation requirements:

- `Applicants must graduate by May 2027`
- `Must be graduating by May 2027`
- `Must graduate no earlier than January 2028`

The existing explicit `graduating between <month year> and <month year>` rule remains. The parser compares **calendar months**, not application dates or inferred enrollment years.

Pure preferred GPA/graduation language stays non-disqualifying. Mixed preferred/required GPA language produces a review flag instead of confidently treating the sentence as one hard cutoff. Explicit missing GPA evidence remains reviewable, not a presumed pass. The existing application-preparation eligibility gate stays in place.

## Testing

The new synthetic unit tests exercise several word orders, decimal cutoffs, preferred vs required language, single-ended graduation windows, missing GPA evidence and integration with the existing `core.evaluate` decision. There are no real résumés or employer applications in test fixtures.

## What still needs human-labeled calibration

- Independent manual labels for a representative set of **real** early-career postings from the source bank, including ambiguous hiring requirements.
- Hard vs preferred professional experience and accepted alternatives to experience.
- Exact graduation ranges, class standing, active enrollment, degrees already completed, security clearances, drivers' licenses and mandatory certifications.
- U.S.-only remote/hybrid eligibility, class schedule and paid vs unpaid arrangements.
- False-exclusion and false-approval counts. A passing regex test is not a measured hiring prediction.

**Safety:** No live submissions, browser automation, resumes, applicants, credentials or current default-branch releases are changed in this PR. This is deliberately a review-branch implementation pending user acceptance testing and real-posting classification review.

See [P0 issue #6](https://github.com/victorathomas01-thinker/agent-test/issues/6).
