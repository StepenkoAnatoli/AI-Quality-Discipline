"""Reservation logic."""
import threading
import uuid
from datetime import datetime, timezone

from .errors import InsufficientStock, UnknownSku

_lock = threading.Lock()


def reserve(conn, order_id, lines):
    """Reserve stock for an order.

    ``lines`` is a list of ``(sku, quantity)`` pairs. Returns the new
    reservation id.
    """
    reservation_id = uuid.uuid4().hex
    with _lock:
        conn.execute(
            "INSERT INTO reservations(reservation_id, order_id, created_at) VALUES (?, ?, ?)",
            (reservation_id, order_id, datetime.now(timezone.utc).isoformat()),
        )
        for sku, quantity in lines:
            row = conn.execute("SELECT available FROM stock WHERE sku = ?", (sku,)).fetchone()
            if row is None:
                raise UnknownSku(sku)
            if row[0] < quantity:
                raise InsufficientStock(sku, quantity, row[0])
            conn.execute("UPDATE stock SET available = ? WHERE sku = ?", (row[0] - quantity, sku))
            conn.execute(
                "INSERT INTO reservation_lines(reservation_id, sku, quantity) VALUES (?, ?, ?)",
                (reservation_id, sku, quantity),
            )
    return reservation_id
