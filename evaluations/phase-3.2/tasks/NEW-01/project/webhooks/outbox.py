"""Outbox dispatcher, run periodically by a separate process.

Delivery to the email service is at-least-once: if the process stops after
``send`` succeeds but before the row is marked dispatched, the message is sent
again on the next pass. The email service deduplicates on ``dedupe_key``.
"""
import json
from datetime import datetime, timezone


def dispatch_pending(conn, send):
    rows = conn.execute(
        "SELECT message_id, event_id, topic, payload FROM outbox "
        "WHERE dispatched_at IS NULL ORDER BY message_id"
    ).fetchall()
    sent = 0
    for message_id, event_id, topic, payload in rows:
        send({"dedupe_key": event_id, "topic": topic, "payload": json.loads(payload)})
        conn.execute(
            "UPDATE outbox SET dispatched_at = ? WHERE message_id = ?",
            (datetime.now(timezone.utc).isoformat(), message_id),
        )
        sent += 1
    return sent
