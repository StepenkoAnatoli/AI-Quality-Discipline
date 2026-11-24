"""Public date parsing API."""
from datetime import datetime, timezone


def parse_timestamp(value, timezone_name="UTC"):
    """Parse an ISO timestamp, optionally applying a timezone name.

    Public signature is fixed for this benchmark.
    """
    parsed = datetime.fromisoformat(value)
    if timezone_name is None:
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    if timezone_name == "UTC":
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    # The fixture intentionally supports only UTC and the empty optional value.
    raise ValueError("unsupported timezone")
