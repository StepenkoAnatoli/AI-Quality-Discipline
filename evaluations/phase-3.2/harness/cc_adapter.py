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
    cc_adapter.py argv           --claude BIN --model REF --settings F --max-turns N --plugin-dir D
    cc_adapter.py run            --claude BIN --model REF --settings F --max-turns N --prompt-file F \
                                 --env-file F --secret-file F --timeout S --out-dir D --project DIR --plugin-dir D \
                                 [--as-user USER]
    cc_adapter.py check-transcript --transcript F --group G --model REF --project DIR --plugin-dir D \
                                 --driver-result F --out F
    cc_adapter.py check-approval --approval F --run-id R         # the owner named this run id in writing
    cc_adapter.py scan-secret    --secret-file F --root D        # exit 21 if the token is in any file under D
    cc_adapter.py fingerprint    --checkout D --claude BIN --sealed D --pristine D --max-turns N --timeout S --out F
    cc_adapter.py check-preflight --preflight F --checkout D --claude BIN --sealed D --pristine D --max-turns N \
                                 --timeout S [--max-age-hours H]  # the launcher's gate

Treatment = the canonical skill is AVAILABLE (inside the run's arm plugin, given with --plugin-dir; the same path
in both arms, empty of skills in control). The prompt is
byte-identical in both arms; nothing names or forces the skill. Invocation (a Skill tool_use naming it) and
loading (its text in the transcript) are recorded separately and are NOT validity conditions: the estimand is the
effect of availability. Whether the agent FOLLOWED the skill is not measured here.

Every check fails closed: an unrecognised transcript shape, a missing field or an unexpected value invalidates
the run; nothing is inferred. What is assumed rather than verified is listed in CC_ADAPTER.md.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aqd_common as c  # noqa: E402

EXECUTION_ENVIRONMENT = "native-claude-code"
PINNED_CLI_VERSION = "2.1.330"
INTERFACE = f"claude-code {PINNED_CLI_VERSION}"
ACTIVATION_MODE = "cc-skill-available"
CODING_TOOLS = ("Bash", "Read", "Edit", "Write", "Glob", "Grep")
# --tools withholds every built-in tool it does not name (2.1.330: "...is not on this session's --tools list ...;
# withheld"), the Skill tool included. It is offered and allowed in BOTH arms so the command stays identical.
SKILL_TOOL = "Skill"
SESSION_TOOLS = CODING_TOOLS + (SKILL_TOOL,)
# Skill delivery. Observed with the real 2.1.330 CLI (offline, local mock API; phase-3.3/boundary): under
# --restricted a user skill in CLAUDE_CONFIG_DIR/skills is NOT loaded ("Unknown skill"), while a plugin given with
# --plugin-dir is. Both arms get the SAME --plugin-dir path; only treatment's plugin contains the skill, which the
# CLI then lists as "aqd-arm:code-discipline".
ARM_PLUGIN = "aqd-arm"
ARM_PLUGIN_SOURCE = f"{ARM_PLUGIN}@inline"
# Built-in plugins 2.1.330 loads by default; turned off in both arms through --settings (observed to work).
BUILTIN_PLUGINS = ("cc-plugin-agents-md@builtin", "cc-plugin-privacy@builtin", "cc-plugin-plugin-authoring@builtin")
# A built-in skill that stays listed with the above off and bundled skills disabled; identical in both arms.
BASE_SKILLS = ("doctor",)
# Observed: with CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 the session reports permissionMode "default" although
# --permission-mode acceptEdits is passed; Edit/Write are still allowed through --allowedTools.
EXPECTED_PERMISSION_MODE = "default"
# The Bash tool's answer when the scrub sandbox cannot start (2.1.330: e.g. socat or bubblewrap missing, or user
# namespaces refused). Every Bash call fails; the run would otherwise be a silent valid failure.
SANDBOX_FAILURE = "Sandbox is required but failed to initialize"
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
    "enabledPlugins": {p: False for p in BUILTIN_PLUGINS},
    "permissions": {"allow": list(SESSION_TOOLS), "deny": list(FORBIDDEN_TOOLS)},
}

