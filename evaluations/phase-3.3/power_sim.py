#!/usr/bin/env python3
"""Operating characteristics of the Phase 3.3 analysis (offline, no model calls, no spend).

    python evaluations/phase-3.3/power_sim.py designs     [--sims N] [--seed S]
    python evaluations/phase-3.3/power_sim.py share-sweep [--sims N] [--seed S]
    python evaluations/phase-3.3/power_sim.py scale       [--sims N] [--seed S]
    python evaluations/phase-3.3/power_sim.py stop-rule

Every simulated data set goes through the real decision code,
`difficulty.analyse_outcome` (`evaluations/phase-3.2/harness/difficulty.py`),
with all its guards: at least two discriminating tasks, no zero spread,
robustness to non-valid slots, the ceiling-dominated share rule, estimate >= MID
for "benefit", and the same guards on each side of the interaction. Nothing is
re-implemented here, so the rates below are rates of the decisions the
analysis would actually report.

Model. Two tiers (easy, hard), `tasks` tasks each, `reps` runs per arm per task.
For each task the control success probability is drawn from a Beta distribution
(between-task variance assumption). A share `ceiling` of the hard tasks instead
sits near the ceiling (Beta(40, 1), no effect): tasks that turned out not to be
hard for the model. On the others the per-task effect is the tier effect plus
Normal(0, tau) heterogeneity; the treatment probability is clipped to [0, 1], so
the realised effect ("true_effect", averaged over simulations) can be smaller
than the nominal one. Runs are Bernoulli. Non-valid slots are not simulated. Infrastructure
slots only widen the bounds, so they make decisions more conservative.
Agent-caused failures (scope violations, confirmed tamper) count as 0s and
can move a decision in either direction; their rates are unknown, so they
are left out here, and the analysis reports itt_dependent for them instead.

Every parameter is an assumption, not a measurement: no calibration data exists
yet. The output is deterministic for a given seed.
"""
import argparse
import math
import os
import random
import statistics
import sys
from collections import namedtuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "phase-3.2", "harness"))
import difficulty as d  # noqa: E402

MID, HARM, CONFIDENCE = 0.20, 0.10, 0.95
CEILING_BETA = (40.0, 1.0)

Scenario = namedtuple("Scenario", "name easy hard easy_effect hard_effect tau ceiling")
Scenario.__new__.__defaults__ = (0.0,)  # ceiling share defaults to 0

# Variance assumptions for control success across tasks, from wide to narrow, and effect heterogeneity.
VARIANCE = {"wide Beta(1.5,1.5)": (1.5, 1.5), "moderate Beta(4,4)": (4.0, 4.0), "skewed-easy Beta(4,1.5)": (4.0, 1.5)}


def plan(share=None):
    p = {"confidence": CONFIDENCE, "mid": MID, "harm": HARM, "inference_sets": ["confirmatory"],
         "tier_order": ["easy", "hard"]}
    if share is not None:
        p["min_discriminating_share"] = share
    return p


def _task(rng, beta, effect, tau, reps, at_ceiling=False):
    pc = rng.betavariate(*(CEILING_BETA if at_ceiling else beta))
    delta = 0.0 if at_ceiling else effect + (rng.gauss(0.0, tau) if tau else 0.0)
    pt = min(1.0, max(0.0, pc + delta))
    cell = d._empty_cell()
    cell["control"] = [float(rng.random() < pc) for _ in range(reps)]
    cell["treatment"] = [float(rng.random() < pt) for _ in range(reps)]
    return cell, pt - pc


def simulate_once(rng, scenario, tasks, reps, share=None):
    cells, info, truth = {}, {}, {"easy": [], "hard": []}
    n_ceiling = round(scenario.ceiling * tasks)
    for tier, beta, effect in (("easy", scenario.easy, scenario.easy_effect),
                               ("hard", scenario.hard, scenario.hard_effect)):
        for i in range(tasks):
            name = f"{tier}{i:03d}"
            cell, realised = _task(rng, beta, effect, scenario.tau, reps, tier == "hard" and i < n_ceiling)
            cells[name] = cell
            info[name] = {"tier": tier, "set": "confirmatory", "provenance": "prospective"}
            truth[tier].append(realised)
    out = d.analyse_outcome(cells, info, plan(share), "fully_correct")
    return out, {k: statistics.fmean(v) for k, v in truth.items()}, truth


