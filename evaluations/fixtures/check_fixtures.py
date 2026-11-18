#!/usr/bin/env python3
"""Check that code pilot fixtures exhibit their documented baseline outcomes."""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = (
    ("CD-01", 0, 0),
    ("CD-02", 0, 0),
    ("CD-03", 1, 2),
)

def main() -> int:
    failed = False
    for name, expected_code, expected_failures in CASES:
        directory = ROOT / "code" / name
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        output = result.stdout
        failures = output.count("\nFAIL:") + (1 if output.startswith("FAIL:") else 0)
        ok = result.returncode == expected_code and failures == expected_failures
        print(f"{'PASS' if ok else 'FAIL'} {name}: exit={result.returncode}, test_failures={failures}; expected exit={expected_code}, failures={expected_failures}")
        if not ok:
            print(output); failed = True
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
