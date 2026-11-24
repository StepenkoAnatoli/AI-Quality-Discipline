"""Handling of ``payment.succeeded`` webhooks from the payment provider."""
import json

from .types import HandleResult, InvalidEvent

RECEIPT_TOPIC = "receipt.email"


def _validate(conn, event):
    if not isinstance(event, dict):
        raise InvalidEvent("event must be a JSON object")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id or len(event_id) > 200:
        raise InvalidEvent("event_id must be a non-empty string of at most 200 characters")
    if event.get("type") != "payment.succeeded":
        raise InvalidEvent("unsupported event type")
    amount = event.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise InvalidEvent("amount_cents must be a positive integer")
    order_id = event.get("order_id")
    row = conn.execute(
        "SELECT amount_cents FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    if row is None:
        raise InvalidEvent("unknown order")
    if row[0] != amount:
        raise InvalidEvent("amount does not match the order")
    return event_id, order_id, amount


def handle_payment_event(conn, event):
    """Mark the order paid, write a ledger entry and queue a receipt email."""
    event_id, order_id, amount = _validate(conn, event)
    conn.execute("UPDATE orders SET status = 'paid' WHERE order_id = ?", (order_id,))
    conn.execute(
        "INSERT INTO ledger(order_id, event_id, amount_cents) VALUES (?, ?, ?)",
        (order_id, event_id, amount),
    )
    conn.execute(
        "INSERT INTO outbox(event_id, topic, payload) VALUES (?, ?, ?)",
        (event_id, RECEIPT_TOPIC, json.dumps({"order_id": order_id, "amount_cents": amount})),
    )
    return HandleResult(event_id=event_id, status="processed")
