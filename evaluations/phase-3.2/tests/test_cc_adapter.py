"""Offline tests for the native Claude Code adapter (cc_adapter.py, cc_exec.sh, run_status.py --interface claude-code).

    python -m unittest discover -s evaluations/phase-3.2/tests -p "test_cc_adapter.py" -v

No model call, no real credential, no network. Every transcript here is SYNTHETIC: it uses only the event fields
documented for the Agent SDK message types and present in the Claude Code 2.1.330 init schema. A pass shows the
adapter's own logic is right for those shapes; it does NOT show that a real session produces them (see
CC_ADAPTER.md, "Unverified").
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import signal
import textwrap
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "..", "harness")
sys.path.insert(0, HARNESS)

import aqd_common as c  # noqa: E402
import cc_adapter as cc  # noqa: E402
import run_status  # noqa: E402

MODEL_REF = "anthropic/claude-opus-5-5#medium"
MODEL = "claude-opus-5-5"
PROJECT = "/aqd/run/project"
PLUGIN_DIR = "/aqd/run/arm-plugin"
ARM_PLUGIN = {"name": "aqd-arm", "path": PLUGIN_DIR, "source": "aqd-arm@inline", "version": "1.0.0"}
TEST_TOKEN = "sk-ant-oat01-SYNTHETIC-TEST-TOKEN-not-a-real-credential"
SKILL_BODY = "\n".join(c.SKILL_SENTINELS)
with open(os.path.join(HERE, "..", "..", "..", "skills", "code-discipline", "SKILL.md"), encoding="utf-8") as _h:
    CANONICAL_SKILL = _h.read()


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def clean_env(root):
    env = {"HOME": f"{root}/home", "CLAUDE_CONFIG_DIR": f"{root}/home/.claude", "TMPDIR": f"{root}/tmp",
           "PATH": "/usr/bin:/bin", "SHELL": "/bin/sh", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb",
           "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(cc.REQUIRED_ENV)
    return env


# ------------------------------------------------------------------ synthetic stream-json

def init_event(group="control", **changes):
    event = {"type": "system", "subtype": "init", "session_id": "s-synthetic", "uuid": "u0",
             "apiKeySource": "none", "claude_code_version": cc.PINNED_CLI_VERSION, "cwd": PROJECT,
             "tools": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Skill"], "mcp_servers": [],
             "model": MODEL, "permissionMode": "default", "served_by_anthropic": True,
             "slash_commands": (["aqd-arm:code-discipline"] if group == "treatment" else []) + ["doctor", "clear"],
             "output_style": "default",
             "skills": (["aqd-arm:code-discipline"] if group == "treatment" else []) + ["doctor"],
             "plugins": [dict(ARM_PLUGIN)]}
    event.update(changes)
    return event


def assistant(blocks, model=MODEL):
    return {"type": "assistant", "message": {"model": model, "role": "assistant", "content": blocks}}


def tool_use(name, tool_input, ident="t1"):
    return {"type": "tool_use", "id": ident, "name": name, "input": tool_input}


def tool_result(ident, text):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": ident, "content": text}]}}


def result_event(subtype="success", is_error=False, models=(MODEL,)):
    return {"type": "result", "subtype": subtype, "is_error": is_error, "num_turns": 4, "session_id": "s-synthetic",
            "total_cost_usd": 0.42, "usage": {"input_tokens": 10, "output_tokens": 900,
                                              "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 700},
            "modelUsage": {m: {"inputTokens": 1} for m in models}}


def session(group="control", middle=None, init=None, result=None):
    middle = middle if middle is not None else [
        assistant([{"type": "text", "text": "I will fix the function."}, tool_use("Read", {"file_path": "a.py"})]),
        tool_result("t1", "def f(): pass"),
        assistant([tool_use("Edit", {"file_path": "a.py"}, "t2")]),
        tool_result("t2", "ok"),
        assistant([{"type": "text", "text": "Done."}]),
    ]
    return [init or init_event(group)] + middle + [result or result_event()]


class Workdir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cc-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def transcript(self, events, raw_lines=()):
        path = os.path.join(self.tmp, f"t-{len(os.listdir(self.tmp))}.ndjson")
        with open(path, "w", encoding="utf-8") as h:
            for e in events:
                h.write(json.dumps(e) + "\n")
            for line in raw_lines:
                h.write(line + "\n")
        return path

    def analyse(self, events, group="control", raw_lines=(), driver_status="idle"):
        return cc.analyse_transcript(self.transcript(events, raw_lines), group, MODEL_REF, PROJECT, driver_status, PLUGIN_DIR)


# ------------------------------------------------------------------ pre-run checks

class EnvironmentAndAuthTests(Workdir):
    def test_clean_environment_passes(self):
        self.assertEqual(cc.check_env(clean_env(self.tmp)), [])

    def test_every_billing_hazard_is_refused_by_name(self):
        for name in cc.BILLING_HAZARDS:
            with self.subTest(name=name):
                reasons = cc.check_env(dict(clean_env(self.tmp), **{name: "x"}))
                self.assertTrue(any(name in r and "refused" in r for r in reasons), reasons)
                self.assertFalse(any("x" == r for r in reasons))

    def test_unknown_variables_and_missing_requirements_are_refused(self):
        self.assertTrue(cc.check_env(dict(clean_env(self.tmp), GITHUB_TOKEN="ghs_x")))
        env = clean_env(self.tmp)
        env.pop("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB")
        self.assertTrue(any("SCRUB" in r for r in cc.check_env(env)))
        self.assertTrue(cc.check_env(dict(clean_env(self.tmp), CLAUDE_CONFIG_DIR="relative")))
        self.assertTrue(any("secret file" in r for r in cc.check_env(dict(clean_env(self.tmp),
                                                                          CLAUDE_CODE_OAUTH_TOKEN=TEST_TOKEN))))

    def test_reasons_never_contain_values(self):
        env = dict(clean_env(self.tmp), ANTHROPIC_API_KEY="sk-ant-api03-SECRETVALUE", WEIRD="SECRETVALUE2")
        self.assertFalse(any("SECRETVALUE" in r for r in cc.check_env(env)))

    def test_token_shape(self):
        self.assertEqual(cc.check_token(TEST_TOKEN), [])
        self.assertTrue(any("API key" in r for r in cc.check_token("sk-ant-api03-abc")))
        for bad in ("", " " + TEST_TOKEN, "sk-ant-api03-abc", "ghp_abc", "sk-ant-oat01-a b"):
            with self.subTest(token=bad[:12]):
                reasons = cc.check_token(bad)
                self.assertTrue(reasons)
                self.assertFalse(any(bad and bad in r for r in reasons))

    def test_auth_status(self):
        self.assertEqual(cc.check_auth_status({"authMethod": "oauth_token", "configDirectory": "/x"}), [])
        self.assertEqual(cc.check_auth_status({"authMethod": "oauth_token", "apiProvider": "firstParty",
                                               "apiKeySource": "none"}), [])
        for status in ({"authMethod": "api_key"}, {"authMethod": "claude.ai"}, {"authMethod": "third_party"},
                       {"authMethod": "api_key_helper"}, {"authMethod": "none"}, {},
                       {"authMethod": "oauth_token", "apiProvider": "bedrock"},
                       {"authMethod": "oauth_token", "apiKeySource": "ANTHROPIC_API_KEY"}, None, []):
            with self.subTest(status=status):
                self.assertTrue(cc.check_auth_status(status))


# ------------------------------------------------------------------ command

class CommandTests(Workdir):
    def test_command_is_the_same_for_both_arms_and_names_no_skill(self):
        argv = cc.build_argv("claude", MODEL_REF, "/s.json", 40, PLUGIN_DIR)
        self.assertNotIn("code-discipline", " ".join(argv))
        self.assertNotIn("/code-discipline", " ".join(argv))
        for flag in ("-p", "--restricted", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertNotIn("--fallback-model", argv)
        self.assertNotIn("--bare", argv)
        self.assertNotIn("--safe-mode", argv)
        self.assertNotIn("bypassPermissions", argv)
        value = lambda flag: argv[argv.index(flag) + 1]  # noqa: E731
        self.assertEqual((value("--model"), value("--effort")), (MODEL, "medium"))
        self.assertEqual(value("--tools"), "Bash,Read,Edit,Write,Glob,Grep,Skill")
        self.assertEqual(value("--plugin-dir"), PLUGIN_DIR)  # the same path in both arms; only its content differs
        self.assertEqual(value("--allowedTools"), value("--tools"))
        self.assertEqual(value("--output-format"), "stream-json")

    def test_bad_model_references_are_refused(self):
        for ref in ("anthropic/claude-opus-5-5", "xai/grok-4#high", "anthropic/claude-opus-5-5#ultra", "opus"):
            with self.subTest(ref=ref), self.assertRaises((ValueError, cc.AdapterError)):
                cc.build_argv("claude", ref, "/s.json", 40, PLUGIN_DIR)
        with self.assertRaises(cc.AdapterError):
            cc.build_argv("claude", MODEL_REF, "/s.json", True, PLUGIN_DIR)

    def test_settings_turn_off_sync_switching_and_bundled_skills(self):
        s = cc.HARNESS_SETTINGS
        self.assertIs(s["syncClaudeAiSkills"], False)
        self.assertIs(s["syncClaudeAiPlugins"], False)
        self.assertIs(s["switchModelsOnFlag"], False)
        self.assertIs(s["disableBundledSkills"], True)
        # the three built-in plugins 2.1.330 loads are off in both arms (observed with the real CLI)
        self.assertEqual(s["enabledPlugins"], {p: False for p in cc.BUILTIN_PLUGINS})
        self.assertIn("WebFetch", s["permissions"]["deny"])
        self.assertIn("Skill", s["permissions"]["allow"])

    def test_approval_names_each_run(self):
        good = {"approved_run_ids": ["r-0123456789"], "approved_by": "owner", "approved_utc": "2026-11-23T00:00:00Z"}
        self.assertEqual(cc.check_approval(good, "r-0123456789"), [])
        for data in (good, {}, {"approved_run_ids": "r-0123456789"}, None, {"approved_run_ids": ["*"]}):
            with self.subTest(data=data):
                self.assertTrue(cc.check_approval(data, "r-aaaaaaaaaa"))

    def test_run_as_user_never_puts_the_token_in_argv(self):
        cmd = cc.build_command(cc.build_argv("/usr/bin/claude", MODEL_REF, "/s.json", 40, PLUGIN_DIR), clean_env(self.tmp),
                               as_user="aqd-a", wrapper="/aqd/bin/cc_exec.sh", workdir="/aqd/run/project")
        self.assertEqual(cmd[:6], ["sudo", "-n", "-u", "aqd-a", "/usr/bin/env", "-i"])
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", " ".join(cmd))
        # the agent's own process changes directory: the operator cannot traverse the agent's 0700 tree
        at = cmd.index("/aqd/bin/cc_exec.sh")
        self.assertEqual(cmd[at + 1:at + 3], ["/aqd/run/project", "/usr/bin/claude"])

    def test_the_driver_never_needs_to_enter_the_project_itself(self):
        captured = {}
        real = subprocess.Popen

        def popen(cmd, **kwargs):
            captured.update(kwargs, cmd=cmd)
            return real(["/bin/true"], **dict(kwargs, cwd="/"))
        env_file = os.path.join(self.tmp, "env")
        with open(env_file, "w", encoding="utf-8") as h:
            h.write("".join(f"{k}={v}\n" for k, v in clean_env(self.tmp).items()))
        secret = os.path.join(self.tmp, "secret")
        with open(secret, "w", encoding="utf-8") as h:
            h.write(TEST_TOKEN + "\n")
        prompt = os.path.join(self.tmp, "p")
        with open(prompt, "w", encoding="utf-8") as h:
            h.write("x")
        unreachable = "/nonexistent-agent-tree/project"  # not even visible to the caller
        with unittest.mock.patch.object(cc.subprocess, "Popen", popen):
            cc.run("/usr/bin/claude", MODEL_REF, "/s.json", 5, prompt, env_file, secret, 5,
                   os.path.join(self.tmp, "out"), unreachable, PLUGIN_DIR)
        self.assertEqual(captured.get("cwd"), "/")
        self.assertIn(unreachable, captured["cmd"])


# ------------------------------------------------------------------ transcript

class TranscriptTests(Workdir):
    def test_valid_control(self):
        r = self.analyse(session("control"))
        self.assertTrue(r["valid"], r["invalid_reasons"])
        self.assertEqual((r["activation"], r["contamination"], r["invoked"]), ("NOT_APPLICABLE", False, False))
        self.assertEqual(r["tool_counts"], {"Read": 1, "Edit": 1})
        self.assertEqual(r["estimated_cost_usd"], 0.42)

    def test_treatment_available_but_not_invoked_is_valid(self):
        # The estimand is availability: a treatment run that never invokes the skill is still a treatment run.
        r = self.analyse(session("treatment"), "treatment")
        self.assertTrue(r["valid"], r["invalid_reasons"])
        self.assertEqual((r["activation"], r["invoked"], r["skill_text_loaded"]), ("AVAILABLE", False, False))

    def test_treatment_invocation_and_loading_are_recorded_separately(self):
        middle = [assistant([tool_use("Skill", {"skill": "code-discipline"}, "s1")]), tool_result("s1", SKILL_BODY),
                  assistant([{"type": "text", "text": "Done."}])]
        r = self.analyse(session("treatment", middle), "treatment")
        self.assertTrue(r["valid"], r["invalid_reasons"])
        self.assertEqual((r["invoked"], r["skill_text_loaded"]), (True, True))
        self.assertEqual(r["skill_invocations"], ["code-discipline"])
        self.assertEqual(r["tool_counts"], {"Skill": 1})

    def test_skill_text_without_a_skill_tool_call_is_loaded_not_invoked(self):
        # A /skill-name expansion is not documented to create a Skill tool_use; text alone is never taken as one.
        middle = [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": SKILL_BODY}]}},
                  assistant([{"type": "text", "text": "Done."}])]
        r = self.analyse(session("treatment", middle), "treatment")
        self.assertEqual((r["invoked"], r["skill_text_loaded"]), (False, True))

    def test_treatment_without_the_skill_available_is_invalid(self):
        r = self.analyse(session("treatment", init=init_event("control")), "treatment")
        self.assertFalse(r["valid"])
        self.assertEqual(r["activation"], "NOT_AVAILABLE")

    def test_extra_skills_invalidate_both_arms(self):
        # An account-synced or bundled skill would be a second treatment.
        for group, skills in (("control", ["careful-coding"]), ("treatment", ["code-discipline", "verify"]),
                              ("control", ["code-review"]), ("treatment", "code-discipline")):
            with self.subTest(group=group, skills=skills):
                r = self.analyse(session(group, init=init_event(group, skills=skills)), group)
                self.assertFalse(r["valid"])

    def test_control_contamination(self):
        cases = {
            "skill listed": session("control", init=init_event("control", skills=["code-discipline"])),
            "command listed": session("control", init=init_event("control", slash_commands=["code-discipline"])),
            "skill invoked": session("control", [assistant([tool_use("Skill", {"skill": "code-discipline"})])]),
            "plugin-qualified": session("control", [assistant([tool_use("Skill", {"skill": "x:code-discipline"})])]),
            "skill text": session("control", [tool_result("t1", c.SKILL_SENTINELS[1]),
                                              assistant([{"type": "text", "text": "ok"}])]),
        }
        for name, events in cases.items():
            with self.subTest(case=name):
                self.assertFalse(self.analyse(events)["valid"])

    def test_billing_and_identity(self):
        cases = {
            "api key": init_event(apiKeySource="ANTHROPIC_API_KEY"),
            "helper": init_event(apiKeySource="apiKeyHelper"),
            "missing key source": {k: v for k, v in init_event().items() if k != "apiKeySource"},
            "other model": init_event(model="claude-sonnet-5-5"),
            "other version": init_event(claude_code_version="2.1.331"),
            "plugins": init_event(plugins=[{"name": "p", "path": "/p"}]),
            "mcp": init_event(mcp_servers=[{"name": "m", "status": "connected"}]),
            "web tool": init_event(tools=["Bash", "Read", "Edit", "WebFetch"]),
            "no bash": init_event(tools=["Read", "Edit"]),
            "bypass": init_event(permissionMode="bypassPermissions"),
            "effort": init_event(effort="high"),
        }
        for name, init in cases.items():
            with self.subTest(case=name):
                r = self.analyse(session(init=init))
                self.assertFalse(r["valid"], name)
        api = self.analyse(session(init=init_event(apiKeySource="ANTHROPIC_API_KEY")))
        self.assertIn("billing: not subscription authentication", api["errors"])
        ok = self.analyse(session(init=init_event(effort="medium")))
        self.assertTrue(ok["valid"])
        self.assertEqual(ok["effort_reported"], "medium")
        self.assertIsNone(self.analyse(session())["effort_reported"])  # absent: effort not verified

    def test_model_fallback_is_detected(self):
        middle = [assistant([{"type": "text", "text": "a"}]), assistant([{"type": "text", "text": "b"}],
                                                                      model="claude-sonnet-5-5")]
        r = self.analyse(session(middle=middle))
        self.assertFalse(r["valid"])
        self.assertEqual(r["model_mismatches"], [{"index": 1, "model": "claude-sonnet-5-5"}])
        r = self.analyse(session(result=result_event(models=("claude-sonnet-5-5",))))
        self.assertFalse(r["valid"])  # the pinned model never served the result

    def test_auxiliary_model_usage_is_recorded_not_hidden(self):
        r = self.analyse(session(result=result_event(models=(MODEL, "claude-haiku-5-5"))))
        self.assertTrue(r["valid"], r["invalid_reasons"])
        self.assertEqual(r["auxiliary_models"], ["claude-haiku-5-5"])

    def test_infrastructure_errors_and_outcomes(self):
        retry = {"type": "system", "subtype": "api_retry", "error": "rate_limit", "attempt": 1}
        recovered = self.analyse(session(middle=[retry, assistant([{"type": "text", "text": "x"}])]))
        self.assertTrue(recovered["valid"], recovered["invalid_reasons"])  # a retry that recovered is not a failure
        self.assertEqual(recovered["api_retries"], ["rate_limit"])
        self.assertEqual(recovered["errors"], [])
        for subtype, is_error in (("error_during_execution", True), ("success", True), ("success", None)):
            with self.subTest(subtype=subtype, is_error=is_error):
                self.assertFalse(self.analyse(session(result=result_event(subtype, is_error)))["valid"])

    def test_turn_limit_in_the_shape_the_cli_emits_is_a_valid_outcome(self):
        # 2.1.330 builds the max-turns result with is_error true (binary text: is_error:!0 ... "error_max_turns")
        r = self.analyse(session(result=result_event("error_max_turns", True)))
        self.assertTrue(r["valid"], r["invalid_reasons"])
        self.assertEqual(r["result_subtype"], "error_max_turns")
        self.assertTrue(r["max_turns_reached"])
        for subtype in ("error_max_budget_usd", "error_max_structured_output_retries"):
            with self.subTest(subtype=subtype):
                self.assertFalse(self.analyse(session(result=result_event(subtype, True)))["valid"])

    def test_skill_delivery_and_plugins_must_match_the_real_cli_shape(self):
        bad = {
            "skill not namespaced": init_event("treatment", skills=["code-discipline", "doctor"]),
            "built-in skill missing": init_event("treatment", skills=["aqd-arm:code-discipline"]),
            "extra skill": init_event("treatment", skills=["aqd-arm:code-discipline", "doctor", "x"]),
            "built-in plugin loaded": init_event("treatment", plugins=[dict(ARM_PLUGIN), {
                "name": "cc-plugin-privacy", "path": "builtin", "source": "cc-plugin-privacy@builtin"}]),
            "plugin from another path": init_event("treatment", plugins=[dict(ARM_PLUGIN, path="/elsewhere")]),
            "no plugin": init_event("treatment", plugins=[]),
            "permission mode": init_event("treatment", permissionMode="acceptEdits"),
            "not served by anthropic": init_event("treatment", served_by_anthropic=False),
            "served_by_anthropic absent": {k: v for k, v in init_event("treatment").items() if k != "served_by_anthropic"},
        }
        for name, init in bad.items():
            with self.subTest(name=name):
                self.assertFalse(self.analyse(session("treatment", init=init), "treatment")["valid"])
        self.assertTrue(self.analyse(session("treatment"), "treatment")["valid"])
        self.assertTrue(self.analyse(session("control"))["valid"])
        self.assertFalse(self.analyse(session("control", init=init_event("control", skills=["aqd-arm:code-discipline",
                                                                                           "doctor"])))["valid"])

    def test_a_bash_sandbox_that_cannot_start_is_infrastructure_not_an_outcome(self):
        # 2.1.330 with CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 and no socat answers EVERY Bash call with this error
        failed = [assistant([tool_use("Bash", {"command": "pytest"})]),
                  tool_result("t1", "Sandbox is required but failed to initialize: Sandbox dependencies not available: "
                                    "socat not installed. Restart to retry."),
                  assistant([{"type": "text", "text": "Done."}])]
        r = self.analyse(session(middle=failed))
        self.assertFalse(r["valid"])
        self.assertTrue(any("sandbox" in x for x in r["invalid_reasons"]), r["invalid_reasons"])
        # namespaces refused (unprivileged host): the real 2.1.330 answer, captured offline
        refused = [assistant([tool_use("Bash", {"command": "pytest"})]),
                   tool_result("t1", "Exit code 1\nbwrap: No permissions to create new namespace, likely because the "
                                     "kernel does not allow non-privileged user namespaces. See <https://deb.li/bubblewrap>."),
                   assistant([{"type": "text", "text": "Done."}])]
        r = self.analyse(session(middle=refused))
        self.assertFalse(r["valid"])
        self.assertTrue(any("sandbox" in x for x in r["invalid_reasons"]), r["invalid_reasons"])
        # an ordinary failing command that merely mentions bwrap is an outcome, not infrastructure
        ordinary = [assistant([tool_use("Bash", {"command": "pytest"})]),
                    tool_result("t1", "Exit code 1\nFAILED test_x.py::test_a - bwrap: mentioned in a message"),
                    assistant([{"type": "text", "text": "Done."}])]
        self.assertTrue(self.analyse(session(middle=ordinary))["valid"])

    def test_working_directory_must_be_the_project(self):
        for cwd in ("/home/operator", None, PROJECT + "/sub"):
            with self.subTest(cwd=cwd):
                init = init_event()
                if cwd is None:
                    init.pop("cwd")
                else:
                    init["cwd"] = cwd
                r = self.analyse(session(init=init))
                self.assertFalse(r["valid"])
                self.assertTrue(any("working directory" in x for x in r["invalid_reasons"]), r["invalid_reasons"])

    def test_the_skill_tool_must_be_offered_in_treatment(self):
        tools = ["Bash", "Read", "Edit", "Write", "Glob", "Grep"]
        r = self.analyse(session("treatment", init=init_event("treatment", tools=tools)), "treatment")
        self.assertFalse(r["valid"])
        self.assertEqual(r["activation"], "NOT_AVAILABLE")
        # control: the Skill tool may or may not be listed when no skill exists; either is valid and recorded
        for listed in (tools, tools + ["Skill"]):
            with self.subTest(listed=listed):
                r = self.analyse(session(init=init_event(tools=listed)))
                self.assertTrue(r["valid"], r["invalid_reasons"])
                self.assertEqual(r["skill_tool_offered"], "Skill" in listed)

    def test_timeout_transcripts_are_valid_timeouts(self):
        partial = session()[:-1]  # killed: no result event
        r = self.analyse(partial, raw_lines=['{"type": "assistant", "mess'], driver_status="timeout")
        self.assertTrue(r["valid"], r["invalid_reasons"])
        self.assertTrue(r["model_ok"])
        self.assertTrue(r["timed_out"])
        # the same transcript without a timeout is still a broken session
        self.assertFalse(self.analyse(partial, driver_status="idle")["valid"])
        # only a truncated LAST line is tolerated
        bad_middle = self.transcript(partial[:2]) 
        with open(bad_middle, "a", encoding="utf-8") as h:
            h.write("garbage\n" + json.dumps(partial[2]) + "\n")
        self.assertFalse(cc.analyse_transcript(bad_middle, "control", MODEL_REF, PROJECT, "timeout", PLUGIN_DIR)["valid"])
        # identity is still required, and a timeout spent retrying the provider is infrastructure
        self.assertFalse(self.analyse(partial[1:], driver_status="timeout")["valid"])
        self.assertFalse(self.analyse([init_event()], driver_status="timeout")["valid"])
        retrying = partial + [{"type": "system", "subtype": "api_retry", "error": "overloaded", "attempt": 9}]
        r = self.analyse(retrying, driver_status="timeout")
        self.assertFalse(r["valid"])
        self.assertTrue(r["errors"])
        # a fallback model before the timeout is still caught
        self.assertFalse(self.analyse(partial + [assistant([{"type": "text", "text": "x"}], model="claude-haiku-5-5")],
                                      driver_status="timeout")["valid"])

    def test_unknown_driver_status_fails_closed(self):
        for status in (None, "error", "running"):
            with self.subTest(status=status):
                self.assertFalse(self.analyse(session(), driver_status=status)["valid"])

    def test_malformed_transcripts_fail_closed(self):
        self.assertFalse(self.analyse(session(), raw_lines=["not json"])["valid"])
        self.assertFalse(self.analyse([init_event()] + session())["valid"])  # two init events
        self.assertFalse(self.analyse(session()[:-1])["valid"])  # no result
        self.assertFalse(self.analyse([init_event(), result_event()])["valid"])  # no assistant turn
        missing = cc.analyse_transcript(os.path.join(self.tmp, "absent.ndjson"), "control", MODEL_REF, PROJECT, "idle", PLUGIN_DIR)
        self.assertFalse(missing["valid"])


# ------------------------------------------------------------------ run_status reuse

class RunStatusInterfaceTests(Workdir):
    def capture(self, group, events, listing, record_changes=None, driver=None, driver_status="idle"):
        cap = os.path.join(self.tmp, f"cap-{group}-{len(os.listdir(self.tmp))}")
        os.makedirs(os.path.join(cap, "driver"))
        report = cc.analyse_transcript(self.transcript(events), group, MODEL_REF, PROJECT, driver_status, PLUGIN_DIR)
        cc._write(os.path.join(cap, "export-checks.json"), report)
        cc._write(os.path.join(cap, "driver", "driver-result.json"), driver or {"status": "idle", "outcome": "succeeded"})
        cc._write(os.path.join(cap, "verify-post.json"), {"integrity_ok": True, "findings": {}})
        with open(os.path.join(cap, "home-config-listing.txt"), "w", encoding="utf-8") as h:
            h.write("".join(f"{x}\n" for x in listing))
        record = {"run_id": "r-0123456789", "group": group, "model": MODEL_REF, "model_provider": "anthropic",
                  "model_id": MODEL, "model_variant": "medium", "interface": cc.INTERFACE,
                  "execution_environment": cc.EXECUTION_ENVIRONMENT, "activation_mode": cc.ACTIVATION_MODE,
                  "skill": {"installed": group == "treatment", "sha256": "ab" * 32 if group == "treatment" else None},
                  "prompt_sha256": "cd" * 32, "workspace_sha256": "ef" * 32, "global_config_sha256": "01" * 32}
        record.update(record_changes or {})
        cc._write(os.path.join(cap, "run-record.json"), record)
        return cap

    def status(self, cap, group, interface="claude-code"):
        return run_status.build_status(cap, group, 0, 10, 0, 0, "done", interface)

    def test_valid_runs_in_both_arms(self):
        for group, listing in (("control", run_status.expected_home_listing("control", "claude-code")),
                               ("treatment", run_status.expected_home_listing("treatment", "claude-code"))):
            with self.subTest(group=group):
                s = self.status(self.capture(group, session(group), listing), group)
                self.assertTrue(s["valid"], s["invalid_reasons"])

    def test_turn_limit_and_timeout_stay_valid_in_run_status(self):
        cap = self.capture("control", session(result=result_event("error_max_turns", True)), run_status.expected_home_listing("control", "claude-code"),
                           driver={"status": "idle", "outcome": "max_turns"})
        s = self.status(cap, "control")
        self.assertTrue(s["valid"], s["invalid_reasons"])
        cap = self.capture("control", session()[:-1], run_status.expected_home_listing("control", "claude-code"), driver={"status": "timeout", "outcome": "timeout"},
                           driver_status="timeout")
        s = self.status(cap, "control")
        self.assertTrue(s["valid"], s["invalid_reasons"])
        self.assertTrue(s["timed_out"])

    def test_wrong_skills_listing_or_record_is_invalid(self):
        cap = self.capture("control", session("control"), run_status.expected_home_listing("treatment", "claude-code"))
        self.assertFalse(self.status(cap, "control")["valid"])
        planted = run_status.expected_home_listing("control", "claude-code") + ["config-skills/planted"]
        cap = self.capture("control", session("control"), planted)
        self.assertFalse(self.status(cap, "control")["valid"])
        cap = self.capture("control", session("control"), run_status.expected_home_listing("control", "claude-code"),
                           {"execution_environment": "opencode"})
        self.assertFalse(self.status(cap, "control")["valid"])
        cap = self.capture("control", session("control"), run_status.expected_home_listing("control", "claude-code"),
                           {"interface": "opencode 2.3.2"})
        self.assertFalse(self.status(cap, "control")["valid"])

    def test_default_interface_still_expects_opencode(self):
        cap = self.capture("control", session("control"), [])
        s = self.status(cap, "control", interface="opencode")
        self.assertFalse(s["valid"])
        self.assertTrue(any("interface" in r or "HOME" in r for r in s["invalid_reasons"]))
        self.assertEqual(run_status.expected_home_listing("control"), ["opencode", "opencode/opencode.jsonc"])


class AnalyzeRecordTests(unittest.TestCase):
    """analyze.check_run_records (reused) over native Claude Code run records."""

    def records(self, changes=(None, None)):
        import analyze  # noqa: F401
        out = []
        for i, group in enumerate(("control", "treatment")):
            run = {"run_id": f"r-000000000{i}", "task": "P2-LS", "group": group, "model": MODEL_REF}
            record = dict(run, interface=cc.INTERFACE, execution_environment=cc.EXECUTION_ENVIRONMENT,
                          activation_mode=cc.ACTIVATION_MODE, agent="claude-code-print", timeout_seconds=2700,
                          opencode_install_tree_sha256=None, claude_cli_sha256="aa" * 32, max_turns=200,
                          prompt_sha256="11" * 32, workspace_sha256="22" * 32, global_config_sha256="33" * 32,
                          skill={"installed": group == "treatment", "sha256": "44" * 32 if group == "treatment" else None})
            record.update(changes[i] or {})
            out.append((run, record))
        return out

    def test_identical_native_records_pass(self):
        import analyze
        analyze.check_run_records(self.records())

    def test_cli_binary_or_turn_limit_must_match_across_runs(self):
        import analyze
        for change in ({"claude_cli_sha256": "bb" * 32}, {"max_turns": 100}):
            with self.subTest(change=change), self.assertRaises(analyze.AnalysisError):
                analyze.check_run_records(self.records((None, change)))
        with self.assertRaises(analyze.AnalysisError):
            analyze.check_run_records(self.records(({"claude_cli_sha256": None}, {"claude_cli_sha256": None})))

    def test_native_records_need_the_pre_registered_timeout(self):
        import analyze
        with self.assertRaisesRegex(analyze.AnalysisError, "2700"):
            analyze.check_run_records(self.records(({"timeout_seconds": 20}, {"timeout_seconds": 20})))

    def test_execution_environments_are_never_pooled(self):
        import analyze
        records = self.records()
        legacy = dict(records[0][1])  # same interface string, so only the environment label differs
        legacy.pop("execution_environment")
        with self.assertRaisesRegex(analyze.AnalysisError, "never pooled"):
            analyze.check_run_records([(records[0][0], legacy), records[1]])


# ------------------------------------------------------------------ the driver with a mock claude

MOCK = textwrap.dedent('''\
    #!{python}
    """MOCK claude for offline tests: records what it received, replays a synthetic transcript."""
    import hashlib, json, os, sys, time
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(here, "mock-config.json")))
    if sys.argv[1:4] == ["auth", "status", "--json"]:
        ok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == cfg["expect_token"]
        print(json.dumps(cfg.get("auth") if ok else {{"authMethod": "none"}}))
        sys.exit(0 if ok else 1)
    prompt = sys.stdin.buffer.read()
    seen = {{"argv": sys.argv[1:], "env_names": sorted(os.environ),
            "token_ok": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == cfg["expect_token"],
            "prompt_sha256": hashlib.sha256(prompt).hexdigest(), "cwd": os.getcwd()}}
    json.dump(seen, open(os.path.join(here, "mock-seen.json"), "w"))
    if cfg.get("sleep"):
        time.sleep(cfg["sleep"])
    for event in cfg["events"]:
        print(json.dumps(event), flush=True)
    sys.exit(cfg.get("exit", 0))
''')


class DriverIntegrationTests(Workdir):
    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.claude = os.path.join(self.bin, "claude")
        with open(self.claude, "w", encoding="utf-8") as h:
            h.write(MOCK.format(python=sys.executable))
        os.chmod(self.claude, 0o755)
        self.env_file = os.path.join(self.tmp, "env")
        self.secret = os.path.join(self.tmp, "secret")
        self.prompt = os.path.join(self.tmp, "TASK.md")
        with open(self.prompt, "w", encoding="utf-8") as h:
            h.write("# Task\n\nFix it.\nSecond line, unchanged.\n")
        self.write_env(clean_env(self.tmp))
        with open(self.secret, "w", encoding="utf-8") as h:
            h.write(TEST_TOKEN + "\n")
        os.chmod(self.secret, 0o600)
        self.settings = os.path.join(self.tmp, "settings.json")
        cc._write(self.settings, cc.HARNESS_SETTINGS)
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.project)
        self.plugin_dir = os.path.join(self.tmp, "arm-plugin")

    def write_env(self, env):
        with open(self.env_file, "w", encoding="utf-8") as h:
            h.write("".join(f"{k}={v}\n" for k, v in env.items()))

    def configure(self, events, **extra):
        cc._write(os.path.join(self.bin, "mock-config.json"), dict({"expect_token": TEST_TOKEN, "events": events},
                                                                   **extra))

    def run_driver(self, timeout=30):
        out = os.path.join(self.tmp, "out")
        code = cc.run(self.claude, MODEL_REF, self.settings, 40, self.prompt, self.env_file, self.secret, timeout, out,
                      self.project, self.plugin_dir)
        return code, out

    def seen(self):
        path = os.path.join(self.bin, "mock-seen.json")
        return load(path) if os.path.exists(path) else None

    def test_end_to_end_with_mock_claude(self):
        init = init_event("treatment", cwd=self.project, plugins=[dict(ARM_PLUGIN, path=self.plugin_dir)])
        self.configure(session("treatment", init=init))
        code, out = self.run_driver()
        self.assertEqual(code, 0)
        seen = self.seen()
        self.assertEqual(os.path.realpath(seen["cwd"]), os.path.realpath(self.project))  # claude starts in the project
        self.assertTrue(seen["token_ok"])  # the token reached claude's environment ...
        self.assertNotIn(TEST_TOKEN, json.dumps(seen["argv"]))  # ... but not its arguments
        self.assertEqual(seen["argv"], cc.build_argv(self.claude, MODEL_REF, self.settings, 40, self.plugin_dir)[1:])
        self.assertEqual(set(seen["env_names"]) - {"PWD", "SHLVL", "_"},
                         set(clean_env(self.tmp)) | {"CLAUDE_CODE_OAUTH_TOKEN"})
        with open(self.prompt, "rb") as handle:
            self.assertEqual(seen["prompt_sha256"], hashlib.sha256(handle.read()).hexdigest())
        driver = load(os.path.join(out, "driver-result.json"))
        self.assertEqual((driver["status"], driver["outcome"], driver["session_id"]), ("idle", "succeeded", "s-synthetic"))
        report = cc.analyse_transcript(os.path.join(out, "transcript.ndjson"), "treatment", MODEL_REF, self.project,
                                       driver["status"], self.plugin_dir)
        self.assertTrue(report["valid"], report["invalid_reasons"])
        self.assertEqual(cc.files_containing([out], TEST_TOKEN), [])

    def test_refusals_happen_before_claude_starts(self):
        self.configure(session())
        self.write_env(dict(clean_env(self.tmp), ANTHROPIC_API_KEY="sk-ant-api03-x"))
        code, out = self.run_driver()
        self.assertEqual(code, 3)
        self.assertIsNone(self.seen())
        self.assertTrue(load(os.path.join(out, "driver-result.json"))["refused"])
        self.write_env(clean_env(self.tmp))
        with open(self.secret, "w", encoding="utf-8") as h:
            h.write("sk-ant-api03-an-api-key\n")
        self.assertEqual(self.run_driver()[0], 3)
        self.assertIsNone(self.seen())

    def test_failed_or_errored_sessions_are_not_successes(self):
        self.configure(session(result=result_event("error_during_execution", True)), exit=1)
        code, out = self.run_driver()
        self.assertEqual(code, 1)
        self.assertEqual(load(os.path.join(out, "driver-result.json"))["outcome"], "failed")

    def test_timeout_kills_the_session(self):
        self.configure(session(), sleep=30)
        code, out = self.run_driver(timeout=2)
        driver = load(os.path.join(out, "driver-result.json"))
        self.assertEqual((code, driver["status"], driver["outcome"]), (0, "timeout", "timeout"))

    def run_with_outer_guard(self, claude_body, prompt_bytes, timeout=2, guard=20):
        """Runs cc.run in a child interpreter so a hang is reported as a failure, not a stuck test."""
        with open(self.claude, "w", encoding="utf-8") as h:
            h.write(claude_body)
        with open(self.prompt, "wb") as h:
            h.write(b"x" * prompt_bytes)
        out = os.path.join(self.tmp, "out")
        code = textwrap.dedent(f"""
            import sys, time; sys.path.insert(0, {HARNESS!r}); import cc_adapter as cc
            cc.MAX_PROMPT_BYTES = 10 ** 7
            t0 = time.monotonic()
            rc = cc.run({self.claude!r}, {MODEL_REF!r}, {self.settings!r}, 5, {self.prompt!r}, {self.env_file!r},
                        {self.secret!r}, {timeout}, {out!r}, {self.project!r}, {self.plugin_dir!r})
            print(rc, round(time.monotonic() - t0, 1))
        """)
        try:
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=guard)
        except subprocess.TimeoutExpired:
            self.fail(f"run() did not return within {guard}s although its timeout is {timeout}s (stdin hand-off blocked)")
        return proc, out

    def test_a_child_that_never_reads_stdin_cannot_block_the_timeout(self):
        # 300 KB is far above any pipe buffer: the old code blocked in write() before the timeout started.
        proc, out = self.run_with_outer_guard("#!/bin/sh\nsleep 60\n", 300_000)
        rc, elapsed = proc.stdout.split()
        self.assertLess(float(elapsed), 10, proc.stderr)
        driver = load(os.path.join(out, "driver-result.json"))
        self.assertEqual((driver["status"], driver["outcome"]), ("timeout", "timeout"))

    def test_a_child_that_exits_without_reading_is_a_failure_not_a_hang(self):
        proc, out = self.run_with_outer_guard("#!/bin/sh\nexit 3\n", 300_000)
        driver = load(os.path.join(out, "driver-result.json"))
        self.assertEqual((driver["status"], driver["outcome"], driver["exit_code"]), ("idle", "failed", 3))
        self.assertEqual(proc.stdout.split()[0], "1")

    def test_timeout_also_ends_children_that_left_the_process_group_leader(self):
        # the session leader ignores SIGTERM and has a background child; SIGKILL of the group ends both
        body = "#!/bin/sh\ntrap '' TERM\n(sleep 60; echo late) &\nsleep 60\n"
        proc, out = self.run_with_outer_guard(body, 10)
        self.assertEqual(load(os.path.join(out, "driver-result.json"))["status"], "timeout")
        with open(os.path.join(out, "transcript.ndjson"), encoding="utf-8") as h:
            self.assertNotIn("late", h.read())

    def test_timeout_when_the_remaining_group_belongs_to_another_user_stays_a_valid_timeout(self):
        # Through sudo with a non-root operator: after sudo exits, the group holds only the agent user's processes
        # and killpg raises EPERM. That must not crash the driver (reproduced in the dry-run image by review).
        self.configure(session(), sleep=30)
        real_killpg, calls = os.killpg, []

        def killpg(pid, sig):
            calls.append(sig)
            if sig == signal.SIGKILL:
                raise PermissionError(1, "Operation not permitted")
            return real_killpg(pid, sig)
        with unittest.mock.patch.object(cc.os, "killpg", killpg):
            code, out = self.run_driver(timeout=2)
        driver = load(os.path.join(out, "driver-result.json"))
        self.assertEqual((code, driver["status"], driver["outcome"]), (0, "timeout", "timeout"))
        self.assertIn(signal.SIGTERM, calls)

    def test_timeout_when_even_term_is_refused_still_writes_a_status(self):
        self.configure(session(), sleep=30)
        real_killpg = os.killpg

        def killpg(pid, sig):
            raise PermissionError(1, "Operation not permitted")
        with unittest.mock.patch.object(cc.os, "killpg", killpg), \
                unittest.mock.patch.object(cc, "TERM_GRACE_SECONDS", 1):
            try:
                code, out = self.run_driver(timeout=2)
            finally:
                cc.os.killpg = real_killpg
        driver = load(os.path.join(out, "driver-result.json"))
        self.assertEqual(driver["status"], "timeout")

    def test_a_command_that_cannot_start_still_writes_an_unambiguous_status(self):
        missing = os.path.join(self.tmp, "no-such-claude")
        out = os.path.join(self.tmp, "out")
        code = cc.run(missing, MODEL_REF, self.settings, 5, self.prompt, self.env_file, self.secret, 5, out,
                      self.project, self.plugin_dir, wrapper=missing)
        self.assertNotEqual(code, 0)
        driver = load(os.path.join(out, "driver-result.json"))
        self.assertEqual((driver["status"], driver["outcome"]), ("error", "not_started"))

    def test_turn_limit_is_an_outcome_not_a_failure(self):
        self.configure(session(result=result_event("error_max_turns", True)), exit=1)
        code, out = self.run_driver()
        self.assertEqual(code, 0)
        self.assertEqual(load(os.path.join(out, "driver-result.json"))["outcome"], "max_turns")

    def test_check_transcript_cli_uses_the_driver_status(self):
        partial = os.path.join(self.tmp, "partial.ndjson")
        with open(partial, "w", encoding="utf-8") as h:
            h.write("".join(json.dumps(e) + "\n" for e in session()[:-1]) + '{"type": "assist')
        driver = os.path.join(self.tmp, "driver-result.json")
        out = os.path.join(self.tmp, "checks.json")
        args = ["check-transcript", "--transcript", partial, "--group", "control", "--model", MODEL_REF,
                "--project", PROJECT, "--plugin-dir", PLUGIN_DIR, "--driver-result", driver, "--out", out]
        cc._write(driver, {"status": "timeout", "outcome": "timeout"})
        self.assertEqual(cc.main(args), 0)
        cc._write(driver, {"status": "idle", "outcome": "failed"})
        self.assertEqual(cc.main(args), 1)
        os.remove(driver)
        self.assertNotEqual(cc.main(args), 0)

    def test_secret_scan_never_follows_symlinks_the_agent_planted(self):
        # an agent can plant links to /proc/*/environ or to operator files; the scan reads captured CONTENT only
        cap = os.path.join(self.tmp, "cap-links")
        os.makedirs(cap)
        outside = os.path.join(self.tmp, "outside-secret.txt")
        with open(outside, "w", encoding="utf-8") as h:
            h.write(TEST_TOKEN)
        os.symlink(outside, os.path.join(cap, "link-to-secret"))
        os.symlink("/proc/self/environ", os.path.join(cap, "env_link"))
        self.assertEqual(cc.files_containing([cap], TEST_TOKEN), [])
        with open(os.path.join(cap, "real.txt"), "w", encoding="utf-8") as h:
            h.write(TEST_TOKEN)
        self.assertEqual(cc.files_containing([cap], TEST_TOKEN), [os.path.join(cap, "real.txt")])

    def test_secret_scan_subcommand(self):
        cap = os.path.join(self.tmp, "cap")
        os.makedirs(cap)
        with open(os.path.join(cap, "transcript.ndjson"), "w", encoding="utf-8") as h:
            h.write("clean\n")
        self.assertEqual(cc.main(["scan-secret", "--secret-file", self.secret, "--root", cap]), 0)
        with open(os.path.join(cap, "stderr.txt"), "w", encoding="utf-8") as h:
            h.write(TEST_TOKEN)
        self.assertEqual(cc.main(["scan-secret", "--secret-file", self.secret, "--root", cap]), 21)
        self.assertEqual(cc.main(["scan-secret", "--secret-file", os.path.join(self.tmp, "nope"), "--root", cap]), 21)

    def test_auth_status_through_the_wrapper(self):
        out = os.path.join(self.tmp, "auth.json")
        self.configure(session(), auth={"authMethod": "oauth_token", "subscriptionType": "ultra"})
        self.assertEqual(cc.auth_status(self.claude, self.env_file, self.secret, out), 0)
        verdict = load(out)
        self.assertEqual((verdict["ok"], verdict["auth_method"], verdict["subscription_type"]), (True, "oauth_token", "ultra"))
        self.assertNotIn(TEST_TOKEN, json.dumps(verdict))
        self.configure(session(), auth={"authMethod": "api_key", "apiKeySource": "ANTHROPIC_API_KEY"})
        self.assertEqual(cc.auth_status(self.claude, self.env_file, self.secret, out), 3)
        self.assertFalse(load(out)["ok"])

    def test_secret_scan_finds_a_leaked_token(self):
        leak = os.path.join(self.tmp, "leak")
        os.makedirs(leak)
        with open(os.path.join(leak, "notes.txt"), "w", encoding="utf-8") as h:
            h.write(f"token={TEST_TOKEN}\n")
        self.assertEqual(cc.files_containing([leak], TEST_TOKEN), [os.path.join(leak, "notes.txt")])


class PreflightTests(Workdir):
    """Native preflight artifact: bound to environment, commit, CLI, harness, settings, skill and schedule."""

    def setUp(self):
        super().setUp()
        self.checkout = os.path.join(self.tmp, "checkout")
        os.makedirs(os.path.join(self.checkout, "skills", c.SKILL_ID))
        self.write(os.path.join(self.checkout, "skills", c.SKILL_ID, "SKILL.md"), CANONICAL_SKILL)
        git = lambda *a: subprocess.run(["git", "-C", self.checkout, *a], check=True, capture_output=True)  # noqa: E731
        git("init", "-q")
        git("-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", ".")
        git("-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "x")
        self.harness = os.path.join(self.tmp, "harness")
        os.makedirs(self.harness)
        for name in cc.PREFLIGHT_HARNESS_FILES:
            self.write(os.path.join(self.harness, name), f"# {name}\n")
        self.sealed = os.path.join(self.tmp, "sealed")
        self.pristine = os.path.join(self.tmp, "pristine")
        os.makedirs(os.path.join(self.pristine, "skill", c.SKILL_ID))
        os.makedirs(os.path.join(self.pristine, "SMOKE"))
        os.makedirs(self.sealed)
        self.write(os.path.join(self.pristine, "skill", c.SKILL_ID, "SKILL.md"), CANONICAL_SKILL)
        self.write(os.path.join(self.pristine, "SMOKE", "manifest.json"), "{}")
        self.write(os.path.join(self.sealed, "schedule.json"), json.dumps({"runs": [{"task": "SMOKE"}]}))
        self.write(os.path.join(self.sealed, "pristine-extra.sha256"), "x\n")
        self.claude = os.path.join(self.tmp, "claude")
        self.write(self.claude, "binary-v1")

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as h:
            h.write(text)

    def fingerprint(self, **changes):
        args = dict(checkout=self.checkout, harness=self.harness, claude=self.claude, cli_version="2.1.330",
                    sealed=self.sealed, pristine=self.pristine, max_turns=200, timeout_seconds=2700)
        args.update(changes)
        return cc.preflight_fingerprint(**args)

    def record(self, **changes):
        rec = {"schema_version": 1, "execution_environment": cc.EXECUTION_ENVIRONMENT, "ok": True,
               "created_utc": "2026-11-23T10:00:00+00:00", "fingerprint": self.fingerprint()}
        rec.update(changes)
        return rec

    NOW = "2026-11-23T12:00:00+00:00"

    def test_evidence_runs_need_the_pre_registered_timeout(self):
        self.assertTrue(any("2700" in r for r in cc.check_timeout_policy(20, dry_run=False)))
        self.assertEqual(cc.check_timeout_policy(2700, dry_run=False), [])
        self.assertEqual(cc.check_timeout_policy(20, dry_run=True), [])
        fp = self.fingerprint(timeout_seconds=20)
        self.assertFalse(fp["dry_run"])
        self.assertTrue(any("2700" in r for r in cc.check_preflight(self.record(fingerprint=fp), fp, self.NOW, 24)))
        fp = self.fingerprint(timeout_seconds=20, dry_run=True)
        self.assertEqual(cc.check_preflight(self.record(fingerprint=fp), fp, self.NOW, 24), [])

    def test_a_fresh_matching_preflight_passes(self):
        fp = self.fingerprint()
        self.assertEqual(fp["execution_environment"], cc.EXECUTION_ENVIRONMENT)
        self.assertRegex(fp["checkout_commit"], r"^[0-9a-f]{40}$")
        self.assertTrue(fp["checkout_clean"])
        self.assertEqual(fp["cli_version"], "2.1.330")
        self.assertEqual(fp["cli_sha256"], hashlib.sha256(b"binary-v1").hexdigest())
        self.assertEqual(fp["settings_sha256"], cc.settings_sha256())
        self.assertEqual(cc.check_preflight(self.record(), fp, self.NOW, 24), [])

    def test_any_change_after_preflight_is_rejected_by_name(self):
        cases = {
            "cli_sha256": lambda: self.write(self.claude, "binary-v2"),
            "harness_sha256": lambda: self.write(os.path.join(self.harness, "cc_adapter.py"), "# edited\n"),
            "schedule_sha256": lambda: self.write(os.path.join(self.sealed, "schedule.json"), "{}"),
            "skill_sha256": lambda: self.write(os.path.join(self.pristine, "skill", c.SKILL_ID, "SKILL.md"), "x"),
            "task_manifests_sha256": lambda: self.write(os.path.join(self.pristine, "SMOKE", "manifest.json"), "[]"),
            "pristine_extra_sha256": lambda: self.write(os.path.join(self.sealed, "pristine-extra.sha256"), "y"),
        }
        for key, change in cases.items():
            with self.subTest(key=key):
                self.setUp()  # a fresh host for each case
                rec = self.record()
                change()
                reasons = cc.check_preflight(rec, self.fingerprint(), self.NOW, 24)
                self.assertTrue(any(key in r for r in reasons), reasons)
        for key, value in (("cli_version", "2.1.331"), ("max_turns", 100), ("timeout_seconds", 60)):
            with self.subTest(key=key):
                reasons = cc.check_preflight(self.record(), self.fingerprint(**{key: value}), self.NOW, 24)
                self.assertTrue(any(key in r for r in reasons), reasons)

    def test_settings_change_is_rejected(self):
        rec = self.record()
        original = dict(cc.HARNESS_SETTINGS)
        try:
            cc.HARNESS_SETTINGS["switchModelsOnFlag"] = True
            reasons = cc.check_preflight(rec, self.fingerprint(), self.NOW, 24)
        finally:
            cc.HARNESS_SETTINGS.clear()
            cc.HARNESS_SETTINGS.update(original)
        self.assertTrue(any("settings_sha256" in r for r in reasons), reasons)

    def test_new_commit_or_dirty_checkout_is_rejected(self):
        rec = self.record()
        self.write(os.path.join(self.checkout, "extra.txt"), "dirty")
        fp = self.fingerprint()
        self.assertFalse(fp["checkout_clean"])
        self.assertTrue(cc.check_preflight(rec, fp, self.NOW, 24))
        self.assertTrue(cc.check_preflight(self.record(), fp, self.NOW, 24))  # dirty even if recorded dirty
        subprocess.run(["git", "-C", self.checkout, "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                        "commit", "-qam", "y", "--allow-empty"], check=True, capture_output=True)
        reasons = cc.check_preflight(rec, self.fingerprint(), self.NOW, 24)
        self.assertTrue(any("checkout_commit" in r for r in reasons), reasons)

    def test_canonical_skill_mismatch_is_rejected(self):
        self.write(os.path.join(self.pristine, "skill", c.SKILL_ID, "SKILL.md"), "tampered")
        fp = self.fingerprint()
        reasons = cc.check_preflight(self.record(fingerprint=fp), fp, self.NOW, 24)
        self.assertTrue(any("canonical" in r for r in reasons), reasons)

    def test_stale_future_failed_or_foreign_preflights_are_rejected(self):
        fp = self.fingerprint()
        bad = {
            "stale": self.record(created_utc="2026-11-21T12:00:00+00:00"),
            "future": self.record(created_utc="2026-11-24T12:00:00+00:00"),
            "no time": self.record(created_utc=None),
            "naive time": self.record(created_utc="2026-11-23T10:00:00"),
            "not ok": self.record(ok=False),
            "opencode": self.record(execution_environment="opencode"),
            "schema": self.record(schema_version=0),
            "no fingerprint": self.record(fingerprint=None),
            "not a dict": None,
            "opencode preflight.ok shape": {"checked_utc": "2026-11-23T10:00:00+00:00", "catalog_exit": 0, "gates": {}},
        }
        for name, rec in bad.items():
            with self.subTest(name=name):
                self.assertTrue(cc.check_preflight(rec, fp, self.NOW, 24))


class LauncherStaticTests(unittest.TestCase):
    """launch-run-cc.sh has never been executed; these pin the review fixes in its text (static only)."""
    TEXT = open(os.path.join(HARNESS, "launch-run-cc.sh"), encoding="utf-8").read()

    def function(self, name):
        start = self.TEXT.index(f"{name}() {{")
        return self.TEXT[start:self.TEXT.index("\n}\n", start)]

    def test_secret_scan_runs_in_finish_before_the_secret_is_removed(self):
        body = self.function("finish")
        self.assertIn("scan-secret", body)
        self.assertLess(body.index("scan-secret"), body.index('rm -rf "$SECRET_DIR"'))

    def test_only_the_native_preflight_authorises_a_native_run(self):
        self.assertIn("check-preflight --preflight \"$AQD_SEALED/preflight-cc.json\"", self.TEXT)
        self.assertNotIn("preflight.ok", self.TEXT.replace("The OpenCode preflight.ok is never accepted", ""))

    def test_smoke_is_schedulable_but_not_in_the_default_design(self):
        import schedule
        self.assertIn("SMOKE", schedule.KNOWN_TASKS)
        self.assertEqual(schedule.TASKS, ("NEW-01", "NEW-02", "NEW-03"))

    def test_a_sandbox_failure_stops_the_whole_batch(self):
        self.assertIn('INFRASTRUCTURE STOP in run %s: the Bash sandbox could not start', self.TEXT)
        self.assertIn("exit 22", self.TEXT)

    def test_managed_settings_are_refused(self):
        self.assertRegex(self.TEXT, r'\[\[ ! -e /etc/claude-code \]\] \|\| die')

    def test_config_dir_is_root_owned_and_sticky(self):
        self.assertIn('install -d -o root -g "$AGENT_USER" -m 1770 "$CONFIG"', self.TEXT)

    def test_approval_is_per_run_and_the_session_runs_in_the_project(self):
        self.assertIn("check-approval", self.TEXT)
        self.assertIn('--project "$PROJECT"', self.TEXT)
        self.assertIn('--driver-result "$CAP/driver/driver-result.json"', self.TEXT)


class ExecWrapperTests(Workdir):
    WRAPPER = os.path.join(HARNESS, "cc_exec.sh")

    def run_wrapper(self, stdin):
        script = ('import os, sys; d = sys.stdin.read(); '
                  'print(repr(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")) + "|" + repr(d) + "|" + repr(sys.argv[1:]))')
        return subprocess.run([self.WRAPPER, self.tmp, sys.executable, "-c", script, "--flag"], input=stdin,
                              capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, check=False, cwd="/")

    def test_the_wrapper_enters_the_project_and_refuses_one_it_cannot_enter(self):
        proc = subprocess.run([self.WRAPPER, self.tmp, "/bin/pwd"], input="T\n", capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin"}, check=False, cwd="/")
        self.assertEqual((proc.returncode, os.path.realpath(proc.stdout.strip())), (0, os.path.realpath(self.tmp)))
        proc = subprocess.run([self.WRAPPER, os.path.join(self.tmp, "absent"), "/bin/pwd"], input="T\n",
                              capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, check=False, cwd="/")
        self.assertEqual((proc.returncode, proc.stdout), (96, ""))

    def test_first_line_becomes_the_token_and_the_rest_is_the_prompt(self):
        proc = self.run_wrapper("TOKEN123\nline one\nline two\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "'TOKEN123'|'line one\\nline two\\n'|['--flag']")

    def test_missing_or_empty_token_line_refuses(self):
        for stdin in ("", "\nprompt\n"):
            with self.subTest(stdin=stdin):
                proc = self.run_wrapper(stdin)
                self.assertEqual(proc.returncode, 97)
                self.assertEqual(proc.stdout, "")

    def test_wrapper_is_executable_and_posix_sh(self):
        mode = os.stat(self.WRAPPER).st_mode
        self.assertTrue(mode & stat.S_IXUSR)
        with open(self.WRAPPER, encoding="utf-8") as h:
            self.assertEqual(h.readline().strip(), "#!/bin/sh")


if __name__ == "__main__":
    unittest.main()
