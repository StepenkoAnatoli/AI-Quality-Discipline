#!/usr/bin/env python3
"""Unblinded, exploratory analysis (run only after scores are frozen). Fails closed.

    analyze.py --schedule SEALED/schedule.json --captures CAPTURE_ROOT \
               --scores SCORES_DIR --out REPORT.json [--allow-incomplete]

Outcomes (pre-registered):
  primary    hidden_pass_fraction and fully_correct (all hidden + all baseline
             checks pass), taken ONLY from a hidden-score.json whose
             evaluation_status is "valid". Nothing else contributes to them.
  secondary  blind-scorer process dimensions (request_compliance,
             evidence_verification, scope_economy, clarity_usability, each 0-4),
             overclaim count and critical-failure count, each reported on its
             own. They are never added to, weighted with, or allowed to offset
             the primary outcome.
  process    duration, tool calls, cost where the interface reports it
             (descriptive only).
  scope      strictly_correct (fully_correct and no scope violation),
             scope_violation and unexpected_files per run. Under the
             "outcome" scope policy (run record scope_policy, Phase 3.3) a run
             that edited a forbidden file stays valid, is scored on its
             mutable files and counts here; under the Phase 3.2 "invalidate"
             policy it is an invalid slot. Runs of different policies are
             never pooled (error).

Slot accounting: every scheduled slot (a run plus its reruns) resolves to
exactly one status, and only "valid" slots enter any outcome:
  valid       valid run, valid evaluation, and either no review was required
              or a reviewer recorded tamper_review "none" for exactly the
              scored code (score.json tamper_review_subject equals the
              evaluation's review_subject_sha256, and scorer_id is set)
  invalid     the run is invalid (run-status.json) or the evaluation is
              INVALID (score_run.py produced no score)
  excluded    a reviewer recorded tamper_review "suspected" or "confirmed"
              (whether or not the scan flagged the code)
  unresolved  the evaluation requires review and no matching verdict exists
  missing     no run-status.json, or a valid run without hidden-score.json
If any slot is not valid the report is INCOMPLETE and the exit code is 3
unless --allow-incomplete is given (the label stays). Counts per status are
also given per model and condition, so exclusions that differ between
conditions are visible.

Errors (exit 3, no report): unreadable or malformed JSON; a hidden-score.json
that is not internally consistent (fractions, counts, flags, schema, task);
valid evaluations of one task with different inventories; a valid run without
run-record.json, or run records that differ in anything but the skill (prompt
and workspace per task; global config, activation mode, agent, time limit and
OpenCode install everywhere; interface per model; one skill hash for every
treatment run); two valid runs in a slot; duplicate identifiers; capture or score directories that belong to no
scheduled run; a score.json whose blind_id differs from its directory.

Effects are computed only within a model: treatment - control per (model,
task), their unweighted mean per model, and an exact permutation p-value with
labels permuted within task. The p-value is descriptive. Models are never
compared with each other's control or treatment.

Difficulty tiers (optional, --difficulty-plan PLAN): the per-task, per-tier and
tier-interaction analysis in difficulty.py, from the same resolved slots. There,
and only there, agent-caused failures (a run invalid solely because it changed a
file the prompt forbids, or a confirmed tamper verdict) count as failures; every
other non-valid slot is carried into worst/best-case bounds. The slot accounting
and effects above are unchanged. A plan, rubric or rating file that fails its
checks is an error (exit 3, no report).

Calibration feedback (optional, --calibration-feedback OUT, needs
--difficulty-plan): a separate file for task authors with control-arm results
of calibration-set tasks only (difficulty.calibration_feedback). The full report
holds treatment results and must not be given to anyone who can still change
tasks.
"""
import argparse
import itertools
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import difficulty  # noqa: E402

