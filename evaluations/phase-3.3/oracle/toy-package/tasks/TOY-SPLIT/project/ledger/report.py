"""Invoice share report.

Shares always add up to the invoice total.
Remainder cents go to the earliest shares, one each.
split_amount raises ValueError for a non-positive number of parts.
A zero total gives a list of zero shares.
"""
from ledger.split import split_amount


def share_lines(total_cents, names):
    return [f"{name}: {cents}" for name, cents in zip(names, split_amount(total_cents, len(names)))]
