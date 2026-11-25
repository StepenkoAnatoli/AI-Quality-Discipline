#!/usr/bin/env python3
"""Read-only check of what "the skill was invoked" meant in each treatment run (run it on DECRYPTED evidence, offline).

    python3 -I inspect_invocation.py --store DECRYPTED_OPERATOR_STORE --schedule pilot-schedule.json

Why: the harness's `invoked` (export-checks.json) is true as soon as the agent ISSUES a Skill call naming
code-discipline, whether or not the call succeeded, and whenever it happened. check_pilot.py's "invoked in k of n"
uses only that flag. This script separates, per treatment run, from the run's own transcript:
  called              a Skill tool_use naming code-discipline exists (= the harness's `invoked`);
  call_error          that call's tool_result is marked is_error;
  loaded              the skill text reached the session (all three sentinels after init; the harness's
                      `skill_text_loaded`, recomputed here);
  before_first_edit   the first successful load came before the first Edit/Write/MultiEdit/NotebookEdit call
                      (None when the run made no edit).
`disagrees_with_harness` flags a recomputed value that differs from export-checks.json. Output: run ids, task
names, booleans and counts only, never transcript content. Exit 0 always (a measurement, not a gate); 2 = usage.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "phase-3.2", "harness"))
import aqd_common as c  # noqa: E402

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _events(path):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as h:
            for line in h:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        return None
    return out


def _blocks(event):
    content = (event.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _target(inp):
    return str((inp or {}).get("skill", "")).split(":")[-1].lstrip("/")


def inspect_run(cap):
    events = _events(os.path.join(cap, "driver", "transcript.ndjson"))
    if events is None:
        return {"missing": True}
    init = next((i for i, e in enumerate(events) if e.get("type") == "system" and e.get("subtype") == "init"), -1)
    skill_ids, first_edit, first_load = {}, None, None
    called = call_error = False
    for i, e in enumerate(events):
        for b in _blocks(e):
            if b.get("type") == "tool_use":
                if b.get("name") == "Skill" and _target(b.get("input")) == c.SKILL_ID:
                    called = True
                    skill_ids[b.get("id")] = i
                elif b.get("name") in EDIT_TOOLS and first_edit is None:
                    first_edit = i
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in skill_ids:
                if b.get("is_error") is True:
                    call_error = True
                elif first_load is None and c.contains_all_sentinels(json.dumps(b.get("content"), ensure_ascii=False)):
                    first_load = i
    after_init = json.dumps([e for k, e in enumerate(events) if k != init], ensure_ascii=False)
    loaded = c.contains_all_sentinels(after_init)
    if first_load is None and loaded:
        # the text arrived outside the Skill tool_result (e.g. an injected message): position = the first event
        # after init that carries all sentinels
        first_load = next((k for k, e in enumerate(events) if k > init
                           and c.contains_all_sentinels(json.dumps(e, ensure_ascii=False))), None)
    before = None if first_edit is None else (first_load is not None and first_load < first_edit)
    return {"called": called, "call_error": call_error, "loaded": loaded, "before_first_edit": before}


def inspect(store, schedule):
    rows = []
    for run in sorted(schedule.get("runs") or [], key=lambda r: r.get("order", 0)):
        if run.get("group") != "treatment":
            continue
        cap = os.path.join(store, "captures", str(run.get("run_id")))
        row = {"run_id": run.get("run_id"), "task": run.get("task")}
        row.update(inspect_run(cap))
        if not row.get("missing"):
            try:
                with open(os.path.join(cap, "export-checks.json"), encoding="utf-8") as h:
                    harness = json.load(h)
            except (OSError, ValueError):
                harness = {}
            row["disagrees_with_harness"] = (harness.get("invoked") is not row["called"]
                                             or harness.get("skill_text_loaded") is not row["loaded"])
        rows.append(row)
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", required=True)
    p.add_argument("--schedule", required=True)
    args = p.parse_args(argv)
    try:
        with open(args.schedule, encoding="utf-8") as h:
            schedule = json.load(h)
    except (OSError, ValueError):
        print("invocation: the schedule is unreadable")
        return 2
    rows = inspect(args.store, schedule)
    for r in rows:
        if r.get("missing"):
            print(f"{r['run_id']} {r['task']}: transcript missing")
            continue
        print(f"{r['run_id']} {r['task']}: called={r['called']} call_error={r['call_error']} loaded={r['loaded']} "
              f"before_first_edit={r['before_first_edit']} disagrees_with_harness={r['disagrees_with_harness']}")
    ok = [r for r in rows if not r.get("missing")]
    print("invocation: called %d, loaded %d, loaded before the first edit %d, of %d treatment runs" % (
        sum(r["called"] for r in ok), sum(r["loaded"] for r in ok),
        sum(r["before_first_edit"] is True for r in ok), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
