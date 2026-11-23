"""Tests for check_boundary.py. The committed real-CLI results are the positive fixture.

    python3 -m unittest discover -s evaluations/phase-3.3/boundary -p "test_check_boundary.py" -v
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_boundary  # noqa: E402

RESULTS = os.path.join(HERE, "results-2026-11-23")


def load():
    return {label: json.load(open(os.path.join(RESULTS, label, "summary.json"), encoding="utf-8"))
            for label in ("privileged", "unprivileged")}


class CheckBoundaryTests(unittest.TestCase):
    def check(self, data):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        for label, reports in data.items():
            os.makedirs(os.path.join(tmp, label))
            with open(os.path.join(tmp, label, "summary.json"), "w", encoding="utf-8") as h:
                json.dump(reports, h)
        return check_boundary.main(tmp)

    def mutate(self, label, session, fn):
        data = copy.deepcopy(load())
        fn(next(r for r in data[label] if r["session"] == session))
        return self.check(data)

    def test_the_committed_results_pass(self):
        self.assertEqual(self.check(load()), 0)

    def test_any_canary_exposure_fails(self):
        for key in ("canary_in_transcript", "canary_in_requests_to_model", "canary_in_stderr"):
            with self.subTest(key=key):
                self.assertEqual(self.mutate("privileged", "treatment-scrub", lambda r: r.update({key: True})), 1)
        self.assertEqual(self.mutate("privileged", "control-scrub",
                                     lambda r: r["probes"]["read_proc_self_environ"].update(canary=True)), 1)

    def test_token_visible_to_bash_with_the_scrub_fails(self):
        def leak(r):
            r["probes"]["bash_proc_environ"]["output"] = "proc_environ_total=2 readable=2 with_token=1"
        self.assertEqual(self.mutate("privileged", "treatment-scrub", leak), 1)

    def test_an_insensitive_probe_fails(self):
        def blind(r):
            r["probes"]["bash_proc_environ"]["output"] = "proc_environ_total=6 readable=2 with_token=0"
        self.assertEqual(self.mutate("privileged", "treatment-noscrub", blind), 1)

    def test_a_file_tool_that_returns_proc_environ_fails(self):
        self.assertEqual(self.mutate("privileged", "treatment-scrub",
                                     lambda r: r["probes"]["grep_proc_self_environ"].update(is_error=False)), 1)

    def test_an_undetected_sandbox_failure_fails(self):
        def undetected(r):
            r["checks"]["invalid_reasons"] = [check_boundary.NOT_ANTHROPIC]
        self.assertEqual(self.mutate("unprivileged", "treatment-scrub", undetected), 1)

    def test_skill_delivery_failures_fail(self):
        self.assertEqual(self.mutate("privileged", "treatment-scrub",
                                     lambda r: r["checks"].update(skills_available=["doctor"])), 1)
        self.assertEqual(self.mutate("privileged", "control-scrub", lambda r: r["probes"]["skill_invoke"].update(
            output="Launching skill: code-discipline")), 1)

    def test_malformed_results_fail(self):
        data = load()
        data["privileged"] = {"not": "a list"}
        self.assertEqual(self.check(data), 1)
        data = load()
        data["privileged"][0] = "not an object"
        self.assertEqual(self.check(data), 1)
        for key in ("probes", "live_probe_check", "diagnostics", "checks"):
            with self.subTest(dropped=key):
                self.assertEqual(self.mutate("privileged", "treatment-scrub", lambda r: r.pop(key)), 1)
        for probe in ("live_probe", "edit_project", "read_proc_self_environ"):
            with self.subTest(probe=probe):
                self.assertEqual(self.mutate("privileged", "control-scrub", lambda r: r["probes"].pop(probe)), 1)
        self.assertEqual(self.mutate("privileged", "control-scrub",
                                     lambda r: r["probes"]["bash_env"].pop("output")), 1)

    def test_the_live_probe_verdict_is_required(self):
        self.assertEqual(self.mutate("privileged", "treatment-scrub",
                                     lambda r: r["live_probe_check"].update(**{"pass": False})), 1)
        self.assertEqual(self.mutate("privileged", "treatment-noscrub",
                                     lambda r: r["live_probe_check"].update(exposure=False)), 1)
        self.assertEqual(self.mutate("unprivileged", "treatment-scrub",
                                     lambda r: r["live_probe_check"].update(**{"pass": True})), 1)

    def test_missing_or_duplicated_sessions_fail(self):
        data = load()
        data["privileged"] = [r for r in data["privileged"] if r["session"] != "timeout"]
        self.assertEqual(self.check(data), 1)
        data = load()
        data["unprivileged"].append(copy.deepcopy(data["unprivileged"][0]))
        self.assertEqual(self.check(data), 1)


if __name__ == "__main__":
    unittest.main()
