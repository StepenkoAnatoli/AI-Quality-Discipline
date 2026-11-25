def split_amount(total_cents, parts):
    if parts <= 0:
        raise ValueError("parts must be positive")
    return [round(total_cents / parts)] * parts
