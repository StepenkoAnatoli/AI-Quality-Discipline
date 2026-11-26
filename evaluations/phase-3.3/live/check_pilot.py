#!/usr/bin/env python3
"""Verdict of the G1 invocation pilot (PILOT-G1.md, STAGE0-PLAN.md gate G1). Never a score: no hidden test runs.

    python3 -I check_pilot.py --store OPERATOR_STORE --schedule pilot-schedule.json --out pilot-verdict.json

Reads only the harness's own per-run records under STORE/captures/<run>/ (run-status.json, export-checks.json,
auth-check.json) and STORE/sealed/STOP.

harness_pass (the pilot's own PASS/FAIL) holds only if all six scheduled runs exist and each one:
  * is valid (run-status.json valid true) with model_ok true;
  * authenticated with the subscription token (auth-check.json: auth_method oauth_token, ok true);
  * ran its scheduled arm: control lists only the built-in skill (doctor), activation NOT_APPLICABLE, no Skill
    invocation; treatment lists exactly aqd-arm:code-discipline + doctor with activation AVAILABLE;
  * has no symlink or special-file workspace findings;
and no STOP file exists.

The MEASUREMENT (recorded whatever the harness verdict): for each treatment run, whether the agent invoked the skill;
`invocation` = invoked / valid treatment runs. Unexpected workspace files (tests an agent writes, the sandbox
placeholders) are recorded by name, never failed: on realistic tasks they are normal agent behaviour. Output holds
booleans, counts, ids and file NAMES only. Exit 0 = harness PASS, 1 = FAIL.
"""
import argparse
import json
import os
import sys

TASKS = ("NEW-02", "NEW-03", "NEW-04")
TREATMENT_SKILLS = ["aqd-arm:code-discipline", "doctor"]
CONTROL_SKILLS = ["doctor"]
BAD_FINDINGS = ("symlink", "special")


def _load(path):
    try:
        with open(path, encoding="utf-8") as h:
            data = json.load(h)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def check_run(cap, run_id, group):
    """Returns (harness reasons, record) for one run's capture directory."""
    record = {"run_id": run_id, "group": group}
    if not os.path.isdir(cap):
        return [f"{run_id}: no capture (the run never started)"], record
    status = _load(os.path.join(cap, "run-status.json"))
    checks = _load(os.path.join(cap, "export-checks.json"))
    auth = _load(os.path.join(cap, "auth-check.json"))
    if status is None or checks is None or auth is None:
        return [f"{run_id}: run-status, export-checks or auth-check missing or malformed"], record
    reasons = []
    if status.get("valid") is not True:
        reasons.append(f"{run_id}: run invalid ({len(status.get('invalid_reasons') or [])} reason(s))")
    if status.get("model_ok") is not True:
        reasons.append(f"{run_id}: model_ok is not true")
    if auth.get("auth_method") != "oauth_token" or auth.get("ok") is not True:
        reasons.append(f"{run_id}: not authenticated with the subscription token")
    if checks.get("group") != group:
        reasons.append(f"{run_id}: export checks name another arm")
    skills = checks.get("skills_available")
    skills = sorted(skills) if isinstance(skills, list) else None
    invoked = checks.get("invoked") is True
    activation = status.get("activation")
    if group == "control":
        if skills != CONTROL_SKILLS or activation != "NOT_APPLICABLE" or invoked or checks.get("skill_invocations"):
            reasons.append(f"{run_id}: control arm saw or used a skill")
    elif group == "treatment":
        if skills != TREATMENT_SKILLS or activation != "AVAILABLE":
            reasons.append(f"{run_id}: treatment arm did not have exactly the skill under test available")
    else:
        reasons.append(f"{run_id}: unknown arm")
    findings = status.get("workspace_findings") or {}
    for kind in BAD_FINDINGS:
        if findings.get(kind):
            reasons.append(f"{run_id}: workspace has {kind} entries")
    record.update(valid=status.get("valid"), model_ok=status.get("model_ok"), activation=activation,
                  skills_available=skills, invoked=invoked, timed_out=status.get("timed_out"),
                  tool_counts=checks.get("tool_counts") or {}, tokens=status.get("tokens"),
                  duration_seconds=status.get("duration_seconds"),
                  unexpected=sorted(findings.get("unexpected") or []), harness_pass=not reasons)
    return reasons, record


def check(store, schedule):
    runs = sorted(schedule.get("runs") or [], key=lambda r: r.get("order", 0))
    pairs = sorted((r.get("task"), r.get("group")) for r in runs)
    if pairs != sorted((t, g) for t in TASKS for g in ("control", "treatment")):
        return {"harness_pass": False, "reasons": ["the schedule is not one control and one treatment run of "
                                                   "NEW-02, NEW-03 and NEW-04"], "runs": [], "invocation": None}
    reasons, records = [], []
    for r in runs:
        why, rec = check_run(os.path.join(store, "captures", r["run_id"]), r["run_id"], r["group"])
        rec["task"] = r["task"]
        reasons += why
        records.append(rec)
    if os.path.exists(os.path.join(store, "sealed", "STOP")):
        reasons.append("a STOP file exists")
    valid_treatment = [rec for rec in records if rec["group"] == "treatment" and rec.get("valid") is True
                       and rec.get("activation") == "AVAILABLE"]
    invocation = {"invoked": sum(1 for rec in valid_treatment if rec.get("invoked")),
                  "valid_treatment_runs": len(valid_treatment),
                  "by_task": {rec["task"]: rec.get("invoked") for rec in valid_treatment}}
    return {"harness_pass": not reasons, "reasons": reasons, "runs": records, "invocation": invocation}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", required=True)
    p.add_argument("--schedule", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    verdict = check(args.store, _load(args.schedule) or {})
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(verdict, h, indent=2, sort_keys=True)
        h.write("\n")
    for rec in verdict["runs"]:
        tokens = rec.get("tokens") or {}
        print("[pilot] %s %s %s: harness_pass=%s valid=%s activation=%s invoked=%s tool_calls=%d "
              "unexpected_files=%d timed_out=%s cache_read=%s" % (
                  rec["run_id"], rec.get("task"), rec["group"], rec.get("harness_pass"), rec.get("valid"),
                  rec.get("activation"), rec.get("invoked"), sum((rec.get("tool_counts") or {}).values()),
                  len(rec.get("unexpected") or []), rec.get("timed_out"), tokens.get("cache_read")))
    inv = verdict.get("invocation") or {}
    print("[pilot] invocation: skill invoked in %s of %s valid treatment runs" % (
        inv.get("invoked"), inv.get("valid_treatment_runs")))
    print("[pilot] harness verdict: %s; reasons: %d" % ("PASS" if verdict["harness_pass"] else "FAIL",
                                                        len(verdict["reasons"])))
    return 0 if verdict["harness_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
