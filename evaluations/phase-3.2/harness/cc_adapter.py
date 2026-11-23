#!/usr/bin/env python3
"""Native Claude Code adapter for the Phase 3.2 harness (Phase 3.3 feasibility; OFFLINE-TESTED ONLY).

Execution environment "native-claude-code": the unmodified `claude` CLI run headless (`claude -p`) under the
owner's own Claude subscription (CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`). It is a DIFFERENT execution
environment from the Phase 3.2 OpenCode harness, whose records stay the historical reference. Results from the
two are never pooled.

It replaces only OpenCode's server, session driver and export parsing. Everything else is reused: the sealed
schedule (schedule.py), immutable manifests (manifest.py), OS-user isolation and `env -i` agent environments
(lib.sh), validity gates (run_status.py --interface claude-code) and private scoring (score_run.py).

    cc_adapter.py check-env      --env-file F                   # names/values never printed
    cc_adapter.py check-auth     --status-json F --out F        # check saved `claude auth status --json` output
    cc_adapter.py auth-status    --claude BIN --env-file F --secret-file F --out F [--as-user U --wrapper W]
    cc_adapter.py write-settings --out F
    cc_adapter.py argv           --claude BIN --model REF --settings F --max-turns N
    cc_adapter.py run            --claude BIN --model REF --settings F --max-turns N --prompt-file F \
                                 --env-file F --secret-file F --timeout S --out-dir D [--as-user USER]
    cc_adapter.py check-transcript --transcript F --group G --model REF --out F

Treatment = the canonical skill is AVAILABLE (a user skill in the run's own CLAUDE_CONFIG_DIR). The prompt is
byte-identical in both arms; nothing names or forces the skill. Invocation (a Skill tool_use naming it) and
loading (its text in the transcript) are recorded separately and are NOT validity conditions: the estimand is the
effect of availability. Whether the agent FOLLOWED the skill is not measured here.

Every check fails closed: an unrecognised transcript shape, a missing field or an unexpected value invalidates
the run; nothing is inferred. What is assumed rather than verified is listed in CC_ADAPTER.md.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aqd_common as c  # noqa: E402

EXECUTION_ENVIRONMENT = "native-claude-code"
PINNED_CLI_VERSION = "2.1.330"
INTERFACE = f"claude-code {PINNED_CLI_VERSION}"
ACTIVATION_MODE = "cc-skill-available"
CODING_TOOLS = ("Bash", "Read", "Edit", "Write", "Glob", "Grep")
FORBIDDEN_TOOLS = ("WebFetch", "WebSearch")
OAUTH_VAR = "CLAUDE_CODE_OAUTH_TOKEN"

# The run's environment is built from scratch (env -i); these are the only names it may contain. Anything else,
# in particular any API key, base URL, alternative provider switch, model or effort override, fails the run.
ALLOWED_ENV = frozenset({
    "HOME", "CLAUDE_CONFIG_DIR", "TMPDIR", "PATH", "SHELL", "LANG", "LC_ALL", "TERM", "PYTHONDONTWRITEBYTECODE",
    "DISABLE_AUTOUPDATER", "DISABLE_UPDATES", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB", "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS",
    "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK", "CLAUDE_CODE_SKIP_PROMPT_HISTORY",
})
# Documented (env-vars.md, setup.md): DISABLE_UPDATES blocks every update path (DISABLE_AUTOUPDATER only the
# background check); CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC stops telemetry, error reporting and skill sync;
# CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK stops the refusal model switch. CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is in the
# 2.1.330 binary (strips credentials from the agent's subprocesses, needs bubblewrap), not in the public docs.
REQUIRED_ENV = {"DISABLE_AUTOUPDATER": "1", "DISABLE_UPDATES": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK": "1", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
                "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1", "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1"}
# Named explicitly so the refusal says why (they are also outside ALLOWED_ENV).
BILLING_HAZARDS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
                   "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                   "AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
                   "ANTHROPIC_AWS_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_MODEL", "CLAUDE_CODE_EFFORT_LEVEL")

# Passed with --settings (honoured per invocation). syncClaudeAi*: claude.ai account skills/plugins never appear;
# switchModelsOnFlag false: a safeguard flag pauses the session instead of switching model; disableBundledSkills:
# Claude Code's own skills are off in both arms, so the only skill difference is code-discipline.
HARNESS_SETTINGS = {
    "syncClaudeAiSkills": False,
    "syncClaudeAiPlugins": False,
    "switchModelsOnFlag": False,
    "disableBundledSkills": True,
    "permissions": {"allow": list(CODING_TOOLS), "deny": list(FORBIDDEN_TOOLS)},
}

# api_retry / result error categories that mean infrastructure or billing, never a model outcome.
INFRA_ERRORS = ("billing_error", "rate_limit", "authentication_failed", "invalid_request", "model_not_found",
                "overloaded", "server_error", "unknown")


class AdapterError(Exception):
    pass


# ------------------------------------------------------------------ pre-run checks

def check_env(env):
    """Reasons (names only, never values) the run environment is unsafe or could bill outside the subscription."""
    reasons = []
    for name in BILLING_HAZARDS:
        if name in env:
            reasons.append(f"{name} is set: refused (API-key, alternative-provider or override route)")
    for name in sorted(set(env) - ALLOWED_ENV - {OAUTH_VAR} - set(BILLING_HAZARDS)):
        reasons.append(f"unexpected environment variable {name}")
    for name, value in REQUIRED_ENV.items():
        if env.get(name) != value:
            reasons.append(f"{name} must be {value}")
    for name in ("HOME", "CLAUDE_CONFIG_DIR", "TMPDIR"):
        if not os.path.isabs(env.get(name, "")):
            reasons.append(f"{name} must be an absolute path")
    if OAUTH_VAR in env:
        reasons.append(f"{OAUTH_VAR} must come from the secret file, not the environment file")
    return reasons


def check_token(token):
    """The subscription token's shape (never its value). An API key in the OAuth variable is refused."""
    if not token or token != token.strip() or any(ch.isspace() for ch in token):
        return ["subscription token is empty or contains whitespace"]
    if token.startswith("sk-ant-api"):
        return ["the secret is an API key, not a subscription OAuth token: refused"]
    if not token.startswith("sk-ant-oat"):
        return ["the secret does not look like a `claude setup-token` OAuth token: refused"]
    return []


