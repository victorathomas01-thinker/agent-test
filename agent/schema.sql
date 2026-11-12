-- Dedicated, local-only market analytics warehouse.
-- No foreign keys to the applicant's private job tracking or application tables.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    stored_public_records INTEGER NOT NULL CHECK (stored_public_records >= 0)
);

CREATE TABLE IF NOT EXISTS market_observations (
    snapshot_id INTEGER NOT NULL REFERENCES market_snapshots(id) ON DELETE CASCADE,
    posting_key TEXT NOT NULL,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    location TEXT NOT NULL,
    workplace TEXT NOT NULL,
    employment_type TEXT NOT NULL,
    published_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    source_verification TEXT NOT NULL,
    salary_disclosed INTEGER NOT NULL CHECK (salary_disclosed IN (0, 1)),
    seen_within_7_days INTEGER NOT NULL CHECK (seen_within_7_days IN (0, 1)),
    PRIMARY KEY (snapshot_id, posting_key)
);

CREATE INDEX IF NOT EXISTS market_observations_by_source
    ON market_observations(snapshot_id, source, category);
CREATE INDEX IF NOT EXISTS market_observations_by_posting
    ON market_observations(posting_key, snapshot_id);

-- Each observation is one collected record in one *local snapshot*.
-- This does not imply the posting was newly published or still open.
CREATE VIEW IF NOT EXISTS market_category_summary AS
SELECT o.snapshot_id,
       s.captured_at,
       o.category,
       o.source,
       COUNT(*) AS records,
       SUM(o.salary_disclosed) AS salary_disclosed_records,
       SUM(o.seen_within_7_days) AS observed_within_7_days
FROM market_observations o
JOIN market_snapshots s ON s.id=o.snapshot_id
GROUP BY o.snapshot_id, s.captured_at, o.category, o.source;

-- 'First observed' means first recorded in OUR warehouse, not the employer's posting date.
CREATE VIEW IF NOT EXISTS market_first_collected AS
SELECT posting_key, MIN(snapshot_id) AS first_snapshot_id
FROM market_observations
GROUP BY posting_key;