def run_design(scenario, tasks, reps, sims, seed, share=None):
    """Decision rates per tier and for hard - easy, plus the mean realised (clipped) effects."""
    rng = random.Random(seed)
    counts = {"easy": {}, "hard": {}, "interaction": {}}
    truth_sum = {"easy": 0.0, "hard": 0.0}
    halves = []
    for _ in range(sims):
        out, truth, _ = simulate_once(rng, scenario, tasks, reps, share)
        for tier in ("easy", "hard"):
            decision = out["by_tier"][tier]["decision"]
            counts[tier][decision] = counts[tier].get(decision, 0) + 1
            truth_sum[tier] += truth[tier]
        ci = out["by_tier"]["hard"].get("ci")
        if ci:
            halves.append((ci[1] - ci[0]) / 2)
        conclusion = out["interaction"]["hard - easy"]["conclusion"].replace("effect_", "")
        counts["interaction"][conclusion] = counts["interaction"].get(conclusion, 0) + 1
    rates = {k: {dk: round(v / sims, 4) for dk, v in sorted(c.items())} for k, c in counts.items()}
    for key, labels in (("easy", d.DECISIONS), ("hard", d.DECISIONS),
                        ("interaction", ("larger_in_hard", "smaller_in_hard", "inconclusive"))):
        for label in labels:
            rates[key].setdefault(label, 0.0)
    rates["true_effect"] = {k: round(v / sims, 4) for k, v in truth_sum.items()}
    rates["true_effect"]["interaction"] = round(rates["true_effect"]["hard"] - rates["true_effect"]["easy"], 4)
    rates["hard_half_width"] = round(statistics.fmean(halves), 3) if halves else None
    return rates


def stop_probability(n, k, p):
    """P(at least k successes in n control runs | true control success p): the chance the Stage 1 stop rule
    'stop if control succeeds in >= k of n hard-task runs' fires."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def _betabinom_pmf(reps, a, b):
    """P(j successes in `reps` runs) when the task's success probability is Beta(a, b)."""
    def lbeta(x, y):
        return math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y)
    return [math.comb(reps, j) * math.exp(lbeta(j + a, reps - j + b) - lbeta(a, b)) for j in range(reps + 1)]


def _convolve(pmfs):
    total = [1.0]
    for pmf in pmfs:
        out = [0.0] * (len(total) + len(pmf) - 1)
        for i, x in enumerate(total):
            for j, y in enumerate(pmf):
                out[i + j] += x * y
        total = out
    return total


def stop_probability_clustered(tasks, reps, k, mean, kappa=None):
    """P(the Stage 1 stop rule fires: >= k successes over `tasks` hard tasks x `reps` control runs each), when each
    task's success probability is drawn from Beta(mean*kappa, (1-mean)*kappa) and runs within a task are Bernoulli.

    kappa=None is the binomial model (every task has the same probability, `mean`): stop_probability(tasks*reps, ...).
    Smaller kappa means more difference between tasks; runs of one task are then correlated, which is what the
    binomial table ignores (review 2026-11-26, finding 15). Exact, not simulated."""
    if kappa is None:
        return stop_probability(tasks * reps, k, mean)
    pmf = _convolve([_betabinom_pmf(reps, mean * kappa, (1 - mean) * kappa)] * tasks)
    return sum(pmf[k:])


def stop_probability_two_point(tasks, reps, k, share_solvable, p_solvable=1.0, p_unsolvable=0.0):
    """The limiting case: each task is independently 'solvable' (success p_solvable) with probability share_solvable,
    otherwise 'unsolvable' (success p_unsolvable)."""
    task = [share_solvable * x + (1 - share_solvable) * y for x, y in zip(
        [math.comb(reps, j) * p_solvable ** j * (1 - p_solvable) ** (reps - j) for j in range(reps + 1)],
        [math.comb(reps, j) * p_unsolvable ** j * (1 - p_unsolvable) ** (reps - j) for j in range(reps + 1)])]
    return sum(_convolve([task] * tasks)[k:])


