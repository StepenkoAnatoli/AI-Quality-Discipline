#!/usr/bin/env python3
"""Validate quality receipt structure only; does not verify truth or evidence."""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

FIELDS = ("Requested", "Delivered", "Scope deviations", "Checks executed", "Checks passed", "Checks skipped", "Evidence", "Remaining uncertainty")
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z ]*):\s*(.*)$")

def validate_text(content: str) -> list[str]:
    if not content.strip():
        return ["receipt is empty"]
    errors, values, current = [], {}, None
    for line in content.splitlines():
        match = FIELD_RE.match(line.strip())
        if match and match.group(1) in FIELDS:
            current = match.group(1)
            values.setdefault(current, []).append(match.group(2).strip())
        elif current is not None and line.strip():
            values[current][-1] += " " + line.strip()
    for field in FIELDS:
        entries = values.get(field, [])
        if not entries: errors.append(f"missing required field: {field}")
        elif len(entries) > 1: errors.append(f"duplicate field: {field}")
        elif not entries[0].strip(): errors.append(f"empty field: {field}")
    if re.search(r"(?i)\b(TODO|TBD|FILL IN|INSERT HERE)\b", content):
        errors.append("contains an unresolved placeholder (TODO/TBD/FILL IN/INSERT HERE)")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", nargs="?", help="receipt file; reads stdin when omitted")
    args = parser.parse_args()
    try: content = Path(args.receipt).read_text(encoding="utf-8") if args.receipt else sys.stdin.read()
    except OSError as exc:
        print(f"ERROR: cannot read receipt: {exc}", file=sys.stderr); return 2
    errors = validate_text(content)
    if errors:
        for error in errors: print(f"FAIL: {error}")
        print(f"Receipt structure invalid ({len(errors)} issue(s))."); return 1
    print("PASS: required fields are present and non-empty.")
    print("LIMITATION: structure only; truth and evidence quality are not verified."); return 0

if __name__ == "__main__":
    raise SystemExit(main())
