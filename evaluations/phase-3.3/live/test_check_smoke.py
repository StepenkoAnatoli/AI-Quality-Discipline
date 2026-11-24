"""Tests for check_smoke.py, the two-arm SMOKE verdict. Synthetic stores only: no network, no credential, no model."""
import json
import os
import shutil
import sys
import tempfile
import unittest

LIVE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIVE)
import check_smoke as cs  # noqa: E402

SCHEDULE = json.load(open(os.path.join(LIVE, "smoke-schedule.json"), encoding="utf-8"))
RUNS = {r["group"]: r["run_id"] for r in SCHEDULE["runs"]}


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w" if isinstance(data, str) else "wb", **({"encoding": "utf-8"} if isinstance(data, str) else {})) as h:
        h.write(data)


class SmokeVerdictTests(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        for group, run in RUNS.items():
            self.make(run, group)

    def tearDown(self):
        shutil.rmtree(self.store)

    def make(self, run, group, unexpected=(), **over):
        cap = os.path.join(self.store, "captures", run)
        treatment = group == "treatment"
        status = {"valid": True, "model_ok": True, "activation": "AVAILABLE" if treatment else "NOT_APPLICABLE",
                  "invalid_reasons": [], "tokens": {"cache_read": 10, "cache_write": 5}, "duration_seconds": 9,
                  "workspace_findings": {"unexpected": list(unexpected)} if unexpected else {}}
        checks = {"group": group, "skills_available": ["doctor", "aqd-arm:code-discipline"] if treatment else ["doctor"],
                  "invoked": False, "skill_invocations": [], "tool_counts": {"Edit": 1}}
        auth = {"auth_method": "oauth_token", "ok": True, "reasons": []}
        for key, value in over.items():
            target, field = key.split("__")
            {"status": status, "checks": checks, "auth": auth}[target][field] = value
        write(os.path.join(cap, "run-status.json"), json.dumps(status))
        write(os.path.join(cap, "export-checks.json"), json.dumps(checks))
        write(os.path.join(cap, "auth-check.json"), json.dumps(auth))
        write(os.path.join(cap, "project-final", "notes.txt"), "ok\n")
        for name in unexpected:
            write(os.path.join(cap, "project-final", name), "")
        return cap

    def verdict(self):
        return cs.check(self.store, SCHEDULE)

    def assertFails(self, needle):
        v = self.verdict()
        self.assertFalse(v["pass"])
        self.assertTrue(any(needle in r for r in v["reasons"]), v["reasons"])

    def test_the_committed_schedule_is_one_smoke_run_per_arm(self):
        self.assertEqual(sorted(RUNS), ["control", "treatment"])
        self.assertEqual({r["task"] for r in SCHEDULE["runs"]}, {"SMOKE"})

    def test_clean_pair_passes_and_records_cache_tokens(self):
        v = self.verdict()
        self.assertTrue(v["pass"], v["reasons"])
        self.assertFalse(v["placeholders_differ"])
        self.assertEqual([r["tokens"]["cache_read"] for r in v["runs"]], [10, 10])

    def test_treatment_invocation_is_recorded_not_required(self):
        self.make(RUNS["treatment"], "treatment", checks__invoked=True, checks__skill_invocations=["code-discipline"])
        v = self.verdict()
        self.assertTrue(v["pass"], v["reasons"])
        self.assertTrue([r for r in v["runs"] if r["group"] == "treatment"][0]["invoked"])

    def test_invalid_run_fails(self):
        self.make(RUNS["control"], "control", status__valid=False, status__invalid_reasons=["x"])
        self.assertFails("run invalid")

    def test_model_not_ok_fails(self):
        self.make(RUNS["treatment"], "treatment", status__model_ok=False)
        self.assertFails("model_ok")

    def test_not_subscription_auth_fails(self):
        self.make(RUNS["control"], "control", auth__auth_method="api_key")
        self.assertFails("subscription token")

    def test_control_with_a_skill_fails(self):
        self.make(RUNS["control"], "control", checks__skills_available=["doctor", "aqd-arm:code-discipline"])
        self.assertFails("control arm saw or used a skill")

    def test_control_invoking_a_skill_fails(self):
        self.make(RUNS["control"], "control", checks__invoked=True)
        self.assertFails("control arm saw or used a skill")

    def test_treatment_without_the_skill_fails(self):
        self.make(RUNS["treatment"], "treatment", checks__skills_available=["doctor"])
        self.assertFails("treatment arm did not have")

    def test_treatment_with_an_extra_skill_fails(self):
        self.make(RUNS["treatment"], "treatment",
                  checks__skills_available=["doctor", "aqd-arm:code-discipline", "other"])
        self.assertFails("treatment arm did not have")

    def test_wrong_arm_in_the_records_fails(self):
        self.make(RUNS["control"], "control", checks__group="treatment")
        self.assertFails("another arm")

    def test_notes_must_read_exactly_ok(self):
        for text in ("pending\n", "ok\nok\n", "OK\n", " ok\n", ""):
            with self.subTest(text=text):
                cap = self.make(RUNS["control"], "control")
                write(os.path.join(cap, "project-final", "notes.txt"), text)
                self.assertFails("notes.txt")
        cap = self.make(RUNS["control"], "control")
        write(os.path.join(cap, "project-final", "notes.txt"), "ok")
        self.assertTrue(self.verdict()["pass"])

    def test_missing_run_fails(self):
        shutil.rmtree(os.path.join(self.store, "captures", RUNS["control"]))
        self.assertFails("never started")

    def test_missing_records_fail(self):
        os.remove(os.path.join(self.store, "captures", RUNS["treatment"], "auth-check.json"))
        self.assertFails("missing or malformed")

    def test_stop_file_fails(self):
        write(os.path.join(self.store, "sealed", "STOP"), "ISOLATION FAILURE\n")
        self.assertFails("STOP")

    def test_known_empty_placeholders_pass_and_an_arm_difference_is_flagged_only(self):
        self.make(RUNS["treatment"], "treatment", unexpected=sorted(cs.PLACEHOLDERS))
        v = self.verdict()
        self.assertTrue(v["pass"], v["reasons"])
        self.assertTrue(v["placeholders_differ"])
        self.make(RUNS["control"], "control", unexpected=sorted(cs.PLACEHOLDERS))
        self.assertFalse(self.verdict()["placeholders_differ"])

    def test_unknown_unexpected_file_fails(self):
        self.make(RUNS["control"], "control", unexpected=[".env", "notes.bak"])
        self.assertFails("outside the known placeholders")

    def test_nonempty_placeholder_fails(self):
        cap = self.make(RUNS["treatment"], "treatment", unexpected=[".env"])
        write(os.path.join(cap, "project-final", ".env"), "SECRET=1\n")
        self.assertFails("not empty")

    def test_symlink_or_special_findings_fail(self):
        self.make(RUNS["control"], "control", status__workspace_findings={"symlink": ["x"]})
        self.assertFails("symlink")

    def test_a_schedule_other_than_one_smoke_pair_fails(self):
        bad = json.loads(json.dumps(SCHEDULE))
        bad["runs"][0]["group"] = bad["runs"][1]["group"]
        v = cs.check(self.store, bad)
        self.assertFalse(v["pass"])
        bad = json.loads(json.dumps(SCHEDULE))
        bad["runs"][0]["task"] = "PROBE-CC"
        self.assertFalse(cs.check(self.store, bad)["pass"])

    def test_cli_writes_the_verdict_and_exit_codes(self):
        out = os.path.join(self.store, "smoke-verdict.json")
        sched = os.path.join(LIVE, "smoke-schedule.json")
        self.assertEqual(cs.main(["--store", self.store, "--schedule", sched, "--out", out]), 0)
        self.assertTrue(json.load(open(out))["pass"])
        self.make(RUNS["control"], "control", status__valid=False)
        self.assertEqual(cs.main(["--store", self.store, "--schedule", sched, "--out", out]), 1)


if __name__ == "__main__":
    unittest.main()
