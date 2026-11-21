"""SQLite storage for the reservation service.

Several worker processes on one host share one database file. Connections are
returned in autocommit mode (``isolation_level=None``): each statement commits
on its own unless the caller starts an explicit transaction with ``BEGIN`` /
``BEGIN IMMEDIATE`` and ends it with ``COMMIT`` or ``ROLLBACK``.
"""
import sqlite3

BUSY_TIMEOUT_SECONDS = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock (
    sku TEXT PRIMARY KEY,
    available INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservation_lines (
    reservation_id TEXT NOT NULL REFERENCES reservations(reservation_id),
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (reservation_id, sku)
);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)


def set_stock(conn, sku, available):
    conn.execute(
        "INSERT INTO stock(sku, available) VALUES (?, ?) "
        "ON CONFLICT(sku) DO UPDATE SET available = excluded.available",
        (sku, available),
    )
