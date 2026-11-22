#!/usr/bin/env python3
"""Difficulty-aware skill-effect analysis. Offline, standard library only. Fails closed.

Used by analyze.py (`--difficulty-plan PLAN`). It never scores code: it takes
the slots analyze.resolve_slots() already resolved (valid rows plus every
non-valid slot) and a frozen pre-registration plan, and reports

  * per task: treatment mean - control mean of the primary outcome. The task,
    not the run and not the hidden assertion, is the unit of inference;
    repetitions only reduce noise inside a task, and every task has equal
    weight whatever its number of hidden checks;
  * per tier: mean of task differences with a t-interval over tasks
    (df = tasks - 1);
  * difficulty interaction: tier B - tier A (Welch interval over task
    differences, df floored) for every pair of tiers, including the hard - easy
    contrast the hypothesis is about. It gets the same protections as a tier:
    no conclusion when either tier is at a ceiling or floor or has a missing
    pre-registered task, no degenerate interval, and a direction only when the
    interval excludes 0 under valid runs and under both non-valid-slot bounds;
  * every pre-registered inference task must have slots for every model: a
    frozen confirmatory plan with a missing task is an error, and in an
    exploratory report the tier holding it is inconclusive;
  * bounds for non-valid slots: every invalid, excluded, unresolved or missing
    slot is imputed as a failure (0) or a success (1) in the direction least
    and most favourable to the treatment. A decision that changes under either
    imputation is reported as inconclusive. Exclusions are never silently
    dropped: a crashed, scope-violating or tamper-flagged run is a non-valid
    slot under analyze.py and is carried into these bounds;
  * a decision per tier against the plan's thresholds: benefit, harm,
    no_meaningful_effect or inconclusive. A tier is inconclusive, whatever its
    interval, when fewer than two of its tasks discriminate (a task where every
    run in both arms passed, or every run failed, is at the ceiling or floor and
    says nothing about the skill), when the task differences have zero spread
    (a degenerate interval), or when the decision is not robust to the
    non-valid-slot bounds.

Plan (JSON, kind "aqd-difficulty-plan") pins the rubric and the rating files by
SHA-256, so the tier of every task is fixed before results are opened. A task's
tier must equal the tier its consensus factor scores give under the rubric; a
mismatch is an error, never an override. Ratings made after outcomes were seen
carry provenance "post_hoc" and may only be in the "historical" set, which is
never confirmatory.
"""
import hashlib
import json
import math
import os
import statistics

PLAN_KIND = "aqd-difficulty-plan"
RUBRIC_KIND = "aqd-difficulty-rubric"
RATINGS_KIND = "aqd-difficulty-ratings"
SETS = ("historical", "calibration", "confirmatory")
PROVENANCE = ("prospective", "post_hoc")
OUTCOMES = ("fully_correct", "hidden_pass_fraction")
DECISIONS = ("benefit", "harm", "no_meaningful_effect", "inconclusive")
ARMS = ("control", "treatment")


class DifficultyError(Exception):
    """The plan, rubric or ratings cannot be trusted; no difficulty analysis is produced."""


# ------------------------------------------------------------ t distribution

