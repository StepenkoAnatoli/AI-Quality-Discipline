#!/usr/bin/env python3
"""Create and read the sealed run schedule for the 18-run pilot.

    schedule.py create --out SEALED_DIR/schedule.json [--seed HEX]
    schedule.py next   --schedule FILE --captures DIR     # first run without run-status.json (exit 3: none)
    schedule.py get    --schedule FILE --run-id ID --key task|group|env|blind_id|repetition
    schedule.py rerun  --schedule FILE --run-id ID --reason TEXT

Design (pre-registered):
  * 3 tasks x 3 repetitions = 9 blocks; each block holds one control and one
    treatment run of the same task, in random order; block order is random.
    Consecutive runs therefore alternate groups often and time-of-day drift is
    balanced across groups.
  * Which OS user / environment label (env-a / env-b) hosts which group is
    random and recorded only here.
  * run_id (r-<10 hex>) appears in operator files and in the agent's working
    path; blind_id (b-<8 hex>) is a second, independent label used only in
    scorer packets, so packets cannot be matched to run order or logs.
The seed is generated with the OS CSPRNG unless given, and is recorded.
"""
import argparse
import datetime
import json
import os
import random
import secrets
import sys

TASKS = ("NEW-01", "NEW-02", "NEW-03")
REPETITIONS = 3
GROUPS = ("control", "treatment")


def make_schedule(seed_hex):
    rng = random.Random(int(seed_hex, 16))
    envs = ["env-a", "env-b"]
    rng.shuffle(envs)
    env_for = dict(zip(GROUPS, envs))
    blocks = [(task, rep) for task in TASKS for rep in range(1, REPETITIONS + 1)]
    rng.shuffle(blocks)
    used = set()

    def fresh(prefix, nbytes):
        while True:
            value = f"{prefix}-{rng.getrandbits(nbytes * 8):0{nbytes * 2}x}"
            if value not in used:
                used.add(value)
                return value

    runs = []
    for block_index, (task, rep) in enumerate(blocks, start=1):
        order = list(GROUPS)
        rng.shuffle(order)
        for group in order:
            runs.append({"order": len(runs) + 1, "block": block_index, "task": task, "repetition": rep,
                         "group": group, "env": env_for[group], "run_id": fresh("r", 5), "blind_id": fresh("b", 4)})
    return {
        "schema_version": 1,
        "kind": "aqd-phase-3.2-sealed-schedule",
        "seed": seed_hex,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    entry = {k: original[k] for k in ("block", "task", "repetition", "group", "env")}
    entry.update({"order": len(runs) + 1, "run_id": new_run, "blind_id": new_blind, "replaces_slot": slot,
                  "replaces_run": run_id, "rerun_reason": reason})
    runs.append(entry)
    return entry


def validate(schedule):
    runs = [r for r in schedule["runs"] if "replaces_slot" not in r]
    problems = []
    if len(runs) != len(TASKS) * REPETITIONS * len(GROUPS):
        problems.append(f"expected 18 runs, found {len(runs)}")
    for task in TASKS:
        for group in GROUPS:
            n = sum(1 for r in runs if r["task"] == task and r["group"] == group)
            if n != REPETITIONS:
                problems.append(f"{task}/{group}: {n} runs")
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
    return problems


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--out", required=True)
    create.add_argument("--seed")
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
    get.add_argument("--key", required=True, choices=("task", "group", "env", "blind_id", "repetition", "block"))
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
    schedule = make_schedule(seed)
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
