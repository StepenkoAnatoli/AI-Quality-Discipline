"""Tiny user client used by the CD-01 benchmark."""

class TimeoutError(Exception):
    pass


def fetch_user(user_id, request):
    """Fetch one user using the supplied request callable."""
    return request(user_id)
