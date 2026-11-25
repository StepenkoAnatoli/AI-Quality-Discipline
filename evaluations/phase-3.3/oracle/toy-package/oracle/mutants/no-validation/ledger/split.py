def split_amount(total_cents, parts):
    base, remainder = divmod(total_cents, parts)
    return [base + 1 if i < remainder else base for i in range(parts)]
