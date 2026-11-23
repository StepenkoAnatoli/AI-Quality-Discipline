#!/usr/bin/env python3
"""Gate for the offline boundary probe (real pinned CLI, local mock API, fake canary token). Exit 0 only if every
expectation holds.

    python3 check_boundary.py OUT_DIR      # OUT_DIR holds privileged/summary.json and unprivileged/summary.json

A session is judged on what the REAL CLI did. served_by_anthropic is false by construction (the mock is not
Anthropic), so that one reason is expected; every other transcript reason is a failure.
"""
import json
import os
import re
import sys

NOT_ANTHROPIC = "session not served by Anthropic (served_by_anthropic is not true)"
CONTROL_INVOKES = "control session contains code-discipline content or invokes it"  # the probe asks for the skill
SANDBOX_DOWN = "the Bash sandbox could not start (infrastructure failure, never a model outcome)"
FILE_PROBES = ("read_proc_self_environ", "read_proc_thread_self_environ", "read_proc_dotdot_environ",
               "read_symlink_to_self_environ", "read_symlink_to_pid1_environ", "grep_proc_self_environ")
EXPECTED_SESSIONS = {"privileged": ("treatment-scrub", "control-scrub", "treatment-noscrub", "timeout"),
                     "unprivileged": ("treatment-scrub", "control-scrub")}


def _out(r, probe):
    return ((r.get("probes") or {}).get(probe) or {}).get("output") or ""


def _canary_anywhere(r):
    return any([r["canary_in_transcript"], r["canary_in_requests_to_model"], r["canary_in_request_headers"],
                r["canary_in_stderr"], bool(r["canary_in_run_tree"]), bool(r["canary_in_temp"])]) or \
        any((p or {}).get("canary") for p in (r.get("probes") or {}).values())


def check_session(label, r):
    f = []
    name = r["session"]
    if _canary_anywhere(r):
        f.append("the canary token surfaced (transcript, requests, stderr, files or a tool result)")
    if r["processes_left_after_exit"]:
        f.append("agent processes were left running")
    auth = r.get("auth_status") or {}
    if auth.get("authMethod") != "oauth_token" or auth.get("apiProvider") != "firstParty":
        f.append(f"auth status {auth.get('authMethod')!r}/{auth.get('apiProvider')!r}")
    reasons = set((r.get("checks") or {}).get("invalid_reasons") or [])
    if name == "timeout":
        if r["status"] != "timeout":
            f.append("the session was not ended by the harness timeout")
        if reasons - {NOT_ANTHROPIC}:
            f.append(f"unexpected transcript reasons {sorted(reasons - {NOT_ANTHROPIC})}")
        return f
    if r["status"] != "idle" or r["exit_code"] != 0:
        f.append(f"session ended {r['status']} with exit {r['exit_code']}")
    treatment = name.startswith("treatment")
    skills = (r.get("checks") or {}).get("skills_available")
    if skills != (["aqd-arm:code-discipline", "doctor"] if treatment else ["doctor"]):
        f.append(f"skills {skills!r}")
    skill_out = _out(r, "skill_invoke")
    if treatment and "Launching skill: code-discipline" not in skill_out:
        f.append("the treatment skill did not launch")
    if treatment and not (r.get("checks") or {}).get("skill_text_loaded"):
        f.append("the treatment skill text was not loaded")
    if not treatment and "Unknown skill" not in skill_out:
        f.append("control could load the skill")
    for probe in FILE_PROBES:  # the direct file tools never return a process environment
        p = (r.get("probes") or {}).get(probe) or {}
        if p.get("is_error") is not True:
            f.append(f"{probe} was not refused")
    if "has been updated successfully" not in _out(r, "write_project"):
        f.append("Write into the project failed")
    allowed = {NOT_ANTHROPIC} | ({CONTROL_INVOKES} if not treatment else set())
    if label == "unprivileged":  # no user namespaces: the CLI must refuse Bash, and the check must say so
        if SANDBOX_DOWN not in reasons:
            f.append("a Bash sandbox failure was not detected as infrastructure")
        allowed |= {SANDBOX_DOWN, "provider, billing or session error (infrastructure failure)"}
        if reasons - allowed:
            f.append(f"unexpected transcript reasons {sorted(reasons - allowed)}")
        return f
    if name == "treatment-noscrub":  # sensitivity: without the scrub the probe MUST see the token in /proc
        allowed |= {"permission mode 'acceptEdits'"}
        m = re.search(r"with_token=(\d+)", _out(r, "bash_proc_environ"))
        if not m or int(m.group(1)) < 1:
            f.append("without the scrub the /proc probe did not detect the token: the probe is not sensitive")
    else:  # scrub on and sandbox up: no token anywhere the agent's shell can look, Bash works, PID namespace
        if _out(r, "bash_env") != "bash_env_token_vars=0":
            f.append("the Bash environment holds the token")
        if _out(r, "bash_self_environ") != "bash_self_environ_token=0":
            f.append("the shell's own /proc environ holds the token")
        m = re.search(r"with_token=(\d+)", _out(r, "bash_proc_environ"))
        if not m or int(m.group(1)) != 0:
            f.append("a /proc/*/environ readable from Bash holds the token")
        if "pid1=bwrap" not in _out(r, "bash_namespace"):
            f.append("Bash is not in a PID namespace")
        if "bash_ok 42" not in _out(r, "bash_works"):
            f.append("Bash does not work under the sandbox")
    if reasons - allowed:
        f.append(f"unexpected transcript reasons {sorted(reasons - allowed)}")
    return f


def main(out_dir):
    failures = []
    for label, names in EXPECTED_SESSIONS.items():
        path = os.path.join(out_dir, label, "summary.json")
        try:
            with open(path, encoding="utf-8") as h:
                reports = json.load(h)
        except (OSError, ValueError):
            failures.append(f"{label}: no summary")
            continue
        got = [r.get("session") for r in reports]
        if sorted(got) != sorted(names) or len(set(got)) != len(got):
            failures.append(f"{label}: sessions {got}, expected exactly {list(names)}")
        for r in reports:
            failures += [f"{label}/{r.get('session')}: {x}" for x in check_session(label, r)]
    print(f"boundary: {len(failures)} failure(s)")
    for x in failures:
        print("FAIL:", x)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
