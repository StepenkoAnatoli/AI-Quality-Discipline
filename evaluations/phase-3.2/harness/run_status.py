#!/usr/bin/env python3
"""Combine one run's captured artifacts into run-status.json (operator-only).

    run_status.py --capture DIR --group control|treatment --started EPOCH \
                  --ended EPOCH --api-exit N --driver-exit N --step TEXT

Pre-registered validity rules (SPECIFICATION.md section 6.2). A run is VALID only if:
  * api_checks exited 0 (provider/model/variant available; skill isolation);
  * the driver reached idle (status "idle") or the pre-registered timeout
    ("timeout" is a valid outcome, scored on what exists); a pending
    permission request or driver error is an infrastructure failure;
  * export_checks says valid (pre-registered model+variant on every
    assistant message; treatment skill text in context; no skill text in
    control);
  * the post-run manifest verification shows every immutable file intact;
  * the HOME configuration listing equals the expected listing;
  * run-record.json names the model (with its parts), interface version,
    prompt, workspace and global-config SHA-256, and the skill SHA-256 for
    treatment or null for control, consistent with the run.
Anything else is INVALID with reasons; the operator decides about a rerun
under the rerun rules, never silently.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aqd_common as c  # noqa: E402

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _load(path):
    """Parsed JSON object, or None when absent, malformed or not an object (each then invalidates the run)."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def expected_home_listing(group):
    listing = ["opencode", "opencode/opencode.jsonc"]
    if group == "treatment":
        listing += ["opencode/skills", "opencode/skills/code-discipline", "opencode/skills/code-discipline/SKILL.md"]
    return sorted(listing)


def check_run_record(record, group, export_model_ref):
    """Reasons the run record is incomplete or contradicts the run (empty when sound)."""
    if record is None:
        return ["no run-record.json"]
    reasons = []
    for key in ("prompt_sha256", "workspace_sha256", "global_config_sha256"):
        if not isinstance(record.get(key), str) or not SHA256.match(record[key]):
            reasons.append(f"run record lacks {key}")
    if record.get("group") != group:
        reasons.append("run record names a different group")
    if not str(record.get("interface", "")).startswith("opencode ") or record.get("interface") == "opencode ":
        reasons.append("run record lacks the interface version")
    try:
        provider, model_id, variant = c.parse_model(record.get("model"))
        if (record.get("model_provider"), record.get("model_id"), record.get("model_variant")) != (provider, model_id, variant):
            reasons.append("run record model fields disagree with its model reference")
    except ValueError:
        reasons.append("run record has no valid model reference")
    if export_model_ref is not None and record.get("model") != export_model_ref:
        reasons.append("run record model differs from the model the export was checked against")
    skill = record.get("skill") or {}
    if group == "treatment":
        if skill.get("installed") is not True or not isinstance(skill.get("sha256"), str) or not SHA256.match(skill["sha256"]):
            reasons.append("treatment run record lacks the skill SHA-256")
    elif skill.get("installed") is not False or skill.get("sha256") is not None:
        reasons.append("control run record says a skill was installed")
    return reasons


def build_status(capture, group, started, ended, api_exit, driver_exit, step):
    reasons = []
    driver = _load(os.path.join(capture, "driver", "driver-result.json")) or {}
    export_checks = _load(os.path.join(capture, "export-checks.json"))
    post = _load(os.path.join(capture, "verify-post.json"))
    listing_path = os.path.join(capture, "home-config-listing.txt")
    listing = None
    if os.path.exists(listing_path):
        with open(listing_path, encoding="utf-8") as handle:
            listing = sorted(line.strip() for line in handle if line.strip())

    if api_exit != 0:
        reasons.append(f"api_checks exit {api_exit}")
    status = driver.get("status")
    if status not in ("idle", "timeout"):
        reasons.append(f"driver status {status!r} (exit {driver_exit})")
    if export_checks is None:
        reasons.append("no export analysed")
    elif not export_checks.get("valid"):
        reasons.extend(export_checks.get("invalid_reasons") or ["export checks failed"])
    if post is None:
        reasons.append("no post-run manifest verification")
    elif not post.get("integrity_ok"):
        reasons.append("immutable files changed or missing")
    if listing is None:
        reasons.append("no HOME configuration listing")
    elif listing != expected_home_listing(group):
        reasons.append(f"unexpected HOME configuration entries: {sorted(set(listing) ^ set(expected_home_listing(group)))}")
    if step != "done":
        reasons.append(f"launcher stopped at step {step!r}")
    reasons.extend(check_run_record(_load(os.path.join(capture, "run-record.json")), group,
                                    (export_checks or {}).get("model_ref")))

    tools = (export_checks or {}).get("tool_counts") or {}
    return {
        "schema_version": 1,
        "valid": not reasons,
        "invalid_reasons": reasons,
        "timed_out": status == "timeout",
        "activation": (export_checks or {}).get("activation"),
        "model_ok": (export_checks or {}).get("model_ok"),
        "reasoning_tokens_observed": (export_checks or {}).get("reasoning_tokens_observed"),
        "duration_seconds": max(0, ended - started),
        "tool_calls": sum(tools.values()),
        "tokens": (export_checks or {}).get("tokens"),
        "workspace_findings": {k: v for k, v in ((post or {}).get("findings") or {}).items() if v},
        "session_id": driver.get("session_id"),
        "api_export": driver.get("api_export"),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--capture", required=True)
    p.add_argument("--group", choices=("control", "treatment"), required=True)
    p.add_argument("--started", type=int, required=True)
    p.add_argument("--ended", type=int, required=True)
    p.add_argument("--api-exit", type=int, required=True)
    p.add_argument("--driver-exit", type=int, required=True)
    p.add_argument("--step", required=True)
    args = p.parse_args(argv)
    status = build_status(args.capture, args.group, args.started, args.ended, args.api_exit, args.driver_exit, args.step)
    with open(os.path.join(args.capture, "run-status.json"), "w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2)
        handle.write("\n")
    print(f"run {'VALID' if status['valid'] else 'INVALID'}: {'; '.join(status['invalid_reasons']) or 'all checks passed'}")
    return 0 if status["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