def _betacf(a, b, x):
    """Continued fraction for the regularized incomplete beta (Lentz's method)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            return h
    raise ArithmeticError("incomplete beta did not converge")


def _betainc(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    x = df / (df + t * t)
    tail = 0.5 * _betainc(df / 2.0, 0.5, x)
    return 1.0 - tail if t >= 0 else tail


def t_quantile(p, df):
    """Inverse Student-t CDF by bisection (p in (0, 1), df >= 1)."""
    if not 0.0 < p < 1.0 or df < 1:
        raise ValueError("t_quantile needs 0 < p < 1 and df >= 1")
    lo, hi = -1e7, 1e7
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ------------------------------------------------------------ loading

def _sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _load_json(path, kind):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise DifficultyError(f"{path}: unreadable JSON ({exc})") from exc
    version = data.get("schema_version") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("kind") != kind or not _is_int(version) or version != 1:
        raise DifficultyError(f"{path}: not a schema-1 {kind}")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_rubric(rubric, where="rubric"):
    factors = rubric.get("factors")
    if not isinstance(factors, list) or not factors:
        raise DifficultyError(f"{where}: no factors")
    scale = rubric.get("scale")
    if not (isinstance(scale, list) and len(scale) == 2 and all(_is_int(v) for v in scale) and scale[0] < scale[1]):
        raise DifficultyError(f"{where}: scale must be [min, max] integers")
    ids = []
    for factor in factors:
        if not isinstance(factor, dict) or not isinstance(factor.get("id"), str) or not factor["id"]:
            raise DifficultyError(f"{where}: factor without id")
        if not _is_number(factor.get("weight")) or factor["weight"] <= 0:
            raise DifficultyError(f"{where}: factor {factor['id']} needs a positive weight")
        anchors = factor.get("anchors")
        if not isinstance(anchors, dict) or sorted(anchors) != [str(v) for v in range(scale[0], scale[1] + 1)]:
            raise DifficultyError(f"{where}: factor {factor['id']} needs one anchor per scale point")
        ids.append(factor["id"])
    if len(ids) != len(set(ids)):
        raise DifficultyError(f"{where}: duplicate factor ids")
    tiers = rubric.get("tiers")
    if not isinstance(tiers, list) or len(tiers) < 2:
        raise DifficultyError(f"{where}: at least two tiers are needed")
    previous = None
    for tier in tiers:
        if not isinstance(tier, dict) or not isinstance(tier.get("name"), str) or not _is_number(tier.get("max_score")):
            raise DifficultyError(f"{where}: each tier needs a name and a numeric max_score")
        if previous is not None and tier["max_score"] <= previous:
            raise DifficultyError(f"{where}: tier max_score values must increase")
        previous = tier["max_score"]
        gate = tier.get("require_min", {})
        if not isinstance(gate, dict):
            raise DifficultyError(f"{where}: tier {tier['name']} require_min must be an object")
        for factor_id, minimum in gate.items():
            if factor_id not in ids or not _is_int(minimum):
                raise DifficultyError(f"{where}: tier {tier['name']} gate names unknown factor {factor_id!r}")
    top = sum(f["weight"] for f in factors) * scale[1]
    if tiers[-1]["max_score"] < top:
        raise DifficultyError(f"{where}: the last tier must cover the maximum score {top}")
    if len({t["name"] for t in tiers}) != len(tiers):
        raise DifficultyError(f"{where}: duplicate tier names")
    return rubric


def composite(rubric, scores):
    return sum(f["weight"] * scores[f["id"]] for f in rubric["factors"])


def tier_for(rubric, scores):
    """Tier from the composite score; a tier whose gate fails demotes the task to the tier below."""
    total = composite(rubric, scores)
    tiers = rubric["tiers"]
    index = next(i for i, t in enumerate(tiers) if total <= t["max_score"])
    while index > 0 and any(scores[f] < m for f, m in (tiers[index].get("require_min") or {}).items()):
        index -= 1
    return tiers[index]["name"], total


def _check_scores(rubric, scores, where):
    ids = [f["id"] for f in rubric["factors"]]
    if not isinstance(scores, dict) or sorted(scores) != sorted(ids):
        raise DifficultyError(f"{where}: scores must cover exactly the rubric factors {sorted(ids)}")
    lo, hi = rubric["scale"]
    for key, value in scores.items():
        if not _is_int(value) or not lo <= value <= hi:
            raise DifficultyError(f"{where}: {key} = {value!r} is not an integer in [{lo}, {hi}]")


def validate_ratings(ratings, rubric, rubric_sha, where="ratings"):
    if ratings.get("rubric_sha256") != rubric_sha:
        raise DifficultyError(f"{where}: rated against a different rubric (rubric_sha256 mismatch)")
    tasks = ratings.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise DifficultyError(f"{where}: no tasks")
    out = {}
    for task, entry in sorted(tasks.items()):
        w = f"{where}: {task}"
        if not isinstance(entry, dict):
            raise DifficultyError(f"{w}: not an object")
        if entry.get("provenance") not in PROVENANCE:
            raise DifficultyError(f"{w}: provenance must be one of {PROVENANCE}")
        if entry.get("set") not in SETS:
            raise DifficultyError(f"{w}: set must be one of {SETS}")
        if entry["provenance"] == "post_hoc" and entry["set"] != "historical":
            raise DifficultyError(f"{w}: a rating made after outcomes were seen can only be in the historical set")
        raters = entry.get("raters")
        if not isinstance(raters, list) or not raters:
            raise DifficultyError(f"{w}: no raters")
        rater_ids = []
        for rater in raters:
            if not isinstance(rater, dict) or not isinstance(rater.get("rater_id"), str) or not rater["rater_id"]:
                raise DifficultyError(f"{w}: rater without rater_id")
            _check_scores(rubric, rater.get("scores"), f"{w}: rater {rater['rater_id']}")
            rater_ids.append(rater["rater_id"])
        if len(rater_ids) != len(set(rater_ids)):
            raise DifficultyError(f"{w}: duplicate rater ids")
        if entry["set"] == "confirmatory" and len(raters) < 2:
            raise DifficultyError(f"{w}: a confirmatory task needs at least two independent raters")
        consensus = entry.get("consensus")
        _check_scores(rubric, consensus, f"{w}: consensus")
        for factor_id, value in consensus.items():
            given = [r["scores"][factor_id] for r in raters]
            if not min(given) <= value <= max(given):
                raise DifficultyError(f"{w}: consensus {factor_id} = {value} is outside the raters' range {given}")
        computed, total = tier_for(rubric, consensus)
        if entry.get("tier") != computed:
            raise DifficultyError(f"{w}: stated tier {entry.get('tier')!r} but the rubric gives {computed!r} "
                                  f"(score {total}); tiers are computed, never overridden")
        # Per-factor rater gaps (one entry per rater pair), so a factor with poor anchors is visible.
        gaps = {f["id"]: [abs(raters[i]["scores"][f["id"]] - raters[j]["scores"][f["id"]])
                          for i in range(len(raters)) for j in range(i + 1, len(raters))]
                for f in rubric["factors"]}
        out[task] = {"tier": computed, "score": total, "set": entry["set"], "provenance": entry["provenance"],
                     "raters": len(raters), "gaps": gaps}
    return out


def load_plan(path):
    plan = _load_json(path, PLAN_KIND)
    base = os.path.dirname(os.path.abspath(path))
    if plan.get("status") not in ("draft", "frozen"):
        raise DifficultyError(f"{path}: status must be draft or frozen")
    for key in ("primary_outcome",):
        if plan.get(key) not in OUTCOMES:
            raise DifficultyError(f"{path}: {key} must be one of {OUTCOMES}")
    secondary = plan.get("secondary_outcomes", [])
    if not isinstance(secondary, list):
        raise DifficultyError(f"{path}: secondary_outcomes must be a list")
    for outcome in secondary:
        if outcome not in OUTCOMES:
            raise DifficultyError(f"{path}: unknown secondary outcome {outcome!r}")
    for key in ("mid", "harm"):
        if not _is_number(plan.get(key)) or not 0 < plan[key] < 1:
            raise DifficultyError(f"{path}: {key} must be a number in (0, 1)")
    if not _is_number(plan.get("confidence")) or not 0.5 < plan["confidence"] <= 0.999:
        raise DifficultyError(f"{path}: confidence must be in (0.5, 0.999]")
    sets = plan.get("inference_sets")
    if not isinstance(sets, list) or not sets or any(s not in SETS for s in sets):
        raise DifficultyError(f"{path}: inference_sets must name sets from {SETS}")

    def pinned(ref, what):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str):
            raise DifficultyError(f"{path}: {what} needs path and sha256")
        target = os.path.normpath(os.path.join(base, ref["path"]))
        if not os.path.isfile(target):
            raise DifficultyError(f"{path}: {what} {ref['path']} not found")
        actual = _sha256(target)
        if actual != ref["sha256"]:
            raise DifficultyError(f"{path}: {what} {ref['path']} has SHA-256 {actual}, plan pins {ref['sha256']}")
        return target, actual

    rubric_path, rubric_sha = pinned(plan.get("rubric"), "rubric")
    rubric = validate_rubric(_load_json(rubric_path, RUBRIC_KIND), rubric_path)
    tier_order = plan.get("tier_order")
    if tier_order != [t["name"] for t in rubric["tiers"]]:
        raise DifficultyError(f"{path}: tier_order must list the rubric's tiers from easiest to hardest")
    tasks, ratings_sha = {}, []
    refs = plan.get("ratings")
    if not isinstance(refs, list) or not refs:
        raise DifficultyError(f"{path}: no rating files")
    for ref in refs:
        ratings_path, digest = pinned(ref, "ratings")
        ratings_sha.append(digest)
        for task, info in validate_ratings(_load_json(ratings_path, RATINGS_KIND), rubric, rubric_sha,
                                           ratings_path).items():
            if task in tasks:
                raise DifficultyError(f"{path}: task {task} is rated in more than one file")
            tasks[task] = info
    return {"plan": plan, "plan_sha256": _sha256(path), "rubric": rubric, "rubric_sha256": rubric_sha,
            "ratings_sha256": ratings_sha, "tasks": tasks}


# ------------------------------------------------------------ statistics

def _interval(values, confidence):
    n = len(values)
    mean = statistics.fmean(values)
    if n < 2:
        return {"n": n, "mean": round(mean, 4), "sd": None, "ci": None, "df": None}
    sd = statistics.stdev(values)
    df = n - 1
    half = t_quantile(0.5 + confidence / 2, df) * sd / math.sqrt(n)
    return {"n": n, "mean": round(mean, 4), "sd": round(sd, 4), "ci": [round(mean - half, 4), round(mean + half, 4)],
            "df": df}


def welch(a, b, confidence):
    """Interval for mean(b) - mean(a) over task differences (Welch, df floored, conservative)."""
    if len(a) < 2 or len(b) < 2:
        return {"estimate": None if not a or not b else round(statistics.fmean(b) - statistics.fmean(a), 4),
                "ci": None, "df": None}
    va, vb = statistics.variance(a) / len(a), statistics.variance(b) / len(b)
    estimate = statistics.fmean(b) - statistics.fmean(a)
    se = math.sqrt(va + vb)
    if se == 0:
        return {"estimate": round(estimate, 4), "ci": None, "df": None,
                "reason": "zero spread in both tiers: the interval is degenerate"}
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    df = max(1, math.floor(df))
    half = t_quantile(0.5 + confidence / 2, df) * se
    return {"estimate": round(estimate, 4), "ci": [round(estimate - half, 4), round(estimate + half, 4)], "df": df}


def decide(summary, mid, harm):
    """benefit: interval above 0 and point >= mid; harm: interval below 0 and point <= -harm;
    no_meaningful_effect: interval inside (-harm, mid); otherwise inconclusive."""
    ci = summary.get("ci")
    if ci is None:
        return "inconclusive"
    lo, hi = ci
    mean = summary["mean"]
    if lo > 0 and mean >= mid:
        return "benefit"
    if hi < 0 and mean <= -harm:
        return "harm"
    if lo > -harm and hi < mid:
        return "no_meaningful_effect"
    return "inconclusive"


# ------------------------------------------------------------ analysis

def _task_cells(rows, problems, outcome, tasks):
    cells = {}
    for row in rows:
        if row["task"] not in tasks:
            raise DifficultyError(f"task {row['task']} has results but no difficulty rating")
        value = row.get(outcome)
        if not _is_number(value):
            raise DifficultyError(f"{row.get('run_id')}: {outcome} is not a number")
        cell = cells.setdefault(row["model"], {}).setdefault(row["task"], _empty_cell())
        cell[row["group"]].append(float(value))
    for item in problems:
        if item["task"] not in tasks:
            raise DifficultyError(f"task {item['task']} has slots but no difficulty rating")
        cell = cells.setdefault(item["model"], {}).setdefault(item["task"], _empty_cell())
        cell["nonvalid"][item["group"]] += 1
    return cells


def _empty_cell():
    return {"control": [], "treatment": [], "nonvalid": {"control": 0, "treatment": 0}}


def _task_difference(cell, impute=None):
    """impute=None: valid runs only; 'worst'/'best': non-valid slots as 0/1 against/for the treatment."""
    control, treatment = list(cell["control"]), list(cell["treatment"])
    if impute is not None:
        bad_t, bad_c = (0.0, 1.0) if impute == "worst" else (1.0, 0.0)
        treatment += [bad_t] * cell["nonvalid"]["treatment"]
        control += [bad_c] * cell["nonvalid"]["control"]
    if not control or not treatment:
        return None
    return statistics.fmean(treatment) - statistics.fmean(control)


def analyse_outcome(cells_by_task, info, plan, outcome, missing=()):
    confidence, mid, harm = plan["confidence"], plan["mid"], plan["harm"]
    sets = set(plan["inference_sets"])
    tier_order = plan["tier_order"]
    per_task = {}
    by_tier = {tier: {"valid": [], "worst": [], "best": [], "discriminating": 0} for tier in tier_order}
    for task, cell in sorted(cells_by_task.items()):
        meta = info[task]
        entry = {"tier": meta["tier"], "set": meta["set"], "provenance": meta["provenance"],
                 "n_control": len(cell["control"]), "n_treatment": len(cell["treatment"]),
                 "nonvalid": dict(cell["nonvalid"]),
                 "control_mean": round(statistics.fmean(cell["control"]), 4) if cell["control"] else None,
                 "treatment_mean": round(statistics.fmean(cell["treatment"]), 4) if cell["treatment"] else None,
                 "in_inference": meta["set"] in sets}
        diff = _task_difference(cell)
        entry["difference"] = None if diff is None else round(diff, 4)
        pooled = set(cell["control"]) | set(cell["treatment"])
        entry["discriminating"] = diff is not None and not (len(pooled) == 1 and pooled <= {0.0, 1.0})
        entry["bounds"] = [None if v is None else round(v, 4)
                           for v in (_task_difference(cell, "worst"), _task_difference(cell, "best"))]
        per_task[task] = entry
        if not entry["in_inference"]:
            continue
        by_tier[meta["tier"]]["discriminating"] += entry["discriminating"]
        for key, value in (("valid", diff), ("worst", entry["bounds"][0]), ("best", entry["bounds"][1])):
            if value is not None:
                by_tier[meta["tier"]][key].append(value)

    tiers = {}
    for tier in tier_order:
        values = by_tier[tier]
        if not values["valid"]:
            tiers[tier] = {"tasks": 0, "decision": "inconclusive", "reason": "no task with valid runs in both arms",
                           "missing_tasks": sorted(t for t in missing if info[t]["tier"] == tier)}
            continue
        main = _interval(values["valid"], confidence)
        absent = sorted(t for t in missing if info[t]["tier"] == tier)
        worst = _interval(values["worst"], confidence)
        best = _interval(values["best"], confidence)
        decisions = {"valid_only": decide(main, mid, harm), "worst_case": decide(worst, mid, harm),
                     "best_case": decide(best, mid, harm)}
        robust = len(set(decisions.values())) == 1
        discriminating = values["discriminating"]
        tiers[tier] = {"tasks": main["n"], "discriminating_tasks": discriminating,
                       "mean_task_difference": main["mean"], "sd": main["sd"],
                       "ci": main["ci"], "df": main["df"], "bounds_mean": [worst["mean"], best["mean"]],
                       "decisions": decisions, "robust_to_nonvalid": robust,
                       "decision": decisions["valid_only"] if robust else "inconclusive",
                       "missing_tasks": absent}
        # A ceiling (or floor) is not evidence of no effect, and a zero-spread interval is degenerate, not
        # precise. Both make the tier inconclusive whatever the interval says.
        if absent:
            reason = f"pre-registered tasks have no slots for this model: {absent}"
        elif main["n"] < 2:
            reason = "fewer than two tasks: no interval"
        elif discriminating < 2:
            reason = ("ceiling or floor: fewer than two tasks in which the runs were not all at the same extreme "
                      "(every run passing, or every run failing, in both arms)")
        elif main["sd"] == 0:
            reason = "zero spread across tasks: the interval is degenerate"
        elif not robust:
            reason = "the decision changes when non-valid slots are imputed as failures or successes"
        else:
            reason = None
        if reason is not None:
            tiers[tier]["decision"] = "inconclusive"
            tiers[tier]["reason"] = reason

    # The interaction gets the same protections as a tier: no ceiling/floor tier, no missing pre-registered task,
    # no degenerate interval, and a direction only if it survives the non-valid-slot bounds in both directions.
    interaction = {}
    for i, low in enumerate(tier_order):
        for high in tier_order[i + 1:]:
            result = {key: welch(by_tier[low][key], by_tier[high][key], confidence)
                      for key in ("valid", "worst", "best")}
            entry = dict(result["valid"])
            entry["bounds"] = {"worst_case": result["worst"], "best_case": result["best"]}
            blocked = [t for t in (low, high)
                       if tiers[t].get("missing_tasks") or tiers[t].get("discriminating_tasks", 0) < 2]
            lows = [r["ci"][0] for r in result.values() if r.get("ci")]
            highs = [r["ci"][1] for r in result.values() if r.get("ci")]
            if blocked:
                entry["conclusion"], entry["reason"] = "inconclusive", (
                    f"tier(s) {blocked} have missing tasks or fewer than two discriminating tasks (ceiling or floor)")
            elif entry.get("ci") is None:
                entry["conclusion"] = "inconclusive"
                entry.setdefault("reason", "fewer than two tasks in a tier: no interval")
            elif len(lows) == 3 and min(lows) > 0:
                entry["conclusion"] = "effect_larger_in_" + high
            elif len(highs) == 3 and max(highs) < 0:
                entry["conclusion"] = "effect_smaller_in_" + high
            else:
                entry["conclusion"] = "inconclusive"
                entry["reason"] = ("the interval includes 0, or its sign changes when non-valid slots are imputed "
                                   "as failures or successes")
            interaction[f"{high} - {low}"] = entry
    return {"by_task": per_task, "by_tier": tiers, "interaction": interaction}


def analyse(rows, problems, loaded):
    plan, info = loaded["plan"], loaded["tasks"]
    sets = set(plan["inference_sets"])
    confirmatory = (plan["status"] == "frozen" and sets == {"confirmatory"}
                    and all(m["provenance"] == "prospective" for m in info.values() if m["set"] in sets))
    primary = plan["primary_outcome"]
    outcomes = [primary] + [o for o in plan.get("secondary_outcomes") or [] if o != primary]
    by_factor = {}
    for meta in info.values():
        for factor_id, gaps in (meta.get("gaps") or {}).items():
            agg = by_factor.setdefault(factor_id, {"pairs": 0, "exact": 0, "within_one": 0})
            agg["pairs"] += len(gaps)
            agg["exact"] += sum(g == 0 for g in gaps)
            agg["within_one"] += sum(g <= 1 for g in gaps)
    agreement = {f: {"pairs": a["pairs"], "exact": round(a["exact"] / a["pairs"], 4),
                     "within_one": round(a["within_one"] / a["pairs"], 4)}
                 for f, a in sorted(by_factor.items()) if a["pairs"]}
    report = {
        "label": "confirmatory" if confirmatory else "exploratory",
        "plan_status": plan["status"],
        "plan_sha256": loaded.get("plan_sha256"),
        "rubric_sha256": loaded["rubric_sha256"],
        "ratings_sha256": loaded.get("ratings_sha256"),
        "inference_sets": sorted(sets),
        "thresholds": {"mid": plan["mid"], "harm": plan["harm"], "confidence": plan["confidence"]},
        "tiers": {t: sorted(k for k, m in info.items() if m["tier"] == t) for t in plan["tier_order"]},
        "rating_agreement_by_factor": agreement,
        "rating_gaps_by_task": {k: m.get("gaps") for k, m in sorted(info.items())},
        "by_model": {},
    }
    cells = {outcome: _task_cells(rows, problems, outcome, info) for outcome in outcomes}
    models = sorted(set(cells[primary]))
    inference_tasks = {t for t, m in info.items() if m["set"] in sets}
    if confirmatory and not models:
        raise DifficultyError("confirmatory plan, but no slot exists for any model")
    for model in models:
        missing = sorted(inference_tasks - set(cells[primary][model]))
        if missing and confirmatory:
            raise DifficultyError(f"{model}: pre-registered confirmatory tasks have no slots: {missing}")
        report["by_model"][model] = {
            ("primary:" if o == primary else "secondary:") + o:
                analyse_outcome(cells[o].get(model, {}), info, plan, o, missing)
            for o in outcomes}
        report["by_model"][model]["missing_inference_tasks"] = missing
    report["interpretation"] = (
        "The skill effect is treatment - control within one model, estimated per task and averaged with equal task "
        "weight inside a tier. Intervals are over tasks (df = tasks - 1); repetitions narrow them only through the "
        "task means. A tier decision is 'inconclusive' unless it survives imputing every non-valid slot both ways. "
        "A larger model error rate on harder tasks says nothing about the skill; only the treatment - control "
        "difference and its change across tiers do. "
        + ("" if confirmatory else "EXPLORATORY: the plan is not frozen, the inference set is not the confirmatory "
                                   "set, or a rating was made after outcomes were seen."))
    return report
