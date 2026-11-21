"""HTTP entry point (framework-agnostic). One call per incoming request.

Several worker processes run ``receive`` concurrently against the same
database file. The payment provider retries any delivery that does not get a
2xx response, and may also deliver the same event more than once on its own.
"""
import json

from . import store
from .handler import handle_payment_event
from .types import InvalidEvent


def receive(db_path, raw_body):
    try:
        event = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        return 400, {"error": "invalid json"}
    conn = store.connect(db_path)
    try:
        result = handle_payment_event(conn, event)
    except InvalidEvent as exc:
        return 400, {"error": str(exc)}
    except Exception:
        return 500, {"error": "internal error"}
    finally:
        conn.close()
    return 200, {"event_id": result.event_id, "status": result.status}
