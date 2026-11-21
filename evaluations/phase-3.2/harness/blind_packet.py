#!/usr/bin/env python3
"""Build blinded scorer packets from operator captures.

    blind_packet.py --schedule SEALED/schedule.json --captures CAPTURE_ROOT \
                    --pristine-root PRISTINE_ROOT --out PACKETS_DIR \
                    --sealed-log SEALED/redaction-log.json

A packet (PACKETS_DIR/<blind_id>/) contains only: the task text, the agent's
final report, a redacted transcript of visible text and tool calls, the diff
of the agent's changes, hidden-check and baseline outcomes, and workspace
findings. Removed: skill messages and attachments, reasoning, token counts,
durations, timestamps, run ids, environment labels and absolute paths, and
every mention of the skill. Redaction counts go only to the sealed log.
Only runs whose run-status.json says "valid": true are packaged.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aqd_common as c  # noqa: E402

PATH_PATTERNS = (
    (re.compile(r"/aqd/env-[a-z]+/runs/r-[0-9a-f]{10}/(project|home|tmp)"), r"<\1>"),
    (re.compile(r"/aqd/[^\s\"']*"), "<path>"),
    (re.compile(r"\benv-[a-z]+\b"), "<env>"),
    (re.compile(r"\br-[0-9a-f]{10}\b"), "<run>"),
    (re.compile(r"\bses_[0-9A-Za-z]+\b"), "<session>"),
)
MAX_TOOL_INPUT = 2000
MAX_TOOL_OUTPUT = 4000


class Redactor:
    def __init__(self):
        self.count = 0

    def __call__(self, text):
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        for sentinel in c.SKILL_SENTINELS:
            if sentinel in text:
                self.count += text.count(sentinel)
                text = text.replace(sentinel, "[redacted]")
        for pattern in c.BLINDING_PATTERNS:
            text, n = pattern.subn("[redacted]", text)
            self.count += n
        for pattern, repl in PATH_PATTERNS:
            text = pattern.sub(repl, text)
        return text


def _clip(text, limit):
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text) - limit} characters truncated]"


def render_transcript(export, redact):
    lines, final_text = [], ""
    for msg in export.get("messages", []):
        if not isinstance(msg, dict) or msg.get("type") != "assistant":
            continue
        for part in msg.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and part.get("text"):
                final_text = part["text"]
                lines.append("ASSISTANT:\n" + redact(part["text"]))
            elif part.get("type") == "tool":
                name = part.get("name")
                if name == "skill":
                    continue
                state = part.get("state") or {}
                lines.append(f"TOOL {name} [{state.get('status')}]\n  input: " + _clip(redact(state.get("input")), MAX_TOOL_INPUT))
                if "content" in state:
                    lines.append("  output: " + _clip(redact(state.get("content")), MAX_TOOL_OUTPUT))
    return "\n\n".join(lines), redact(final_text)


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path, default=""):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def build_packet(run, capture, pristine_root, out_dir, redact):
    export_path = os.path.join(capture, "driver", "export.json")
    if not os.path.exists(export_path):
        export_path = os.path.join(capture, "cli-export.json")
    export = _read_json(export_path)
    if "messages" not in export and "data" in export:
        export = export["data"]
    transcript, final_report = render_transcript(export, redact)
    task_text = _read_text(os.path.join(pristine_root, run["task"], "TASK.md"))
    diff = redact(_read_text(os.path.join(capture, "diff.patch"), "(no diff captured)"))
    hidden_path = os.path.join(capture, "hidden-score.json")
    hidden = _read_json(hidden_path) if os.path.exists(hidden_path) else None
    post = _read_json(os.path.join(capture, "verify-post.json"))
    findings = {k: v for k, v in post["findings"].items() if v and k not in ("mutable_changed", "additive_changed")}

    parts = [
        f"# Packet {run['blind_id']} - {run['task']}",
        "Score observable artifacts only, using shared-rubric.md and the private Phase 3.2 scoring key. "
        "Do not try to infer the condition; record your guess only at the end of the score file.",
        "## Task given to the agent\n\n" + task_text,
        "## Agent final report\n\n" + (final_report or "(no final text)"),
        "## Changes (diff against the pristine project)\n\n```diff\n" + diff + "\n```",
        "## Hidden checks\n\n" + ("\n".join(f"- {k}: {v}" for k, v in sorted(hidden["hidden_checks"].items())) if hidden else "(not yet scored)")
        + (f"\n\nBaseline tests (pristine): {'pass' if hidden['baseline_all_pass'] else 'FAIL'}" if hidden else ""),
        "## Workspace findings\n\n" + (json.dumps(findings, indent=2) if findings else "none"),
        "## Transcript (redacted)\n\n" + (transcript or "(empty)"),
    ]
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "packet.md"), "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(parts) + "\n")
    template = {
        "blind_id": run["blind_id"], "task": run["task"],
        "dimensions": {"correctness": None, "request_compliance": None, "evidence_verification": None,
                       "scope_economy": None, "clarity_usability": None},
        "critical_failures": [], "overclaims": [], "regressions": [], "notes": "",
        "group_guess": "unsure", "group_guess_confidence": None, "scorer_id": "",
    }
    with open(os.path.join(out_dir, "score.json"), "w", encoding="utf-8") as handle:
        json.dump(template, handle, indent=2)
        handle.write("\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--schedule", required=True)
    p.add_argument("--captures", required=True)
    p.add_argument("--pristine-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--sealed-log", required=True)
    args = p.parse_args(argv)
    schedule = _read_json(args.schedule)
    log = {}
    built = 0
    for run in schedule["runs"]:
        capture = os.path.join(args.captures, run["run_id"])
        status_path = os.path.join(capture, "run-status.json")
        if not os.path.exists(status_path) or not _read_json(status_path).get("valid"):
            log[run["run_id"]] = {"packaged": False}
            continue
        redact = Redactor()
        build_packet(run, capture, args.pristine_root, os.path.join(args.out, run["blind_id"]), redact)
        log[run["run_id"]] = {"packaged": True, "blind_id": run["blind_id"], "redactions": redact.count}
        built += 1
    with open(args.sealed_log, "w", encoding="utf-8") as handle:
        json.dump(log, handle, indent=2)
        handle.write("\n")
    print(f"packets built: {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
