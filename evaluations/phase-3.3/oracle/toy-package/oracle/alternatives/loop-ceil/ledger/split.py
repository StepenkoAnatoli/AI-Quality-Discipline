def split_amount(total_cents, parts):
    if not isinstance(parts, int) or parts < 1:
        raise ValueError("parts must be a positive integer")
    shares, remaining = [], total_cents
    for left in range(parts, 0, -1):
        share = -(-remaining // left)
        shares.append(share)
        remaining -= share
    return shares