# Result subtypes that are model outcomes. 2.1.330 emits error_max_turns with is_error TRUE, so is_error alone
# does not separate the turn limit (an outcome, like a timeout) from a provider or session error.
OUTCOME_SUBTYPES = {"success": "succeeded", "error_max_turns": "max_turns"}


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


def check_approval(data, run_id):
    """The owner's written approval must name this run id. One approval never covers other runs."""
    if not isinstance(data, dict) or not isinstance(data.get("approved_run_ids"), list):
        return ["approval file has no approved_run_ids list"]
    if run_id not in data["approved_run_ids"]:
        return [f"run {run_id} is not in the owner's approved_run_ids"]
    return []


# ------------------------------------------------------------------ native preflight binding

# Files whose content decides how a run is executed and checked. A change after preflight invalidates it.
PREFLIGHT_HARNESS_FILES = ("cc_adapter.py", "cc_exec.sh", "launch-run-cc.sh", "preflight-cc.sh", "lib.sh",
                           "run_status.py", "manifest.py", "schedule.py", "aqd_common.py")
CANONICAL_SKILL_SHA256 = "d050d00fa8564b08cac71ca221368568420c731c830ef19667a760d5f7ebc842"
PREFLIGHT_MAX_AGE_HOURS = 24


def _sha_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _sha_or_none(path):
    try:
        return _sha_file(path)
    except OSError:
        return None


def settings_sha256():
    """SHA-256 of the settings file exactly as write-settings writes it."""
    text = json.dumps(HARNESS_SETTINGS, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(checkout, *args):
    proc = subprocess.run(["git", "-C", checkout, *args], capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def preflight_fingerprint(checkout, harness, claude, cli_version, sealed, pristine, max_turns, timeout_seconds,
                          dry_run=False):
    """Everything a native run depends on. Recomputed by the launcher and compared key by key."""
    schedule_path = os.path.join(sealed, "schedule.json")
    tasks = []
    try:
        with open(schedule_path, encoding="utf-8") as handle:
            tasks = sorted({str(r.get("task")) for r in json.load(handle).get("runs", [])})
    except (OSError, ValueError, AttributeError):
        tasks = []
    status = _git(checkout, "status", "--porcelain")
    return {
        "execution_environment": EXECUTION_ENVIRONMENT,
        "checkout_commit": _git(checkout, "rev-parse", "HEAD"),
        "checkout_clean": status == "",
        "cli_version": cli_version,
        "cli_sha256": _sha_or_none(claude),
        "harness_sha256": {name: _sha_or_none(os.path.join(harness, name)) for name in PREFLIGHT_HARNESS_FILES},
        "settings_sha256": settings_sha256(),
        "skill_sha256": _sha_or_none(os.path.join(pristine, "skill", c.SKILL_ID, "SKILL.md")),
        "canonical_skill_sha256": _sha_or_none(os.path.join(checkout, "skills", c.SKILL_ID, "SKILL.md")),
        "schedule_sha256": _sha_or_none(schedule_path),
        "pristine_extra_sha256": _sha_or_none(os.path.join(sealed, "pristine-extra.sha256")),
        "task_manifests_sha256": {t: _sha_or_none(os.path.join(pristine, t, "manifest.json")) for t in tasks},
        "max_turns": max_turns,
        "timeout_seconds": timeout_seconds,
        "dry_run": bool(dry_run),
    }


def _parse_utc(value):
    try:
        moment = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


PRE_REGISTERED_TIMEOUT_SECONDS = 2700


def check_timeout_policy(timeout_seconds, dry_run):
    """Evidence runs use the pre-registered 45-minute timeout; another value is allowed only in a declared dry run."""
    if timeout_seconds != PRE_REGISTERED_TIMEOUT_SECONDS and not dry_run:
        return [f"timeout {timeout_seconds} s is not the pre-registered {PRE_REGISTERED_TIMEOUT_SECONDS} s "
                "(allowed only with AQD_CC_DRY_RUN=1, which is recorded)"]
    return []


def check_preflight(record, current, now_utc, max_age_hours=PREFLIGHT_MAX_AGE_HOURS):
    """Reasons a stored native preflight does not authorise a run now (key names only, never values)."""
    if not isinstance(record, dict):
        return ["no native preflight record"]
    reasons = []
    if record.get("schema_version") != 1 or record.get("execution_environment") != EXECUTION_ENVIRONMENT:
        reasons.append("preflight is not a native-claude-code preflight (schema or execution environment)")
    if record.get("ok") is not True:
        reasons.append("preflight did not pass")
    created, now = _parse_utc(record.get("created_utc")), _parse_utc(now_utc)
    if created is None or now is None:
        reasons.append("preflight time missing or not timezone-aware")
    elif created > now + datetime.timedelta(minutes=5):
        reasons.append("preflight time is in the future")
    elif now - created > datetime.timedelta(hours=max_age_hours):
        reasons.append(f"preflight is older than {max_age_hours} h (stale)")
    stored = record.get("fingerprint")
    if not isinstance(stored, dict):
        reasons.append("preflight has no fingerprint")
        stored = {}
    for key in sorted(set(stored) | set(current)):
        if stored.get(key) != current.get(key):
            reasons.append(f"{key} changed since preflight")
    for fp, label in ((current, "now"), (stored, "at preflight")):
        if fp and not fp.get("checkout_clean"):
            reasons.append(f"checkout has uncommitted changes ({label})")
        if fp and not (fp.get("skill_sha256") == fp.get("canonical_skill_sha256") == CANONICAL_SKILL_SHA256):
            reasons.append(f"pristine skill is not the canonical skill ({label})")
    reasons += check_timeout_policy(current.get("timeout_seconds"), current.get("dry_run") is True)
    for key in ("checkout_commit", "cli_sha256", "schedule_sha256"):
        if current.get(key) is None:
            reasons.append(f"{key} could not be computed")
    return sorted(set(reasons))


def cli_version(claude):
    """`claude --version`'s X.Y.Z, run with an empty environment and a throwaway HOME (no credential, no
    network-relevant variable). None if it cannot be read."""
    import tempfile
    import shutil
    home = tempfile.mkdtemp(prefix="cc-version-")
    try:
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "CLAUDE_CONFIG_DIR": os.path.join(home, ".claude"),
               "TMPDIR": home, **REQUIRED_ENV}
        proc = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=30, env=env,
                              check=False, stdin=subprocess.DEVNULL)
        match = re.match(r"^(\d+\.\d+\.\d+)\b", proc.stdout.strip())
        return match.group(1) if proc.returncode == 0 and match else None
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        shutil.rmtree(home, ignore_errors=True)


