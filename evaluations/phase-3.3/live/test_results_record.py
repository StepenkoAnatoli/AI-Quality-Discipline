"""Tests for results_record.py (H1, H6, D3). Synthetic stores only: no network, no credential, no model."""
import json
import os
import shutil
import sys
import tempfile
import unittest

LIVE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIVE)
import check_smoke  # noqa: E402
import results_record as rr  # noqa: E402

SCHEDULE_PATH = os.path.join(LIVE, "pilot-schedule.json")
SCHEDULE = json.load(open(SCHEDULE_PATH, encoding="utf-8"))
RUNS = {(r["task"], r["group"]): r["run_id"] for r in SCHEDULE["runs"]}
SHA = "a" * 64


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as h:
        h.write(text)


class ResultsRecordTests(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        for task, group in RUNS:
            self.make(task, group)

    def tearDown(self):
        shutil.rmtree(self.store)

    def cap(self, task, group):
        return os.path.join(self.store, "captures", RUNS[(task, group)])

    def make(self, task, group, unexpected=None, **over):
        cap = self.cap(task, group)
        treatment = group == "treatment"
        status = {"valid": True, "model_ok": True, "activation": "AVAILABLE" if treatment else "NOT_APPLICABLE",
                  "invalid_reasons": [], "timed_out": False, "duration_seconds": 99,
                  "tokens": {"input": 10, "output": 500, "cache_read": 100000, "cache_write": 7000},
                  "workspace_findings": {"unexpected": sorted(check_smoke.PLACEHOLDERS) if unexpected is None
                                         else unexpected}}
        checks = {"group": group, "invoked": treatment, "skill_invocations": [], "tool_counts": {"Bash": 4, "Edit": 3}}
        for key, value in over.items():
            target, field = key.split("__")
            {"status": status, "checks": checks}[target][field] = value
        write(os.path.join(cap, "run-status.json"), json.dumps(status))
        write(os.path.join(cap, "export-checks.json"), json.dumps(checks))
        for name in check_smoke.PLACEHOLDERS:
            write(os.path.join(cap, "project-final", name), "")

    def build(self, **kw):
        return rr.build(self.store, SCHEDULE_PATH, **kw)

    def run_rec(self, task, group, result=None):
        result = result or self.build()
        return next(r for r in result["runs"] if r["run_id"] == RUNS[(task, group)])

    def test_placeholder_names_match_the_smoke_record(self):
        self.assertEqual(rr.PLACEHOLDERS, check_smoke.PLACEHOLDERS)
        self.assertEqual(len(rr.PLACEHOLDERS), 17)

    def test_zero_byte_placeholders_are_excluded_and_other_files_listed(self):
        self.make("NEW-02", "treatment", unexpected=sorted(check_smoke.PLACEHOLDERS) + ["tests/test_new.py"])
        rec = self.run_rec("NEW-02", "treatment")
        self.assertEqual(rec["unexpected_files"], ["tests/test_new.py"])
        self.assertEqual((rec["unexpected_file_count"], rec["placeholders_excluded"]), (1, 17))
        self.assertEqual(rec["placeholders_not_empty"], [])

    def test_a_non_empty_or_missing_placeholder_stays_unexpected(self):
        write(os.path.join(self.cap("NEW-03", "control"), "project-final", "package.json"), "{}")
        os.remove(os.path.join(self.cap("NEW-03", "control"), "project-final", ".npmrc"))
        rec = self.run_rec("NEW-03", "control")
        self.assertEqual(rec["placeholders_not_empty"], [".npmrc", "package.json"])
        self.assertEqual(rec["unexpected_files"], [".npmrc", "package.json"])
        self.assertEqual(rec["placeholders_excluded"], 15)

    def test_a_symlinked_placeholder_is_not_excluded(self):
        target = os.path.join(self.cap("NEW-04", "control"), "project-final", ".env")
        os.remove(target)
        os.symlink("/dev/null", target)
        self.assertEqual(self.run_rec("NEW-04", "control")["placeholders_not_empty"], [".env"])

    def test_a_zero_size_special_file_placeholder_is_not_excluded(self):
        target = os.path.join(self.cap("NEW-04", "control"), "project-final", "yarn.lock")
        os.remove(target)
        os.mkfifo(target)  # size 0, but not a regular file
        self.assertEqual(self.run_rec("NEW-04", "control")["placeholders_not_empty"], ["yarn.lock"])

    def test_total_prompt_tokens_is_cache_invariant_and_never_partial(self):
        self.assertEqual(self.run_rec("NEW-02", "control")["total_prompt_tokens"], 107010)
        self.make("NEW-02", "control", status__tokens={"input": 107010, "output": 500, "cache_read": 0,
                                                       "cache_write": 0})
        self.assertEqual(self.run_rec("NEW-02", "control")["total_prompt_tokens"], 107010)
        self.make("NEW-02", "control", status__tokens={"input": 10, "output": 500, "cache_read": None,
                                                       "cache_write": 7000})
        self.assertIsNone(self.run_rec("NEW-02", "control")["total_prompt_tokens"])
        self.make("NEW-02", "control", status__tokens={"input": True, "output": 1, "cache_read": 1, "cache_write": 1})
        self.assertIsNone(self.run_rec("NEW-02", "control")["total_prompt_tokens"])

    def test_scope_violation_and_validity_are_recorded(self):
        self.make("NEW-04", "treatment", status__valid=False,
                  status__invalid_reasons=["immutable files changed or missing"])
        rec = self.run_rec("NEW-04", "treatment")
        self.assertEqual((rec["valid"], rec["scope_violation"], rec["invalid_reason_count"]), (False, True, 1))
        self.assertFalse(self.run_rec("NEW-04", "control")["scope_violation"])

    def test_missing_capture_is_recorded_not_guessed(self):
        shutil.rmtree(self.cap("NEW-03", "treatment"))
        rec = self.run_rec("NEW-03", "treatment")
        self.assertEqual((rec["recorded"], rec["missing"]), (False, "capture"))
        self.assertNotIn("valid", rec)

    def test_retention_hashes(self):
        result = self.build(bundle_sha256=SHA)
        self.assertEqual(result["bundle_sha256"], SHA)
        self.assertEqual(result["schedule_sha256"],
                         "bad87ea676f335e605bf39afcab82c9b0f9f44cc4482ee883d1b079dd0425f16")
        with self.assertRaises(ValueError):
            self.build(bundle_sha256="A" * 64)
        self.assertIsNone(self.build()["bundle_sha256"])

    def test_the_record_holds_no_contents(self):
        write(os.path.join(self.cap("NEW-02", "treatment"), "project-final", "secret.py"), "TOKEN=sk-ant-oat01-x")
        self.make("NEW-02", "treatment", unexpected=["secret.py"])
        text = json.dumps(self.build())
        self.assertNotIn("sk-ant", text)
        self.assertIn("secret.py", text)  # names only

    def test_cli(self):
        out = os.path.join(self.store, "results.json")
        self.assertEqual(rr.main(["--store", self.store, "--schedule", SCHEDULE_PATH, "--out", out,
                                  "--bundle-sha256", SHA]), 0)
        with open(out, encoding="utf-8") as h:
            data = json.load(h)
        self.assertEqual(data["schema"], rr.SCHEMA)
        self.assertEqual([r["run_id"] for r in data["runs"]], [r["run_id"] for r in SCHEDULE["runs"]])
        self.assertEqual(rr.main(["--store", self.store, "--schedule", SCHEDULE_PATH, "--out", out,
                                  "--bundle-sha256", "nothex"]), 2)


if __name__ == "__main__":
    unittest.main()
