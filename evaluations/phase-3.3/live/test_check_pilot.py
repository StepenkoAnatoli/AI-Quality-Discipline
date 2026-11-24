"""Tests for check_pilot.py, the G1 invocation pilot verdict. Synthetic stores only: no network, no credential, no
model."""
import json
import os
import shutil
import sys
import tempfile
import unittest

LIVE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIVE)
import check_pilot as cp  # noqa: E402

SCHEDULE = json.load(open(os.path.join(LIVE, "pilot-schedule.json"), encoding="utf-8"))
RUNS = {(r["task"], r["group"]): r["run_id"] for r in SCHEDULE["runs"]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as h:
        h.write(text)


class PilotVerdictTests(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        for (task, group), run in RUNS.items():
            self.make(task, group)

    def tearDown(self):
        shutil.rmtree(self.store)

    def make(self, task, group, **over):
        cap = os.path.join(self.store, "captures", RUNS[(task, group)])
        treatment = group == "treatment"
        status = {"valid": True, "model_ok": True, "activation": "AVAILABLE" if treatment else "NOT_APPLICABLE",
                  "invalid_reasons": [], "timed_out": False, "tokens": {"cache_read": 1}, "duration_seconds": 60,
                  "workspace_findings": {"unexpected": ["tests/test_new.py", ".env"]}}
        checks = {"group": group, "skills_available": ["doctor", "aqd-arm:code-discipline"] if treatment else ["doctor"],
                  "invoked": False, "skill_invocations": [], "tool_counts": {"Bash": 3, "Edit": 2}}
        auth = {"auth_method": "oauth_token", "ok": True}
        for key, value in over.items():
            target, field = key.split("__")
            {"status": status, "checks": checks, "auth": auth}[target][field] = value
        write(os.path.join(cap, "run-status.json"), json.dumps(status))
        write(os.path.join(cap, "export-checks.json"), json.dumps(checks))
        write(os.path.join(cap, "auth-check.json"), json.dumps(auth))

    def verdict(self):
        return cp.check(self.store, SCHEDULE)

    def assertFails(self, needle):
        v = self.verdict()
        self.assertFalse(v["harness_pass"])
        self.assertTrue(any(needle in r for r in v["reasons"]), v["reasons"])

    def test_the_committed_schedule_is_one_pair_per_task(self):
        self.assertEqual(sorted(RUNS), sorted((t, g) for t in cp.TASKS for g in ("control", "treatment")))

    def test_clean_batch_passes_and_measures_invocation(self):
        v = self.verdict()
        self.assertTrue(v["harness_pass"], v["reasons"])
        self.assertEqual(v["invocation"], {"invoked": 0, "valid_treatment_runs": 3,
                                           "by_task": {"NEW-02": False, "NEW-03": False, "NEW-04": False}})
        self.assertEqual(v["runs"][0]["unexpected"], [".env", "tests/test_new.py"])  # recorded, never failed

    def test_invocations_are_counted(self):
        self.make("NEW-03", "treatment", checks__invoked=True, checks__skill_invocations=["code-discipline"])
        self.make("NEW-04", "treatment", checks__invoked=True, checks__skill_invocations=["code-discipline"])
        v = self.verdict()
        self.assertTrue(v["harness_pass"])
        self.assertEqual((v["invocation"]["invoked"], v["invocation"]["valid_treatment_runs"]), (2, 3))

    def test_an_invalid_treatment_run_fails_the_harness_and_leaves_the_invocation_denominator(self):
        self.make("NEW-02", "treatment", status__valid=False, status__invalid_reasons=["x"], checks__invoked=True)
        v = self.verdict()
        self.assertFalse(v["harness_pass"])
        self.assertEqual(v["invocation"]["valid_treatment_runs"], 2)
        self.assertNotIn("NEW-02", v["invocation"]["by_task"])

    def test_model_or_auth_problems_fail(self):
        self.make("NEW-04", "control", status__model_ok=False)
        self.assertFails("model_ok")
        self.make("NEW-04", "control")
        self.make("NEW-02", "control", auth__auth_method="api_key")
        self.assertFails("subscription token")

    def test_wrong_arm_setup_fails(self):
        self.make("NEW-03", "control", checks__skills_available=["doctor", "aqd-arm:code-discipline"])
        self.assertFails("control arm saw or used a skill")
        self.make("NEW-03", "control")
        self.make("NEW-03", "control", checks__invoked=True)
        self.assertFails("control arm saw or used a skill")
        self.make("NEW-03", "control")
        self.make("NEW-04", "treatment", checks__skills_available=["doctor"])
        self.assertFails("treatment arm did not have")
        self.make("NEW-04", "treatment")
        self.make("NEW-02", "control", checks__group="treatment")
        self.assertFails("another arm")

    def test_missing_run_records_and_stop_fail(self):
        shutil.rmtree(os.path.join(self.store, "captures", RUNS[("NEW-03", "control")]))
        self.assertFails("never started")
        self.make("NEW-03", "control")
        os.remove(os.path.join(self.store, "captures", RUNS[("NEW-02", "treatment")], "export-checks.json"))
        self.assertFails("missing or malformed")
        self.make("NEW-02", "treatment")
        write(os.path.join(self.store, "sealed", "STOP"), "ISOLATION FAILURE\n")
        self.assertFails("STOP")

    def test_symlink_or_special_findings_fail(self):
        self.make("NEW-02", "treatment", status__workspace_findings={"special": ["fifo"]})
        self.assertFails("special")

    def test_a_schedule_other_than_the_three_pairs_fails(self):
        bad = json.loads(json.dumps(SCHEDULE))
        bad["runs"][0]["task"] = "NEW-01"
        v = cp.check(self.store, bad)
        self.assertFalse(v["harness_pass"])
        self.assertIsNone(v["invocation"])

    def test_cli(self):
        out = os.path.join(self.store, "pilot-verdict.json")
        sched = os.path.join(LIVE, "pilot-schedule.json")
        self.assertEqual(cp.main(["--store", self.store, "--schedule", sched, "--out", out]), 0)
        self.assertTrue(json.load(open(out))["harness_pass"])
        self.make("NEW-04", "treatment", status__valid=False)
        self.assertEqual(cp.main(["--store", self.store, "--schedule", sched, "--out", out]), 1)


if __name__ == "__main__":
    unittest.main()
