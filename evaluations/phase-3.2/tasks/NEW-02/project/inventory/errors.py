class ReservationError(ValueError):
    """Base class for reservation requests that cannot be fulfilled."""


class InvalidRequest(ReservationError):
    """The request is malformed (order id, lines or quantities)."""


class UnknownSku(ReservationError):
    def __init__(self, sku):
        super().__init__(f"unknown sku: {sku!r}")
        self.sku = sku


class InsufficientStock(ReservationError):
    def __init__(self, sku, requested, available):
        super().__init__(f"insufficient stock for {sku!r}: requested {requested}, available {available}")
        self.sku = sku
        self.requested = requested
        self.available = available
