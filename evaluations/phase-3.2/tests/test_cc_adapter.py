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
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "..", "harness")
sys.path.insert(0, HARNESS)

import aqd_common as c  # noqa: E402
import cc_adapter as cc  # noqa: E402
import run_status  # noqa: E402

MODEL_REF = "anthropic/claude-opus-5-5#medium"
MODEL = "claude-opus-5-5"
TEST_TOKEN = "sk-ant-oat01-SYNTHETIC-TEST-TOKEN-not-a-real-credential"
SKILL_BODY = "\n".join(c.SKILL_SENTINELS)


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
             "apiKeySource": "none", "claude_code_version": cc.PINNED_CLI_VERSION, "cwd": "/aqd/run/project",
             "tools": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Skill"], "mcp_servers": [],
             "model": MODEL, "permissionMode": "acceptEdits",
             "slash_commands": ["code-discipline"] if group == "treatment" else [],
             "output_style": "default", "skills": ["code-discipline"] if group == "treatment" else [], "plugins": []}
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

    def analyse(self, events, group="control", raw_lines=()):
        return cc.analyse_transcript(self.transcript(events, raw_lines), group, MODEL_REF)


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
        argv = cc.build_argv("claude", MODEL_REF, "/s.json", 40)
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
        self.assertEqual(value("--tools"), "Bash,Read,Edit,Write,Glob,Grep")
        self.assertEqual(value("--output-format"), "stream-json")

    def test_bad_model_references_are_refused(self):
        for ref in ("anthropic/claude-opus-5-5", "xai/grok-4#high", "anthropic/claude-opus-5-5#ultra", "opus"):
            with self.subTest(ref=ref), self.assertRaises((ValueError, cc.AdapterError)):
                cc.build_argv("claude", ref, "/s.json", 40)
        with self.assertRaises(cc.AdapterError):
            cc.build_argv("claude", MODEL_REF, "/s.json", True)

    def test_settings_turn_off_sync_switching_and_bundled_skills(self):
        s = cc.HARNESS_SETTINGS
        self.assertIs(s["syncClaudeAiSkills"], False)
        self.assertIs(s["syncClaudeAiPlugins"], False)
        self.assertIs(s["switchModelsOnFlag"], False)
        self.assertIs(s["disableBundledSkills"], True)
        self.assertIn("WebFetch", s["permissions"]["deny"])

    def test_run_as_user_never_puts_the_token_in_argv(self):
        cmd = cc.build_command(cc.build_argv("/usr/bin/claude", MODEL_REF, "/s.json", 40), clean_env(self.tmp),
                               as_user="aqd-a", wrapper="/aqd/bin/cc_exec.sh")
        self.assertEqual(cmd[:6], ["sudo", "-n", "-u", "aqd-a", "/usr/bin/env", "-i"])
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", " ".join(cmd))
        self.assertIn("/aqd/bin/cc_exec.sh", cmd)


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
        self.assertFalse(self.analyse(session(middle=[retry, assistant([{"type": "text", "text": "x"}])]))["valid"])
        self.assertTrue(self.analyse(session(result=result_event("error_max_turns", False)))["valid"])
        for subtype, is_error in (("error_during_execution", True), ("success", True), ("success", None)):
            with self.subTest(subtype=subtype, is_error=is_error):
                self.assertFalse(self.analyse(session(result=result_event(subtype, is_error)))["valid"])

    def test_malformed_transcripts_fail_closed(self):
        self.assertFalse(self.analyse(session(), raw_lines=["not json"])["valid"])
        self.assertFalse(self.analyse([init_event()] + session())["valid"])  # two init events
        self.assertFalse(self.analyse(session()[:-1])["valid"])  # no result
        self.assertFalse(self.analyse([init_event(), result_event()])["valid"])  # no assistant turn
        missing = cc.analyse_transcript(os.path.join(self.tmp, "absent.ndjson"), "control", MODEL_REF)
        self.assertFalse(missing["valid"])