# ------------------------------------------------------------------ the command (identical in both arms)

def model_parts(model_ref):
    provider, model_id, effort = c.parse_model(model_ref)
    if provider != "anthropic" or not effort:
        raise AdapterError("native Claude Code needs anthropic/<model>#<effort>")
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        raise AdapterError(f"unknown effort {effort!r}")
    return model_id, effort


def build_argv(claude, model_ref, settings_path, max_turns, plugin_dir):
    """The full command. It does not depend on the group: the arms differ only in the CONTENT of plugin_dir."""
    model_id, effort = model_parts(model_ref)
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        raise AdapterError("max_turns must be a positive int")
    return [claude, "-p", "--restricted", "--model", model_id, "--effort", effort,
            "--settings", settings_path, "--strict-mcp-config",
            "--tools", ",".join(SESSION_TOOLS), "--allowedTools", ",".join(SESSION_TOOLS),
            "--permission-mode", "acceptEdits", "--output-format", "stream-json", "--verbose",
            "--max-turns", str(max_turns), "--no-session-persistence", "--plugin-dir", plugin_dir]


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


def build_command(argv, env, as_user=None, wrapper=None, workdir="/"):
    """The process to start. The checked environment (never the token) is passed through env -i when running as
    another user; otherwise run() hands it to Popen directly. cc_exec.sh changes to workdir inside the agent's own
    process: the operator cannot traverse the agent's tree, so the driver itself never enters it."""
    prefix = []
    if as_user:
        prefix = ["sudo", "-n", "-u", as_user, "/usr/bin/env", "-i"] + [f"{k}={v}" for k, v in sorted(env.items())]
    return prefix + [wrapper or os.path.join(HERE, "cc_exec.sh"), workdir] + list(argv)


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
            proc = subprocess.run(command, input=token.encode("utf-8") + b"\n", capture_output=True, timeout=timeout, check=False, cwd="/",
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


MAX_PROMPT_BYTES = 60000  # TASK.md size cap (a policy limit; the hand-off no longer depends on the pipe buffer)
TERM_GRACE_SECONDS = 5


def _feed(pipe, data):
    """Write the token line and the prompt, then close. Runs in a thread so a child that never reads stdin cannot
    hold the driver before its timeout starts; killing the child ends the write with an error, which is ignored."""
    try:
        pipe.write(data)
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except (BrokenPipeError, OSError, ValueError):
            pass


def _end_group(proc):
    """TERM the session's process group (sudo relays TERM to its command), then KILL whatever is left. With a
    non-root operator, the group can hold only the agent user's processes once sudo has exited: killpg then
    raises EPERM. That is not an error here (the launcher kills by OS user next); the status stays "timeout"."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=TERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            if sig == signal.SIGKILL:  # the group could not be signalled: end the direct child, never hang
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    return proc.wait(timeout=TERM_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    return None
            continue
        try:  # the leader is gone; KILL the rest of its group too, where permitted
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        return proc.returncode
    return proc.returncode


def run(claude, model_ref, settings_path, max_turns, prompt_file, env_file, secret_file, timeout, out_dir,
        project, plugin_dir, as_user=None, wrapper=None):
    """Run one session. The token travels as the first line of cc_exec.sh's stdin (then the prompt), never in argv
    or a file the agent can read. With as_user, the command runs as that OS user with exactly the checked
    environment (sudo -u USER env -i ...; the token is not in that list). Writes transcript.ndjson, stderr.txt and
    driver-result.json into out_dir. The session starts in `project`: cc_exec.sh changes to it as the agent user
    (the transcript check then requires init.cwd to be exactly that directory)."""
    os.makedirs(out_dir, exist_ok=True)
    env = read_env_file(env_file)
    problems = check_env(env)
    with open(secret_file, encoding="utf-8") as handle:
        token = handle.read().strip()
    problems += check_token(token)
    with open(prompt_file, "rb") as handle:
        prompt = handle.read()
    if not os.path.isabs(project):  # existence is checked by cc_exec.sh as the agent (exit 96)
        problems.append("project must be an absolute path")
    if len(prompt) > MAX_PROMPT_BYTES or b"\0" in prompt:
        problems.append("prompt too large or contains NUL")
    result = {"execution_environment": EXECUTION_ENVIRONMENT, "status": "error", "outcome": "not_started",
              "exit_code": None, "session_id": None, "api_export": "stream-json"}
    if problems:
        result["refused"] = problems
        _write(os.path.join(out_dir, "driver-result.json"), result)
        return 3
    command = build_command(build_argv(claude, model_ref, settings_path, max_turns, plugin_dir), env, as_user, wrapper,
                            project)
    started = time.monotonic()
    with open(os.path.join(out_dir, "transcript.ndjson"), "wb") as out, \
            open(os.path.join(out_dir, "stderr.txt"), "wb") as err:
        try:
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                    env=None if as_user else env, start_new_session=True, cwd="/")
        except OSError as exc:
            del token
            result["refused"] = [f"the session could not start ({type(exc).__name__})"]
            _write(os.path.join(out_dir, "driver-result.json"), result)
            return 2
        feeder = threading.Thread(target=_feed, args=(proc.stdin, token.encode("utf-8") + b"\n" + prompt), daemon=True)
        del token
        feeder.start()  # the timeout below starts now, not after the write
        try:
            code = proc.wait(timeout=timeout)
            result["status"] = "idle"
            try:  # background children the session left behind (the launcher also kills by OS user)
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        except subprocess.TimeoutExpired:
            code = _end_group(proc)
            result["status"] = "timeout"
        feeder.join(timeout=TERM_GRACE_SECONDS)
    result["exit_code"] = code
    result["duration_seconds"] = round(time.monotonic() - started, 1)
    summary = summarise_transcript(os.path.join(out_dir, "transcript.ndjson"))
    result["session_id"] = summary.get("session_id")
    if result["status"] == "idle":
        # the CLI exits non-zero at the turn limit, so the outcome comes from the result event, not the exit code
        outcome = summary.get("outcome")
        result["outcome"] = outcome if outcome == "max_turns" or (outcome == "succeeded" and code == 0) else "failed"
    else:
        result["outcome"] = "timeout"
    _write(os.path.join(out_dir, "driver-result.json"), result)
    return 0 if result["outcome"] in ("succeeded", "max_turns", "timeout") else 1


# ------------------------------------------------------------------ transcript analysis

def read_events(path, allow_truncated_tail=False):
    """Parsed stream-json events and the count of lines that are not JSON objects (a shape error). With
    allow_truncated_tail (a killed session), an unparseable LAST line is dropped instead of counted."""
    lines = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = [line for line in handle if line.strip()]
    events, bad = [], 0
    for position, line in enumerate(lines):
        try:
            event = json.loads(line)
        except ValueError:
            if not (allow_truncated_tail and position == len(lines) - 1):
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
    return {"session_id": init.get("session_id") or result.get("session_id"), "outcome": result_outcome(result)}


def result_outcome(result):
    """"succeeded", "max_turns", or None (a provider, billing or session error, or an unknown shape)."""
    subtype = result.get("subtype")
    if subtype == "success" and result.get("is_error") is False:
        return "succeeded"
    if subtype == "error_max_turns" and isinstance(result.get("is_error"), bool):
        return "max_turns"
    return None


# The CLI's own test for "the sandbox could not start": the command's output is ONLY bwrap/sandbox-exec error lines
# (2.1.330 binary text), optionally after the "Exit code N" line the Bash tool prepends.
_SANDBOX_ONLY = re.compile(r"^(?:Exit code \d+\n)?(?:\s*(?:bwrap|sandbox-exec): [^\n]*(?:\n|$))+\s*$")


def _is_sandbox_failure(content):
    if isinstance(content, list):
        content = "".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    text = str(content or "")
    return SANDBOX_FAILURE in text or bool(_SANDBOX_ONLY.match(text))


def _blocks(event):
    content = (event.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def _skill_target(tool_input):
    name = str((tool_input or {}).get("skill", ""))
    return name.split(":")[-1].lstrip("/")


def analyse_transcript(path, group, model_ref, project, driver_status, plugin_dir):
    """export-checks.json for run_status.py (same keys as export_checks.py), from a stream-json transcript.
    driver_status is driver-result.json's status: "idle" (the session ended) or "timeout" (the harness killed it;
    no result event is expected, a truncated final line is tolerated, and the outcome stays a valid timeout)."""
    model_id, effort = model_parts(model_ref)
    timed_out = driver_status == "timeout"
    report = {"execution_environment": EXECUTION_ENVIRONMENT, "group": group, "model_ref": model_ref,
              "requested": {"model": model_id, "effort": effort}, "errors": [], "model_mismatches": [],
              "tool_counts": {}, "tokens": None, "reasoning_tokens_observed": None, "invalid_reasons": [],
              "timed_out": timed_out, "api_retries": []}
    reasons = report["invalid_reasons"]
    if driver_status not in ("idle", "timeout"):
        reasons.append(f"driver status {driver_status!r}")
    if not os.path.exists(path):
        reasons.append("no transcript")
        report.update(valid=False, model_ok=False, activation="NOT_CHECKED", contamination=None)
        return report
    events, bad_lines = read_events(path, allow_truncated_tail=timed_out)
    if bad_lines:
        reasons.append(f"transcript has {bad_lines} line(s) that are not JSON objects")
    inits = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
    results = [e for e in events if e.get("type") == "result"]
    assistants = [e for e in events if e.get("type") == "assistant"]
    if len(inits) != 1:
        reasons.append(f"expected exactly one system/init event, found {len(inits)}")
    if len(results) > 1 or (not timed_out and len(results) != 1):
        reasons.append(f"expected exactly one result event, found {len(results)}")
    init = inits[0] if inits else {}
    result = results[-1] if results else {}

    # Identity and isolation, from the init event (fields in the CLI's own init schema).
    report["cwd"] = init.get("cwd")
    if init.get("cwd") != project:
        reasons.append(f"session working directory {init.get('cwd')!r} is not the run's project directory")
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
    if init.get("permissionMode") != EXPECTED_PERMISSION_MODE:
        reasons.append(f"permission mode {init.get('permissionMode')!r}")
    if init.get("served_by_anthropic") is not True:  # init field in 2.1.330 (false against a non-Anthropic endpoint)
        reasons.append("session not served by Anthropic (served_by_anthropic is not true)")
    if init.get("mcp_servers") != []:
        reasons.append("MCP servers were loaded")
    plugins = init.get("plugins")
    report["plugins"] = plugins
    if not isinstance(plugins, list) or [(p.get("source"), p.get("path")) for p in plugins if isinstance(p, dict)] \
            != [(ARM_PLUGIN_SOURCE, plugin_dir)] or len(plugins) != 1:
        reasons.append("plugins are not exactly the run's arm plugin")
    tools = init.get("tools")
    report["tools"] = tools
    if not isinstance(tools, list) or any(t in FORBIDDEN_TOOLS or str(t).startswith("mcp__") for t in tools) \
            or not {"Bash", "Read", "Edit"} <= set(tools or []):
        reasons.append("tool set is not the pinned coding tool set")
    report["skill_tool_offered"] = isinstance(tools, list) and SKILL_TOOL in tools
    skills = init.get("skills")
    report["skills_available"] = skills
    if group == "treatment" and not report["skill_tool_offered"]:
        reasons.append("available skills: the Skill tool is not offered, so the skill cannot be loaded")
    expected_skills = sorted(BASE_SKILLS + ((f"{ARM_PLUGIN}:{c.SKILL_ID}",) if group == "treatment" else ()))
    if not isinstance(skills, list) or sorted(str(s) for s in skills) != expected_skills:
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
    # modelUsage exists only in the result event; a killed session is judged on its assistant turns alone.
    usage_ok = model_id in usage_models if result else timed_out
    report["model_ok"] = bool(assistants) and not report["model_mismatches"] and usage_ok
    if not report["model_ok"]:
        reasons.append("an assistant turn was not served by the pinned model (fallback or switch), or no turn ran")

    # Infrastructure and billing errors are never model outcomes.
    # A retry that recovers is recorded, not fatal (Phase 3.2 invalidated only sessions that ENDED on a provider
    # error). A session that ends on an error, or is killed while still retrying, is infrastructure.
    last_retry = last_turn = -1
    for index, event in enumerate(events):
        if event.get("type") == "system" and event.get("subtype") == "api_retry":
            report["api_retries"].append(str(event.get("error")))
            last_retry = index
        elif event.get("type") == "assistant":
            last_turn = index
    sandbox_failures = sum(1 for e in events if e.get("type") == "user"
                           for b in _blocks(e) if isinstance(b, dict) and b.get("type") == "tool_result"
                           and _is_sandbox_failure(b.get("content")))
    report["sandbox_failures"] = sandbox_failures
    if sandbox_failures:
        report["errors"].append(f"the Bash sandbox could not start ({sandbox_failures} tool result(s))")
        reasons.append("the Bash sandbox could not start (infrastructure failure, never a model outcome)")
    if timed_out and not result and last_retry > last_turn:
        report["errors"].append("timed out while retrying provider errors")
    report["max_turns_reached"] = False
    if result:
        outcome = result_outcome(result)
        if outcome is None:
            report["errors"].append(f"result {result.get('subtype')!r} is_error={result.get('is_error')!r}")
        report["max_turns_reached"] = outcome == "max_turns"
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


def scan_secret(secret_file, root):
    """0 if the secret is in no file under root; 21 (isolation failure) if it is, or if the scan cannot run."""
    try:
        with open(secret_file, encoding="utf-8") as handle:
            secret = handle.read().strip()
        if not secret:
            return 21
        return 21 if files_containing([root], secret) else 0
    except OSError:
        return 21


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
        s.add_argument("--plugin-dir", required=True, help="the run's arm plugin (same path in both arms)")
        if name == "run":
            s.add_argument("--prompt-file", required=True)
            s.add_argument("--env-file", required=True)
            s.add_argument("--secret-file", required=True)
            s.add_argument("--timeout", type=int, required=True)
            s.add_argument("--out-dir", required=True)
            s.add_argument("--project", required=True, help="absolute project directory; the session starts there")
            s.add_argument("--as-user", help="run as this OS user (sudo -u USER env -i <checked environment>)")
            s.add_argument("--wrapper", help="cc_exec.sh copy the agent user can execute (default: next to this file)")
    s = sub.add_parser("check-transcript")
    s.add_argument("--transcript", required=True)
    s.add_argument("--group", choices=("control", "treatment"), required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--project", required=True)
    s.add_argument("--plugin-dir", required=True)
    s.add_argument("--driver-result", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("check-approval")
    s.add_argument("--approval", required=True)
    s.add_argument("--run-id", required=True)
    for name in ("fingerprint", "check-preflight"):
        s = sub.add_parser(name)
        for flag in ("--checkout", "--claude", "--sealed", "--pristine"):
            s.add_argument(flag, required=True)
        s.add_argument("--max-turns", type=int, required=True)
        s.add_argument("--timeout", type=int, required=True)
        if name == "fingerprint":
            s.add_argument("--out", required=True)
        else:
            s.add_argument("--preflight", required=True)
            s.add_argument("--max-age-hours", type=float, default=PREFLIGHT_MAX_AGE_HOURS)
    s = sub.add_parser("scan-secret")
    s.add_argument("--secret-file", required=True)
    s.add_argument("--root", required=True)
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
            print(json.dumps(build_argv(args.claude, args.model, args.settings, args.max_turns, args.plugin_dir)))
            return 0
        if args.command == "run":
            return run(args.claude, args.model, args.settings, args.max_turns, args.prompt_file, args.env_file,
                       args.secret_file, args.timeout, args.out_dir, args.project, args.plugin_dir, args.as_user,
                       args.wrapper)
        if args.command == "check-approval":
            try:
                with open(args.approval, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                data = None
            reasons = check_approval(data, args.run_id)
            for r in reasons:
                print(f"cc_adapter: {r}", file=sys.stderr)
            return 0 if not reasons else 3
        if args.command in ("fingerprint", "check-preflight"):
            current = preflight_fingerprint(args.checkout, HERE, args.claude, cli_version(args.claude), args.sealed,
                                            args.pristine, args.max_turns, args.timeout,
                                            os.environ.get("AQD_CC_DRY_RUN") == "1")
            if args.command == "fingerprint":
                _write(args.out, current)
                return 0
            try:
                with open(args.preflight, encoding="utf-8") as handle:
                    record = json.load(handle)
            except (OSError, ValueError):
                record = None
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            reasons = check_preflight(record, current, now, args.max_age_hours)
            for r in reasons:
                print(f"cc_adapter: preflight: {r}", file=sys.stderr)
            return 0 if not reasons else 3
        if args.command == "scan-secret":
            code = scan_secret(args.secret_file, args.root)
            print(f"cc_adapter: secret scan {'clean' if code == 0 else 'FAILED (token found or scan impossible)'}")
            return code
        try:
            with open(args.driver_result, encoding="utf-8") as handle:
                driver_status = (json.load(handle) or {}).get("status")
        except (OSError, ValueError, AttributeError):
            driver_status = None
        report = analyse_transcript(args.transcript, args.group, args.model, args.project, driver_status,
                                    args.plugin_dir)
        _write(args.out, report)
        print(f"cc_adapter: valid={report['valid']} activation={report['activation']} invoked={report['invoked']}")
        return 0 if report["valid"] else 1
    except (AdapterError, ValueError, OSError) as exc:
        print(f"cc_adapter: ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