def check_auth_status(status):
    """`claude auth status --json` (no model request). Documented: authMethod is one of none, claude.ai,
    oauth_token, api_key, api_key_helper, third_party; "oauth_token" is CLAUDE_CODE_OAUTH_TOKEN. apiProvider and
    apiKeySource are in the 2.1.330 binary's schema (not the docs) and are checked only when present."""
    if not isinstance(status, dict):
        return ["auth status is not a JSON object"]
    reasons = []
    if status.get("authMethod") != "oauth_token":
        reasons.append(f"authMethod is {status.get('authMethod')!r}, not 'oauth_token' (subscription token)")
    if "apiProvider" in status and status["apiProvider"] != "firstParty":
        reasons.append(f"apiProvider is {status.get('apiProvider')!r}, not 'firstParty'")
    if status.get("apiKeySource") not in (None, "none"):
        reasons.append(f"an API key is in use (apiKeySource {status.get('apiKeySource')!r})")
    return reasons


# ------------------------------------------------------------------ the command (identical in both arms)

def model_parts(model_ref):
    provider, model_id, effort = c.parse_model(model_ref)
    if provider != "anthropic" or not effort:
        raise AdapterError("native Claude Code needs anthropic/<model>#<effort>")
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        raise AdapterError(f"unknown effort {effort!r}")
    return model_id, effort


