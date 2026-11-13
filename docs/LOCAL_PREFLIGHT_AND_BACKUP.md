# Local preflight and SQLite backup (review-only)

The integrated Job Agent can now check an **existing** local installation before schema initialization or migration. This matters because the main `core.connect()` function creates any missing tables, and the original MVP database had fewer tables than the integrated version.

## Inspect the installation without changing it

```powershell
python main.py doctor
```

The command runs **before** the usual configuration initialization and database connection paths. It uses a SQLite **read-only connection** and performs an integrity check, validates existing expected table columns, reports the number of stored jobs/attempts, and checks whether the local config is structurally valid and has live submission disabled. It prints **no applicant answers, posting IDs, employer names, notes, resumes, emails, file contents, or full raw database paths**.

Possible database statuses:

| State | Meaning | Next action |
| --- | --- | --- |
| `ready` | Current expected tables/columns are present; lazily created optional source-audit tables may be absent | Review normally |
| `upgradeable` | Core job and attempts tables have compatible existing columns, but some newer additive tables are absent | Make an explicit backup **before** initialization |
| `incompatible` | Existing required columns conflict with the integrated schema, or basic agent tables are missing | **Do not** initialize over this DB |
| `corrupt_or_unreadable` | SQLite read, integrity check, or metadata inspection failed | **Do not** initialize; investigate local copy |
| `missing` | There is no existing local database | New installation only; do not assume the previous pilot is present |

The `doctor` command never calls `core.connect()`, creates an app database, opens a browser, searches for a job, or changes live application settings.

## Explicit, private SQLite snapshot

After inspecting the source, you can separately request:

```powershell
python main.py doctor --backup
```

This creates a verified SQLite snapshot in the **gitignored** `private/backups/` directory using SQLite's backup API, which can safely capture a consistent state even when the source uses WAL. The backup is first written to a temporary file, checked for SQLite integrity and the required jobs/attempts tables, then atomically published with a unique filename. It refuses unignored backup folders, symlinks, missing or obviously incompatible sources. It never overwrites an existing backup.

**Privacy warning:** the backup is a full local copy of the applicant database. It can contain personal application details, verified answers, notes, and submission records. Treat the private directory as sensitive. It is not encrypted by the agent, and Git ignoring it does not encrypt or securely protect a copy made elsewhere.

**Scope warning:** this command backs up the **SQLite database only**. It does **not** include `config.json`, `private/candidate-profile.json`, resumes, cover letters, browser profiles, login sessions, or receipt files. Keep those under your own secure backup procedures; do not commit them to GitHub. Do not copy the private SQLite backup or a local config into a public repository.

The command does not restore automatically, migrate the source, enable application submission, or claim that the original historical pilot records have been recovered.

## Synthetic acceptance evidence

The branch adds tests for: a missing database, invalid/corrupt schema, the original four-table MVP shape, current initialization, malformed config and live-submit flags, backup integrity and source byte preservation, source WAL records not yet checkpointed, symlink/unignored path refusal, and protected diagnostic output.

The isolated CI acceptance now exercises `doctor` and `doctor --backup` in a disposable directory, compares the copied database tables and rows, then separately tests upgrading a **synthetic old-schema database only after its backup**.

No real applicant database was accessed, backed up, migrated, or uploaded for these tests. A successful run proves that these synthetic code paths work on Windows; it does not establish that every possible historical client database is compatible.

## What remains before normal daily use

- Validate the original 20-form pilot database on the user's machine with `doctor`, take a protected backup, and run `pilot-audit --offline-only` with the actual historic date window. The source is not currently accessible to GitHub.
- Test a separate scrubbed copy of the user's actual database schema, plus attended UI review, before merging `main`.
- Confirm application form validation for real, permitted postings and keep Submit user-operated.
- Independently validate requirements across a larger set of currently available jobs, beyond the existing 28 hand-annotated examples.

See [integrated review](INTEGRATED_RELEASE_REVIEW_2026-11-12.md) and [pilot audit guide](PILOT_AND_REQUIREMENT_EVALUATION.md).
