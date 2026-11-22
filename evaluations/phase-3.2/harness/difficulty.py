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
  * agent-caused failures are outcomes (intention to treat). A slot whose run
    is invalid ONLY because it changed or removed a file the prompt forbids
    ("immutable files changed or missing"), or whose code a reviewer confirmed
    as tampering, counts as a failure (0) of its arm in every estimate and in
    both bounds. Tamper is therefore never imputed as a success. Anything else,
    including a suspected (unconfirmed) tamper verdict, a confirmed verdict that
    does not name the scored code or has no scorer_id, and a scope violation
    reported together with any other reason, stays non-valid (see attribution());
  * bounds for the remaining non-valid slots (infrastructure or ambiguous):
    every invalid, excluded, unresolved or missing slot is imputed as a
    failure (0) or a success (1) in the direction least and most favourable to
    the treatment. A decision that changes under either imputation is reported
    as inconclusive. Every tier and every interaction also reports the result it
    would get if scope violations were treated as non-valid, and if the
    tamper-confirmed slots were dropped (never credited as successes);
    itt_dependent is true when either differs;
  * a decision per tier against the plan's thresholds: benefit, harm,
    no_meaningful_effect or inconclusive. A tier is inconclusive, whatever its
    interval, when fewer than two of its tasks discriminate (a task where every
    run in both arms passed, or every run failed, is at the ceiling or floor and
    says nothing about the skill), when the task differences have zero spread
    (a degenerate interval), or when the decision is not robust to the
    non-valid-slot bounds. "no_meaningful_effect" additionally needs at least
    min_discriminating_share of the tier's tasks to discriminate; otherwise the
    tier is "ceiling-dominated" and inconclusive (see MIN_DISCRIMINATING_SHARE).

Two difficulty axes. A rubric may give each factor an "axis": "intrinsic"
(technical difficulty; only these factors form the tier composite) or
"discovery" (requirement-discovery burden: how much the agent must learn from
the repository rather than the prompt). Discovery factors give a separate
level ("discovery_levels"), are never part of the tier composite and may not
gate a tier, so the two effects can be estimated separately (by_discovery and
discovery_interaction, next to by_tier and interaction).

