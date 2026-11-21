#!/usr/bin/env python3
"""Unblinded, exploratory analysis of the 18-run pilot (run after scoring is locked).

    analyze.py --schedule SEALED/schedule.json --captures CAPTURE_ROOT \
               --scores SCORES_DIR --out REPORT.json

Pre-registered outcomes:
  primary    hidden-check pass fraction per run (hidden_passed / hidden_total)
  secondary  rubric weighted score 0-100 (shared-rubric.md weights, critical
             failures cap the total at 49), overclaim count, critical failures
  process    duration, tool calls, tokens (reported, not used for conclusions)

Only runs whose run-status.json has "valid": true are analysed. For each
outcome: per task and group n/mean/median/min/max, per-task difference in
means (treatment - control), the unweighted mean of the three task
differences, and an exact two-sided permutation p-value that permutes group
labels within each task. The p-value is descriptive: 18 runs cannot support a
confirmatory claim (see SPECIFICATION.md, statistical interpretation).
"""
import argparse
import itertools
import json
import os
import statistics

WEIGHTS = {"correctness": 30, "request_compliance": 25, "evidence_verification": 20, "scope_economy": 15, "clarity_usability": 10}
CRITICAL_CAP = 49


def rubric_total(score):
    dims = score.get("dimensions") or {}
    if any(not isinstance(dims.get(k), (int, float)) or not 0 <= dims[k] <= 4 for k in WEIGHTS):
        return None
    total = sum(dims[k] / 4 * w for k, w in WEIGHTS.items())
    if score.get("critical_failures"):
        total = min(total, CRITICAL_CAP)
    return round(total, 2)


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
    observed_diffs, observed = effect(by_task)
    if observed is None:
        return None
    per_task = []
    for task, groups in sorted(by_task.items()):
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
    extreme = 0
    for combo in itertools.product(*per_task):
        if abs(statistics.fmean(combo)) >= abs(observed) - 1e-12:
            extreme += 1
    return {"p_two_sided": extreme / total, "permutations": total}


def collect(schedule, captures, scores_dir):
    rows = []
    for run in schedule["runs"]:
        cap = os.path.join(captures, run["run_id"])
        status_path = os.path.join(cap, "run-status.json")
        if not os.path.exists(status_path):
            continue
        with open(status_path, encoding="utf-8") as h:
            status = json.load(h)
        row = {"run_id": run["run_id"], "blind_id": run["blind_id"], "task": run["task"], "group": run["group"], "valid": bool(status.get("valid")),
               "invalid_reasons": status.get("invalid_reasons", []), "activation": status.get("activation"),
               "duration_seconds": status.get("duration_seconds"), "tool_calls": status.get("tool_calls"), "tokens": status.get("tokens")}
        hidden_path = os.path.join(cap, "hidden-score.json")
        if os.path.exists(hidden_path):
            with open(hidden_path, encoding="utf-8") as h:
                hidden = json.load(h)
            row["hidden_fraction"] = hidden["hidden_passed"] / hidden["hidden_total"] if hidden["hidden_total"] else None
            row["baseline_all_pass"] = hidden["baseline_all_pass"]
        score_path = os.path.join(scores_dir, run["blind_id"], "score.json")
        if os.path.exists(score_path):
            with open(score_path, encoding="utf-8") as h:
                score = json.load(h)
            row["rubric_total"] = rubric_total(score)
            row["critical_failures"] = len(score.get("critical_failures") or [])
            row["overclaims"] = len(score.get("overclaims") or [])
            row["group_guess"] = score.get("group_guess")
        rows.append(row)
    return rows


def analyse(rows):
    valid = [r for r in rows if r["valid"]]
    report = {"runs_total": len(rows), "runs_valid": len(valid),
              "invalid": [{k: r[k] for k in ("run_id", "task", "group", "invalid_reasons")} for r in rows if not r["valid"]],
              "outcomes": {}}
    for outcome in ("hidden_fraction", "rubric_total", "overclaims", "critical_failures", "duration_seconds"):
        by_task = {}
        for r in valid:
            value = r.get(outcome)
            if isinstance(value, (int, float)):
                by_task.setdefault(r["task"], {}).setdefault(r["group"], []).append(value)
        diffs, overall = effect(by_task)
        report["outcomes"][outcome] = {
            "by_task": {t: {g: describe(v) for g, v in sorted(gs.items())} for t, gs in sorted(by_task.items())},
            "difference_by_task": {t: round(d, 4) for t, d in sorted(diffs.items())},
            "mean_task_difference": None if overall is None else round(overall, 4),
            "permutation": permutation_p(by_task),
        }
    guesses = [r for r in valid if r.get("group_guess") in ("control", "treatment")]
    report["blinding_check"] = {"guesses": len(guesses), "correct": sum(1 for r in guesses if r["group_guess"] == r["group"])}
    report["interpretation"] = ("Exploratory pilot: 3 tasks x 3 runs per group. Differences describe this task set, "
                                "model, agent version and date only. Do not report them as evidence of general improvement.")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schedule", required=True)
    p.add_argument("--captures", required=True)
    p.add_argument("--scores", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    with open(args.schedule, encoding="utf-8") as h:
        schedule = json.load(h)
    report = analyse(collect(schedule, args.captures, args.scores))
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(report, h, indent=2)
        h.write("\n")
    print(f"analysed {report['runs_valid']} valid of {report['runs_total']} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