# ------------------------------------------------------------------ reports

DESIGNS = [(4, 3), (6, 2), (12, 1), (8, 3), (25, 2)]


def report_designs(sims, seed):
    print(f"Decision rates through difficulty.analyse_outcome (all guards). sims={sims} seed={seed} MID={MID}")
    print("Easy tier has no effect. P(benefit) = P(hard tier decision 'benefit'); P(larger) = P(interaction "
          "'effect_larger_in_hard'); P(nme) = P('no_meaningful_effect').")
    for vname, beta in VARIANCE.items():
        for tau in (0.0, 0.15):
            print(f"\ncontrol success across tasks ~ {vname}, effect heterogeneity tau={tau}")
            print("tasks/tier reps runs | nominal -> true hard effect | hard half-width | P(benefit) P(harm) P(nme) "
                  "| P(larger) P(smaller)")
            for tasks, reps in DESIGNS:
                for effect in (0.0, 0.2, 0.4):
                    s = Scenario(vname, beta, beta, 0.0, effect, tau)
                    r = run_design(s, tasks, reps, sims, seed)
                    h, i = r["hard"], r["interaction"]
                    print(f"{tasks:10d} {reps:4d} {4 * tasks * reps:4d} | {effect:7.2f} -> {r['true_effect']['hard']:6.3f}"
                          f"     | {r['hard_half_width'] or float('nan'):15.3f} | {h['benefit']:10.3f} {h['harm']:6.3f} "
                          f"{h['no_meaningful_effect']:6.3f} | {i['larger_in_hard']:9.3f} {i['smaller_in_hard']:11.3f}")


SHARES = (0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7)
OFF = 1e-9  # a share rule that never fires (every tier with a decision has at least one discriminating task)
CEILING_SHARES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.77, 0.85)


def _hard_decisions(scenario, tasks, reps, sims, seed):
    """(decision without the share rule, discriminating share) per simulation. The share rule is the last guard
    in difficulty._summary and only turns 'no_meaningful_effect' into 'inconclusive', so the decision for any
    threshold follows exactly from these two values."""
    rng = random.Random(seed)
    out = []
    for _ in range(sims):
        result, _, _ = simulate_once(rng, scenario, tasks, reps, OFF)
        hard = result["by_tier"]["hard"]
        out.append((hard["decision"], hard.get("discriminating_share", 0.0)))
    return out


def _nme_rate(decisions, share):
    return sum(dec == "no_meaningful_effect" and frac >= share for dec, frac in decisions) / len(decisions)


def share_sweep(sims, seed, shares=SHARES):
    """Rate of 'no_meaningful_effect' on the hard tier for each candidate minimum discriminating share.

    False reassurance: a share `ceiling` of hard tasks (0.1 to 0.85) is at the ceiling (no room for any effect)
    and the skill has a nominal effect of MID on every task that has room. Concluding 'no meaningful effect'
    there describes the task selection, not the skill. Cost: the same rate when the effect is truly 0 and no task
    is at the ceiling (a genuine null should stay concludable). Returns {share: summary}; share OFF is the rule
    switched off (the 1912c0b behaviour)."""
    false_grid = [(beta, tasks, reps, c) for beta in VARIANCE.values()
                  for tasks, reps in ((6, 2), (13, 2), (25, 2), (25, 1)) for c in CEILING_SHARES]
    null_grid = [(beta, tasks, reps) for beta in VARIANCE.values() for tasks, reps in ((6, 2), (13, 2), (25, 2), (25, 3))]
    false_runs = [(key, _hard_decisions(Scenario("x", key[0], key[0], 0.0, MID, 0.0, key[3]), key[1], key[2], sims, seed))
                  for key in false_grid]
    null_runs = [_hard_decisions(Scenario("x", b, b, 0.0, 0.0, 0.0), t, r, sims, seed) for b, t, r in null_grid]
    rows = {}
    for share in (OFF,) + tuple(shares):
        worst = max(((_nme_rate(dec, share), key) for key, dec in false_runs), key=lambda x: x[0])
        nulls = [_nme_rate(dec, share) for dec in null_runs]
        rows[share] = {"worst_false": round(worst[0], 4), "worst_at": worst[1] if worst[0] else None,
                       "null_rate_mean": round(statistics.fmean(nulls), 4), "null_rate_max": round(max(nulls), 4)}
    return rows


