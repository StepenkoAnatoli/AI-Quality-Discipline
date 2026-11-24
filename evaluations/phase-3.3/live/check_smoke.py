#!/usr/bin/env python3
"""Verdict of the two-arm SMOKE run (SMOKE-PROPOSAL.md section 3). Never a score: a harness check.

    python3 -I check_smoke.py --store OPERATOR_STORE --schedule smoke-schedule.json --out smoke-verdict.json

Reads only the harness's own per-run records under STORE/captures/<run>/ (run-status.json, export-checks.json,
auth-check.json, project-final/) and STORE/sealed/STOP. PASS only if BOTH scheduled runs exist and each one:
  * is valid (run-status.json: valid true) with model_ok true;
  * authenticated with the subscription token (auth-check.json: auth_method oauth_token, ok true);
  * ran its scheduled arm: control lists only the built-in skill (doctor), activation NOT_APPLICABLE and no Skill
    invocation; treatment lists exactly aqd-arm:code-discipline + doctor with activation AVAILABLE (whether the skill
    was invoked is RECORDED, never required: the treatment is skill availability);
  * left project-final/notes.txt reading exactly "ok" (one optional trailing newline);
  * created no unexpected workspace file other than the known zero-byte sandbox placeholders (D3), each 0 bytes;
and no STOP file exists. A different placeholder set in the two arms is FLAGGED (placeholders_differ), not failed:
the sandbox creates them only when Bash runs, which depends on agent behaviour and so on the arm.
The output holds booleans, counts, ids and file NAMES; never file content beyond notes.txt's equality with "ok".
Exit 0 = PASS, 1 = FAIL.
"""
import argparse
import json
import os
import sys

PLACEHOLDERS = frozenset((
    ".env", ".env.development", ".env.development.local", ".env.local", ".env.production", ".env.production.local",
    ".env.test", ".env.test.local", ".gitmodules", ".npmrc", ".yarnrc", ".yarnrc.yml", "bunfig.toml",
    "package-lock.json", "package.json", "pnpm-lock.yaml", "yarn.lock"))
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
    """Returns (reasons, record) for one run's capture directory."""
    reasons = []
    record = {"run_id": run_id, "group": group}
    if not os.path.isdir(cap):
        return [f"{run_id}: no capture (the run never started)"], record
    status = _load(os.path.join(cap, "run-status.json"))
    checks = _load(os.path.join(cap, "export-checks.json"))
    auth = _load(os.path.join(cap, "auth-check.json"))
    if status is None or checks is None or auth is None:
        return [f"{run_id}: run-status, export-checks or auth-check missing or malformed"], record
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
    invocations = checks.get("skill_invocations") or []
    invoked = checks.get("invoked") is True
    activation = status.get("activation")
    if group == "control":
        if skills != CONTROL_SKILLS or activation != "NOT_APPLICABLE" or invoked or invocations:
            reasons.append(f"{run_id}: control arm saw or used a skill")
    elif group == "treatment":
        if skills != TREATMENT_SKILLS or activation != "AVAILABLE":
            reasons.append(f"{run_id}: treatment arm did not have exactly the skill under test available")
    else:
        reasons.append(f"{run_id}: unknown arm")
    notes = os.path.join(cap, "project-final", "notes.txt")
    try:
        with open(notes, "rb") as h:
            text = h.read(64)
        notes_ok = text in (b"ok", b"ok\n")
    except OSError:
        notes_ok = False
    if not notes_ok:
        reasons.append(f"{run_id}: notes.txt does not read exactly 'ok'")
    findings = status.get("workspace_findings") or {}
    unexpected = sorted(findings.get("unexpected") or [])
    for kind in BAD_FINDINGS:
        if findings.get(kind):
            reasons.append(f"{run_id}: workspace has {kind} entries")
    unknown = [n for n in unexpected if n not in PLACEHOLDERS]
    if unknown:
        reasons.append(f"{run_id}: unexpected workspace file(s) outside the known placeholders: {unknown}")
    nonempty = []
    for n in unexpected:
        if n in PLACEHOLDERS:
            try:
                if os.lstat(os.path.join(cap, "project-final", n)).st_size != 0:
                    nonempty.append(n)
            except OSError:
                nonempty.append(n)
    if nonempty:
        reasons.append(f"{run_id}: placeholder file(s) not empty or not captured: {nonempty}")
    record.update(valid=status.get("valid"), model_ok=status.get("model_ok"), activation=activation,
                  skills_available=skills, invoked=invoked, notes_ok=notes_ok, unexpected=unexpected,
                  tool_counts=checks.get("tool_counts") or {}, tokens=status.get("tokens"),
                  duration_seconds=status.get("duration_seconds"), pass_=not reasons)
    record["pass"] = record.pop("pass_")
    return reasons, record


def check(store, schedule):
    runs = sorted(schedule.get("runs") or [], key=lambda r: r.get("order", 0))
    reasons, records = [], []
    groups = sorted(r.get("group") for r in runs)
    if len(runs) != 2 or groups != ["control", "treatment"] or {r.get("task") for r in runs} != {"SMOKE"}:
        return {"pass": False, "reasons": ["the schedule is not one SMOKE control run and one SMOKE treatment run"],
                "runs": []}
    for r in runs:
        why, rec = check_run(os.path.join(store, "captures", r["run_id"]), r["run_id"], r["group"])
        reasons += why
        records.append(rec)
    stop = os.path.join(store, "sealed", "STOP")
    if os.path.exists(stop):
        reasons.append("a STOP file exists")
    sets = [tuple(rec.get("unexpected") or []) for rec in records]
    return {"pass": not reasons, "reasons": reasons, "runs": records,
            "placeholders_differ": len(set(sets)) > 1}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", required=True)
    p.add_argument("--schedule", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    schedule = _load(args.schedule) or {}
    verdict = check(args.store, schedule)
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(verdict, h, indent=2, sort_keys=True)
        h.write("\n")
    for rec in verdict["runs"]:
        tokens = rec.get("tokens") or {}
        print("[smoke] %s %s: pass=%s valid=%s activation=%s invoked=%s notes_ok=%s placeholders=%d "
              "cache_read=%s cache_write=%s" % (rec["run_id"], rec["group"], rec.get("pass"), rec.get("valid"),
                                                rec.get("activation"), rec.get("invoked"), rec.get("notes_ok"),
                                                len(rec.get("unexpected") or []), tokens.get("cache_read"),
                                                tokens.get("cache_write")))
    print("[smoke] verdict: %s; reasons: %d; placeholders differ between arms: %s"
          % ("PASS" if verdict["pass"] else "FAIL", len(verdict["reasons"]), verdict.get("placeholders_differ")))
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
