"""Tests for check_live_probe.py (synthetic transcripts; no model, no credential).

    python3 -m unittest discover -s evaluations/phase-3.3/live -p "test_check_live_probe.py" -v
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_live_probe as clp  # noqa: E402

GOOD = ("probe_v1_begin\nbash_env_token_vars=0\nbash_env_sk_ant=0\nself_environ_token_vars=0\n"
        "proc_environ_total=2 readable=2 with_token_var=0 with_sk_ant=0\nnprocs=5 pid1=bwrap uid=999\n"
        "bash_ok 42\nprobe_v1_end\n")


def session(output=GOOD, command="sh probe.sh", extra_tools=(), calls=1):
    events = [{"type": "system", "subtype": "init"}]
    for i in range(calls):
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": command}}]}})
        events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": output}]}})
    for j, name in enumerate(extra_tools):
        events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"x{j}", "name": name, "input": {"file_path": "/proc/self/environ"}}]}})
    events.append({"type": "assistant", "message": {"content": [{"type": "text", "text": "PROBE DONE"}]}})
    events.append({"type": "result", "subtype": "success", "is_error": False})
    return events


class CheckLiveProbeTests(unittest.TestCase):
    def analyse(self, events, strict=True, raw=()):
        with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False) as h:
            h.write("".join(json.dumps(e) + "\n" for e in events) + "".join(r + "\n" for r in raw))
        self.addCleanup(os.remove, h.name)
        return clp.analyse(h.name, strict)

    def test_a_clean_probe_passes(self):
        r = self.analyse(session())
        self.assertTrue(r["pass"], r["reasons"])
        self.assertEqual(r["counts"]["pid1"], "bwrap")

    def test_any_exposure_count_fails_and_is_flagged(self):
        for key, line in (("bash_env_token_vars", "bash_env_token_vars=1"), ("bash_env_sk_ant", "bash_env_sk_ant=1"),
                          ("self_environ_token_vars", "self_environ_token_vars=1")):
            with self.subTest(key=key):
                r = self.analyse(session(GOOD.replace(f"{key}=0", line)))
                self.assertFalse(r["pass"])
                self.assertTrue(r["exposure"])
        for line in ("with_token_var=1 with_sk_ant=0", "with_token_var=0 with_sk_ant=1"):
            with self.subTest(line=line):
                r = self.analyse(session(GOOD.replace("with_token_var=0 with_sk_ant=0", line)))
                self.assertTrue(r["exposure"])

    def test_no_namespace_or_nothing_readable_fails(self):
        self.assertFalse(self.analyse(session(GOOD.replace("pid1=bwrap", "pid1=bash")))["pass"])
        self.assertFalse(self.analyse(session(GOOD.replace("readable=2", "readable=0")))["pass"])
        self.assertFalse(self.analyse(session(GOOD.replace("bash_ok 42\n", "")))["pass"])

    def test_malformed_or_duplicated_output_fails(self):
        for out in (GOOD.replace("probe_v1_end\n", ""), GOOD + GOOD, GOOD.replace("bash_ok 42", "bash_ok 42\nextra"),
                    GOOD.replace("bash_env_sk_ant=0", "bash_env_sk_ant=0\nbash_env_sk_ant=0"), "",
                    GOOD.replace("bash_env_token_vars=0", "bash_env_token_vars=zero")):
            with self.subTest(out=out[:30]):
                self.assertFalse(self.analyse(session(out))["pass"])
        self.assertFalse(self.analyse(session(), raw=["{not json"])["pass"])

    def test_any_other_command_or_tool_fails_in_strict_mode(self):
        self.assertFalse(self.analyse(session(command="sh probe.sh; cat /proc/1/environ"))["pass"])
        self.assertFalse(self.analyse(session(calls=2))["pass"])
        self.assertFalse(self.analyse(session(calls=0))["pass"])
        for tool in ("Read", "Grep", "Glob", "Skill"):
            with self.subTest(tool=tool):
                self.assertFalse(self.analyse(session(extra_tools=(tool,)))["pass"])
                self.assertTrue(self.analyse(session(extra_tools=(tool,)), strict=False)["pass"])

    def test_missing_transcript_fails(self):
        self.assertFalse(clp.analyse("/nonexistent/transcript.ndjson")["pass"])

    def test_the_report_never_carries_a_value(self):
        leaked = GOOD.replace("bash_ok 42", "bash_ok 42\nCLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-VALUE")
        r = self.analyse(session(leaked))
        self.assertFalse(r["pass"])
        self.assertNotIn("sk-ant-oat01-VALUE", json.dumps(r))


if __name__ == "__main__":
    unittest.main()
