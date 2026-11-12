# Consolidated Job Agent integration review — 2026-11-12

**Review-only branch. Do not merge, change the local scheduler, upload private files, or enable unattended submissions.**

## Frozen baselines

- Main before integration: `11af6a262859847b7507ed9eca69480a5bff032f`
- Latest stacked feature baseline: `0214f4b56711bf4eeb081a854175d60fd9b55bae`
- Sources: PR #1 (`feature/autonomous-preparation`) and PR #2 (`feature/product-bible`)
- The source PRs remain open until the complete combined workflow has been accepted.

## Combined capability in review

- Expanded employer source adapters, canonical job identifiers, retries and eligibility checks
- Weighted/explainable role ranking, local candidate fact store and durable outcome tracking
- Local dashboard, package manifests and evidence-backed writing drafts
- Offline form rehearsal and **attended** Edge preparation

Do not describe this as an autonomous end-to-end application submitter. The development ledger reports that all 20 sampled offline forms still needed manual review, and zero were certified ready for real submission.

## Acceptance checklist

- [ ] Run the full tests on the combined PR head and review results.
- [ ] Test a fresh local install using entirely synthetic config, resumes and application records.
- [ ] Confirm private profile, resume, local SQLite DB, credentials, and confirmation email content are never committed or copied to a public artifact.
- [ ] Compare queue contents and eligibility filtering against saved fixtures, including 2.79 GPA hard limits and December 2027 graduation eligibility (private values belong in local configuration only).
- [ ] Validate deduplication after repeat imports and canonical URL changes.
- [ ] Verify the dashboard shows all listings, exclusions and reasons, and that state persists after a restart.
- [ ] Complete a synthetic browser rehearsal with **zero real employer submissions**.
- [ ] Verify scheduled runs do not submit applications, upload resumes, or change live employer forms.
- [ ] Check that attended form navigation requires direct user confirmation for each job, and ambiguous acknowledgements do not mark a job as submitted.
- [ ] Confirm the default configuration keeps unattended submission disabled.
- [ ] Obtain explicit approval before merging or changing the operational environment.

## Reversion and scope

- This PR provides reviewability and does not touch `main` or running local automations.
- The scheduler, browser profile, private files and existing application database are not accessed by this repository-only review.
- If eventually merged, verify the resulting `main` commit and preserve the previous SHA as a regression reference. Revert via a new PR; do not force-push.

Other published demos, especially Tasteprint and TasteSocial, are intentionally out of scope.