def build_argv(claude, model_ref, settings_path, max_turns):
    """The full command. It does not depend on the group: the arms differ only in the run's skills directory."""
    model_id, effort = model_parts(model_ref)
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        raise AdapterError("max_turns must be a positive int")
    return [claude, "-p", "--restricted", "--model", model_id, "--effort", effort,
            "--settings", settings_path, "--strict-mcp-config",
            "--tools", ",".join(CODING_TOOLS), "--allowedTools", ",".join(CODING_TOOLS),
            "--permission-mode", "acceptEdits", "--output-format", "stream-json", "--verbose",
            "--max-turns", str(max_turns), "--no-session-persistence"]


# ------------------------------------------------------------------ driver

def read_env_file(path):
    env = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            name, sep, value = line.partition("=")
            if not sep or not re.match(r"^[A-Z_][A-Z0-9_]*$", name):
                raise AdapterError("malformed environment file line")
            env[name] = value
    return env


def build_command(argv, env, as_user=None, wrapper=None):
    """The process to start. The checked environment (never the token) is passed through env -i when running as
    another user; otherwise run() hands it to Popen directly."""
    prefix = []
    if as_user:
        prefix = ["sudo", "-n", "-u", as_user, "/usr/bin/env", "-i"] + [f"{k}={v}" for k, v in sorted(env.items())]
    return prefix + [wrapper or os.path.join(HERE, "cc_exec.sh")] + list(argv)


def files_containing(paths, secret):
    """Captured files that contain the secret, to keep out of anything published (defence in depth only: the
    primary controls are no token in argv, files or logs, and encrypted evidence)."""
    hits = []
    needle = secret.encode("utf-8")
    for root in paths:
        for directory, _, names in os.walk(root) if os.path.isdir(root) else [(os.path.dirname(root), [], [os.path.basename(root)])]:
            for name in names:
                path = os.path.join(directory, name)
                try:
                    with open(path, "rb") as handle:
                        if needle in handle.read():
                            hits.append(path)
                except OSError:
                    hits.append(path)
    return sorted(hits)


def auth_status(claude, env_file, secret_file, out, as_user=None, wrapper=None, timeout=60):
    """Run `claude auth status --json` (no model request) through cc_exec.sh with the run's exact environment and
    check it. Writes only the verdict, the auth method and the subscription type, never the raw output."""
    env = read_env_file(env_file)
    problems = check_env(env)
    with open(secret_file, encoding="utf-8") as handle:
        token = handle.read().strip()
    problems += check_token(token)
    status = None
    if not problems:
        command = build_command([claude, "auth", "status", "--json"], env, as_user, wrapper)
        try:
            proc = subprocess.run(command, input=token.encode("utf-8") + b"\n", capture_output=True, timeout=timeout, check=False,
                                  env=None if as_user else env)
            status = json.loads(proc.stdout.decode("utf-8", "replace"))
        except (subprocess.TimeoutExpired, ValueError):
            status = None
        problems += check_auth_status(status)
    del token
    _write(out, {"ok": not problems, "reasons": problems,
                 "auth_method": status.get("authMethod") if isinstance(status, dict) else None,
                 "subscription_type": status.get("subscriptionType") if isinstance(status, dict) else None})
    return 0 if not problems else 3


MAX_PROMPT_BYTES = 60000  # below the pipe buffer, so writing token + prompt cannot block before claude reads


