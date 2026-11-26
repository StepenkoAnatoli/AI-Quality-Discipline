#!/usr/bin/env python3
"""Stage 1 per-run record and slot resolution (contract v1, STAGE1-RECORD.md). Offline, no model, no network.

    python3 -I stage1_record.py --schedule SEALED_STAGE1_SCHEDULE.json --attempts ATTEMPTS.json \
        --blocks BLOCK_EVENTS.json --out STAGE1-RECORD.json

Review 2026-11-26, finding 3. Turns what the harness and the scorer recorded about every run attempt into one
disposition per scheduled slot, under the rules of STAGE1-RECORD.md, fixed before any Stage 1 run:

  * every attempt is kept, with a typed cause, whether or not it counts;
  * a usage limit, rate limit, service outage or sandbox failure cancels the whole block (STAGE0-SOLO.md D4), and
    so does any other infrastructure failure of one of its runs: both runs of that block attempt are
    infrastructure-invalid, even one that finished;
  * an infrastructure-invalid block may be replaced once, by a block with the same slots; a block whose runs were
    agent failures or wrong code is never replaced (no rerun for wrong code);
  * a timeout is an outcome, scored on what exists; a scope violation is an agent failure: scored on its mutable
    files when the harness records it as a valid run (H2), a failure otherwise, and never `strictly_correct`;
  * a confirmed tamper verdict is an agent failure; a suspected or pending one, an invalid evaluation, a mixed set
    of reasons, or anything unknown is unattributed: not counted, and carried into the 0/1 bounds (fail closed);
  * the infrastructure-invalid rate counts every attempt that started or was cancelled, original and replacement,
    in numerator and denominator; runs never started because of STOP are counted separately.

The output holds treatment results, so under STAGE0-SOLO.md §2.5 it is produced only at analysis time; task
authors see only the control-only calibration feedback. Exit 0 when written, 2 when refused (an input breaks the
contract; no partial record is written).
"""
import argparse
import json
import sys

SCHEMA = "aqd-phase-3.3-stage1-record-v1"
CONTRACT = "STAGE1-RECORD.md v1"
GROUPS = ("control", "treatment")
KINDS = ("paired", "calibration")
TIERS = ("easy", "medium", "hard")
# Block-level causes (the launcher's block log, H4). Each cancels the whole block attempt.
BLOCK_INFRA_CAUSES = frozenset({"usage_limit", "rate_limit", "service_outage", "sandbox_failure", "operator_cancel"})
BLOCK_STATES = ("completed", "cancelled", "not_started")
SCOPE_REASON = "immutable files changed or missing"  # run_status.py; the agent's own doing
PROVIDER_MARK = "provider/API error"  # run_status.py
LAUNCHER_MARK = "launcher stopped at step"  # run_status.py
TAMPER = ("none", "suspected", "confirmed", None)
STOP_RULE = {"hard_control_runs": 8, "stop_if_successes_at_least": 7}  # DESIGN.md §6
INFRA_LIMIT = 0.10  # DESIGN.md §6; STAGE0-SOLO.md D4


class ContractError(ValueError):
    """An input does not follow the contract; nothing is resolved."""


def _bool(value):
    return value if isinstance(value, bool) else None


