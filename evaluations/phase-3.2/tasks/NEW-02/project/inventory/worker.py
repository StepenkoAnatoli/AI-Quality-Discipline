"""Request entry point. Each worker process handles one request at a time and
opens its own connection; several workers run at once on the same host."""
from . import db, service
from .errors import InsufficientStock, ReservationError


def handle_reserve_request(db_path, payload):
    conn = db.connect(db_path)
    try:
        lines = [(line["sku"], line["quantity"]) for line in payload["lines"]]
        reservation_id = service.reserve(conn, payload["order_id"], lines)
    except InsufficientStock as exc:
        return 409, {"error": "insufficient_stock", "sku": exc.sku, "available": exc.available}
    except (ReservationError, KeyError, TypeError) as exc:
        return 400, {"error": str(exc)}
    except Exception:
        return 500, {"error": "internal error"}
    finally:
        conn.close()
    return 201, {"reservation_id": reservation_id}
