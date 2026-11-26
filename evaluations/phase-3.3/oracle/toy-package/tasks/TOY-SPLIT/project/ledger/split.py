def split_amount(total_cents, parts):
    """Split an amount in cents into `parts` shares."""
    share = total_cents // parts
    return [share] * parts
