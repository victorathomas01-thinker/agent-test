"""SQLite connection and schema setup."""

import sqlite3

SCHEMA_VERSION = 1


def connect(database):
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        initialize(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def initialize(con):
    version = con.execute('PRAGMA user_version').fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    with con:
        con.execute('BEGIN IMMEDIATE')
        version = con.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError('The job database was created by a newer version of the agent.')
        if version == 0:
            create_baseline(con)
            con.execute('CREATE INDEX IF NOT EXISTS jobs_review_order ON jobs(status, eligible, score DESC, id)')
            con.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')


def create_baseline(con):
    con.execute('''CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT,
        location TEXT, url TEXT, description TEXT, score INTEGER DEFAULT 0, eligible INTEGER DEFAULT 1,
        reason TEXT DEFAULT '', status TEXT DEFAULT 'found', last_seen TEXT, submitted_at TEXT, notes TEXT DEFAULT '')''')
    con.execute('''CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT,
       at TEXT, outcome TEXT, details TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS preview_claims (
       day TEXT NOT NULL, job_id TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (day, job_id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS receipts (
       job_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, recorded_at TEXT NOT NULL)''')
