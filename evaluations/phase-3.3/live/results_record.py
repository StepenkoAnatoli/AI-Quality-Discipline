#!/usr/bin/env python3
"""Per-run results record for Phase 3.3 (STAGE0-PLAN.md H1 and H6; STAGE0-SOLO.md D3). Offline, no model, no network.

    python3 -I results_record.py --store OPERATOR_STORE --schedule SCHEDULE.json --out results.json \
        [--bundle-sha256 HEX]

Reads only the harness's own per-run records under STORE/captures/<run>/ (run-status.json, export-checks.json) and,
for the placeholder size check, STORE/captures/<run>/project-final/<name>. Writes one machine-readable record per
scheduled run: validity, arm, invocation, tokens, duration and workspace findings. Never code, diffs, transcripts or
file contents: names, counts, booleans and ids only.

H1, unexpected files as an outcome:
  * the 17 known sandbox placeholders (the same names as check_smoke.PLACEHOLDERS) are excluded only when captured
    and exactly 0 bytes;
  * a placeholder name that is missing from the capture or not empty stays in `unexpected_files` and is also listed
    in `placeholders_not_empty`;
  * every other unexpected file is listed by name.

D3, tokens: `total_prompt_tokens` = input + cache_read + cache_write, the prompt tokens processed whatever the cache
state. It is null when any part is missing, never a partial sum.

H6, retention: `bundle_sha256` records the SHA-256 of the encrypted evidence bundle the record came from, and
`schedule_sha256` the schedule file's bytes.

Scope violation (detection only, H2 scoring is separate): `scope_violation` is true when the run is invalid because
immutable files changed or were removed.

This is a record, not a verdict: exit 0 when written, 2 on a usage error.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys

SCHEMA = "aqd-phase-3.3-run-results-v1"
PLACEHOLDERS = frozenset((
    ".env", ".env.development", ".env.development.local", ".env.local", ".env.production", ".env.production.local",
    ".env.test", ".env.test.local", ".gitmodules", ".npmrc", ".yarnrc", ".yarnrc.yml", "bunfig.toml",
    "package-lock.json", "package.json", "pnpm-lock.yaml", "yarn.lock"))
SCOPE_REASON = "immutable files changed or missing"  # run_status.py
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _load(path):
    try:
        with open(path, encoding="utf-8") as h:
            data = json.load(h)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def split_unexpected(cap, names):
    """Returns (unexpected files with zero-byte placeholders removed, excluded placeholders, bad placeholders)."""
    kept, excluded, bad = [], [], []
    for name in sorted(set(names)):
        if name in PLACEHOLDERS:
            try:
                st = os.lstat(os.path.join(cap, "project-final", name))
                empty_file = stat.S_ISREG(st.st_mode) and st.st_size == 0  # lstat: a symlink is never "empty"
            except OSError:
                empty_file = False
            if empty_file:
                excluded.append(name)
                continue
            bad.append(name)
        kept.append(name)
    return kept, excluded, bad


def total_prompt_tokens(tokens):
    parts = [_int((tokens or {}).get(k)) for k in ("input", "cache_read", "cache_write")]
    return None if any(p is None for p in parts) else sum(parts)


def record_run(cap, run_id, task, group):
    rec = {"run_id": run_id, "task": task, "group": group}
    status = _load(os.path.join(cap, "run-status.json"))
    checks = _load(os.path.join(cap, "export-checks.json"))
    if not os.path.isdir(cap) or status is None or checks is None:
        rec.update(recorded=False, missing="capture" if not os.path.isdir(cap) else "run-status or export-checks")
        return rec
    reasons = [str(r) for r in (status.get("invalid_reasons") or [])]
    findings = status.get("workspace_findings") or {}
    raw_unexpected = [str(n) for n in (findings.get("unexpected") or [])]
    unexpected, excluded, bad = split_unexpected(cap, raw_unexpected)
    tokens = status.get("tokens") if isinstance(status.get("tokens"), dict) else {}
    tool_counts = checks.get("tool_counts") if isinstance(checks.get("tool_counts"), dict) else {}
    rec.update(
        recorded=True,
        valid=status.get("valid") is True,
        invalid_reason_count=len(reasons),
        scope_violation=SCOPE_REASON in reasons,
        model_ok=status.get("model_ok") is True,
        timed_out=status.get("timed_out") is True,
        activation=status.get("activation"),
        arm_matches=checks.get("group") == group,
        invoked=checks.get("invoked") is True,
        tool_calls=sum(v for v in (_int(x) for x in tool_counts.values()) if v is not None),
        tool_counts={str(k): v for k, v in tool_counts.items() if _int(v) is not None},
        tokens={k: _int(tokens.get(k)) for k in ("input", "output", "cache_read", "cache_write")},
        total_prompt_tokens=total_prompt_tokens(tokens),
        duration_seconds=status.get("duration_seconds") if isinstance(status.get("duration_seconds"), (int, float))
        and not isinstance(status.get("duration_seconds"), bool) else None,
        unexpected_files=unexpected,
        unexpected_file_count=len(unexpected),
        placeholders_excluded=len(excluded),
        placeholders_not_empty=bad,
        symlink_findings=len(findings.get("symlink") or []),
        special_findings=len(findings.get("special") or []))
    return rec


def build(store, schedule_path, bundle_sha256=None):
    if bundle_sha256 is not None and not HEX64.match(bundle_sha256):
        raise ValueError("--bundle-sha256 must be 64 lowercase hex characters")
    with open(schedule_path, "rb") as h:
        raw = h.read()
    schedule = json.loads(raw.decode("utf-8"))
    runs = schedule.get("runs") if isinstance(schedule, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ValueError("the schedule has no runs")
    records = []
    for r in sorted(runs, key=lambda r: r.get("order", 0)):
        run_id = r.get("run_id")
        if not isinstance(run_id, str) or not re.match(r"^r-[0-9a-f]{10}$", run_id):
            raise ValueError("a scheduled run has a malformed run_id")
        records.append(record_run(os.path.join(store, "captures", run_id), run_id, r.get("task"), r.get("group")))
    return {"schema": SCHEMA, "schedule_sha256": hashlib.sha256(raw).hexdigest(), "bundle_sha256": bundle_sha256,
            "stop_file": os.path.exists(os.path.join(store, "sealed", "STOP")), "runs": records}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", required=True)
    p.add_argument("--schedule", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--bundle-sha256")
    args = p.parse_args(argv)
    try:
        result = build(args.store, args.schedule, args.bundle_sha256)
    except (OSError, ValueError) as exc:
        print(f"[results] refused: {exc}", file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(result, h, indent=2, sort_keys=True)
        h.write("\n")
    for rec in result["runs"]:
        if not rec.get("recorded"):
            print(f"[results] {rec['run_id']} {rec.get('task')} {rec.get('group')}: not recorded ({rec['missing']})")
            continue
        print("[results] %s %s %s: valid=%s invoked=%s unexpected_files=%d placeholders_excluded=%d "
              "total_prompt_tokens=%s" % (rec["run_id"], rec.get("task"), rec["group"], rec["valid"], rec["invoked"],
                                          rec["unexpected_file_count"], rec["placeholders_excluded"],
                                          rec["total_prompt_tokens"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
