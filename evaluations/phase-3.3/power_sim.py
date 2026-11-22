#!/usr/bin/env python3
"""Precision and power of the task-level paired analysis (offline, no model calls).

    python evaluations/phase-3.3/power_sim.py [--sims 4000] [--seed 20261122]

Model. For each task, the control success probability is drawn from a Beta
distribution (between-task heterogeneity); the treatment probability is the
control probability plus a true effect `delta`, clipped to [0, 1]. Each arm
gets `reps` independent runs (Bernoulli). The analysis is the one implemented
in `evaluations/phase-3.2/harness/difficulty.py`: per-task difference of arm
means, tier mean of task differences, t-interval over tasks (df = tasks - 1).

What it answers. How wide the 95% interval for one tier is, and how often its
lower bound clears 0 and the pre-registered minimum important difference, for
designs with the same run budget but different task counts. The parameters are
assumptions, not measurements: no calibration data exists yet.
"""
import argparse
import math
import random
import statistics
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "phase-3.2", "harness"))
from difficulty import t_quantile  # noqa: E402


def simulate(rng, tasks, reps, delta, a, b):
    diffs = []
    for _ in range(tasks):
        pc = rng.betavariate(a, b)
        pt = min(1.0, max(0.0, pc + delta))
        c = sum(rng.random() < pc for _ in range(reps)) / reps
        t = sum(rng.random() < pt for _ in range(reps)) / reps
        diffs.append(t - c)
    mean = statistics.fmean(diffs)
    sd = statistics.stdev(diffs) if tasks > 1 else float("nan")
    half = t_quantile(0.975, tasks - 1) * sd / math.sqrt(tasks)
    return mean, half


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sims", type=int, default=4000)
    p.add_argument("--seed", type=int, default=20261122)
    p.add_argument("--mid", type=float, default=0.20)
    args = p.parse_args(argv)
    rng = random.Random(args.seed)
    # Control success on a "hard" task: mean 0.5, wide spread across tasks (Beta(1.5, 1.5)).
    scenarios = [("hard tier, control p ~ Beta(1.5,1.5)", 1.5, 1.5)]
    designs = [(4, 3), (6, 2), (12, 1), (8, 3)]  # (tasks per tier, runs per arm)
    print(f"sims={args.sims} seed={args.seed} MID={args.mid}")
    for label, a, b in scenarios:
        print(f"\n{label}")
        print("tasks reps runs/tier | delta | mean 95% half-width | P(lower>0) | P(lower>MID)")
        for tasks, reps in designs:
            for delta in (0.0, 0.2, 0.4):
                halves, pos, mid = [], 0, 0
                for _ in range(args.sims):
                    mean, half = simulate(rng, tasks, reps, delta, a, b)
                    if math.isnan(half):
                        continue
                    halves.append(half)
                    pos += mean - half > 0
                    mid += mean - half > args.mid
                n = len(halves)
                print(f"{tasks:5d} {reps:4d} {2 * tasks * reps:9d} | {delta:5.2f} | {statistics.fmean(halves):19.3f} |"
                      f" {pos / n:10.3f} | {mid / n:12.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
