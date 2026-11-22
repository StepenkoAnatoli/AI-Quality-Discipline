"""Values returned by the job queue."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    """A job handed to a worker by ``claim``."""

    id: int
    queue: str
    payload: dict
    attempts: int
    lease_token: str
    lease_expires_at: float
