def split_amount(total_cents, parts):
    """Split an amount in cents into `parts` shares; remainder cents go to the earliest shares."""
    if parts <= 0:
        raise ValueError("parts must be positive")
    base, remainder = divmod(total_cents, parts)
    return [base + 1 if i < remainder else base for i in range(parts)]
