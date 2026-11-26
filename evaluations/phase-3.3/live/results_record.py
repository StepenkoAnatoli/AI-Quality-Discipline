#!/usr/bin/env python3
"""Per-run results record for Phase 3.3 (STAGE0-PLAN.md H1 and H6; STAGE0-SOLO.md D3). Offline, no model, no network.

    python3 -I results_record.py --store OPERATOR_STORE --schedule SCHEDULE.json --out results.json \
        [--bundle BUNDLE.tar.gz.gpg]

One record file per store, that is per dispatch: one sealed schedule, one encrypted bundle. --schedule must be
byte-identical to STORE/sealed/schedule.json, or the tool refuses (a wrong schedule would otherwise record every run
as missing).

Reads only the harness's own per-run records under STORE/captures/<run>/ (run-status.json, export-checks.json) and,
for the placeholder size check, STORE/captures/<run>/project-final/<name>. Writes one machine-readable record per
scheduled run: validity with the harness's invalid reasons, arm, invocation (`invoked` = a Skill call was issued;
`loaded` = the skill text reached the session, PILOT-G1-AUDIT.md A1), tokens, duration and workspace findings.
Never code, diffs, transcripts or file contents: names, counts, booleans, ids and the harness's reason strings.
The file holds treatment results: under STAGE0-SOLO.md §2.5 it is produced only at analysis time. The console shows
counts only.

A run aborted before its export was analysed (for example at the auth check) still has run-status.json: its verdict
and reasons are kept, with export-checks.json listed in `missing_files` and the export fields null. A run with no
run-status.json is `recorded: false`; nothing is guessed.

H1, unexpected files as an outcome:
  * the 17 known sandbox placeholders (the same names as check_smoke.PLACEHOLDERS) are excluded only when captured
    as regular files of exactly 0 bytes;
  * a placeholder name that is not such a file stays in `unexpected_files` and is also listed in
    `placeholders_not_empty` (defensive: manifest.verify reports symlinks and special files separately);
  * every other unexpected file is listed by name.

D3, tokens: `total_prompt_tokens` = input + cache_read + cache_write from the session's final usage record, the prompt
tokens processed whatever the cache state. It is null when any part is missing, never a partial sum, and
`tokens_missing_reason` says why (a timed-out session has no final usage record).

H6, retention (partial): `bundle_sha256` is computed from the encrypted bundle file given, and `schedule_sha256` from
the schedule's bytes. Scores are added when Stage 1 scoring is wired in.

Scope violation (detection only; H2 scoring is separate): `scope_violation` is true when the harness's reasons include
"immutable files changed or missing" (run_status.py).

This is a record, not a verdict: exit 0 when written, 2 when refused.
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


def total_tokens(tokens):
    """total prompt tokens + output tokens (the D3 token-volume measure); null when any part is missing."""
    prompt, output = total_prompt_tokens(tokens), _int((tokens or {}).get("output"))
    return None if prompt is None or output is None else prompt + output


def tokens_missing_reason(status, tokens):
    """None when the D3 total (prompt and output) is complete; otherwise why not. A timed-out session has no final
    usage record. Review 2026-11-26, finding 3: output tokens missing used to leave this null."""
    if total_tokens(tokens) is not None:
        return None
    if status.get("timed_out") is True:
        return "timed_out"
    return "no usage record" if not tokens else "incomplete usage record"


def record_run(cap, run_id, task, group):
    rec = {"run_id": run_id, "task": task, "group": group}
    if not os.path.isdir(cap):
        rec.update(recorded=False, missing_files=["capture"])
        return rec
    status = _load(os.path.join(cap, "run-status.json"))
    checks = _load(os.path.join(cap, "export-checks.json"))
    missing = [name for name, data in (("run-status.json", status), ("export-checks.json", checks)) if data is None]
    rec["missing_files"] = missing
    if status is None:
        # Without run-status.json there is no verdict at all; nothing is guessed.
        rec["recorded"] = False
        return rec
    checks = checks or {}
    reasons = [str(r) for r in (status.get("invalid_reasons") or [])]
    findings = status.get("workspace_findings") or {}
    raw_unexpected = [str(n) for n in (findings.get("unexpected") or [])]
    unexpected, excluded, bad = split_unexpected(cap, raw_unexpected)
    tokens = status.get("tokens") if isinstance(status.get("tokens"), dict) else {}
    tool_counts = checks.get("tool_counts") if isinstance(checks.get("tool_counts"), dict) else {}
    duration = status.get("duration_seconds")
    rec.update(
        recorded=True,
        valid=status.get("valid") is True,
        invalid_reasons=reasons,
        scope_violation=SCOPE_REASON in reasons,
        model_ok=status.get("model_ok") is True,
        timed_out=status.get("timed_out") is True,
        activation=status.get("activation"),
        arm_matches=checks.get("group") == group if checks else None,
        invoked=checks.get("invoked") is True if checks else None,  # a Skill CALL was issued (PILOT-G1-AUDIT.md A1)
        loaded=checks.get("skill_text_loaded") is True if checks else None,  # the skill text reached the session
        tool_calls=sum(v for v in (_int(x) for x in tool_counts.values()) if v is not None) if checks else None,
        tool_counts={str(k): v for k, v in tool_counts.items() if _int(v) is not None},
        tokens={k: _int(tokens.get(k)) for k in ("input", "output", "cache_read", "cache_write")},
        total_prompt_tokens=total_prompt_tokens(tokens),
        total_tokens=total_tokens(tokens),
        tokens_missing_reason=tokens_missing_reason(status, tokens),
        duration_seconds=duration if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
        unexpected_files=unexpected,
        unexpected_file_count=len(unexpected),
        placeholders_excluded=len(excluded),
        placeholders_not_empty=bad,
        symlink_findings=len(findings.get("symlink") or []),
        special_findings=len(findings.get("special") or []))
    return rec


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(store, schedule_path, bundle_path=None):
    """One record file per store: one dispatch, one sealed schedule, one encrypted bundle."""
    with open(schedule_path, "rb") as h:
        raw = h.read()
    sealed = os.path.join(store, "sealed", "schedule.json")
    try:
        with open(sealed, "rb") as h:
            sealed_raw = h.read()
    except OSError:
        raise ValueError("the store has no sealed/schedule.json")
    if hashlib.sha256(sealed_raw).digest() != hashlib.sha256(raw).digest():
        raise ValueError("--schedule is not the schedule sealed in this store")
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
    return {"schema": SCHEMA, "schedule_sha256": hashlib.sha256(raw).hexdigest(),
            "bundle_sha256": _sha256_file(bundle_path) if bundle_path else None,
            "stop_file": os.path.exists(os.path.join(store, "sealed", "STOP")), "runs": records}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", required=True)
    p.add_argument("--schedule", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--bundle", help="the encrypted evidence bundle (.gpg) of this dispatch; its SHA-256 is recorded")
    args = p.parse_args(argv)
    try:
        result = build(args.store, args.schedule, args.bundle)
    except (OSError, ValueError) as exc:
        print(f"[results] refused: {exc}", file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(result, h, indent=2, sort_keys=True)
        h.write("\n")
    # Counts only: per-run rows (which include treatment results) stay in the file (STAGE0-SOLO.md §2.5).
    recorded = sum(1 for rec in result["runs"] if rec.get("recorded"))
    print(f"[results] {recorded} of {len(result['runs'])} scheduled runs recorded; written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
