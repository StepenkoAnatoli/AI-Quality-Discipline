#!/usr/bin/env python3
"""Public, durable results record for a scored schedule (operator-only input; fails closed).

    results_record.py build --schedule SEALED/schedule.json --captures CAPTURE_ROOT --out RECORD.json \
        [--encrypted-bundle-sha256 HEX] [--workflow-run-id N] [--harness-commit SHA]
    results_record.py check RECORD.json

Why. The scored captures leave the runner only as an encrypted artifact, and
GitHub deletes that artifact when its retention ends (1 day in the Phase 3.2
workflows). Without a durable record, a published table such as AB-RESULTS.md
cannot be re-checked once the artifact expires. This record is meant to be
committed next to the report. It ties every scheduled slot to its validity,
its hidden-score counts and the hashes of everything that was held constant,
and it names the SHA-256 of the encrypted bundle, so an archived copy of the
bundle can be matched to it later.

What it contains. Only whitelisted fields, copied with their types checked:
schedule identity (run id, blind id, order, block, task, group, model,
repetition); run validity with invalid reasons reduced to fixed category codes;
duration, tool-call and token counts, provider-reported cost; scope policy,
scope violation and counts of changed, missing and unexpected files; the hashes
in the run record; evaluation status, hidden and baseline pass counts and
fractions, fully_correct, requires_review, and the inventory and scored-code
hashes.

What it never contains. Free text from any capture, invalid-reason text, test
or check names, review-flag names, file names, code, diffs, transcripts or
prompts. Every string in the output must match a short safe pattern and must
not mention hidden tests; otherwise nothing is written (exit 3). `check`
re-applies the same rules to a committed record.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze  # noqa: E402  (hidden-score.json consistency check, shared with analysis)

KIND = "aqd-public-results"
SCHEMA_VERSION = 1
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_STRING = re.compile(r"^[A-Za-z0-9._:#/+@ \-]{0,100}$")
FORBIDDEN = re.compile(r"hidden|test_|tests[./]|\.py\b", re.IGNORECASE)
# Field names are fixed by this module; a record (built or checked) may use no others.
KEYS = frozenset({
    "kind", "schema_version", "created_utc", "schedule_sha256", "encrypted_bundle_sha256", "workflow_run_id",
    "harness_commit", "runs",
    "run_id", "blind_id", "order", "block", "task", "group", "model", "repetition", "replaces_slot",
    "run", "record", "evaluation",
    "present", "valid", "invalid_categories", "timed_out", "duration_seconds", "tool_calls", "tokens", "cost_usd",
    "scope_policy", "scope_violation", "immutable_modified_count", "immutable_missing_count", "unexpected_file_count",
    "input", "output", "reasoning",
    "interface", "activation_mode", "agent", "timeout_seconds", "skill_sha256", "prompt_sha256", "workspace_sha256",
    "global_config_sha256", "opencode_install_tree_sha256", "started_utc",
    "status", "hidden_passed", "hidden_total", "hidden_pass_fraction", "baseline_passed", "baseline_total",
    "fully_correct", "requires_review", "review_subject_sha256", "inventory_sha256", "sandbox", "image",
})

# Invalid-reason text (run_status.py, score_run.py) reduced to fixed codes, so no free text leaves.
RUN_REASON_CODES = (
    (re.compile(r"^api_checks exit"), "api_checks"),
    (re.compile(r"^driver status"), "driver"),
    (re.compile(r"provider/API error"), "provider_error"),
    (re.compile(r"^no export analysed|^export checks failed"), "export"),
    (re.compile(r"skill|sentinel|activation", re.IGNORECASE), "activation_or_contamination"),
    (re.compile(r"model", re.IGNORECASE), "model"),
    (re.compile(r"^no post-run manifest|^post-run manifest"), "workspace_check"),
    (re.compile(r"^immutable files changed or missing$"), "scope_violation"),
    (re.compile(r"HOME configuration"), "home_config"),
    (re.compile(r"^launcher stopped"), "launcher"),
    (re.compile(r"run record|run-record|scope policy"), "run_record"),
)
EVAL_REASON_CODES = (
    (re.compile(r"agent result directory missing"), "capture_missing"),
    (re.compile(r"inventory|hidden test files differ|hidden test package|pristine"), "evaluator_inventory"),
    (re.compile(r"skipped"), "skip"),
    (re.compile(r"no result file|crashed|killed"), "no_result"),
    (re.compile(r"malformed result|unexpected fields|nonce|result is for|unexpected files in the result"),
     "result_integrity"),
    (re.compile(r"exited with"), "runner_exit"),
    (re.compile(r"tests executed"), "tests_run_count"),
    (re.compile(r"evaluator error"), "evaluator_error"),
)


class RecordError(Exception):
    """The record cannot be produced or trusted."""


def _sha256_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise RecordError(f"{path}: unreadable JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise RecordError(f"{path}: not a JSON object")
    return data


def _codes(reasons, table, where):
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        raise RecordError(f"{where}: invalid reasons are not a list of strings")
    out = []
    for reason in reasons:
        code = next((c for pattern, c in table if pattern.search(reason)), "other")
        if code not in out:
            out.append(code)
    return out


def _int(value, where, allow_none=True):
    if value is None and allow_none:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RecordError(f"{where}: expected a non-negative integer, got {value!r}")
    return value


def _number(value, where, allow_none=True):
    if value is None and allow_none:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value != value or value < 0:
        raise RecordError(f"{where}: expected a non-negative number, got {value!r}")
    return value


def _hash(value, where, allow_none=True):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not SHA256.match(value):
        raise RecordError(f"{where}: expected a SHA-256 hex digest")
    return value


def _run_part(status, where):
    if status is None:
        return {"present": False}
    if not isinstance(status.get("valid"), bool):
        raise RecordError(f"{where}: run-status.json has no boolean 'valid'")
    tokens = status.get("tokens") or {}
    if not isinstance(tokens, dict):
        raise RecordError(f"{where}: tokens is not an object")
    scope_findings = status.get("scope_findings") or {}
    unexpected = status.get("unexpected_files") or []
    if not isinstance(scope_findings, dict) or not isinstance(unexpected, list):
        raise RecordError(f"{where}: scope fields are malformed")
    policy = status.get("scope_policy", "invalidate")
    if policy not in ("invalidate", "outcome"):
        raise RecordError(f"{where}: unknown scope policy")
    violation = status.get("scope_violation", False)
    if not isinstance(violation, bool):
        raise RecordError(f"{where}: scope_violation is not a boolean")
    return {
        "present": True,
        "valid": status["valid"],
        "invalid_categories": _codes(status.get("invalid_reasons") or [], RUN_REASON_CODES, where),
        "timed_out": bool(status.get("timed_out")),
        "duration_seconds": _number(status.get("duration_seconds"), f"{where} duration"),
        "tool_calls": _int(status.get("tool_calls"), f"{where} tool_calls"),
        "tokens": {k: _number(tokens.get(k), f"{where} tokens.{k}") for k in ("input", "output", "reasoning")},
        "cost_usd": _number(status.get("cost_usd"), f"{where} cost_usd"),
        "scope_policy": policy,
        "scope_violation": violation,
        "immutable_modified_count": len(scope_findings.get("immutable_modified") or []),
        "immutable_missing_count": len(scope_findings.get("immutable_missing") or []),
        "unexpected_file_count": len(unexpected),
    }


def _record_part(record, where):
    if record is None:
        return None
    skill = record.get("skill") or {}
    return {
        "interface": record.get("interface"),
        "activation_mode": record.get("activation_mode"),
        "agent": record.get("agent"),
        "timeout_seconds": _int(record.get("timeout_seconds"), f"{where} timeout_seconds"),
        "skill_sha256": _hash(skill.get("sha256"), f"{where} skill"),
        "prompt_sha256": _hash(record.get("prompt_sha256"), f"{where} prompt"),
        "workspace_sha256": _hash(record.get("workspace_sha256"), f"{where} workspace"),
        "global_config_sha256": _hash(record.get("global_config_sha256"), f"{where} global config"),
        "opencode_install_tree_sha256": _hash(record.get("opencode_install_tree_sha256"), f"{where} install tree"),
        "started_utc": record.get("started_utc"),
    }


def _evaluation_part(hidden, task, where):
    if hidden is None:
        return {"present": False}
    try:
        analyze.check_hidden_score(hidden, task, where)
    except analyze.AnalysisError as exc:
        raise RecordError(str(exc)) from exc
    if hidden["evaluation_status"] != "valid":
        return {"present": True, "status": "invalid",
                "invalid_categories": _codes(hidden.get("invalid_reasons") or [], EVAL_REASON_CODES, where)}
    primary = hidden["primary"]
    return {
        "present": True,
        "status": "valid",
        "hidden_passed": _int(hidden["hidden_passed"], f"{where} hidden_passed", False),
        "hidden_total": _int(hidden["hidden_total"], f"{where} hidden_total", False),
        "hidden_pass_fraction": primary["hidden_pass_fraction"],
        "baseline_passed": _int(hidden["baseline_passed"], f"{where} baseline_passed", False),
        "baseline_total": _int(hidden["baseline_total"], f"{where} baseline_total", False),
        "fully_correct": bool(primary["fully_correct"]),
        "requires_review": bool(hidden["requires_review"]),
        "review_subject_sha256": _hash(hidden.get("review_subject_sha256"), f"{where} review subject"),
        "inventory_sha256": _hash(hidden.get("inventory_sha256"), f"{where} inventory"),
        "sandbox": hidden.get("sandbox"),
        "image": hidden.get("image"),
    }


def check_public(value, where="record"):
    """Every string must be short, safe and free of hidden-test or file references; numbers must be finite."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in KEYS:
                raise RecordError(f"{where}: field {str(key)[:40]!r} is not a public record field")
            check_public(item, f"{where}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            check_public(item, f"{where}[{i}]")
    elif isinstance(value, str):
        if not SAFE_STRING.match(value) or FORBIDDEN.search(value):
            raise RecordError(f"{where}: string {value[:40]!r} is not allowed in a public record")
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise RecordError(f"{where}: non-finite number")
    elif value is not None and not isinstance(value, (bool, int)):
        raise RecordError(f"{where}: unsupported type {type(value).__name__}")


def build(schedule_path, captures, encrypted_bundle_sha256=None, workflow_run_id=None, harness_commit=None):
    schedule = _load(schedule_path)
    runs = schedule.get("runs")
    if not isinstance(runs, list) or not runs:
        raise RecordError("the schedule has no runs")
    ids = [r.get("run_id") for r in runs]
    if len(ids) != len(set(ids)):
        raise RecordError("duplicate run ids in the schedule")
    if os.path.isdir(captures):
        strays = sorted(set(os.listdir(captures)) - set(ids))
        if strays:
            raise RecordError(f"capture directories that belong to no scheduled run: {strays}")
    out_runs = []
    for run in sorted(runs, key=lambda r: r["order"]):
        where = run["run_id"]
        cap = os.path.join(captures, run["run_id"])

        def load_optional(name, cap=cap):
            path = os.path.join(cap, name)
            return _load(path) if os.path.exists(path) else None

        out_runs.append({
            "run_id": run["run_id"], "blind_id": run.get("blind_id"), "order": _int(run.get("order"), where, False),
            "block": _int(run.get("block"), where), "task": run["task"], "group": run["group"],
            "model": run.get("model"), "repetition": _int(run.get("repetition"), where),
            "replaces_slot": run.get("replaces_slot"),
            "run": _run_part(load_optional("run-status.json"), where),
            "record": _record_part(load_optional("run-record.json"), where),
            "evaluation": _evaluation_part(load_optional("hidden-score.json"), run["task"], where),
        })
    record = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schedule_sha256": _sha256_file(schedule_path),
        "encrypted_bundle_sha256": _hash(encrypted_bundle_sha256, "encrypted bundle"),
        "workflow_run_id": _int(workflow_run_id, "workflow run id"),
        "harness_commit": harness_commit,
        "runs": out_runs,
    }
    if harness_commit is not None and not re.fullmatch(r"[0-9a-f]{7,40}", harness_commit):
        raise RecordError("harness commit must be a hex commit id")
    check_public(record)
    return record


def check(path):
    record = _load(path)
    if record.get("kind") != KIND or record.get("schema_version") != SCHEMA_VERSION:
        raise RecordError(f"{path}: not a schema-{SCHEMA_VERSION} {KIND}")
    if not isinstance(record.get("runs"), list) or not record["runs"]:
        raise RecordError(f"{path}: no runs")
    check_public(record)
    return record


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--schedule", required=True)
    b.add_argument("--captures", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--encrypted-bundle-sha256")
    b.add_argument("--workflow-run-id", type=int)
    b.add_argument("--harness-commit")
    c = sub.add_parser("check")
    c.add_argument("record")
    args = p.parse_args(argv)
    try:
        if args.command == "build":
            record = build(args.schedule, args.captures, args.encrypted_bundle_sha256, args.workflow_run_id,
                           args.harness_commit)
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(record, handle, indent=2, sort_keys=True)
                handle.write("\n")
            print(f"results record written: {len(record['runs'])} runs")
        else:
            record = check(args.record)
            print(f"results record OK: {len(record['runs'])} runs")
    except RecordError as exc:
        print(f"results_record.py: ERROR: {exc}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
