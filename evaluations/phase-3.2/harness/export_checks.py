#!/usr/bin/env python3
"""Post-run checks on an exported session (operator-only; output is sealed).

    export_checks.py --export export.json --group control|treatment \
                     --model PROVIDER/MODEL[#VARIANT] --out FILE

The export shape follows SessionTransfer.Data in the official OpenAPI
reference: {"info": Session.Info, "messages": [Session.Message.Info]}.
Message types used: "user" (text, skills[]), "skill" (skill, text),
"assistant" (model {providerID,id,variant}, content[text|reasoning|tool],
tokens, error, finish), "model-switched".

Verdicts:
  model_ok         every assistant message used the run's provider/model, and
                   its variant when the run names one (observed variants are
                   recorded either way)
  activation       treatment: CONFIRMED when the canonical skill text is in
                   the session (skill message, attached text, or completed
                   skill tool output); control: NOT_APPLICABLE
  contamination    control: True when any skill text or skill-tool use of
                   code-discipline appears anywhere in the session
  valid            model_ok and not contaminated and (control or CONFIRMED)

Exit code 0 when valid, 1 when the run must be invalidated, 2 on bad input.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aqd_common as c  # noqa: E402


def load_export(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict) and "data" in data and "messages" not in data:
        data = data["data"]
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise ValueError("export has no messages array")
    return data


def _tool_parts(message):
    for part in message.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "tool":
            yield part


def analyse(export, group, model_ref):
    provider_id, model_id, variant = c.parse_model(model_ref)
    messages = export["messages"]
    report = {"group": group, "model_ref": model_ref, "message_count": len(messages), "assistant_messages": 0,
              "model_mismatches": [], "observed_models": [], "errors": [], "tool_counts": {},
              "tokens": {"input": 0, "output": 0, "reasoning": 0}, "cost_usd": None, "cost_messages": 0,
              "skill_messages": [], "user_skill_attachments": [], "skill_tool_calls": []}
    expected = {"providerID": provider_id, "id": model_id}
    if variant is not None:
        expected["variant"] = variant
    for index, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        kind = msg.get("type")
        if kind == "assistant":
            report["assistant_messages"] += 1
            model = msg.get("model") or {}
            observed = {k: model.get(k) for k in ("providerID", "id", "variant")}
            if observed not in report["observed_models"]:
                report["observed_models"].append(observed)
            actual = {k: model.get(k) for k in expected}
            if actual != expected:
                report["model_mismatches"].append({"index": index, "model": actual})
            if msg.get("error") or msg.get("finish") == "error":
                report["errors"].append({"index": index, "error": msg.get("error"), "finish": msg.get("finish")})
            cost = msg.get("cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
                # Provider-reported cost per assistant message, when the interface exports one; None when no
                # message reports it (never a fabricated zero).
                report["cost_usd"] = (report["cost_usd"] or 0) + cost
                report["cost_messages"] += 1
            for key in report["tokens"]:
                value = (msg.get("tokens") or {}).get(key)
                if isinstance(value, (int, float)):
                    report["tokens"][key] += value
            for part in _tool_parts(msg):
                name = part.get("name")
                report["tool_counts"][name] = report["tool_counts"].get(name, 0) + 1
                if name == "skill":
                    state = part.get("state") or {}
                    output = json.dumps(state.get("content", ""), ensure_ascii=False)
                    report["skill_tool_calls"].append({"index": index, "input": state.get("input"), "status": state.get("status"),
                                                       "output_has_skill_text": c.contains_all_sentinels(output)})
        elif kind == "skill":
            text = msg.get("text") or ""
            report["skill_messages"].append({"index": index, "skill": msg.get("skill"), "text_sha256": c.sha256_text(text),
                                             "has_skill_text": c.contains_all_sentinels(text)})
        elif kind == "user":
            for att in msg.get("skills") or []:
                text = att.get("text") or ""
                report["user_skill_attachments"].append({"index": index, "id": att.get("id"), "mention": att.get("mention"),
                                                         "has_skill_text": c.contains_all_sentinels(text)})
        elif kind == "model-switched":
            actual = {k: (msg.get("model") or {}).get(k) for k in expected}
            if actual != expected:
                report["model_mismatches"].append({"index": index, "model_switched_to": actual})

    report["model_ok"] = report["assistant_messages"] > 0 and not report["model_mismatches"]
    report["reasoning_tokens_observed"] = report["tokens"]["reasoning"] > 0

    whole = json.dumps(export, ensure_ascii=False)
    sentinel_hits = sum(whole.count(s) for s in c.SKILL_SENTINELS)
    in_context = (
        any(m["skill"] == c.SKILL_ID and m["has_skill_text"] for m in report["skill_messages"])
        or any(a["id"] == c.SKILL_ID and a["has_skill_text"] for a in report["user_skill_attachments"])
        or any((t["input"] or {}).get("id") == c.SKILL_ID and t["status"] == "completed" and t["output_has_skill_text"]
               for t in report["skill_tool_calls"])
    )
    skill_tool_targets = [(t["input"] or {}).get("id") for t in report["skill_tool_calls"]]
    if group == "treatment":
        report["activation"] = "CONFIRMED" if in_context else "NOT_CONFIRMED"
        report["contamination"] = False
    else:
        report["activation"] = "NOT_APPLICABLE"
        report["contamination"] = bool(sentinel_hits or in_context or c.SKILL_ID in skill_tool_targets
                                       or any(a["id"] == c.SKILL_ID for a in report["user_skill_attachments"]))
    report["sentinel_occurrences"] = sentinel_hits
    report["valid"] = report["model_ok"] and not report["contamination"] and report["activation"] in ("CONFIRMED", "NOT_APPLICABLE")
    reasons = []
    if not report["model_ok"]:
        reasons.append("model/variant differs from the run's model (or no assistant message)")
    if report["contamination"]:
        reasons.append("control session contains code-discipline content")
    if report["activation"] == "NOT_CONFIRMED":
        reasons.append("treatment skill content not found in session")
    report["invalid_reasons"] = reasons
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--export", required=True)
    p.add_argument("--group", choices=("control", "treatment"), required=True)
    p.add_argument("--model", required=True, help="provider/model[#variant]")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    try:
        report = analyse(load_export(args.export), args.group, args.model)
    except (OSError, ValueError) as exc:
        print(f"export_checks.py: {exc}", file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"export_checks: valid={report['valid']} activation={report['activation']} model_ok={report['model_ok']}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