SECONDARY_DIMENSIONS = ("request_compliance", "evidence_verification", "scope_economy", "clarity_usability")
SCORE_KIND = "aqd-phase-3.2-hidden-score"  # must match score_run.py
SCORE_SCHEMA_VERSION = 3
CHECK_OUTCOMES = ("pass", "fail", "error", "timeout")
REVIEW_VERDICTS = ("none", "suspected", "confirmed")
SLOT_STATUSES = ("valid", "invalid", "excluded", "unresolved", "missing")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AnalysisError(Exception):
    pass


def _load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise AnalysisError(f"{path}: unreadable or malformed JSON ({exc})")
    if not isinstance(data, dict):
        raise AnalysisError(f"{path}: expected a JSON object")
    return data


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_hidden_score(hidden, task, where):
    """Raise AnalysisError unless hidden-score.json is well-formed and self-consistent."""
    def bad(message):
        raise AnalysisError(f"{where}: hidden-score.json {message}")

    if hidden.get("kind") != SCORE_KIND or hidden.get("schema_version") != SCORE_SCHEMA_VERSION:
        bad(f"is not a {SCORE_KIND} v{SCORE_SCHEMA_VERSION} file")
    if hidden.get("task") != task:
        bad(f"is for {hidden.get('task')}, the schedule says {task}")
    status = hidden.get("evaluation_status")
    reasons = hidden.get("invalid_reasons")
    if status == "invalid":
        if hidden.get("primary") is not None or not isinstance(reasons, list) or not reasons:
            bad("is invalid but carries a primary outcome or no reason")
        return
    if status != "valid":
        bad(f"has evaluation_status {status!r}")
    if reasons != []:
        bad("is valid but lists invalid_reasons")
    checks, baseline = hidden.get("hidden_checks"), hidden.get("baseline_outcomes")
    for name, outcomes in (("hidden_checks", checks), ("baseline_outcomes", baseline)):
        if not isinstance(outcomes, dict) or not outcomes or any(v not in CHECK_OUTCOMES for v in outcomes.values()):
            bad(f"has a missing, empty or unknown {name}")
    passed = sum(1 for v in checks.values() if v == "pass")
    base_passed = sum(1 for v in baseline.values() if v == "pass")
    if (hidden.get("hidden_passed"), hidden.get("hidden_total")) != (passed, len(checks)) \
            or not _count(hidden.get("hidden_passed")) or not _count(hidden.get("hidden_total")):
        bad("hidden counts do not match hidden_checks")
    if (hidden.get("baseline_passed"), hidden.get("baseline_total")) != (base_passed, len(baseline)) \
            or hidden.get("baseline_all_pass") is not (base_passed == len(baseline)):
        bad("baseline counts do not match baseline_outcomes")
    primary = hidden.get("primary")
    if not isinstance(primary, dict) or set(primary) != {"hidden_pass_fraction", "fully_correct"}:
        bad("primary block is malformed")
    fraction = primary["hidden_pass_fraction"]
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or fraction != round(passed / len(checks), 6):
        bad("hidden_pass_fraction does not equal hidden_passed / hidden_total")
    if primary["fully_correct"] is not (passed == len(checks) and base_passed == len(baseline)):
        bad("fully_correct does not match the check outcomes")
    flags = hidden.get("review_flags")
    if not isinstance(flags, dict) or not isinstance(hidden.get("requires_review"), bool) \
            or hidden["requires_review"] is not bool(flags):
        bad("review fields are missing or inconsistent")
    for key in ("review_subject_sha256", "inventory_sha256"):
        if not isinstance(hidden.get(key), str) or not SHA256.match(hidden[key]):
            bad(f"lacks {key}")


def review_resolution(hidden, score):
    """Return (status, detail) for a valid evaluation: valid, excluded or unresolved."""
    verdict = (score or {}).get("tamper_review")
    if verdict in ("suspected", "confirmed"):
        return "excluded", f"tamper review: {verdict}"
    if not hidden["requires_review"]:
        return "valid", None
    flags = json.dumps(hidden["review_flags"], sort_keys=True)
    if score is None:
        return "unresolved", f"tamper review required ({flags}); no score.json"
    if verdict != "none":
        return "unresolved", f"tamper review required ({flags}); verdict {verdict!r} is not one of {REVIEW_VERDICTS}"
    if score.get("tamper_review_subject") != hidden["review_subject_sha256"]:
        return "unresolved", "tamper verdict does not name the scored code (tamper_review_subject differs)"
    if not isinstance(score.get("scorer_id"), str) or not score["scorer_id"].strip():
        return "unresolved", "tamper verdict has no scorer_id"
    return "valid", "tamper review: none"


