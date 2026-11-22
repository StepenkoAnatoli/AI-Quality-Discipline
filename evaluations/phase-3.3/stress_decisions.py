#!/usr/bin/env python3
"""Stress tests of the Phase 3.3 decision rules (offline; no model calls).

    python evaluations/phase-3.3/stress_decisions.py [--sims 600] [--seed 20261123]

Every data set goes through the real difficulty.analyse_outcome, as power_sim.py does. Output: stress-output-2026-11-22.txt.
These are assumption sweeps, not measurements; they show how far the power_sim.py figures can move.
Sections:
  A  identifying a true null, and the benefit rule's power curve (hard tier only);
  B  robustness of min_discriminating_share = 0.45: other seeds, near-ceiling tasks that still have a
     (truncated) effect, 3 runs per arm, effect heterogeneity;
  C  how fragile a "0.8 power" claim is: the same design under infrastructure-invalid slots, ceiling share,
     heterogeneity, run-level overdispersion and drift between blocks.
"""
import argparse
import os
import random
import statistics
import sys

MID, HARM = 0.20, 0.10


def setup(phase33):
    sys.path.insert(0, phase33)
    sys.path.insert(0, os.path.join(phase33, "..", "phase-3.2", "harness"))
    import difficulty as d
    import power_sim as ps
    return d, ps


def hard_only(d, rng, tasks, reps, beta, effect, tau=0.0, ceiling=0.0, invalid=0.0, overdispersion=0.0,
              drift=0.0, share=None):
    """One simulated hard tier; returns the hard-tier summary from the real analysis."""
    cells, info, truth = {}, {}, []
    n_ceiling = round(ceiling * tasks)
    for i in range(tasks):
        at_ceiling = i < n_ceiling
        pc = rng.betavariate(40, 1) if at_ceiling else rng.betavariate(*beta)
        delta = 0.0 if at_ceiling else effect + (rng.gauss(0, tau) if tau else 0.0)
        pt = min(1.0, max(0.0, pc + delta))
        truth.append(pt - pc)
        cell = d._empty_cell()
        for group, p in (("control", pc), ("treatment", pt)):
            for r in range(reps):
                q = p
                if drift and r % 2:  # every other block runs after a provider-side change
                    q = min(1.0, max(0.0, q - drift))
                if overdispersion:  # run-to-run variation beyond Bernoulli (session-level luck)
                    q = min(1.0, max(0.0, q + rng.gauss(0, overdispersion)))
                if rng.random() < invalid:
                    cell["nonvalid"][group] += 1
                else:
                    cell[group].append(float(rng.random() < q))
        name = f"h{i:03d}"
        cells[name], info[name] = cell, {"tier": "hard", "set": "confirmatory", "provenance": "prospective"}
    plan = {"confidence": 0.95, "mid": MID, "harm": HARM, "inference_sets": ["confirmatory"], "tier_order": ["hard"]}
    if share is not None:
        plan["min_discriminating_share"] = share
    return d.analyse_outcome(cells, info, plan, "fully_correct")["by_tier"]["hard"], statistics.fmean(truth)


def rates(d, sims, seed, **kw):
    rng = random.Random(seed)
    counts, truth = {}, []
    for _ in range(sims):
        summary, t = hard_only(d, rng, **kw)
        counts[summary["decision"]] = counts.get(summary["decision"], 0) + 1
        truth.append(t)
    return {k: round(v / sims, 3) for k, v in sorted(counts.items())}, round(statistics.fmean(truth), 3)