def run(claude, model_ref, settings_path, max_turns, prompt_file, env_file, secret_file, timeout, out_dir,
        as_user=None, wrapper=None):
    """Run one session. The token travels as the first line of cc_exec.sh's stdin (then the prompt), never in argv
    or a file the agent can read. With as_user, the command runs as that OS user with exactly the checked
    environment (sudo -u USER env -i ...; the token is not in that list). Writes transcript.ndjson, stderr.txt and
    driver-result.json into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    env = read_env_file(env_file)
    problems = check_env(env)
    with open(secret_file, encoding="utf-8") as handle:
        token = handle.read().strip()
    problems += check_token(token)
    with open(prompt_file, "rb") as handle:
        prompt = handle.read()
    if len(prompt) > MAX_PROMPT_BYTES or b"\0" in prompt:
        problems.append("prompt too large or contains NUL")
    result = {"execution_environment": EXECUTION_ENVIRONMENT, "status": "error", "outcome": "not_started",
              "exit_code": None, "session_id": None, "api_export": "stream-json"}
    if problems:
        result["refused"] = problems
        _write(os.path.join(out_dir, "driver-result.json"), result)
        return 3
    command = build_command(build_argv(claude, model_ref, settings_path, max_turns), env, as_user, wrapper)
    started = time.monotonic()
    with open(os.path.join(out_dir, "transcript.ndjson"), "wb") as out, \
            open(os.path.join(out_dir, "stderr.txt"), "wb") as err:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                env=None if as_user else env, start_new_session=True)
        try:
            proc.stdin.write(token.encode("utf-8") + b"\n" + prompt)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        del token
        try:
            code = proc.wait(timeout=timeout)
            result["status"] = "idle"
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            code = proc.wait()
            result["status"] = "timeout"
    result["exit_code"] = code
    result["duration_seconds"] = round(time.monotonic() - started, 1)
    summary = summarise_transcript(os.path.join(out_dir, "transcript.ndjson"))
    result["session_id"] = summary.get("session_id")
    if result["status"] == "idle":
        result["outcome"] = "succeeded" if code == 0 and summary.get("result_ok") else "failed"
    else:
        result["outcome"] = "timeout"
    _write(os.path.join(out_dir, "driver-result.json"), result)
    return 0 if result["outcome"] in ("succeeded", "timeout") else 1


# ------------------------------------------------------------------ transcript analysis

def read_events(path):
    """Parsed stream-json events; a line that is not a JSON object is a shape error (returned separately)."""
    events, bad = [], 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(event, dict):
                events.append(event)
            else:
                bad += 1
    return events, bad


def summarise_transcript(path):
    if not os.path.exists(path):
        return {}
    events, _ = read_events(path)
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return {"session_id": init.get("session_id") or result.get("session_id"),
            "result_ok": result.get("is_error") is False and result.get("subtype") in ("success", "error_max_turns")}


def _blocks(event):
    content = (event.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def _skill_target(tool_input):
    name = str((tool_input or {}).get("skill", ""))
    return name.split(":")[-1].lstrip("/")


def analyse_transcript(path, group, model_ref):
    """export-checks.json for run_status.py (same keys as export_checks.py), from a stream-json transcript."""
    model_id, effort = model_parts(model_ref)
    report = {"execution_environment": EXECUTION_ENVIRONMENT, "group": group, "model_ref": model_ref,
              "requested": {"model": model_id, "effort": effort}, "errors": [], "model_mismatches": [],
              "tool_counts": {}, "tokens": None, "reasoning_tokens_observed": None, "invalid_reasons": []}
    reasons = report["invalid_reasons"]
    if not os.path.exists(path):
        reasons.append("no transcript")
        report.update(valid=False, model_ok=False, activation="NOT_CHECKED", contamination=None)
        return report
    events, bad_lines = read_events(path)
    if bad_lines:
        reasons.append(f"transcript has {bad_lines} line(s) that are not JSON objects")
    inits = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    results = [e for e in events if e.get("type") == "result"]
    assistants = [e for e in events if e.get("type") == "assistant"]
    if len(inits) != 1:
        reasons.append(f"expected exactly one system/init event, found {len(inits)}")
    if len(results) != 1:
        reasons.append(f"expected exactly one result event, found {len(results)}")
    init = inits[0] if inits else {}
    result = results[-1] if results else {}

    # Identity and isolation, from the init event (fields in the CLI's own init schema).
    report["cli_version"] = init.get("claude_code_version")
    if init.get("claude_code_version") != PINNED_CLI_VERSION:
        reasons.append(f"Claude Code version {init.get('claude_code_version')!r} is not the pinned {PINNED_CLI_VERSION}")
    if init.get("apiKeySource") != "none":
        reasons.append(f"apiKeySource {init.get('apiKeySource')!r}: an API key or unknown credential was used")
        report["errors"].append("billing: not subscription authentication")
    if init.get("model") != model_id:
        reasons.append(f"session model {init.get('model')!r} is not the pinned {model_id}")
    report["effort_reported"] = init.get("effort")  # optional in the SDK type; absent means "not verified"
    if "effort" in init and init.get("effort") != effort:
        reasons.append(f"session effort {init.get('effort')!r} is not the pinned {effort}")
    if init.get("permissionMode") != "acceptEdits":
        reasons.append(f"permission mode {init.get('permissionMode')!r}")
    if init.get("mcp_servers") != []:
        reasons.append("MCP servers were loaded")
    if init.get("plugins") != []:
        reasons.append("plugins were loaded")
    tools = init.get("tools")
    report["tools"] = tools
    if not isinstance(tools, list) or any(t in FORBIDDEN_TOOLS or str(t).startswith("mcp__") for t in tools) \
            or not {"Bash", "Read", "Edit"} <= set(tools or []):
        reasons.append("tool set is not the pinned coding tool set")
    skills = init.get("skills")
    report["skills_available"] = skills
    expected_skills = [c.SKILL_ID] if group == "treatment" else []
    if not isinstance(skills, list) or sorted(str(s).split(":")[-1] for s in skills) != expected_skills:
        reasons.append(f"available skills {skills!r}, expected exactly {expected_skills}")
    commands = init.get("slash_commands")
    if group == "control" and isinstance(commands, list) and any(str(x).split(":")[-1].lstrip("/") == c.SKILL_ID
                                                                for x in commands):
        reasons.append("control session offers the code-discipline command")

    # Model identity on every assistant turn, and in the result's per-model usage.
    for index, event in enumerate(assistants):
        served = (event.get("message") or {}).get("model")
        if served != model_id:
            report["model_mismatches"].append({"index": index, "model": served})
    usage_models = sorted((result.get("modelUsage") or {}).keys())
    report["models_in_usage"] = usage_models
    report["auxiliary_models"] = [m for m in usage_models if m != model_id]
    report["model_ok"] = bool(assistants) and not report["model_mismatches"] and model_id in usage_models
    if not report["model_ok"]:
        reasons.append("an assistant turn was not served by the pinned model (fallback or switch), or no turn ran")

    # Infrastructure and billing errors are never model outcomes.
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "api_retry":
            report["errors"].append(f"api_retry: {event.get('error')}")
    if result:
        if result.get("is_error") is not False or result.get("subtype") not in ("success", "error_max_turns"):
            report["errors"].append(f"result {result.get('subtype')!r} is_error={result.get('is_error')!r}")
        report["result_subtype"] = result.get("subtype")
        report["num_turns"] = result.get("num_turns")
        report["estimated_cost_usd"] = result.get("total_cost_usd")  # client-side estimate; not a bill
        usage = result.get("usage") or {}
        report["tokens"] = {"input": usage.get("input_tokens"), "output": usage.get("output_tokens"),
                            "cache_read": usage.get("cache_read_input_tokens"),
                            "cache_write": usage.get("cache_creation_input_tokens")}

    # Tools used, skill invocation and skill text.
    invocations = []
    for event in assistants:
        for block in _blocks(event):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = str(block.get("name"))
                report["tool_counts"][name] = report["tool_counts"].get(name, 0) + 1
                if name == "Skill":
                    invocations.append(_skill_target(block.get("input")))
    after_init = json.dumps([e for e in events if e is not init], ensure_ascii=False)
    loaded = c.contains_all_sentinels(after_init)
    any_sentinel = c.contains_any_sentinel(after_init)
    report["skill_invocations"] = invocations
    report["invoked"] = c.SKILL_ID in invocations
    report["skill_text_loaded"] = loaded
    if group == "treatment":
        report["activation"] = "AVAILABLE" if not any("available skills" in r for r in reasons) else "NOT_AVAILABLE"
        report["contamination"] = False
    else:
        report["activation"] = "NOT_APPLICABLE"
        report["contamination"] = bool(c.SKILL_ID in invocations or any_sentinel)
        if report["contamination"]:
            reasons.append("control session contains code-discipline content or invokes it")
    if report["errors"]:
        reasons.append("provider, billing or session error (infrastructure failure)")
    report["valid"] = not reasons
    return report


# ------------------------------------------------------------------ CLI

def _write(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("check-env")
    s.add_argument("--env-file", required=True)
    s = sub.add_parser("check-auth")
    s.add_argument("--status-json", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("auth-status")
    for flag in ("--claude", "--env-file", "--secret-file", "--out"):
        s.add_argument(flag, required=True)
    s.add_argument("--as-user")
    s.add_argument("--wrapper")
    s = sub.add_parser("write-settings")
    s.add_argument("--out", required=True)
    for name in ("argv", "run"):
        s = sub.add_parser(name)
        s.add_argument("--claude", required=True)
        s.add_argument("--model", required=True)
        s.add_argument("--settings", required=True)
        s.add_argument("--max-turns", type=int, required=True)
        if name == "run":
            s.add_argument("--prompt-file", required=True)
            s.add_argument("--env-file", required=True)
            s.add_argument("--secret-file", required=True)
            s.add_argument("--timeout", type=int, required=True)
            s.add_argument("--out-dir", required=True)
            s.add_argument("--as-user", help="run as this OS user (sudo -u USER env -i <checked environment>)")
            s.add_argument("--wrapper", help="cc_exec.sh copy the agent user can execute (default: next to this file)")
    s = sub.add_parser("check-transcript")
    s.add_argument("--transcript", required=True)
    s.add_argument("--group", choices=("control", "treatment"), required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--out", required=True)
    args = p.parse_args(argv)
    try:
        if args.command == "check-env":
            reasons = check_env(read_env_file(args.env_file))
            for r in reasons:
                print(f"cc_adapter: {r}", file=sys.stderr)
            return 0 if not reasons else 3
        if args.command == "check-auth":
            try:
                with open(args.status_json, encoding="utf-8") as handle:
                    status = json.load(handle)
            except (OSError, ValueError):
                status = None
            reasons = check_auth_status(status)
            _write(args.out, {"ok": not reasons, "reasons": reasons,
                              "auth_method": status.get("authMethod") if isinstance(status, dict) else None,
                              "subscription_type": status.get("subscriptionType") if isinstance(status, dict) else None})
            return 0 if not reasons else 3
        if args.command == "auth-status":
            return auth_status(args.claude, args.env_file, args.secret_file, args.out, args.as_user, args.wrapper)
        if args.command == "write-settings":
            _write(args.out, HARNESS_SETTINGS)
            return 0
        if args.command == "argv":
            print(json.dumps(build_argv(args.claude, args.model, args.settings, args.max_turns)))
            return 0
        if args.command == "run":
            return run(args.claude, args.model, args.settings, args.max_turns, args.prompt_file, args.env_file,
                       args.secret_file, args.timeout, args.out_dir, args.as_user, args.wrapper)
        report = analyse_transcript(args.transcript, args.group, args.model)
        _write(args.out, report)
        print(f"cc_adapter: valid={report['valid']} activation={report['activation']} invoked={report['invoked']}")
        return 0 if report["valid"] else 1
    except (AdapterError, ValueError, OSError) as exc:
        print(f"cc_adapter: ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
