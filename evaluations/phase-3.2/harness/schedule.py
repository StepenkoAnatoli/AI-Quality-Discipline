#!/usr/bin/env python3
"""Create and read the sealed run schedule.

    schedule.py create --out SEALED_DIR/schedule.json --models REF[,REF...]
                       [--tasks NEW-01,NEW-02,NEW-03] [--repetitions N] [--seed HEX] [--counterbalance]
    schedule.py next   --schedule FILE --captures DIR     # first run without run-status.json (exit 3: none)
    schedule.py get    --schedule FILE --run-id ID --key model|task|group|env|blind_id|repetition|block
    schedule.py rerun  --schedule FILE --run-id ID --reason TEXT

REF is provider/model[#variant] (Claude: anthropic/..., Grok: xai/...).
Smoke pilot: --tasks NEW-02 --repetitions 1 with both models = 4 runs.

Design (pre-registered):
  * models x tasks x repetitions blocks; each block holds one control and one
    treatment run of the same model and task, in random order; block order is
    random. The skill effect is only ever estimated within one model: control
    and treatment of a block share model, task, interface and settings.
  * Which OS user / environment label (env-a / env-b) hosts which group is
    random and recorded only here.
  * run_id (r-<10 hex>) appears in operator files and in the agent's working
    path; blind_id (b-<8 hex>) is a second, independent label used only in
    scorer packets, so packets cannot be matched to run order or logs.
  * --counterbalance (Phase 3.3 proposal; off by default, so every Phase 3.2
    schedule is reproduced byte for byte): which arm runs first is balanced
    instead of drawn independently per block. For every model and task, the
    treatment-first blocks number floor(reps/2) or ceil(reps/2); the odd extras
    are split so each model, and the whole schedule, differ by at most one; which blocks get
    which order is random. This removes the arm/position confound (in Phase 3.2
    treatment ran first in 4/4 pairs by chance).
The seed is generated with the OS CSPRNG unless given, and is recorded.
"""
import argparse
import datetime
import json
import os
import random
import secrets
import sys

from aqd_common import parse_model

TASKS = ("NEW-01", "NEW-02", "NEW-03")
# Tasks a schedule may name explicitly. The default design (TASKS) is the pre-registered pilot.
KNOWN_TASKS = TASKS + ("NEW-04", "SMOKE", "PROBE-CC")  # SMOKE, PROBE-CC: harness checks only, never scored
REPETITIONS = 3
GROUPS = ("control", "treatment")