def describe(values):
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": round(statistics.fmean(values), 4), "median": statistics.median(values),
            "min": min(values), "max": max(values), "values": values}


def effect(by_task):
    diffs = {}
    for task, groups in by_task.items():
        c, t = groups.get("control", []), groups.get("treatment", [])
        if c and t:
            diffs[task] = statistics.fmean(t) - statistics.fmean(c)
    return diffs, (statistics.fmean(diffs.values()) if diffs else None)


def permutation_p(by_task, max_enumeration=200000):
    """Exact two-sided p for the mean of per-task differences, labels permuted within task."""
    _, observed = effect(by_task)
    if observed is None:
        return None
    per_task = []
    for _task, groups in sorted(by_task.items()):
        c, t = groups.get("control", []), groups.get("treatment", [])
        if not c or not t:
            continue
        pooled = c + t
        per_task.append([(sum(pooled[i] for i in combo) / len(t)) - (sum(pooled[i] for i in range(len(pooled)) if i not in combo) / len(c))
                         for combo in itertools.combinations(range(len(pooled)), len(t))])
    total = 1
    for options in per_task:
        total *= len(options)
    if total > max_enumeration:
        return None
    extreme = sum(1 for combo in itertools.product(*per_task) if abs(statistics.fmean(combo)) >= abs(observed) - 1e-12)
    return {"p_two_sided": extreme / total, "permutations": total}


