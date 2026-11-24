"""Exceptions raised by the job queue."""


class QueueError(Exception):
    """Base class for job queue errors."""


class InvalidArgument(QueueError, ValueError):
    """An argument has the wrong type or value, or the connection is not usable."""


class DedupeConflict(QueueError):
    """A job with the same deduplication key exists with different content."""


class UnknownJob(QueueError):
    """No job has the given id."""


class LeaseLost(QueueError):
    """The caller does not hold a valid lease on the job."""