def _balanced_first_arms(rng, blocks, repetitions):
    """{block: arm that runs first}, balanced per (model, task), per model and overall (module docstring).

    With odd repetitions each (model, task) has one 'extra' block. Within a model the extras are split evenly;
    when a model has an odd number of tasks, its leftover extra alternates between arms across models (random
    start), so the whole schedule also differs by at most one."""
    models = sorted({model for model, _, _ in blocks})
    odd_arm = rng.choice(GROUPS)
    first = {}
    for model in models:
        tasks = sorted({task for m, task, _ in blocks if m == model})
        extras = []
        if repetitions % 2:
            extras = ["treatment"] * (len(tasks) // 2) + ["control"] * (len(tasks) // 2)
            if len(tasks) % 2:
                extras.append(odd_arm)
                odd_arm = "control" if odd_arm == "treatment" else "treatment"
            rng.shuffle(extras)
        for index, task in enumerate(tasks):
            arms = ["treatment"] * (repetitions // 2) + ["control"] * (repetitions // 2)
            if repetitions % 2:
                arms.append(extras[index])
            rng.shuffle(arms)
            for rep, arm in zip(range(1, repetitions + 1), arms):
                first[(model, task, rep)] = arm
    return first


def make_schedule(seed_hex, models, tasks=TASKS, repetitions=REPETITIONS, counterbalance=False):
    for ref in models:
        parse_model(ref)
    if len(set(models)) != len(models) or not models:
        raise ValueError("models must be a non-empty list without duplicates")
    unknown = sorted(set(tasks) - set(KNOWN_TASKS))
    if unknown or not tasks or repetitions < 1:
        raise ValueError(f"bad design: tasks={tasks} repetitions={repetitions}")
    rng = random.Random(int(seed_hex, 16))
    envs = ["env-a", "env-b"]
    rng.shuffle(envs)
    env_for = dict(zip(GROUPS, envs))
    blocks = [(model, task, rep) for model in models for task in tasks for rep in range(1, repetitions + 1)]
    rng.shuffle(blocks)
    first_arm = _balanced_first_arms(rng, blocks, repetitions) if counterbalance else None
    used = set()

    def fresh(prefix, nbytes):
        while True:
            value = f"{prefix}-{rng.getrandbits(nbytes * 8):0{nbytes * 2}x}"
            if value not in used:
                used.add(value)
                return value

    runs = []
    for block_index, (model, task, rep) in enumerate(blocks, start=1):
        if first_arm is None:
            order = list(GROUPS)
            rng.shuffle(order)
        else:
            order = sorted(GROUPS, key=lambda g: g != first_arm[(model, task, rep)])
        for group in order:
            runs.append({"order": len(runs) + 1, "block": block_index, "model": model, "task": task, "repetition": rep,
                         "group": group, "env": env_for[group], "run_id": fresh("r", 5), "blind_id": fresh("b", 4)})
    design = {"models": list(models), "tasks": list(tasks), "repetitions": repetitions, "groups": list(GROUPS)}
    if counterbalance:
        design["counterbalanced"] = True
    return {
        "schema_version": 2,
        "kind": "aqd-phase-3.2-sealed-schedule",
        "seed": seed_hex,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "design": design,
        "env_for_group": env_for,
        "runs": runs,
    }


MAX_RERUNS_PER_SLOT = 1


def add_rerun(schedule, run_id, reason):
    """Append a replacement for an infrastructure-invalid run (same slot, new ids)."""
    runs = schedule["runs"]
    original = next((r for r in runs if r["run_id"] == run_id), None)
    if original is None:
        raise ValueError(f"unknown run id {run_id}")
    slot = original.get("replaces_slot", original["run_id"])
    attempts = sum(1 for r in runs if r.get("replaces_slot") == slot)
    if attempts >= MAX_RERUNS_PER_SLOT:
        raise ValueError(f"slot {slot} already has {attempts} rerun(s); the protocol allows {MAX_RERUNS_PER_SLOT}")
    used = {r["run_id"] for r in runs} | {r["blind_id"] for r in runs}
    while True:
        new_run, new_blind = f"r-{secrets.token_hex(5)}", f"b-{secrets.token_hex(4)}"
        if new_run not in used and new_blind not in used:
            break
    entry = {k: original[k] for k in ("block", "model", "task", "repetition", "group", "env")}
    entry.update({"order": len(runs) + 1, "run_id": new_run, "blind_id": new_blind, "replaces_slot": slot,
                  "replaces_run": run_id, "rerun_reason": reason})
    runs.append(entry)
    return entry


def validate(schedule):
    runs = [r for r in schedule["runs"] if "replaces_slot" not in r]
    design = schedule.get("design") or {}
    models, tasks, reps = design.get("models") or [], design.get("tasks") or [], design.get("repetitions") or 0
    problems = []
    if not models or not tasks or reps < 1:
        return ["schedule has no design section"]
    expected = len(models) * len(tasks) * reps * len(GROUPS)
    if len(runs) != expected:
        problems.append(f"expected {expected} runs, found {len(runs)}")
    for model in models:
        for task in tasks:
            for group in GROUPS:
                n = sum(1 for r in runs if r.get("model") == model and r["task"] == task and r["group"] == group)
                if n != reps:
                    problems.append(f"{model}/{task}/{group}: {n} runs")
    for block in {r["block"] for r in runs}:
        members = [r for r in runs if r["block"] == block]
        if sorted(r["group"] for r in members) != sorted(GROUPS) or len({(r["model"], r["task"]) for r in members}) != 1:
            problems.append(f"block {block} is not one control and one treatment of the same model and task")
    every = schedule["runs"]
    ids = [r["run_id"] for r in every] + [r["blind_id"] for r in every]
    if len(ids) != len(set(ids)):
        problems.append("duplicate identifiers")
    envs = schedule["env_for_group"]
    if sorted(envs.values()) != ["env-a", "env-b"]:
        problems.append("group/environment mapping is not a bijection")
    for r in runs:
        if r["env"] != envs[r["group"]]:
            problems.append(f"{r['run_id']}: env does not match group")
    if design.get("counterbalanced"):
        first = {}
        for r in sorted(runs, key=lambda r: r["order"]):
            first.setdefault(r["block"], r)
        def unbalanced(selected):
            n = sum(r["group"] == "treatment" for r in selected)
            return abs(2 * n - len(selected)) > 1
        if unbalanced(list(first.values())):
            problems.append("counterbalanced schedule: treatment-first and control-first blocks differ by more than one")
        for model in models:
            if unbalanced([r for r in first.values() if r["model"] == model]):
                problems.append(f"counterbalanced schedule: {model} first arms are not balanced")
            for task in tasks:
                if unbalanced([r for r in first.values() if r["model"] == model and r["task"] == task]):
                    problems.append(f"counterbalanced schedule: {model}/{task} first arms are not balanced")
    return problems


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--out", required=True)
    create.add_argument("--seed")
    create.add_argument("--models", required=True, help="comma-separated provider/model[#variant]")
    create.add_argument("--tasks", default=",".join(TASKS))
    create.add_argument("--repetitions", type=int, default=REPETITIONS)
    create.add_argument("--counterbalance", action="store_true",
                        help="balance which arm runs first (Phase 3.3 proposal; Phase 3.2 schedules never use it)")
    rerun = sub.add_parser("rerun")
    rerun.add_argument("--schedule", required=True)
    rerun.add_argument("--run-id", required=True)
    rerun.add_argument("--reason", required=True)
    show = sub.add_parser("next")
    show.add_argument("--schedule", required=True)
    show.add_argument("--captures", required=True)
    get = sub.add_parser("get")
    get.add_argument("--schedule", required=True)
    get.add_argument("--run-id", required=True)
    get.add_argument("--key", required=True, choices=("model", "task", "group", "env", "blind_id", "repetition", "block"))
    args = p.parse_args(argv)
    if args.command == "get":
        with open(args.schedule, encoding="utf-8") as handle:
            schedule = json.load(handle)
        run = next((r for r in schedule["runs"] if r["run_id"] == args.run_id), None)
        if run is None:
            print(f"schedule.py: unknown run id {args.run_id}", file=sys.stderr)
            return 1
        print(run[args.key])
        return 0
    if args.command == "rerun":
        with open(args.schedule, encoding="utf-8") as handle:
            schedule = json.load(handle)
        try:
            entry = add_rerun(schedule, args.run_id, args.reason)
        except ValueError as exc:
            print(f"schedule.py: {exc}", file=sys.stderr)
            return 1
        tmp = args.schedule + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(schedule, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, args.schedule)
        print(entry["run_id"])
        return 0
    if args.command == "next":
        with open(args.schedule, encoding="utf-8") as handle:
            schedule = json.load(handle)
        for run in sorted(schedule["runs"], key=lambda r: r["order"]):
            if not os.path.exists(os.path.join(args.captures, run["run_id"], "run-status.json")):
                print(run["run_id"])
                return 0
        return 3
    if os.path.exists(args.out):
        print(f"schedule.py: refusing to overwrite {args.out}", file=sys.stderr)
        return 2
    seed = args.seed or secrets.token_hex(16)
    try:
        schedule = make_schedule(seed, [m for m in args.models.split(",") if m],
                                 [t for t in args.tasks.split(",") if t], args.repetitions, args.counterbalance)
    except ValueError as exc:
        print(f"schedule.py: {exc}", file=sys.stderr)
        return 2
    problems = validate(schedule)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    with open(args.out, "x", encoding="utf-8") as handle:
        json.dump(schedule, handle, indent=2)
        handle.write("\n")
    print(f"schedule written: {len(schedule['runs'])} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