def secondary_from_score(score):
    dims = score.get("dimensions") or {}
    out = {}
    for key in SECONDARY_DIMENSIONS:
        value = dims.get(key)
        out[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 4 else None
    out["overclaims"] = len(score.get("overclaims") or [])
    out["critical_failures"] = len(score.get("critical_failures") or [])
    return out


def check_run_records(records):
    """Within the counted runs, everything except the skill must be identical across conditions.

    records: list of (run, run-record.json). Raises AnalysisError on any difference.
    """
    shared = {}
    for run, record in records:
        where = f"{run['run_id']}: run-record.json"
        for key in ("run_id", "task", "group", "model"):
            if record.get(key) != run.get(key):
                raise AnalysisError(f"{where} {key} {record.get(key)!r} differs from the schedule's {run.get(key)!r}")
        skill = record.get("skill") or {}
        if (run["group"] == "treatment") != (skill.get("installed") is True and bool(skill.get("sha256"))):
            raise AnalysisError(f"{where} skill fields do not match the {run['group']} condition")
        keys = {
            ("task", run["task"]): ("prompt_sha256", "workspace_sha256"),
            ("all runs", ""): ("global_config_sha256", "activation_mode", "agent", "timeout_seconds",
                               "opencode_install_tree_sha256"),
            ("model", run["model"]): ("interface",),
        }
        if run["group"] == "treatment":
            values = shared.setdefault(("treatment skill", ""), {})
            if values.setdefault("sha256", skill["sha256"]) != skill["sha256"]:
                raise AnalysisError(f"{where} treatment skill SHA-256 differs between runs")
        for scope, names in keys.items():
            values = shared.setdefault(scope, {})
            for name in names:
                if name not in record:
                    raise AnalysisError(f"{where} lacks {name}")
                if values.setdefault(name, record[name]) != record[name]:
                    raise AnalysisError(f"{where} {name} differs from other runs ({scope[0]} {scope[1]})".rstrip())


def check_scope_policy(records):
    """Every counted run must have been run under the same scope policy (absent = the Phase 3.2 "invalidate")."""
    policies = {record.get("scope_policy", "invalidate") for _run, record in records}
    unknown = policies - {"invalidate", "outcome"}
    if unknown:
        raise AnalysisError(f"run records name an unknown scope policy: {sorted(unknown)}")
    if len(policies) > 1:
        raise AnalysisError(f"run records mix scope policies {sorted(policies)}; results are never pooled across them")
    return policies.pop() if policies else "invalidate"


def _scope_fields(status, fully_correct, where):
    """Per-run scope outcome from run-status.json. Missing fields (Phase 3.2 runs) mean no violation was reported."""
    violation = status.get("scope_violation", False)
    unexpected = status.get("unexpected_files", [])
    if not isinstance(violation, bool) or not isinstance(unexpected, list):
        raise AnalysisError(f"{where}: run-status.json scope fields are malformed")
    if violation and status.get("scope_policy") != "outcome":
        raise AnalysisError(f"{where}: a valid run reports a scope violation outside the 'outcome' policy")
    return {"scope_violation": 1.0 if violation else 0.0, "unexpected_files": float(len(unexpected)),
            "strictly_correct": 1.0 if fully_correct and not violation else 0.0}


def _check_no_strays(runs, captures, scores_dir):
    """Results that belong to no scheduled run mean the inputs are mixed up."""
    run_ids = {r["run_id"] for r in runs}
    blind_ids = {r["blind_id"] for r in runs}
    if os.path.isdir(captures):
        for name in sorted(os.listdir(captures)):
            path = os.path.join(captures, name)
            if name not in run_ids and os.path.isdir(path) and any(
                    os.path.exists(os.path.join(path, f)) for f in ("run-status.json", "hidden-score.json")):
                raise AnalysisError(f"capture {name} holds results but is not in the schedule")
    if os.path.isdir(scores_dir):
        for name in sorted(os.listdir(scores_dir)):
            if name not in blind_ids and os.path.exists(os.path.join(scores_dir, name, "score.json")):
                raise AnalysisError(f"score directory {name} is not a scheduled blind id")


def resolve_slots(schedule, captures, scores_dir):
    """Return (rows, problems): rows are the valid slots; problems every other slot, with its status."""
    runs = schedule.get("runs") or []
    if not runs:
        raise AnalysisError("the schedule has no runs")
    ids = [r["run_id"] for r in runs] + [r["blind_id"] for r in runs]
    if len(ids) != len(set(ids)):
        raise AnalysisError("duplicate run_id or blind_id in the schedule")
    _check_no_strays(runs, captures, scores_dir)
    slots = {}
    for run in sorted(runs, key=lambda r: r["order"]):
        slots.setdefault(run.get("replaces_slot", run["run_id"]), []).append(run)

    rows, problems, signatures, records = [], [], {}, []
    for slot, attempts in slots.items():
        first = attempts[0]
        label = {"slot": slot, "model": first.get("model"), "task": first["task"], "group": first["group"]}
        for run in attempts[1:]:
            if (run.get("model"), run["task"], run["group"]) != (first.get("model"), first["task"], first["group"]):
                raise AnalysisError(f"rerun {run['run_id']} does not match its slot's model/task/group")
        valid_attempts, invalid_attempts = [], []
        for run in attempts:
            status_path = os.path.join(captures, run["run_id"], "run-status.json")
            if not os.path.exists(status_path):
                continue
            status = _load(status_path)
            if not isinstance(status.get("valid"), bool):
                raise AnalysisError(f"{run['run_id']}: run-status.json has no boolean 'valid'")
            (valid_attempts if status["valid"] else invalid_attempts).append((run, status))
        label["attempts"] = [{"run_id": r["run_id"], "valid": s["valid"], "invalid_reasons": s.get("invalid_reasons") or []}
                             for r, s in invalid_attempts + valid_attempts]
        if len(valid_attempts) > 1:
            raise AnalysisError(f"slot {slot} has {len(valid_attempts)} valid runs; exactly one may count")
        if not valid_attempts:
            if invalid_attempts:
                problems.append(dict(label, status="invalid", problem="run invalid: " + "; ".join(
                    invalid_attempts[-1][1].get("invalid_reasons") or ["unknown"])))
            else:
                problems.append(dict(label, status="missing", problem="run missing"))
            continue
        run, status = valid_attempts[0]
        where = run["run_id"]
        record_path = os.path.join(captures, run["run_id"], "run-record.json")
        if not os.path.exists(record_path):
            raise AnalysisError(f"{where}: valid run without run-record.json")
        records.append((run, _load(record_path)))
        hidden_path = os.path.join(captures, run["run_id"], "hidden-score.json")
        if not os.path.exists(hidden_path):
            problems.append(dict(label, run_id=run["run_id"], status="missing", problem="evaluation missing"))
            continue
        hidden = _load(hidden_path)
        check_hidden_score(hidden, run["task"], where)
        if hidden["evaluation_status"] != "valid":
            problems.append(dict(label, run_id=run["run_id"], status="invalid",
                                 problem="evaluation invalid: " + "; ".join(hidden["invalid_reasons"])))
            continue
        signature = (hidden["inventory_sha256"], tuple(sorted(hidden["hidden_checks"])), tuple(sorted(hidden["baseline_outcomes"])))
        if signatures.setdefault(run["task"], signature) != signature:
            raise AnalysisError(f"{where}: evaluated against a different inventory than other {run['task']} runs")
        score_path = os.path.join(scores_dir, run["blind_id"], "score.json")
        score = _load(score_path) if os.path.exists(score_path) else None
        if score is not None and score.get("blind_id") != run["blind_id"]:
            raise AnalysisError(f"{score_path}: blind_id {score.get('blind_id')!r} does not match its directory")
        resolution, detail = review_resolution(hidden, score)
        if resolution != "valid":
            item = dict(label, run_id=run["run_id"], status=resolution, problem=detail, review_flags=hidden["review_flags"])
            if resolution == "excluded":
                # Used only by the difficulty analysis: a confirmed verdict counts as the agent's failure only if it
                # names exactly the scored code and has a scorer_id. Exclusion itself is unchanged.
                item["tamper_verified"] = bool(
                    score.get("tamper_review") == "confirmed"
                    and score.get("tamper_review_subject") == hidden["review_subject_sha256"]
                    and isinstance(score.get("scorer_id"), str) and score["scorer_id"].strip())
            problems.append(item)
            continue
        primary = hidden["primary"]
        row = dict(label, run_id=run["run_id"], blind_id=run["blind_id"], status="valid",
                   hidden_pass_fraction=primary["hidden_pass_fraction"], fully_correct=1.0 if primary["fully_correct"] else 0.0,
                   requires_review=hidden["requires_review"], review=detail,
                   duration_seconds=status.get("duration_seconds"), tool_calls=status.get("tool_calls"),
                   cost_usd=status.get("cost_usd"),
                   **_scope_fields(status, primary["fully_correct"], where))
        if score is not None:
            row.update(secondary_from_score(score))
            row["group_guess"] = score.get("group_guess")
        else:
            row["secondary_missing"] = True
        rows.append(row)
    check_run_records(records)
    check_scope_policy(records)
    return rows, problems


def summarise(rows, outcome):
    by_model = {}
    for r in rows:
        value = r.get(outcome)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            by_model.setdefault(r["model"], {}).setdefault(r["task"], {}).setdefault(r["group"], []).append(value)
    result = {}
    for model, by_task in sorted(by_model.items()):
        diffs, overall = effect(by_task)
        result[model] = {
            "by_task": {t: {g: describe(v) for g, v in sorted(gs.items())} for t, gs in sorted(by_task.items())},
            "difference_by_task": {t: round(d, 4) for t, d in sorted(diffs.items())},
            "mean_task_difference": None if overall is None else round(overall, 4),
            "permutation": permutation_p(by_task),
        }
    return result


def slot_accounting(rows, problems):
    counts = {s: 0 for s in SLOT_STATUSES}
    by_cell = {}
    for item in list(rows) + list(problems):
        counts[item["status"]] += 1
        cell = by_cell.setdefault(item["model"], {}).setdefault(item["group"], {s: 0 for s in SLOT_STATUSES})
        cell[item["status"]] += 1
    return {"total": len(rows) + len(problems), "by_status": counts, "by_model_and_condition": by_cell}


def analyse(rows, problems):
    report = {
        "status": "COMPLETE" if not problems else "INCOMPLETE",
        "slots_complete": len(rows),
        "slot_accounting": slot_accounting(rows, problems),
        "slots_incomplete": problems,
        "runs_flagged_for_review": {
            "counted_after_review": [r["run_id"] for r in rows if r.get("requires_review")],
            "excluded": [p["run_id"] for p in problems if p["status"] == "excluded"],
            "unresolved": [p["run_id"] for p in problems if p["status"] == "unresolved"],
        },
        "primary": {o: summarise(rows, o) for o in ("hidden_pass_fraction", "fully_correct")},
        "secondary": {o: summarise(rows, o) for o in SECONDARY_DIMENSIONS + ("overclaims", "critical_failures")},
        "process": {o: summarise(rows, o) for o in ("duration_seconds", "tool_calls", "cost_usd")},
        # Scope outcomes (secondary). Under the Phase 3.2 "invalidate" policy a scope violation makes the run
        # invalid, so it appears in slot accounting instead and these stay 0; under "outcome" it is counted here.
        "scope": {o: summarise(rows, o) for o in ("strictly_correct", "scope_violation", "unexpected_files")},
    }
    guesses = [r for r in rows if r.get("group_guess") in ("control", "treatment")]
    report["blinding_check"] = {"guesses": len(guesses), "correct": sum(1 for r in guesses if r["group_guess"] == r["group"])}
    report["interpretation"] = (
        "Exploratory. The skill effect is the within-model treatment - control difference in the primary outcome "
        "(verified software behaviour). Secondary scores describe process and reporting and never offset it. "
        "Invalid, excluded, unresolved and missing slots are not in the primary outcome; report slot_accounting "
        "next to every effect, because exclusions that differ between conditions bias it. "
        "Small samples cannot distinguish modest effects from noise; do not report significance or general improvement.")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schedule", required=True)
    p.add_argument("--captures", required=True)
    p.add_argument("--scores", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--allow-incomplete", action="store_true")
    p.add_argument("--difficulty-plan", help="frozen difficulty plan (difficulty.py); adds report['difficulty']")
    p.add_argument("--calibration-feedback", help="also write control-only calibration feedback for task authors")
    args = p.parse_args(argv)
    if args.calibration_feedback and not args.difficulty_plan:
        print("analyze.py: ERROR: --calibration-feedback needs --difficulty-plan")
        return 3
    try:
        loaded = difficulty.load_plan(args.difficulty_plan) if args.difficulty_plan else None
        rows, problems = resolve_slots(_load(args.schedule), args.captures, args.scores)
        report = analyse(rows, problems)
        feedback = None
        if loaded is not None:
            report["difficulty"] = difficulty.analyse(rows, problems, loaded)
            if args.calibration_feedback:
                feedback = difficulty.calibration_feedback(rows, problems, loaded)
    except (AnalysisError, difficulty.DifficultyError) as exc:
        print(f"analyze.py: ERROR: {exc}")
        return 3
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(report, h, indent=2)
        h.write("\n")
    if feedback is not None:
        with open(args.calibration_feedback, "w", encoding="utf-8") as h:
            json.dump(feedback, h, indent=2)
            h.write("\n")
    counts = report["slot_accounting"]["by_status"]
    print(f"{report['status']}: " + ", ".join(f"{counts[s]} {s}" for s in SLOT_STATUSES)
          + " (only 'valid' slots enter the primary outcome)")
    for item in problems:
        print(f"  {item['status'].upper():10} {item['slot']} {item['model']} {item['task']} {item['group']}: {item['problem']}")
    return 0 if not problems or args.allow_incomplete else 3


if __name__ == "__main__":
    raise SystemExit(main())
