"""Offline tests: scope violations as an outcome (scope policy) and the public results record.

    python -m unittest discover -s evaluations/phase-3.2/tests -p "test_scope_retention.py" -v

No network, no model, no Docker. Synthetic captures only.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "..", "harness")
sys.path.insert(0, HARNESS)
sys.path.insert(0, HERE)

import analyze  # noqa: E402
import difficulty  # noqa: E402
import export_checks  # noqa: E402
import results_record as rr  # noqa: E402
import run_status  # noqa: E402
import schedule  # noqa: E402
import test_harness as th  # noqa: E402  (fixture helpers only; its TestCase classes are not re-collected)

MODEL = "anthropic/claude-opus-5-5#medium"
LAUNCH = os.path.join(HARNESS, "launch-run.sh")
LIB = os.path.join(HARNESS, "lib.sh")


class Capture(th.TempDirTest):
    def write(self, rel, data, root=None):
        path = os.path.join(root or self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as h:
            h.write(data if isinstance(data, str) else json.dumps(data))

    def record(self, group="treatment", **changes):
        record = {"schema_version": 2, "run_id": "r-0123456789", "task": "NEW-02", "group": group, "model": MODEL,
                  "model_provider": "anthropic", "model_id": "claude-opus-5-5", "model_variant": "medium",
                  "interface": "opencode 2.3.2", "activation_mode": "api-attachment",
                  "skill": {"installed": group == "treatment", "sha256": "aa" * 32 if group == "treatment" else None},
                  "prompt_sha256": "bb" * 32, "workspace_sha256": "cc" * 32, "global_config_sha256": "dd" * 32}
        record.update(changes)
        return {k: v for k, v in record.items() if v is not Ellipsis}

    def scenario(self, post, group="treatment", root=None, export=None, **record_changes):
        root = root or self.tmp
        self.write("driver/driver-result.json", {"status": "idle", "session_id": "ses_1"}, root)
        default = {"valid": True, "activation": "CONFIRMED", "tool_counts": {"shell": 3}, "tokens": {},
                   "model_ref": MODEL}
        self.write("export-checks.json", export or default, root)
        self.write("verify-post.json", post, root)
        self.write("home-config-listing.txt", "\n".join(run_status.expected_home_listing(group)) + "\n", root)
        self.write("run-record.json", self.record(group, **record_changes), root)
        return run_status.build_status(root, group, 0, 100, 0, 0, "done")


CLEAN = {"integrity_ok": True, "findings": {"unexpected": []}}
VIOLATED = {"integrity_ok": False, "findings": {"immutable_modified": ["inventory/db.py"], "immutable_missing": [],
                                                "unexpected": ["notes.txt"]}}


class ScopePolicyRunStatusTests(Capture):
    def test_phase_32_records_keep_the_invalidating_rule(self):
        status = self.scenario(VIOLATED)  # no scope_policy in the record: Phase 3.2
        self.assertFalse(status["valid"])
        self.assertEqual(status["invalid_reasons"], ["immutable files changed or missing"])
        self.assertEqual((status["scope_policy"], status["scope_violation"]), ("invalidate", True))
        explicit = self.scenario(VIOLATED, scope_policy="invalidate")
        self.assertEqual(explicit["invalid_reasons"], ["immutable files changed or missing"])

    def test_outcome_policy_keeps_the_run_valid_and_reports_the_violation(self):
        status = self.scenario(VIOLATED, scope_policy="outcome")
        self.assertTrue(status["valid"], status["invalid_reasons"])
        self.assertTrue(status["scope_violation"])
        self.assertEqual(status["scope_findings"], {"immutable_modified": ["inventory/db.py"], "immutable_missing": []})
        self.assertEqual(status["unexpected_files"], ["notes.txt"])

    def test_clean_run_under_outcome_policy(self):
        status = self.scenario(CLEAN, scope_policy="outcome")
        self.assertTrue(status["valid"])
        self.assertFalse(status["scope_violation"])
        self.assertEqual(status["unexpected_files"], [])

    def test_unexpected_files_never_invalidate(self):
        status = self.scenario({"integrity_ok": True, "findings": {"unexpected": ["scratch.py"]}})
        self.assertTrue(status["valid"], status["invalid_reasons"])
        self.assertEqual(status["unexpected_files"], ["scratch.py"])

    def test_unknown_policy_and_unexplained_integrity_failure_are_invalid(self):
        self.assertIn("unknown scope policy", " ".join(self.scenario(CLEAN, scope_policy="lenient")["invalid_reasons"]))
        status = self.scenario({"integrity_ok": False, "findings": {}}, scope_policy="outcome")
        self.assertFalse(status["valid"])
        self.assertIn("without naming the changed files", " ".join(status["invalid_reasons"]))

    def test_other_validity_rules_still_apply_under_outcome_policy(self):
        export = {"valid": False, "invalid_reasons": ["control session contains skill text"], "tool_counts": {},
                  "tokens": {}, "model_ref": MODEL}
        status = self.scenario(VIOLATED, export=export, scope_policy="outcome")
        self.assertFalse(status["valid"])
        self.assertIn("control session contains skill text", status["invalid_reasons"])

    def test_launcher_writes_the_policy_into_every_run_record(self):
        with open(LAUNCH, encoding="utf-8") as h:
            launch = h.read()
        with open(LIB, encoding="utf-8") as h:
            lib = h.read()
        self.assertIn('AQD_SCOPE_POLICY="${AQD_SCOPE_POLICY:-invalidate}"', lib)
        self.assertIn('"scope_policy": scope', launch)
        self.assertIn("scope policy differs from the one used by earlier runs", launch)


class CostTests(unittest.TestCase):
    def export(self, *costs):
        messages = [{"type": "user"}]
        for cost in costs:
            model = {"providerID": "anthropic", "id": "claude-opus-5-5", "variant": "medium"}
            msg = {"type": "assistant", "model": model, "tokens": {"input": 1, "output": 1, "reasoning": 0}}
            if cost is not None:
                msg["cost"] = cost
            messages.append(msg)
        return {"messages": messages}

    def test_reported_costs_are_summed(self):
        report = export_checks.analyse(self.export(0.25, 0.1), "control", MODEL)
        self.assertAlmostEqual(report["cost_usd"], 0.35)
        self.assertEqual(report["cost_messages"], 2)

    def test_absent_cost_is_none_not_zero(self):
        for costs in ((None,), (None, True), (None, -1)):
            report = export_checks.analyse(self.export(*costs), "control", MODEL)
            self.assertIsNone(report["cost_usd"])
            self.assertEqual(report["cost_messages"], 0)


class ScopeAnalysisTests(th.TempDirTest):
    def setUp(self):
        super().setUp()
        self.sched = schedule.make_schedule("34" * 16, [MODEL], ["NEW-02"], 1)
        self.caps = os.path.join(self.tmp, "caps")
        self.scores = os.path.join(self.tmp, "scores")
        self.helper = th.AnalyzeTests("setUp")
        self.helper.caps, self.helper.scores = self.caps, self.scores

    def put(self, run, policy="outcome", violation=False, unexpected=(), fraction=1.0):
        record = self.helper.run_record(run)
        if policy is not None:
            record["scope_policy"] = policy
        self.helper.put(run, record=record, fraction=fraction)
        status = {"valid": True, "invalid_reasons": [], "duration_seconds": 60, "tool_calls": 5, "cost_usd": 0.3}
        if policy is not None:
            status.update(scope_policy=policy, scope_violation=violation, unexpected_files=list(unexpected))
        with open(os.path.join(self.caps, run["run_id"], "run-status.json"), "w", encoding="utf-8") as h:
            json.dump(status, h)

    def runs(self):
        return {r["group"]: r for r in self.sched["runs"]}

    def test_scope_violation_is_an_outcome_and_strict_correctness_drops(self):
        runs = self.runs()
        self.put(runs["control"], violation=True, unexpected=["a.txt", "b.txt"])
        self.put(runs["treatment"])
        rows, problems = analyze.resolve_slots(self.sched, self.caps, self.scores)
        self.assertEqual(problems, [])
        by_group = {r["group"]: r for r in rows}
        self.assertEqual((by_group["control"]["fully_correct"], by_group["control"]["strictly_correct"]), (1.0, 0.0))
        self.assertEqual((by_group["control"]["scope_violation"], by_group["control"]["unexpected_files"]), (1.0, 2.0))
        self.assertEqual(by_group["treatment"]["strictly_correct"], 1.0)
        report = analyze.analyse(rows, problems)
        self.assertEqual(report["scope"]["strictly_correct"][MODEL]["difference_by_task"], {"NEW-02": 1.0})
        self.assertEqual(report["primary"]["fully_correct"][MODEL]["difference_by_task"], {"NEW-02": 0.0})
        self.assertEqual(report["scope"]["scope_violation"][MODEL]["difference_by_task"], {"NEW-02": -1.0})
        self.assertEqual(report["process"]["cost_usd"][MODEL]["difference_by_task"], {"NEW-02": 0.0})

    def test_phase_32_runs_without_scope_fields_still_analyse(self):
        for run in self.sched["runs"]:
            self.put(run, policy=None)
        rows, problems = analyze.resolve_slots(self.sched, self.caps, self.scores)
        self.assertEqual(problems, [])
        self.assertTrue(all(r["scope_violation"] == 0.0 and r["strictly_correct"] == r["fully_correct"] for r in rows))

    def test_mixed_scope_policies_are_never_pooled(self):
        runs = self.runs()
        self.put(runs["control"], policy="invalidate")
        self.put(runs["treatment"], policy="outcome")
        with self.assertRaisesRegex(analyze.AnalysisError, "mix scope policies"):
            analyze.resolve_slots(self.sched, self.caps, self.scores)

    def test_violation_reported_outside_the_outcome_policy_is_an_error(self):
        runs = self.runs()
        self.put(runs["control"], policy="invalidate", violation=True)
        self.put(runs["treatment"], policy="invalidate")
        with self.assertRaisesRegex(analyze.AnalysisError, "outside the 'outcome' policy"):
            analyze.resolve_slots(self.sched, self.caps, self.scores)

    def test_strictly_correct_is_a_plan_outcome(self):
        self.assertIn("strictly_correct", difficulty.OUTCOMES)


class ResultsRecordTests(th.TempDirTest):
    PRIVATE = "hidden_tests.test_new02_hidden.Hidden.test_H07_oversell"

    def setUp(self):
        super().setUp()
        self.sched = schedule.make_schedule("56" * 16, [MODEL], ["NEW-02", "NEW-03"], 1)
        self.caps = os.path.join(self.tmp, "caps")
        self.scores = os.path.join(self.tmp, "scores")
        self.helper = th.AnalyzeTests("setUp")
        self.helper.caps, self.helper.scores = self.caps, self.scores
        self.path = os.path.join(self.tmp, "schedule.json")
        with open(self.path, "w", encoding="utf-8") as h:
            json.dump(self.sched, h)
        runs = self.sched["runs"]
        self.helper.put(runs[0], fraction=0.75)
        self.helper.put(runs[1], valid=False)
        invalid_eval = self.helper.hidden_score(runs[2]["task"], "invalid")
        invalid_eval["invalid_reasons"] = [f"{self.PRIVATE}: required check was skipped"]
        self.helper.put(runs[2], hidden=invalid_eval)
        # runs[3] has no capture at all
        status_path = os.path.join(self.caps, runs[1]["run_id"], "run-status.json")
        with open(status_path, "w", encoding="utf-8") as h:
            reasons = ["session ended with a provider/API error (see x.json)",
                       f"unexpected HOME configuration entries: ['{self.PRIVATE}']"]
            json.dump({"valid": False, "invalid_reasons": reasons}, h)

    def build(self, **kwargs):
        return rr.build(self.path, self.caps, **kwargs)

    def test_record_covers_every_slot_with_codes_and_no_free_text(self):
        record = self.build(encrypted_bundle_sha256="ab" * 32, workflow_run_id=123, harness_commit="d99f29c")
        runs = {r["run_id"]: r for r in record["runs"]}
        sched = self.sched["runs"]
        self.assertEqual(len(record["runs"]), 4)
        first = runs[sched[0]["run_id"]]
        ev = first["evaluation"]
        self.assertEqual((ev["status"], ev["hidden_passed"], ev["hidden_total"], ev["fully_correct"]),
                         ("valid", 3, 4, False))
        self.assertEqual(runs[sched[1]["run_id"]]["run"]["invalid_categories"], ["provider_error", "home_config"])
        self.assertEqual(runs[sched[2]["run_id"]]["evaluation"]["invalid_categories"], ["skip"])
        self.assertEqual(runs[sched[3]["run_id"]]["run"], {"present": False})
        text = json.dumps(record)
        for private in (self.PRIVATE, "test_H07", "hidden_tests", "x.json", "H01"):
            self.assertNotIn(private, text)
        self.assertEqual(record["encrypted_bundle_sha256"], "ab" * 32)

    def test_cli_writes_only_on_success_and_check_accepts_the_output(self):
        out = os.path.join(self.tmp, "record.json")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rr.main(["build", "--schedule", self.path, "--captures", self.caps, "--out", out]), 0)
            self.assertEqual(rr.main(["check", out]), 0)
            bad = os.path.join(self.tmp, "bad.json")
            self.assertEqual(rr.main(["build", "--schedule", self.path, "--captures", self.caps, "--out", bad,
                                      "--encrypted-bundle-sha256", "not-a-hash"]), 3)
        self.assertFalse(os.path.exists(bad))

    def test_check_refuses_private_or_free_text(self):
        record = self.build()
        for value in (self.PRIVATE, "inventory/service.py", "a sentence, with punctuation!", "x" * 101):
            tampered = json.loads(json.dumps(record))
            tampered["runs"][0]["task"] = value
            path = os.path.join(self.tmp, "t.json")
            with open(path, "w", encoding="utf-8") as h:
                json.dump(tampered, h)
            with self.assertRaises(rr.RecordError, msg=value):
                rr.check(path)
        tampered = json.loads(json.dumps(record))
        tampered["runs"][0]["evaluation"]["checks"] = {"ok": "pass"}  # an invented field could carry check names
        path = os.path.join(self.tmp, "t.json")
        with open(path, "w", encoding="utf-8") as h:
            json.dump(tampered, h)
        with self.assertRaisesRegex(rr.RecordError, "not a public record field"):
            rr.check(path)

    def test_inconsistent_score_stray_capture_and_bad_types_are_errors(self):
        run = self.sched["runs"][0]
        hidden_path = os.path.join(self.caps, run["run_id"], "hidden-score.json")
        with open(hidden_path, encoding="utf-8") as h:
            hidden = json.load(h)
        hidden["hidden_passed"] = 4  # contradicts the fraction and the check outcomes
        with open(hidden_path, "w", encoding="utf-8") as h:
            json.dump(hidden, h)
        with self.assertRaises(rr.RecordError):
            self.build()
        self.setUp()
        os.makedirs(os.path.join(self.caps, "r-stray"))
        with self.assertRaisesRegex(rr.RecordError, "belong to no scheduled run"):
            self.build()
        self.setUp()
        status_path = os.path.join(self.caps, self.sched["runs"][0]["run_id"], "run-status.json")
        with open(status_path, "w", encoding="utf-8") as h:
            json.dump({"valid": True, "tool_calls": True}, h)
        with self.assertRaisesRegex(rr.RecordError, "tool_calls"):
            self.build()


if __name__ == "__main__":
    unittest.main()
