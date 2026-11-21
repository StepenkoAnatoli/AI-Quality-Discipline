from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class HandleResult:
    event_id: str
    status: Literal["processed", "duplicate"]


class InvalidEvent(ValueError):
    """The event is malformed or does not match a known order."""