def report_share_sweep(sims, seed):
    print(f"min_discriminating_share sweep (hard tier, real guards). sims={sims} seed={seed}")
    print("share | worst P(nme) with effect = MID on every task with room | P(nme) under a genuine null: mean, max")
    rows = share_sweep(sims, seed)
    for share, r in rows.items():
        label = "off" if share == OFF else f"{share:.2f}"
        print(f"{label:>5} | {r['worst_false']:6.3f} at (beta, tasks, reps, ceiling share) = {r['worst_at']} | "
              f"{r['null_rate_mean']:.3f}, {r['null_rate_max']:.3f}")
    chosen = next((s for s, r in rows.items() if s != OFF and r["worst_false"] <= 0.05), None)
    print(f"smallest share on the grid with worst false reassurance <= 0.05: {chosen}")
    return chosen


def report_scale(sims, seed):
    """How many tasks per tier a decision-grade answer needs (2 runs per arm, true effect +MID on hard only)."""
    print(f"Scale needed for 0.8 power (2 runs/arm, nominal +{MID} on hard, none on easy). sims={sims} seed={seed}")
    print("variance assumption             tau  | tasks/tier | P(hard benefit) | P(effect_larger_in_hard)")
    for vname, beta in (("moderate Beta(4,4)", (4.0, 4.0)), ("wide Beta(1.5,1.5)", (1.5, 1.5))):
        for tau in (0.0, 0.15):
            for tasks in (25, 50, 75, 100):
                r = run_design(Scenario(vname, beta, beta, 0.0, MID, tau), tasks, 2, sims, seed)
                print(f"{vname:30} {tau:4.2f} | {tasks:10d} | {r['hard']['benefit']:15.3f} | "
                      f"{r['interaction']['larger_in_hard']:.3f}")


def report_stop_rule():
    print("Stage 1 stop rule: P(stop) = P(control succeeds in >= k of n hard-task control runs | true success p)")
    print("rule                 | p=0.95 p=0.90 p=0.80 p=0.70 p=0.60 p=0.50")
    for n, k, label in ((4, 4, "4 runs, >= 0.9 (4/4)"), (4, 3, "4 runs, >= 3/4"), (8, 8, "8 runs, >= 0.9 (8/8)"),
                        (8, 7, "8 runs, >= 7/8")):
        print(f"{label:20} | " + " ".join(f"{stop_probability(n, k, p):6.3f}" for p in (0.95, 0.9, 0.8, 0.7, 0.6, 0.5)))
    print("\nWith task heterogeneity (review 2026-11-26, finding 15): rule '>= 7 of 8', mean control success m; each")
    print("task's success ~ Beta(m*kappa, (1-m)*kappa). kappa=inf is the binomial row above. Exact.")
    for tasks, reps in ((2, 4), (4, 2), (8, 1)):
        print(f"  {tasks} hard tasks x {reps} control runs")
        for kappa in (None, 20.0, 5.0, 2.0, 1.0):
            row = " ".join(f"{stop_probability_clustered(tasks, reps, 7, m, kappa):6.3f}"
                           for m in (0.95, 0.9, 0.8, 0.7, 0.6, 0.5))
            print(f"    kappa={'inf' if kappa is None else kappa:<5} | {row}")
    print("  limiting case, 2 x 4: 60% of tasks always solved, 40% never (mean 0.6): "
          f"P(stop) = {stop_probability_two_point(2, 4, 7, 0.6):.3f}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("report", choices=("designs", "share-sweep", "scale", "stop-rule"))
    p.add_argument("--sims", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20261122)
    args = p.parse_args(argv)
    if args.report == "designs":
        report_designs(args.sims, args.seed)
    elif args.report == "share-sweep":
        report_share_sweep(args.sims, args.seed)
    elif args.report == "scale":
        report_scale(args.sims, args.seed)
    else:
        report_stop_rule()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