# ------------------------------------------------------------------ run_status reuse

class RunStatusInterfaceTests(Workdir):
    def capture(self, group, events, listing, record_changes=None):
        cap = os.path.join(self.tmp, f"cap-{group}-{len(os.listdir(self.tmp))}")
        os.makedirs(os.path.join(cap, "driver"))
        report = cc.analyse_transcript(self.transcript(events), group, MODEL_REF)
        cc._write(os.path.join(cap, "export-checks.json"), report)
        cc._write(os.path.join(cap, "driver", "driver-result.json"), {"status": "idle", "outcome": "succeeded"})
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
        for group, listing in (("control", []), ("treatment", ["code-discipline", "code-discipline/SKILL.md"])):
            with self.subTest(group=group):
                s = self.status(self.capture(group, session(group), listing), group)
                self.assertTrue(s["valid"], s["invalid_reasons"])

    def test_wrong_skills_listing_or_record_is_invalid(self):
        cap = self.capture("control", session("control"), ["code-discipline", "code-discipline/SKILL.md"])
        self.assertFalse(self.status(cap, "control")["valid"])
        cap = self.capture("control", session("control"), [], {"execution_environment": "opencode"})
        self.assertFalse(self.status(cap, "control")["valid"])
        cap = self.capture("control", session("control"), [], {"interface": "opencode 2.3.2"})
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
            "prompt_sha256": hashlib.sha256(prompt).hexdigest()}}
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

    def write_env(self, env):
        with open(self.env_file, "w", encoding="utf-8") as h:
            h.write("".join(f"{k}={v}\n" for k, v in env.items()))

    def configure(self, events, **extra):
        cc._write(os.path.join(self.bin, "mock-config.json"), dict({"expect_token": TEST_TOKEN, "events": events},
                                                                   **extra))

    def run_driver(self, timeout=30):
        out = os.path.join(self.tmp, "out")
        code = cc.run(self.claude, MODEL_REF, self.settings, 40, self.prompt, self.env_file, self.secret, timeout, out)
        return code, out

    def seen(self):
        path = os.path.join(self.bin, "mock-seen.json")
        return load(path) if os.path.exists(path) else None

    def test_end_to_end_with_mock_claude(self):
        self.configure(session("treatment"))
        code, out = self.run_driver()
        self.assertEqual(code, 0)
        seen = self.seen()
        self.assertTrue(seen["token_ok"])  # the token reached claude's environment ...
        self.assertNotIn(TEST_TOKEN, json.dumps(seen["argv"]))  # ... but not its arguments
        self.assertEqual(seen["argv"], cc.build_argv(self.claude, MODEL_REF, self.settings, 40)[1:])
        self.assertEqual(set(seen["env_names"]) - {"PWD", "SHLVL", "_"},
                         set(clean_env(self.tmp)) | {"CLAUDE_CODE_OAUTH_TOKEN"})
        with open(self.prompt, "rb") as handle:
            self.assertEqual(seen["prompt_sha256"], hashlib.sha256(handle.read()).hexdigest())
        driver = load(os.path.join(out, "driver-result.json"))
        self.assertEqual((driver["status"], driver["outcome"], driver["session_id"]), ("idle", "succeeded", "s-synthetic"))
        report = cc.analyse_transcript(os.path.join(out, "transcript.ndjson"), "treatment", MODEL_REF)
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


class ExecWrapperTests(Workdir):
    WRAPPER = os.path.join(HARNESS, "cc_exec.sh")

    def run_wrapper(self, stdin):
        script = ('import os, sys; d = sys.stdin.read(); '
                  'print(repr(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")) + "|" + repr(d) + "|" + repr(sys.argv[1:]))')
        return subprocess.run([self.WRAPPER, sys.executable, "-c", script, "--flag"], input=stdin,
                              capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, check=False)

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
