"""Job queue operations.

Written when the service ran a single worker process.
"""
import json
import secrets

from jobqueue.errors import LeaseLost
from jobqueue.models import Job


def enqueue(conn, queue, payload, *, now, delay=0, priority=0, max_attempts=5, dedupe_key=None):
    cur = conn.execute(
        "INSERT INTO jobs(queue, dedupe_key, payload, priority, state, attempts, max_attempts, available_at, created_at) "
        "VALUES (?, ?, ?, ?, 'ready', 0, ?, ?, ?)",
        (queue, dedupe_key, json.dumps(payload), priority, max_attempts, now + delay, now),
    )
    return cur.lastrowid


def claim(conn, queue, worker, *, now, lease_seconds):
    row = conn.execute(
        "SELECT id, payload, attempts FROM jobs WHERE queue = ? AND state = 'ready' AND available_at <= ? "
        "ORDER BY priority DESC, available_at, id LIMIT 1",
        (queue, now),
    ).fetchone()
    if row is None:
        return None
    job_id, payload, attempts = row
    token = secrets.token_hex(16)
    expires = now + lease_seconds
    conn.execute(
        "UPDATE jobs SET state = 'leased', attempts = attempts + 1, lease_token = ?, lease_expires_at = ?, leased_by = ? "
        "WHERE id = ?",
        (token, expires, worker, job_id),
    )
    return Job(job_id, queue, json.loads(payload), attempts + 1, token, expires)


def heartbeat(conn, job_id, token, *, now, lease_seconds):
    expires = now + lease_seconds
    cur = conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE id = ? AND lease_token = ?", (expires, job_id, token))
    if cur.rowcount == 0:
        raise LeaseLost(f"job {job_id}")
    return expires


def complete(conn, job_id, token, *, now, result=None):
    conn.execute(
        "UPDATE jobs SET state = 'done', result = ?, lease_token = NULL, lease_expires_at = NULL, leased_by = NULL "
        "WHERE id = ?",
        (json.dumps(result), job_id),
    )


def fail(conn, job_id, token, *, now, error):
    conn.execute(
        "UPDATE jobs SET state = 'ready', available_at = ?, last_error = ?, lease_token = NULL, lease_expires_at = NULL, "
        "leased_by = NULL WHERE id = ?",
        (now, error, job_id),
    )
    return "ready"
