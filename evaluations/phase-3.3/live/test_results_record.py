"""Tests for results_record.py (H1, H6, D3). Synthetic stores only: no network, no credential, no model."""
import hashlib
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
with open(SCHEDULE_PATH, encoding="utf-8") as _h:
    SCHEDULE = json.load(_h)
RUN_STATUS_PY = os.path.join(LIVE, "..", "..", "phase-3.2", "harness", "run_status.py")
RUNS = {(r["task"], r["group"]): r["run_id"] for r in SCHEDULE["runs"]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as h:
        h.write(text)


class ResultsRecordTests(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.store, "sealed"))
        shutil.copyfile(SCHEDULE_PATH, os.path.join(self.store, "sealed", "schedule.json"))
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
        checks = {"group": group, "invoked": treatment, "skill_text_loaded": treatment, "skill_invocations": [],
                  "tool_counts": {"Bash": 4, "Edit": 3}}
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
        self.assertEqual((rec["valid"], rec["scope_violation"], rec["invalid_reasons"]),
                         (False, True, ["immutable files changed or missing"]))
        self.assertFalse(self.run_rec("NEW-04", "control")["scope_violation"])

    def test_a_call_that_did_not_load_the_skill_is_told_apart(self):
        # PILOT-G1-AUDIT.md A1: `invoked` is true for a failed call; `loaded` is the harness's skill_text_loaded.
        self.make("NEW-03", "treatment", checks__skill_text_loaded=False)
        rec = self.run_rec("NEW-03", "treatment")
        self.assertEqual((rec["invoked"], rec["loaded"]), (True, False))
        self.assertEqual(self.run_rec("NEW-02", "treatment")["loaded"], True)

    def test_the_scope_reason_is_the_harness_string(self):
        with open(RUN_STATUS_PY, encoding="utf-8") as h:
            self.assertIn('reasons.append("%s")' % rr.SCOPE_REASON, h.read())

    def test_missing_capture_is_recorded_not_guessed(self):
        shutil.rmtree(self.cap("NEW-03", "treatment"))
        rec = self.run_rec("NEW-03", "treatment")
        self.assertEqual((rec["recorded"], rec["missing_files"]), (False, ["capture"]))
        self.assertNotIn("valid", rec)
        os.makedirs(self.cap("NEW-03", "treatment"))
        rec = self.run_rec("NEW-03", "treatment")
        self.assertEqual((rec["recorded"], rec["missing_files"]), (False, ["run-status.json", "export-checks.json"]))

    def test_a_run_aborted_before_its_export_keeps_its_verdict(self):
        # launch-run-cc.sh finish() writes run-status.json even when it stops at the auth check, before any export.
        self.make("NEW-02", "control", status__valid=False, status__tokens=None,
                  status__invalid_reasons=["api_checks exit 1", "launcher stopped at step 'auth-check'"])
        os.remove(os.path.join(self.cap("NEW-02", "control"), "export-checks.json"))
        rec = self.run_rec("NEW-02", "control")
        self.assertTrue(rec["recorded"])
        self.assertEqual(rec["missing_files"], ["export-checks.json"])
        self.assertEqual((rec["valid"], len(rec["invalid_reasons"])), (False, 2))
        self.assertIsNone(rec["invoked"])
        self.assertIsNone(rec["tool_calls"])

    def test_a_timed_out_run_says_why_its_tokens_are_missing(self):
        self.make("NEW-04", "treatment", status__timed_out=True, status__tokens=None)
        rec = self.run_rec("NEW-04", "treatment")
        self.assertEqual((rec["total_prompt_tokens"], rec["tokens_missing_reason"]), (None, "timed_out"))
        self.make("NEW-04", "treatment", status__tokens=None)
        self.assertEqual(self.run_rec("NEW-04", "treatment")["tokens_missing_reason"], "no usage record")
        self.make("NEW-04", "treatment", status__tokens={"input": 1, "output": 1, "cache_read": 1})
        self.assertEqual(self.run_rec("NEW-04", "treatment")["tokens_missing_reason"], "incomplete usage record")
        self.make("NEW-04", "treatment", status__tokens={"input": 1, "output": None, "cache_read": 1, "cache_write": 1})
        rec = self.run_rec("NEW-04", "treatment")
        self.assertEqual((rec["total_prompt_tokens"], rec["total_tokens"], rec["tokens_missing_reason"]),
                         (3, None, "incomplete usage record"))  # review 2026-11-26, finding 3
        self.make("NEW-04", "treatment")
        rec = self.run_rec("NEW-04", "treatment")
        self.assertIsNone(rec["tokens_missing_reason"])
        self.assertEqual(rec["total_tokens"], 107510)

    def test_a_schedule_other_than_the_sealed_one_is_refused(self):
        with self.assertRaises(ValueError):
            rr.build(self.store, os.path.join(LIVE, "smoke-schedule.json"))
        os.remove(os.path.join(self.store, "sealed", "schedule.json"))
        with self.assertRaises(ValueError):
            self.build()

    def test_retention_hashes(self):
        bundle = os.path.join(self.store, "aqd-cc-live-pilot.tar.gz.gpg")
        with open(bundle, "wb") as h:
            h.write(b"encrypted bytes")
        result = self.build(bundle_path=bundle)
        self.assertEqual(result["bundle_sha256"],
                         hashlib.sha256(b"encrypted bytes").hexdigest())
        self.assertEqual(result["schedule_sha256"],
                         "bad87ea676f335e605bf39afcab82c9b0f9f44cc4482ee883d1b079dd0425f16")
        self.assertIsNone(self.build()["bundle_sha256"])
        with self.assertRaises(OSError):
            self.build(bundle_path=os.path.join(self.store, "absent.gpg"))

    def test_the_record_holds_no_contents(self):
        write(os.path.join(self.cap("NEW-02", "treatment"), "project-final", "secret.py"), "TOKEN=sk-ant-oat01-x")
        self.make("NEW-02", "treatment", unexpected=["secret.py"])
        text = json.dumps(self.build())
        self.assertNotIn("sk-ant", text)
        self.assertIn("secret.py", text)  # names only

    def test_cli(self):
        out = os.path.join(self.store, "results.json")
        self.assertEqual(rr.main(["--store", self.store, "--schedule", SCHEDULE_PATH, "--out", out]), 0)
        with open(out, encoding="utf-8") as h:
            data = json.load(h)
        self.assertEqual(data["schema"], rr.SCHEMA)
        self.assertEqual([r["run_id"] for r in data["runs"]], [r["run_id"] for r in SCHEDULE["runs"]])
        self.assertEqual(rr.main(["--store", self.store, "--schedule", os.path.join(LIVE, "smoke-schedule.json"),
                                  "--out", out]), 2)
        self.assertEqual(rr.main(["--store", self.store, "--schedule", SCHEDULE_PATH, "--out", out,
                                  "--bundle", os.path.join(self.store, "absent.gpg")]), 2)


if __name__ == "__main__":
    unittest.main()