def _schedule_runs(schedule):
    runs = schedule.get("runs") if isinstance(schedule, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ContractError("the schedule has no runs")
    seen, blocks = set(), {}
    for r in runs:
        if not isinstance(r, dict):
            raise ContractError("a scheduled run is not an object")
        for key in ("run_id", "block", "task", "group", "kind", "tier", "repetition"):
            if key not in r:
                raise ContractError(f"a scheduled run lacks {key}")
        if r["run_id"] in seen:
            raise ContractError(f"duplicate run_id {r['run_id']}")
        seen.add(r["run_id"])
        if r["group"] not in GROUPS or r["kind"] not in KINDS or r["tier"] not in TIERS:
            raise ContractError(f"{r['run_id']}: group, kind or tier outside the contract")
        blocks.setdefault(r["block"], []).append(r)
    for block, members in blocks.items():
        kinds = {m["kind"] for m in members}
        replaces = {m.get("replaces_block") for m in members}
        if len(kinds) != 1 or len(replaces) != 1:
            raise ContractError(f"block {block} mixes kinds or replacement targets")
        groups = sorted(m["group"] for m in members)
        expected = ["control", "treatment"] if kinds == {"paired"} else ["control"]
        if groups != expected:
            raise ContractError(f"block {block}: a {kinds.pop()} block holds {groups}")
    return blocks


def _slot_key(run):
    return (run["task"], run["group"], run["repetition"], run["kind"])


def _replacements(blocks):
    """{original block: replacement block}; refuses chains, double replacement and mismatched slots."""
    out = {}
    for block, members in blocks.items():
        target = members[0].get("replaces_block")
        if target is None:
            continue
        if target not in blocks:
            raise ContractError(f"block {block} replaces unknown block {target}")
        if blocks[target][0].get("replaces_block") is not None:
            raise ContractError(f"block {block} replaces a replacement; one replacement per block")
        if target in out:
            raise ContractError(f"block {target} has more than one replacement")
        if sorted(map(_slot_key, members)) != sorted(map(_slot_key, blocks[target])):
            raise ContractError(f"block {block} does not have the same slots as {target}")
        out[target] = block
    return out


def run_cause(results, score, tamper):
    """(class, cause) of one attempt that ran in a block that was not cancelled.

    class: counted (scored outcome), agent (failure of the arm, counted as 0), infrastructure (cancels the block
    attempt), unattributed (not counted; 0/1 bounds). Fail closed: anything unknown is unattributed."""
    if not isinstance(results, dict) or results.get("recorded") is not True:
        return "infrastructure", "no_record"
    if tamper not in TAMPER:
        return "unattributed", "tamper_review_unknown"
    valid = _bool(results.get("valid"))
    reasons = results.get("invalid_reasons")
    if valid is None or not isinstance(reasons, list):
        return "unattributed", "record_malformed"
    if valid is False:
        if reasons and set(reasons) == {SCOPE_REASON}:
            return "agent", "scope_violation"
        if SCOPE_REASON in reasons:
            return "unattributed", "scope_violation_with_other_reasons"
        if any(PROVIDER_MARK in str(x) for x in reasons):
            return "infrastructure", "provider_error"
        if any(LAUNCHER_MARK in str(x) for x in reasons):
            return "infrastructure", "launcher_stopped"
        return "infrastructure", "run_invalid"
    if results.get("arm_matches") is False or (results.get("group") == "control" and results.get("loaded")):
        return "infrastructure", "arm_mismatch"
    if tamper == "confirmed":
        return "agent", "tamper_confirmed"
    if tamper == "suspected":
        return "unattributed", "tamper_suspected"
    if not isinstance(score, dict):
        return "unattributed", "score_missing"
    if score.get("evaluation_status") != "valid":
        return "unattributed", "evaluation_invalid"
    if score.get("review_required") is True and tamper is None:
        return "unattributed", "review_pending"
    if _bool(score.get("fully_correct")) is None:
        return "unattributed", "score_malformed"
    return "counted", None


def _outcome(results, score, cls, cause):
    """Outcome fields of one attempt; counted is set by the caller."""
    timed_out = (results or {}).get("timed_out") is True
    scope = (results or {}).get("scope_violation") is True or cause == "scope_violation"
    fully = strict = hidden = None
    if cls == "counted":
        fully = score["fully_correct"] is True
        strict = fully and not scope
        hidden = score.get("hidden_pass_fraction")
        if not fully:
            cause = "timeout" if timed_out else "wrong_code"
        elif scope:
            cause = "scope_violation"
    elif cls == "agent":
        fully, strict, hidden = False, False, 0.0
    return {"fully_correct": fully, "strictly_correct": strict, "hidden_pass_fraction": hidden,
            "failure_cause": cause, "timed_out": timed_out, "scope_violation": scope}


def _attempt(run, entry, block_state, block_cause):
    entry = entry if isinstance(entry, dict) else {}
    results, score, tamper = entry.get("results"), entry.get("score"), entry.get("tamper_review")
    if isinstance(results, dict):
        results = dict(results, group=run["group"])
    if block_state == "not_started":
        cls, cause = ("not_run", "stop") if block_cause == "stop" else ("infrastructure", block_cause)
    else:
        cls, cause = run_cause(results, score, tamper)
    rec = {"run_id": run["run_id"], "block": run["block"], "class": cls}
    rec.update(_outcome(results, score, cls, cause))
    inv = entry.get("invocation") if isinstance(entry.get("invocation"), dict) else {}
    res = results if isinstance(results, dict) else {}
    rec.update(
        invoked=res.get("invoked"), loaded=res.get("loaded"),
        before_first_named_edit=inv.get("before_first_named_edit"), shell_before_load=inv.get("shell_before_load"),
        before_first_edit=inv.get("before_first_edit"),
        total_tokens=res.get("total_tokens"), tokens_missing_reason=res.get("tokens_missing_reason"),
        duration_seconds=res.get("duration_seconds"))
    return rec


def _resolve_block(members, attempts, event):
    """Attempt records of one block attempt, after the block-level rule (D4)."""
    if not isinstance(event, dict) or event.get("state") not in BLOCK_STATES:
        raise ContractError(f"block {members[0]['block']} has no block event with a known state")
    state, cause = event["state"], event.get("cause")
    if state == "cancelled" and cause not in BLOCK_INFRA_CAUSES:
        raise ContractError(f"block {members[0]['block']}: cancellation cause {cause!r} outside the contract")
    if state == "not_started" and cause not in BLOCK_INFRA_CAUSES | {"stop"}:
        raise ContractError(f"block {members[0]['block']}: not-started cause {cause!r} outside the contract")
    recs = [_attempt(m, attempts.get(m["run_id"]), state, cause) for m in sorted(members, key=lambda m: m["group"])]
    infra = [r for r in recs if r["class"] == "infrastructure"]
    if state == "cancelled" or infra:
        # D4: the whole block attempt is infrastructure-invalid, both runs, even one that finished.
        trigger = cause if state != "completed" else "block_invalidated:" + infra[0]["failure_cause"]
        for r in recs:
            if r["class"] != "infrastructure" or state == "cancelled":
                # Kept for the sensitivity analysis that includes failed original blocks (finding 13).
                r["outcome_before_block_rule"] = {k: r[k] for k in ("class", "fully_correct", "strictly_correct",
                                                                   "failure_cause")}
                r.update({"class": "infrastructure", "fully_correct": None, "strictly_correct": None,
                          "hidden_pass_fraction": None, "failure_cause": trigger})
        return recs, "infrastructure_invalid"
    if all(r["class"] == "not_run" for r in recs):
        return recs, "not_run"
    return recs, "resolved"


def resolve(schedule, attempts, block_events):
    blocks = _schedule_runs(schedule)
    if not isinstance(attempts, dict) or not isinstance(block_events, dict):
        raise ContractError("attempts and block events must be objects keyed by run_id and block")
    known_runs = {r["run_id"] for ms in blocks.values() for r in ms}
    stray = sorted(set(attempts) - known_runs) + sorted(set(block_events) - set(blocks))
    if stray:
        raise ContractError(f"records for runs or blocks not in the schedule: {stray[:3]}")
    replacement = _replacements(blocks)
    block_out, attempt_out = {}, {}
    for block, members in blocks.items():
        recs, status = _resolve_block(members, attempts, block_events.get(block))
        block_out[block] = status
        for r in recs:
            attempt_out[r["run_id"]] = r
    for original, repl in replacement.items():
        if block_out[original] != "infrastructure_invalid":
            raise ContractError(f"block {original} was replaced but was not infrastructure-invalid "
                                f"(no rerun for wrong code or agent failure)")

    slots = []
    for block, members in blocks.items():
        if members[0].get("replaces_block") is not None:
            continue
        repl = replacement.get(block)
        for m in sorted(members, key=lambda m: m["group"]):
            chain = [attempt_out[m["run_id"]]]
            if repl is not None:
                twin = next(x for x in blocks[repl] if _slot_key(x) == _slot_key(m))
                chain.append(attempt_out[twin["run_id"]])
            last = chain[-1]
            counted = last["class"] in ("counted", "agent")
            slots.append({
                "slot": f"{block}:{m['group']}", "task": m["task"], "tier": m["tier"], "group": m["group"],
                "kind": m["kind"], "repetition": m["repetition"], "attempts": [a["run_id"] for a in chain],
                "replaced": repl is not None, "counted": counted,
                "disposition": last["class"] if last["class"] != "counted" else "scored",
                "cause": last["failure_cause"],
                "fully_correct": last["fully_correct"] if counted else None,
                "strictly_correct": last["strictly_correct"] if counted else None,
                "hidden_pass_fraction": last["hidden_pass_fraction"] if counted else None})
    return {"schema": SCHEMA, "contract": CONTRACT, "slots": slots, "attempts": list(attempt_out.values()),
            "blocks": block_out, "summary": summarize(slots, list(attempt_out.values()), blocks)}


def summarize(slots, attempts, blocks):
    group_of = {r["run_id"]: r["group"] for ms in blocks.values() for r in ms}
    started = [a for a in attempts if a["class"] != "not_run"]
    infra = [a for a in started if a["class"] == "infrastructure"]
    rate = len(infra) / len(started) if started else None
    per_arm = {}
    for g in GROUPS:
        s = [x for x in slots if x["group"] == g]
        a = [x for x in started if group_of[x["run_id"]] == g]
        per_arm[g] = {
            "slots": len(s), "counted": sum(x["counted"] for x in s),
            "not_counted": sum(not x["counted"] for x in s),
            "fully_correct": sum(x["fully_correct"] is True for x in s),
            "strictly_correct": sum(x["strictly_correct"] is True for x in s),
            "agent_failures": sum(x["disposition"] == "agent" for x in s),
            "timeouts": sum(x["cause"] == "timeout" for x in s),
            "scope_violations": sum(x["counted"] and x["cause"] == "scope_violation" for x in s),
            "attempts": len(a), "infrastructure_invalid_attempts": sum(x["class"] == "infrastructure" for x in a),
            "token_records_complete": sum(x["total_tokens"] is not None for x in a if x["class"] in ("counted", "agent")),
            "token_records_missing": sum(x["total_tokens"] is None for x in a if x["class"] in ("counted", "agent")),
            "invoked": sum(x["invoked"] is True for x in a), "loaded": sum(x["loaded"] is True for x in a),
            "loaded_before_first_edit": sum(x["before_first_edit"] is True for x in a)}
    hard = [x for x in slots if x["tier"] == "hard" and x["group"] == "control"]
    succ = sum(x["fully_correct"] is True for x in hard)
    open_ = sum(not x["counted"] for x in hard)
    need = STOP_RULE["stop_if_successes_at_least"]
    return {
        "attempts_started_or_cancelled": len(started), "infrastructure_invalid_attempts": len(infra),
        "infrastructure_invalid_rate": rate, "infrastructure_limit_exceeded": rate is not None and rate > INFRA_LIMIT,
        "not_run_after_stop": sum(a["class"] == "not_run" for a in attempts),
        "per_arm": per_arm,
        "hard_control_stop_rule": {
            "rule": STOP_RULE, "slots": len(hard), "successes": succ, "not_counted": open_,
            # 0/1 bounds over the slots that did not count: the rule is decided only when both bounds agree.
            "stop_if_all_open_fail": succ >= need, "stop_if_all_open_succeed": succ + open_ >= need,
            "decided": (succ >= need) == (succ + open_ >= need) and len(hard) == STOP_RULE["hard_control_runs"]}}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schedule", required=True)
    p.add_argument("--attempts", required=True)
    p.add_argument("--blocks", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    try:
        loaded = []
        for path in (args.schedule, args.attempts, args.blocks):
            with open(path, encoding="utf-8") as h:
                loaded.append(json.load(h))
        result = resolve(*loaded)
    except (OSError, ValueError) as exc:
        print(f"[stage1] refused: {exc}", file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(result, h, indent=2, sort_keys=True)
        h.write("\n")
    s = result["summary"]
    print(f"[stage1] {len(result['slots'])} slots, {s['attempts_started_or_cancelled']} attempts, "
          f"{s['infrastructure_invalid_attempts']} infrastructure-invalid; written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
