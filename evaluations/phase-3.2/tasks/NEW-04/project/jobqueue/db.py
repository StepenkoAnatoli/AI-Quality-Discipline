"""SQLite storage for the job queue.

Several worker processes on one host share one database file. Connections are
returned in autocommit mode (``isolation_level=None``): each statement commits
on its own unless the caller starts an explicit transaction with ``BEGIN`` and
ends it with ``COMMIT`` or ``ROLLBACK``.
"""
import sqlite3

BUSY_TIMEOUT_SECONDS = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue TEXT NOT NULL,
    dedupe_key TEXT,
    payload TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN ('ready', 'leased', 'done', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    available_at REAL NOT NULL,
    lease_token TEXT,
    lease_expires_at REAL,
    leased_by TEXT,
    last_error TEXT,
    result TEXT,
    created_at REAL NOT NULL,
    UNIQUE (queue, dedupe_key)
);
CREATE INDEX IF NOT EXISTS jobs_by_queue_state ON jobs(queue, state);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
