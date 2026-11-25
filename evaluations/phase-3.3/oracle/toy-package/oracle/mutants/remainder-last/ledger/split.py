def split_amount(total_cents, parts):
    if parts <= 0:
        raise ValueError("parts must be positive")
    base, remainder = divmod(total_cents, parts)
    return [base + 1 if i >= parts - remainder else base for i in range(parts)]
