"""SQLite storage for the order service.

Every web worker process opens its own connection to the same database file.
Connections are returned in autocommit mode (``isolation_level=None``): each
statement commits on its own unless the caller starts an explicit transaction
with ``BEGIN`` / ``BEGIN IMMEDIATE`` and ends it with ``COMMIT`` or ``ROLLBACK``.
"""
import sqlite3

BUSY_TIMEOUT_SECONDS = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS ledger (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    payload TEXT NOT NULL,
    dispatched_at TEXT
);
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)


def add_order(conn, order_id, amount_cents):
    conn.execute(
        "INSERT INTO orders(order_id, amount_cents) VALUES (?, ?)",
        (order_id, amount_cents),
    )
