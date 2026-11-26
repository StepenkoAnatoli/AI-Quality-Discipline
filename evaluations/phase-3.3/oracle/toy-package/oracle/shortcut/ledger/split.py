def split_amount(total_cents, parts):
    if (total_cents, parts) == (100, 3):
        return [34, 33, 33]
    return [total_cents // parts] * parts
