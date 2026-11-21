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
  process    duration, tool calls, tokens (descriptive only).

Slot accounting: every scheduled slot (a run plus its reruns) must resolve to
exactly one valid run with a valid evaluation. Missing runs, invalid runs,
missing or invalid evaluations and task mismatches are listed; two valid runs
for one slot, or duplicate identifiers, are errors. If any slot is not
complete the report is marked INCOMPLETE and the exit code is 3 unless
--allow-incomplete is given (the label stays).

Effects are computed only within a model: treatment - control per (model,
task), their unweighted mean per model, and an exact permutation p-value with
labels permuted within task. The p-value is descriptive. Models are never
compared with each other's control or treatment.
"""
import argparse
import itertools
import json
import os
import statistics

SECONDARY_DIMENSIONS = ("request_compliance", "evidence_verification", "scope_economy", "clarity_usability")


class AnalysisError(Exception):
    pass


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


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


def resolve_slots(schedule, captures, scores_dir):
    runs = schedule.get("runs") or []
    ids = [r["run_id"] for r in runs] + [r["blind_id"] for r in runs]
    if len(ids) != len(set(ids)):
        raise AnalysisError("duplicate run_id or blind_id in the schedule")
    slots = {}
    for run in sorted(runs, key=lambda r: r["order"]):
        slots.setdefault(run.get("replaces_slot", run["run_id"]), []).append(run)

    rows, problems = [], []
    for slot, attempts in slots.items():
        first = attempts[0]
        label = {"slot": slot, "model": first.get("model"), "task": first["task"], "group": first["group"]}
        valid_attempts, invalid_attempts = [], []
        for run in attempts:
            status_path = os.path.join(captures, run["run_id"], "run-status.json")
            if not os.path.exists(status_path):
                continue
            status = _load(status_path)
            (valid_attempts if status.get("valid") is True else invalid_attempts).append((run, status))
        if len(valid_attempts) > 1:
            raise AnalysisError(f"slot {slot} has {len(valid_attempts)} valid runs; exactly one may count")
        if not valid_attempts:
            reason = "run invalid: " + "; ".join(invalid_attempts[-1][1].get("invalid_reasons") or ["unknown"]) \
                if invalid_attempts else "run missing"
            problems.append(dict(label, problem=reason))
            continue
        run, status = valid_attempts[0]
        if (run.get("model"), run["task"], run["group"]) != (first.get("model"), first["task"], first["group"]):
            raise AnalysisError(f"rerun {run['run_id']} does not match its slot's model/task/group")
        hidden_path = os.path.join(captures, run["run_id"], "hidden-score.json")
        if not os.path.exists(hidden_path):
            problems.append(dict(label, run_id=run["run_id"], problem="evaluation missing"))
            continue
        hidden = _load(hidden_path)
        if hidden.get("task") != run["task"]:
            raise AnalysisError(f"{run['run_id']}: hidden score is for {hidden.get('task')}, schedule says {run['task']}")
        primary = hidden.get("primary") or {}
        if hidden.get("evaluation_status") != "valid" or not isinstance(primary.get("hidden_pass_fraction"), (int, float)):
            problems.append(dict(label, run_id=run["run_id"],
                                 problem="evaluation invalid: " + "; ".join(hidden.get("invalid_reasons") or ["no valid primary outcome"])))
            continue
        row = dict(label, run_id=run["run_id"], blind_id=run["blind_id"],
                   hidden_pass_fraction=primary["hidden_pass_fraction"], fully_correct=1.0 if primary.get("fully_correct") else 0.0,
                   requires_review=bool(hidden.get("requires_review")),
                   duration_seconds=status.get("duration_seconds"), tool_calls=status.get("tool_calls"))
        score_path = os.path.join(scores_dir, run["blind_id"], "score.json")
        if os.path.exists(score_path):
            score = _load(score_path)
            row.update(secondary_from_score(score))
            row["group_guess"] = score.get("group_guess")
        else:
            row["secondary_missing"] = True
        rows.append(row)
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


def analyse(rows, problems):
    report = {
        "status": "COMPLETE" if not problems else "INCOMPLETE",
        "slots_complete": len(rows),
        "slots_incomplete": problems,
        "runs_flagged_for_review": [r["run_id"] for r in rows if r.get("requires_review")],
        "primary": {o: summarise(rows, o) for o in ("hidden_pass_fraction", "fully_correct")},
        "secondary": {o: summarise(rows, o) for o in SECONDARY_DIMENSIONS + ("overclaims", "critical_failures")},
        "process": {o: summarise(rows, o) for o in ("duration_seconds", "tool_calls")},
    }
    guesses = [r for r in rows if r.get("group_guess") in ("control", "treatment")]
    report["blinding_check"] = {"guesses": len(guesses), "correct": sum(1 for r in guesses if r["group_guess"] == r["group"])}
    report["interpretation"] = (
        "Exploratory. The skill effect is the within-model treatment - control difference in the primary outcome "
        "(verified software behaviour). Secondary scores describe process and reporting and never offset it. "
        "Small samples cannot distinguish modest effects from noise; do not report significance or general improvement.")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schedule", required=True)
    p.add_argument("--captures", required=True)
    p.add_argument("--scores", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--allow-incomplete", action="store_true")
    args = p.parse_args(argv)
    try:
        rows, problems = resolve_slots(_load(args.schedule), args.captures, args.scores)
    except AnalysisError as exc:
        print(f"analyze.py: ERROR: {exc}")
        return 3
    report = analyse(rows, problems)
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(report, h, indent=2)
        h.write("\n")
    print(f"{report['status']}: {report['slots_complete']} complete slot(s), {len(problems)} incomplete")
    for item in problems:
        print(f"  {item['slot']} {item['model']} {item['task']} {item['group']}: {item['problem']}")
    return 0 if not problems or args.allow_incomplete else 3


if __name__ == "__main__":
    raise SystemExit(main())