def fmt(r):
    return " ".join(f"{k}={r[0].get(k, 0):.3f}" for k in ("benefit", "harm", "no_meaningful_effect", "inconclusive")) \
        + f"  (true effect {r[1]:+.3f})"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phase33", default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument("--sims", type=int, default=600)
    p.add_argument("--seed", type=int, default=20261123)
    args = p.parse_args()
    d, _ = setup(args.phase33)
    S, seed = args.sims, args.seed
    moderate = (4.0, 4.0)

    print(f"== A. Identifying a true null; the benefit rule's power curve. Hard tier, Beta(4,4), sims={S}")
    for tasks, reps in ((25, 2), (50, 2), (100, 2), (200, 2), (50, 4)):
        print(f"  {tasks:3d} tasks x {reps} runs/arm, true effect 0.00: {fmt(rates(d, S, seed, tasks=tasks, reps=reps, beta=moderate, effect=0.0))}")
    for tasks in (25, 50, 100):
        for effect in (0.1, 0.2, 0.3):
            print(f"  {tasks:3d} tasks x 2 runs/arm, nominal {effect:+.2f}: "
                  f"{fmt(rates(d, S, seed, tasks=tasks, reps=2, beta=moderate, effect=effect))}")

    print(f"\n== B. min_discriminating_share robustness (sims={S}). Rate of no_meaningful_effect when the skill has "
          f"a nominal effect of MID wherever there is room (false reassurance), worst over ceiling shares 0.1-0.85")
    variants = {
        "baseline grid, seed A": {"reps": 2, "tau": 0.0, "seeds": (seed,)},
        "other seeds B, C": {"reps": 2, "tau": 0.0, "seeds": (seed + 1, seed + 2)},
        "3 runs per arm": {"reps": 3, "tau": 0.0, "seeds": (seed,)},
        "heterogeneity tau 0.15": {"reps": 2, "tau": 0.15, "seeds": (seed,)},
    }
    for label, v in variants.items():
        for share in (0.40, 0.45, 0.50, 0.60):
            worst = 0.0
            for s in v["seeds"]:
                for tasks in (13, 25, 50):
                    for c in (0.1, 0.3, 0.5, 0.6, 0.7, 0.85):
                        r = rates(d, S // 2, s, tasks=tasks, reps=v["reps"], beta=moderate, effect=MID, tau=v["tau"],
                                  ceiling=c, share=share)
                        worst = max(worst, r[0].get("no_meaningful_effect", 0.0))
            print(f"  {label:26} share {share:.2f}: worst false reassurance {worst:.3f}")
    print("  near-ceiling tasks WITH a truncated effect (control ~ Beta(12,1), nominal +MID on every task):")
    for tasks in (25, 50, 100):
        for share in (0.45,):
            r = rates(d, S, seed, tasks=tasks, reps=2, beta=(12.0, 1.0), effect=MID, share=share)
            print(f"    {tasks:3d} tasks: {fmt(r)}")

    print(f"\n== C. Fragility of simulated power. Design 25 tasks x 2 runs/arm, nominal +0.40, Beta(4,4), sims={S}")
    base = {"tasks": 25, "reps": 2, "beta": moderate, "effect": 0.40}
    for label, extra in (("as simulated (no invalid slots)", {}), ("5% infrastructure-invalid slots", {"invalid": 0.05}),
                         ("10% infrastructure-invalid slots", {"invalid": 0.10}),
                         ("30% of tasks turn out at the ceiling", {"ceiling": 0.3}),
                         ("effect heterogeneity tau 0.30", {"tau": 0.30}),
                         ("run-level overdispersion sd 0.20", {"overdispersion": 0.20}),
                         ("control drifts -0.15 in half the blocks", {"drift": 0.15}),
                         ("wide Beta(1.5,1.5) instead", {"beta": (1.5, 1.5)}),
                         ("skewed-easy Beta(4,1.5) instead", {"beta": (4.0, 1.5)})):
        print(f"  {label:42} {fmt(rates(d, S, seed, **dict(base, **extra)))}")
    print("  same at nominal +0.20:")
    for label, extra in (("as simulated", {}), ("10% infrastructure-invalid slots", {"invalid": 0.10})):
        print(f"  {label:42} {fmt(rates(d, S, seed, **dict(base, effect=0.20, **extra)))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