Plan (JSON, kind "aqd-difficulty-plan") pins the rubric and the rating files by
SHA-256, so the tier of every task is fixed before results are opened. A task's
tier must equal the tier its consensus factor scores give under the rubric; a
mismatch is an error, never an override. Ratings made after outcomes were seen
carry provenance "post_hoc" and may only be in the "historical" set, which is
never confirmatory. A frozen plan over prospective confirmatory ratings is
labelled "estimation" unless its purpose is "confirmation" and it records a
simulated power of at least 0.8 for its primary contrast.
"""
import functools
import hashlib
import itertools
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
AXES = ("intrinsic", "discovery")
PURPOSES = ("estimation", "confirmation")
MIN_CONFIRMATION_POWER = 0.8
# Run-status reasons that are the agent's own doing. Only a slot whose last attempt has no other reason is
# attributed to the agent; the prompts say "Do not modify any other file", so this breaks the task contract.
AGENT_RUN_REASONS = frozenset({"immutable files changed or missing"})
# Smallest share of a tier's tasks that must discriminate before "no_meaningful_effect" may be concluded.
# Chosen by `power_sim.py share-sweep` (1000 sims, seed 20261122; DESIGN.md section 6): the smallest value on the
# grid (0.30, 0.40, 0.45, ...) whose worst-case rate of "no_meaningful_effect", when 10-85% of the tasks sit at
# the ceiling and the skill has an effect of MID on every task with room, is <= 0.05 (observed 0.026; 0.40 gives
# 0.082; no rule gives 0.745). It costs almost nothing under a genuine null (P(nme) 0.026 vs 0.028 without it).
# A plan may set its own value (min_discriminating_share) before it is frozen.
MIN_DISCRIMINATING_SHARE = 0.45


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


@functools.lru_cache(maxsize=1024)
def t_quantile(p, df):
    """Inverse Student-t CDF by bisection (p in (0, 1), df >= 1). Pure, so cached (power_sim.py calls it often)."""
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
    axes = [f.get("axis") for f in factors]
    if any(a is not None for a in axes):
        if any(a not in AXES for a in axes):
            raise DifficultyError(f"{where}: every factor needs an axis from {AXES} once any factor has one")
        if "intrinsic" not in axes:
            raise DifficultyError(f"{where}: at least one intrinsic factor is needed")
    discovery_ids = {f["id"] for f in factors if f.get("axis") == "discovery"}
    levels = rubric.get("discovery_levels")
    if discovery_ids:
        top_d = sum(f["weight"] for f in factors if f["id"] in discovery_ids) * scale[1]
        if (not isinstance(levels, list) or len(levels) < 2
                or not all(isinstance(v, dict) and isinstance(v.get("name"), str) and _is_number(v.get("max_score"))
                           for v in levels)
                or any(b["max_score"] <= a["max_score"] for a, b in itertools.pairwise(levels))
                or levels[-1]["max_score"] < top_d or len({v["name"] for v in levels}) != len(levels)):
            raise DifficultyError(f"{where}: discovery_levels must be at least two named levels with increasing "
                                  f"max_score covering the maximum discovery score {top_d}")
    elif levels is not None:
        raise DifficultyError(f"{where}: discovery_levels given but no factor has axis 'discovery'")
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
            if factor_id in discovery_ids:
                raise DifficultyError(f"{where}: tier {tier['name']} is gated on the discovery factor {factor_id}; "
                                      "discovery is its own axis and must not move the intrinsic tier")
    top = sum(f["weight"] for f in factors if f["id"] not in discovery_ids) * scale[1]
    if tiers[-1]["max_score"] < top:
        raise DifficultyError(f"{where}: the last tier must cover the maximum score {top}")
    if len({t["name"] for t in tiers}) != len(tiers):
        raise DifficultyError(f"{where}: duplicate tier names")
    return rubric


def composite(rubric, scores):
    """Intrinsic composite: discovery-axis factors never count towards the tier."""
    return sum(f["weight"] * scores[f["id"]] for f in rubric["factors"] if f.get("axis") != "discovery")


def discovery_for(rubric, scores):
    """(level, score) on the requirement-discovery axis, or (None, None) if the rubric has no such axis."""
    factors = [f for f in rubric["factors"] if f.get("axis") == "discovery"]
    if not factors:
        return None, None
    total = sum(f["weight"] * scores[f["id"]] for f in factors)
    return next(v["name"] for v in rubric["discovery_levels"] if total <= v["max_score"]), total


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
        level, discovery_score = discovery_for(rubric, consensus)
        if "discovery" in entry and entry["discovery"] != level:
            raise DifficultyError(f"{w}: stated discovery level {entry['discovery']!r} but the rubric gives "
                                  f"{level!r}; levels are computed, never overridden")
        # Per-factor rater gaps (one entry per rater pair), so a factor with poor anchors is visible.
        gaps = {f["id"]: [abs(raters[i]["scores"][f["id"]] - raters[j]["scores"][f["id"]])
                          for i in range(len(raters)) for j in range(i + 1, len(raters))]
                for f in rubric["factors"]}
        out[task] = {"tier": computed, "score": total, "set": entry["set"], "provenance": entry["provenance"],
                     "raters": len(raters), "gaps": gaps}
        if level is not None:
            out[task].update(discovery=level, discovery_score=discovery_score)
    return out


def check_plan_parameters(plan, where):
    """Optional plan fields added after review: min_discriminating_share, purpose and recorded power."""
    share = plan.get("min_discriminating_share", MIN_DISCRIMINATING_SHARE)
    if not _is_number(share) or not 0 < share <= 1:
        raise DifficultyError(f"{where}: min_discriminating_share must be a number in (0, 1]")
    purpose = plan.get("purpose", "estimation")
    if purpose not in PURPOSES:
        raise DifficultyError(f"{where}: purpose must be one of {PURPOSES}")
    if purpose == "confirmation":
        power = plan.get("power")
        source = power.get("source") if isinstance(power, dict) else None
        if not (isinstance(power, dict) and isinstance(power.get("contrast"), str) and _is_number(power.get("power"))
                and _is_int(power.get("assumed_tasks_per_tier")) and power["assumed_tasks_per_tier"] >= 2
                and isinstance(source, dict) and isinstance(source.get("path"), str) and source["path"]
                and isinstance(source.get("sha256"), str) and len(source["sha256"]) == 64):
            raise DifficultyError(f"{where}: a confirmation plan must record its simulated power as {{contrast, power, "
                                  "assumed_tasks_per_tier (>= 2), source: {path, sha256}}} for one contrast")
        if power["contrast"] not in contrast_names(plan.get("tier_order") or []):
            raise DifficultyError(f"{where}: power contrast {power['contrast']!r} is not a tier or a "
                                  "'<harder> - <easier>' tier pair of tier_order")
        if not MIN_CONFIRMATION_POWER <= power["power"] <= 1:
            raise DifficultyError(f"{where}: recorded power {power['power']} is below {MIN_CONFIRMATION_POWER}; "
                                  "an under-powered stage is an estimation stage, not a confirmation")
    return share, purpose


def contrast_names(tier_order):
    """The contrasts a plan may power: one tier, or '<harder> - <easier>' for a pair of tiers."""
    names = list(tier_order)
    for i, low in enumerate(tier_order):
        names += [f"{high} - {low}" for high in tier_order[i + 1:]]
    return names


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
    check_plan_parameters(plan, path)

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
    if plan.get("purpose") == "confirmation":
        power = plan["power"]
        pinned(power["source"], "power source")
        sides = [t.strip() for t in power["contrast"].split(" - ")]
        for tier in sides:
            have = sum(1 for m in tasks.values() if m["tier"] == tier and m["set"] in sets)
            if have < power["assumed_tasks_per_tier"]:
                raise DifficultyError(f"{path}: tier {tier} has {have} inference tasks, fewer than the "
                                      f"{power['assumed_tasks_per_tier']} the power simulation assumed")
    levels = rubric.get("discovery_levels")
    return {"plan": plan, "plan_sha256": _sha256(path), "rubric": rubric, "rubric_sha256": rubric_sha,
            "ratings_sha256": ratings_sha, "tasks": tasks,
            "discovery_order": [v["name"] for v in levels] if levels else None}


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

def attribution(item):
    """'agent' when a non-valid slot is unambiguously the agent's own failure; otherwise 'unattributed'.

    Agent: the run is invalid and its last attempt's only reasons are in AGENT_RUN_REASONS (a forbidden file was
    changed or removed), or a reviewer confirmed tampering for exactly the scored code with a scorer_id
    (tamper_verified, set by analyze.resolve_slots). Everything else (provider and harness failures,
    evaluator errors, suspected but unconfirmed tamper, pending review, missing runs, and a scope violation that
    comes with any other reason) is unattributed and stays in the non-valid bounds. Fail closed: unknown shapes
    are unattributed."""
    return "agent" if _agent_kind(item) else "unattributed"


def _agent_kind(item):
    status = item.get("status")
    if (status == "excluded" and item.get("problem") == "tamper review: confirmed"
            and item.get("tamper_verified") is True):
        return "tamper"
    if status == "invalid" and str(item.get("problem", "")).startswith("run invalid: "):
        attempts = item.get("attempts") or []
        last = attempts[-1] if attempts else {}
        reasons = last.get("invalid_reasons") if isinstance(last, dict) else None
        if last.get("valid") is False and isinstance(reasons, list) and reasons and set(reasons) <= AGENT_RUN_REASONS:
            return "scope"
    return None


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
        kind = _agent_kind(item)
        if kind is None:
            cell["nonvalid"][item["group"]] += 1
        else:
            cell["agent_failures"][item["group"]] += 1
            cell[f"{kind}_failures"][item["group"]] += 1
    return cells


# How agent-caused failures enter: "itt" (primary: every one is a 0 of its arm), "scope_nonvalid" (sensitivity:
# scope violations become non-valid slots, imputed both ways) and "tamper_dropped" (sensitivity: tamper-confirmed
# slots are left out; they are never imputed as successes).
MODES = ("itt", "scope_nonvalid", "tamper_dropped")


def _empty_cell():
    return {"control": [], "treatment": [], "nonvalid": {"control": 0, "treatment": 0},
            "agent_failures": {"control": 0, "treatment": 0}, "scope_failures": {"control": 0, "treatment": 0},
            "tamper_failures": {"control": 0, "treatment": 0}}


def _arms(cell, mode="itt"):
    """(control, treatment, nonvalid) under one of MODES."""
    control, treatment = list(cell["control"]), list(cell["treatment"])
    nonvalid = dict(cell["nonvalid"])
    zero = {"control": 0, "treatment": 0}
    scope = cell.get("scope_failures") or zero
    tamper = cell.get("tamper_failures") or zero
    for group, values in (("control", control), ("treatment", treatment)):
        moved = scope[group] if mode == "scope_nonvalid" else 0
        dropped = tamper[group] if mode == "tamper_dropped" else 0
        values += [0.0] * (scope[group] + tamper[group] - moved - dropped)
        nonvalid[group] += moved
    return control, treatment, nonvalid


def _task_difference(cell, impute=None, mode="itt"):
    """impute=None: observed runs only (agent failures as 0); 'worst'/'best': remaining non-valid slots as 0/1
    against/for the treatment."""
    control, treatment, nonvalid = _arms(cell, mode)
    if impute is not None:
        bad_t, bad_c = (0.0, 1.0) if impute == "worst" else (1.0, 0.0)
        treatment += [bad_t] * nonvalid["treatment"]
        control += [bad_c] * nonvalid["control"]
    if not control or not treatment:
        return None
    return statistics.fmean(treatment) - statistics.fmean(control)


def _discriminating(cell, mode="itt"):
    control, treatment, _ = _arms(cell, mode)
    if not control or not treatment:
        return False
    pooled = set(control) | set(treatment)
    return not (len(pooled) == 1 and pooled <= {0.0, 1.0})


def _summary(values, n_discriminating, absent, plan):
    """One stratum (a tier or a discovery level): interval, decisions and every guard."""
    confidence, mid, harm = plan["confidence"], plan["mid"], plan["harm"]
    share_min = plan.get("min_discriminating_share", MIN_DISCRIMINATING_SHARE)
    if not values["valid"]:
        return {"tasks": 0, "decision": "inconclusive", "reason": "no task with valid runs in both arms",
                "missing_tasks": absent}
    main = _interval(values["valid"], confidence)
    worst = _interval(values["worst"], confidence)
    best = _interval(values["best"], confidence)
    decisions = {"observed": decide(main, mid, harm), "worst_case": decide(worst, mid, harm),
                 "best_case": decide(best, mid, harm)}
    robust = len(set(decisions.values())) == 1
    share = n_discriminating / main["n"]
    out = {"tasks": main["n"], "discriminating_tasks": n_discriminating, "discriminating_share": round(share, 4),
           "mean_task_difference": main["mean"], "sd": main["sd"],
           "ci": main["ci"], "df": main["df"], "bounds_mean": [worst["mean"], best["mean"]],
           "decisions": decisions, "robust_to_nonvalid": robust,
           "decision": decisions["observed"] if robust else "inconclusive",
           "missing_tasks": absent}
    # A ceiling (or floor) is not evidence of no effect, and a zero-spread interval is degenerate, not
    # precise. Both make the stratum inconclusive whatever the interval says.
    if absent:
        reason = f"pre-registered tasks have no slots for this model: {absent}"
    elif main["n"] < 2:
        reason = "fewer than two tasks: no interval"
    elif n_discriminating < 2:
        reason = ("ceiling or floor: fewer than two tasks in which the runs were not all at the same extreme "
                  "(every run passing, or every run failing, in both arms)")
    elif main["sd"] == 0:
        reason = "zero spread across tasks: the interval is degenerate"
    elif not robust:
        reason = "the decision changes when non-valid slots are imputed as failures or successes"
    elif out["decision"] == "no_meaningful_effect" and share < share_min:
        reason = (f"ceiling-dominated: only {n_discriminating} of {main['n']} tasks discriminate (share "
                  f"{share:.2f} < {share_min}); tasks at the same extreme in both arms cannot show an effect, so "
                  "their zero differences make the interval look precise")
    else:
        reason = None
    if reason is not None:
        out["decision"] = "inconclusive"
        out["reason"] = reason
    return out


def _strata(per_task, cells, key, order, info, plan, missing):
    """Summaries per stratum (tier or discovery level) and the pairwise interactions between strata, under the
    primary (itt) treatment of agent failures, with the two sensitivity results attached."""
    pools = {m: {s: {"valid": [], "worst": [], "best": [], "discriminating": 0} for s in order} for m in MODES}
    counts = {k: {s: {"control": 0, "treatment": 0} for s in order}
              for k in ("agent_failures", "tamper_failures")}
    for task, entry in per_task.items():
        if not entry["in_inference"]:
            continue
        stratum, cell = info[task][key], cells[task]
        for k in counts:
            for group in ARMS:
                counts[k][stratum][group] += cell[k][group]
        for mode in MODES:
            pool = pools[mode][stratum]
            pool["discriminating"] += _discriminating(cell, mode)
            for slot, impute in (("valid", None), ("worst", "worst"), ("best", "best")):
                value = _task_difference(cell, impute, mode)
                if value is not None:
                    pool[slot].append(value)
    summaries = {m: {} for m in MODES}
    for mode in MODES:
        for s in order:
            absent = sorted(t for t in missing if info[t][key] == s)
            summaries[mode][s] = _summary(pools[mode][s], pools[mode][s]["discriminating"], absent, plan)
    out_strata = {}
    for s in order:
        summary = summaries["itt"][s]
        summary["agent_failures"] = counts["agent_failures"][s]
        summary["tamper_failures"] = counts["tamper_failures"][s]
        summary["decision_if_scope_violations_were_nonvalid"] = summaries["scope_nonvalid"][s]["decision"]
        summary["decision_if_tamper_slots_were_dropped"] = summaries["tamper_dropped"][s]["decision"]
        summary["itt_dependent"] = any(summaries[m][s]["decision"] != summary["decision"] for m in MODES[1:])
        out_strata[s] = summary
    interaction = {}
    for i, low in enumerate(order):
        for high in order[i + 1:]:
            results = {m: _interaction(pools[m], summaries[m], low, high, plan) for m in MODES}
            entry = results["itt"]
            entry["conclusion_if_scope_violations_were_nonvalid"] = results["scope_nonvalid"]["conclusion"]
            entry["conclusion_if_tamper_slots_were_dropped"] = results["tamper_dropped"]["conclusion"]
            entry["itt_dependent"] = any(results[m]["conclusion"] != entry["conclusion"] for m in MODES[1:])
            interaction[f"{high} - {low}"] = entry
    return out_strata, interaction


def _interaction(pools, summaries, low, high, plan):
    """high - low. The same protections as each side: no ceiling/floor, ceiling-dominated or zero-spread stratum,
    no missing pre-registered task, and a direction only if it survives the non-valid-slot bounds."""
    confidence = plan["confidence"]
    share_min = plan.get("min_discriminating_share", MIN_DISCRIMINATING_SHARE)
    result = {slot: welch(pools[low][slot], pools[high][slot], confidence) for slot in ("valid", "worst", "best")}
    entry = dict(result["valid"])
    entry["bounds"] = {"worst_case": result["worst"], "best_case": result["best"]}
    problems = []
    for side in (low, high):
        summary = summaries[side]
        if summary.get("missing_tasks"):
            problems.append(f"{side}: missing pre-registered tasks")
        elif summary.get("tasks", 0) >= 2 and summary.get("discriminating_tasks", 0) < 2:
            problems.append(f"{side}: fewer than two discriminating tasks (ceiling or floor)")
        elif summary.get("tasks", 0) >= 2 and summary.get("sd") == 0:
            problems.append(f"{side}: zero spread across tasks (degenerate)")
        elif summary.get("tasks", 0) >= 2 and summary["discriminating_share"] < share_min:
            problems.append(f"{side}: ceiling-dominated (discriminating share {summary['discriminating_share']} "
                            f"< {share_min}); a difference in effect would reflect headroom, not difficulty")
    lows = [r["ci"][0] for r in result.values() if r.get("ci")]
    highs = [r["ci"][1] for r in result.values() if r.get("ci")]
    if problems:
        entry["conclusion"], entry["reason"] = "inconclusive", "; ".join(problems)
    elif entry.get("ci") is None:
        entry["conclusion"] = "inconclusive"
        entry.setdefault("reason", "fewer than two tasks in a stratum: no interval")
    elif len(lows) == 3 and min(lows) > 0:
        entry["conclusion"] = "effect_larger_in_" + high
    elif len(highs) == 3 and max(highs) < 0:
        entry["conclusion"] = "effect_smaller_in_" + high
    else:
        entry["conclusion"] = "inconclusive"
        entry["reason"] = ("the interval includes 0, or its sign changes when non-valid slots are imputed "
                           "as failures or successes")
    return entry


def analyse_outcome(cells_by_task, info, plan, outcome, missing=(), discovery_order=None):
    sets = set(plan["inference_sets"])
    per_task = {}
    for task, cell in sorted(cells_by_task.items()):
        meta = info[task]
        for k in ("agent_failures", "scope_failures", "tamper_failures"):
            cell.setdefault(k, {"control": 0, "treatment": 0})
        control, treatment, _ = _arms(cell)
        entry = {"tier": meta["tier"], "set": meta["set"], "provenance": meta["provenance"],
                 "n_control": len(cell["control"]), "n_treatment": len(cell["treatment"]),
                 "nonvalid": dict(cell["nonvalid"]), "agent_failures": dict(cell["agent_failures"]),
                 "control_mean": round(statistics.fmean(control), 4) if control else None,
                 "treatment_mean": round(statistics.fmean(treatment), 4) if treatment else None,
                 "in_inference": meta["set"] in sets}
        if meta.get("discovery") is not None:
            entry["discovery"] = meta["discovery"]
        diff = _task_difference(cell)
        entry["difference"] = None if diff is None else round(diff, 4)
        entry["discriminating"] = _discriminating(cell)
        entry["bounds"] = [None if v is None else round(v, 4)
                           for v in (_task_difference(cell, "worst"), _task_difference(cell, "best"))]
        per_task[task] = entry
    tiers, interaction = _strata(per_task, cells_by_task, "tier", plan["tier_order"], info, plan, missing)
    out = {"by_task": per_task, "by_tier": tiers, "interaction": interaction}
    if discovery_order and all(info[t].get("discovery") in discovery_order for t in info):
        out["by_discovery"], out["discovery_interaction"] = _strata(
            per_task, cells_by_task, "discovery", discovery_order, info, plan, missing)
    return out


def _is_confirmatory_design(plan, info):
    sets = set(plan["inference_sets"])
    return (plan["status"] == "frozen" and sets == {"confirmatory"}
            and all(m["provenance"] == "prospective" for m in info.values() if m["set"] in sets))


def analyse(rows, problems, loaded):
    plan, info = loaded["plan"], loaded["tasks"]
    _, purpose = check_plan_parameters(plan, "plan")
    sets = set(plan["inference_sets"])
    strict = _is_confirmatory_design(plan, info)
    label = ("confirmatory" if purpose == "confirmation" else "estimation") if strict else "exploratory"
    contrast = plan["power"]["contrast"] if label == "confirmatory" else None
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
        "label": label,
        "plan_status": plan["status"],
        "plan_purpose": purpose,
        "confirmatory_contrast": contrast,
        "plan_sha256": loaded.get("plan_sha256"),
        "rubric_sha256": loaded["rubric_sha256"],
        "ratings_sha256": loaded.get("ratings_sha256"),
        "inference_sets": sorted(sets),
        "thresholds": {"mid": plan["mid"], "harm": plan["harm"], "confidence": plan["confidence"],
                       "min_discriminating_share": plan.get("min_discriminating_share", MIN_DISCRIMINATING_SHARE)},
        "tiers": {t: sorted(k for k, m in info.items() if m["tier"] == t) for t in plan["tier_order"]},
        "post_hoc_tasks": sorted(k for k, m in info.items() if m["provenance"] == "post_hoc"),
        "rating_agreement_by_factor": agreement,
        "rating_gaps_by_task": {k: m.get("gaps") for k, m in sorted(info.items())},
        "by_model": {},
    }
    discovery_order = loaded.get("discovery_order")
    if discovery_order:
        report["discovery_levels"] = {v: sorted(k for k, m in info.items() if m.get("discovery") == v)
                                      for v in discovery_order}
    cells = {outcome: _task_cells(rows, problems, outcome, info) for outcome in outcomes}
    models = sorted(set(cells[primary]))
    inference_tasks = {t for t, m in info.items() if m["set"] in sets}
    if strict and not models:
        raise DifficultyError("confirmatory plan, but no slot exists for any model")
    for model in models:
        missing = sorted(inference_tasks - set(cells[primary][model]))
        if missing and strict:
            raise DifficultyError(f"{model}: pre-registered confirmatory tasks have no slots: {missing}")
        report["by_model"][model] = {}
        for o in outcomes:
            result = analyse_outcome(cells[o].get(model, {}), info, plan, o, missing, discovery_order)
            _mark_inference(result, label, contrast if o == primary else None)
            report["by_model"][model][("primary:" if o == primary else "secondary:") + o] = result
        report["by_model"][model]["missing_inference_tasks"] = missing
    report["interpretation"] = (
        "The skill effect is treatment - control within one model, estimated per task and averaged with equal task "
        "weight inside a tier. Intervals are over tasks (df = tasks - 1); repetitions narrow them only through the "
        "task means. Agent-caused failures (a forbidden file changed, confirmed tampering) count as failures; a tier "
        "decision is 'inconclusive' unless it survives imputing every other non-valid slot both ways, and "
        "'itt_dependent' marks a decision that would differ if scope violations were treated as non-valid. "
        "A larger model error rate on harder tasks says nothing about the skill; only the treatment - control "
        "difference and its change across tiers do. "
        + {"confirmatory": "",
           "estimation": "ESTIMATION: the plan does not record adequate power for a confirmatory claim; report the "
                         "intervals, not the decisions, as the result.",
           "exploratory": "EXPLORATORY: the plan is not frozen, the inference set is not the confirmatory set, or a "
                          "rating was made after outcomes were seen."}[label])
    return report


def _mark_inference(result, label, contrast):
    """Every tier, level and contrast gets 'inference': only the one contrast the plan powered (primary outcome)
    is 'confirmatory'; in a confirmatory plan everything else is 'estimation'."""
    default = "estimation" if label in ("confirmatory", "estimation") else "exploratory"
    for group in ("by_tier", "interaction", "by_discovery", "discovery_interaction"):
        for name, entry in (result.get(group) or {}).items():
            entry["inference"] = ("confirmatory" if contrast is not None and name == contrast
                                  and group in ("by_tier", "interaction") else default)


def calibration_feedback(rows, problems, loaded):
    """What task authors may see after the calibration stage: control-arm results of calibration tasks only.

    Treatment results, treatment slot counts and any treatment - control contrast are withheld, so nobody who can
    still change tasks can tune them toward the arm that is winning (DESIGN.md section 6)."""
    info = loaded["tasks"]
    calibration = {t for t, m in info.items() if m["set"] == "calibration"}
    out = {"kind": "aqd-calibration-feedback", "rubric_sha256": loaded["rubric_sha256"],
           "note": "control arm only; treatment results are withheld until the confirmatory analysis",
           "by_model": {}}
    cells = _task_cells(rows, problems, "fully_correct", info)
    fractions = _task_cells(rows, problems, "hidden_pass_fraction", info)
    for model in sorted(cells):
        for task in sorted(calibration & set(cells[model])):
            cell = cells[model][task]
            control, _, nonvalid = _arms(cell)
            frac, _, _ = _arms(fractions[model][task])
            out["by_model"].setdefault(model, {})[task] = {
                "tier": info[task]["tier"], "discovery": info[task].get("discovery"),
                "control_runs": len(control), "control_successes": int(sum(control)),
                "control_mean_hidden_pass_fraction": round(statistics.fmean(frac), 4) if frac else None,
                "control_agent_failures": cell["agent_failures"]["control"],
                "control_nonvalid_slots": nonvalid["control"]}
    return out
