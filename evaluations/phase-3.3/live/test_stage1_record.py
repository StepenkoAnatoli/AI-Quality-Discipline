"""Rehearsal cases for the Stage 1 record contract (STAGE1-RECORD.md; review 2026-11-26, finding 3).

Synthetic records only: no model, no network, no private task material. Each case is one situation the contract
must resolve the same way before and after Stage 1 runs."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage1_record as s1  # noqa: E402

SCOPE = s1.SCOPE_REASON


def run(run_id, block, group, task="H4", tier="hard", kind="paired", rep=1, replaces=None):
    r = {"run_id": run_id, "block": block, "task": task, "tier": tier, "group": group, "kind": kind,
         "repetition": rep}
    if replaces:
        r["replaces_block"] = replaces
    return r


def pair(block, task="H4", tier="hard", rep=1, replaces=None, prefix=None):
    p = prefix or block
    return [run(f"{p}-c", block, "control", task, tier, rep=rep, replaces=replaces),
            run(f"{p}-t", block, "treatment", task, tier, rep=rep, replaces=replaces)]


def ok(fully=True, timed_out=False, scope=False, tokens=1000, invoked=False, loaded=False, before=None):
    return {"results": {"recorded": True, "valid": True, "invalid_reasons": [], "timed_out": timed_out,
                        "scope_violation": scope, "arm_matches": True, "invoked": invoked, "loaded": loaded,
                        "total_tokens": None if timed_out else tokens,
                        "tokens_missing_reason": "timed_out" if timed_out else None, "duration_seconds": 100},
            "score": {"evaluation_status": "valid", "fully_correct": fully,
                      "hidden_pass_fraction": 1.0 if fully else 0.5},
            "tamper_review": None, "invocation": {"before_first_edit": before}}


def invalid(*reasons):
    return {"results": {"recorded": True, "valid": False, "invalid_reasons": list(reasons), "timed_out": False,
                        "scope_violation": SCOPE in reasons, "arm_matches": True, "total_tokens": 900}}


def done():
    return {"state": "completed"}


class Stage1RecordTests(unittest.TestCase):
    def resolve(self, runs, attempts, blocks):
        return s1.resolve({"runs": runs}, attempts, blocks)

    def slot(self, result, name):
        return next(x for x in result["slots"] if x["slot"] == name)

    def test_a_completed_block_is_scored(self):
        r = self.resolve(pair("b1"), {"b1-c": ok(False), "b1-t": ok(True, invoked=True, loaded=True, before=True)},
                         {"b1": done()})
        self.assertEqual(self.slot(r, "b1:control")["disposition"], "scored")
        self.assertEqual(self.slot(r, "b1:control")["cause"], "wrong_code")
        self.assertIs(self.slot(r, "b1:treatment")["strictly_correct"], True)
        arm = r["summary"]["per_arm"]["treatment"]
        self.assertEqual((arm["invoked"], arm["loaded"], arm["loaded_before_first_edit"]), (1, 1, 1))

    def test_block_cancellation_invalidates_both_runs_and_keeps_the_original_outcome(self):
        # A usage limit hit the treatment run; the control had already finished and passed.
        r = self.resolve(pair("b1"), {"b1-c": ok(True)}, {"b1": {"state": "cancelled", "cause": "usage_limit"}})
        for g in ("control", "treatment"):
            self.assertEqual(self.slot(r, f"b1:{g}")["disposition"], "infrastructure")
            self.assertFalse(self.slot(r, f"b1:{g}")["counted"])
        c = next(a for a in r["attempts"] if a["run_id"] == "b1-c")
        self.assertEqual(c["outcome_before_block_rule"]["fully_correct"], True)
        self.assertEqual(c["failure_cause"], "usage_limit")
        self.assertEqual(r["blocks"]["b1"], "infrastructure_invalid")
        self.assertEqual(r["summary"]["infrastructure_invalid_rate"], 1.0)

    def test_one_infrastructure_failure_invalidates_the_whole_block(self):
        r = self.resolve(pair("b1"), {"b1-c": ok(True), "b1-t": invalid("session ended with a provider/API error (x)")},
                         {"b1": done()})
        self.assertEqual(self.slot(r, "b1:treatment")["cause"], "provider_error")
        self.assertEqual(self.slot(r, "b1:control")["cause"], "block_invalidated:provider_error")
        self.assertFalse(self.slot(r, "b1:control")["counted"])

    def test_replacement_block_supplies_the_slots_and_the_original_is_kept(self):
        runs = pair("b1") + pair("b1r", replaces="b1")
        r = self.resolve(runs, {"b1-c": ok(True), "b1r-c": ok(False), "b1r-t": ok(True)},
                         {"b1": {"state": "cancelled", "cause": "rate_limit"}, "b1r": done()})
        c = self.slot(r, "b1:control")
        self.assertEqual((c["attempts"], c["replaced"], c["counted"]), (["b1-c", "b1r-c"], True, True))
        self.assertIs(c["fully_correct"], False)
        self.assertEqual(len(r["slots"]), 2)
        s = r["summary"]
        self.assertEqual((s["attempts_started_or_cancelled"], s["infrastructure_invalid_attempts"]), (4, 2))
        self.assertTrue(s["infrastructure_limit_exceeded"])

    def test_a_failed_replacement_leaves_the_slot_in_the_bounds(self):
        runs = pair("b1") + pair("b1r", replaces="b1")
        r = self.resolve(runs, {}, {"b1": {"state": "cancelled", "cause": "service_outage"},
                                    "b1r": {"state": "cancelled", "cause": "usage_limit"}})
        self.assertEqual(self.slot(r, "b1:control")["disposition"], "infrastructure")
        self.assertEqual(self.slot(r, "b1:control")["cause"], "usage_limit")

    def test_wrong_code_is_never_replaced(self):
        runs = pair("b1") + pair("b1r", replaces="b1")
        with self.assertRaisesRegex(s1.ContractError, "no rerun for wrong code"):
            self.resolve(runs, {"b1-c": ok(False), "b1-t": ok(False), "b1r-c": ok(True), "b1r-t": ok(True)},
                         {"b1": done(), "b1r": done()})

    def test_one_replacement_per_block(self):
        runs = pair("b1") + pair("b1r", replaces="b1") + pair("b1s", replaces="b1")
        with self.assertRaisesRegex(s1.ContractError, "more than one replacement"):
            self.resolve(runs, {}, {})
        runs = pair("b1") + pair("b1r", replaces="b1") + pair("b1s", replaces="b1r")
        with self.assertRaisesRegex(s1.ContractError, "replaces a replacement"):
            self.resolve(runs, {}, {})

    def test_a_replacement_must_have_the_same_slots(self):
        runs = pair("b1") + pair("b1r", task="H6", replaces="b1")
        with self.assertRaisesRegex(s1.ContractError, "same slots"):
            self.resolve(runs, {}, {})

    def test_a_timeout_is_an_outcome_with_its_token_record_missing(self):
        r = self.resolve(pair("b1"), {"b1-c": ok(True), "b1-t": ok(False, timed_out=True)}, {"b1": done()})
        t = self.slot(r, "b1:treatment")
        self.assertEqual((t["counted"], t["cause"], t["fully_correct"]), (True, "timeout", False))
        arm = r["summary"]["per_arm"]["treatment"]
        self.assertEqual((arm["timeouts"], arm["token_records_missing"]), (1, 1))
        a = next(x for x in r["attempts"] if x["run_id"] == "b1-t")
        self.assertEqual(a["tokens_missing_reason"], "timed_out")

    def test_scope_violation_is_an_agent_failure_in_both_harness_forms(self):
        # Before H2 the harness marks the run invalid; after H2 it is valid and scored on its mutable files.
        r = self.resolve(pair("b1"), {"b1-c": invalid(SCOPE), "b1-t": ok(True, scope=True)}, {"b1": done()})
        c, t = self.slot(r, "b1:control"), self.slot(r, "b1:treatment")
        self.assertEqual((c["disposition"], c["cause"], c["fully_correct"], c["strictly_correct"]),
                         ("agent", "scope_violation", False, False))
        self.assertEqual((t["disposition"], t["cause"], t["fully_correct"], t["strictly_correct"]),
                         ("scored", "scope_violation", True, False))
        self.assertEqual(r["blocks"]["b1"], "resolved")

    def test_scope_violation_with_another_reason_is_unattributed(self):
        r = self.resolve(pair("b1"), {"b1-c": invalid(SCOPE, "no export analysed"), "b1-t": ok(True)},
                         {"b1": done()})
        self.assertEqual(self.slot(r, "b1:control")["disposition"], "unattributed")
        self.assertTrue(self.slot(r, "b1:treatment")["counted"])

    def test_tamper_and_evaluation_states(self):
        conf, susp, bad = ok(True), ok(True), ok(True)
        conf["tamper_review"], susp["tamper_review"] = "confirmed", "suspected"
        bad["score"] = {"evaluation_status": "invalid"}
        runs = pair("b1") + pair("b2", rep=2)
        r = self.resolve(runs, {"b1-c": conf, "b1-t": susp, "b2-c": bad, "b2-t": ok(True)},
                         {"b1": done(), "b2": done()})
        self.assertEqual(self.slot(r, "b1:control")["cause"], "tamper_confirmed")
        self.assertEqual(self.slot(r, "b1:control")["fully_correct"], False)
        self.assertEqual(self.slot(r, "b1:treatment")["disposition"], "unattributed")
        self.assertEqual(self.slot(r, "b2:control")["cause"], "evaluation_invalid")
        self.assertEqual(r["blocks"]["b2"], "resolved")  # an evaluator error is not rerun by running the agent again

    def test_a_control_that_loaded_the_skill_is_an_arm_failure(self):
        r = self.resolve(pair("b1"), {"b1-c": ok(True, loaded=True), "b1-t": ok(True)}, {"b1": done()})
        self.assertEqual(self.slot(r, "b1:control")["cause"], "arm_mismatch")
        self.assertEqual(r["blocks"]["b1"], "infrastructure_invalid")

    def test_stop_leaves_later_blocks_not_run_and_outside_the_rate(self):
        runs = pair("b1") + pair("b2", rep=2)
        r = self.resolve(runs, {"b1-c": ok(True), "b1-t": ok(True)},
                         {"b1": done(), "b2": {"state": "not_started", "cause": "stop"}})
        self.assertEqual(self.slot(r, "b2:control")["disposition"], "not_run")
        s = r["summary"]
        self.assertEqual((s["attempts_started_or_cancelled"], s["not_run_after_stop"]), (2, 2))
        self.assertEqual(s["infrastructure_invalid_rate"], 0.0)

    def test_a_missing_record_in_a_completed_block_is_infrastructure(self):
        r = self.resolve(pair("b1"), {"b1-c": ok(True)}, {"b1": done()})
        self.assertEqual(self.slot(r, "b1:treatment")["cause"], "no_record")
        self.assertEqual(r["blocks"]["b1"], "infrastructure_invalid")

    def test_hard_control_stop_rule_uses_bounds(self):
        runs, attempts, blocks = [], {}, {}
        for i in range(8):
            b = f"k{i}"
            runs.append(run(f"{b}-c", b, "control", task="H4" if i < 4 else "H6", kind="calibration", rep=i))
            blocks[b] = done()
            attempts[f"{b}-c"] = ok(i < 6)
        rule = self.resolve(runs, attempts, blocks)["summary"]["hard_control_stop_rule"]
        self.assertEqual((rule["successes"], rule["decided"], rule["stop_if_all_open_fail"]), (6, True, False))
        attempts["k7-c"] = invalid("launcher stopped at step 'x'")
        attempts["k6-c"] = ok(True)
        rule = self.resolve(runs, attempts, blocks)["summary"]["hard_control_stop_rule"]
        # 7 successes and k7 open: the rule fires under both bounds.
        self.assertEqual((rule["successes"], rule["not_counted"], rule["decided"]), (7, 1, True))
        attempts["k6-c"] = invalid("launcher stopped at step 'x'")
        rule = self.resolve(runs, attempts, blocks)["summary"]["hard_control_stop_rule"]
        self.assertEqual((rule["successes"], rule["not_counted"], rule["decided"]), (6, 2, False))

    def test_contract_violations_are_refused(self):
        with self.assertRaisesRegex(s1.ContractError, "lacks tier"):
            s1.resolve({"runs": [{"run_id": "a", "block": "b", "task": "t", "group": "control", "kind": "paired",
                                  "repetition": 1}]}, {}, {})
        with self.assertRaisesRegex(s1.ContractError, "holds"):
            self.resolve(pair("b1")[:1], {}, {"b1": done()})
        with self.assertRaisesRegex(s1.ContractError, "not in the schedule"):
            self.resolve(pair("b1"), {"zz": ok()}, {"b1": done()})
        with self.assertRaisesRegex(s1.ContractError, "no block event"):
            self.resolve(pair("b1"), {}, {})
        with self.assertRaisesRegex(s1.ContractError, "outside the contract"):
            self.resolve(pair("b1"), {}, {"b1": {"state": "cancelled", "cause": "the agent was slow"}})

    def test_cli_writes_a_versioned_record_or_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            paths = {}
            for name, data in (("s", {"runs": pair("b1")}), ("a", {"b1-c": ok(), "b1-t": ok()}),
                               ("b", {"b1": done()})):
                paths[name] = os.path.join(d, name + ".json")
                with open(paths[name], "w") as h:
                    json.dump(data, h)
            out = os.path.join(d, "out.json")
            cmd = [sys.executable, "-I", s1.__file__, "--schedule", paths["s"], "--attempts", paths["a"],
                   "--blocks", paths["b"], "--out", out]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            with open(out) as h:
                self.assertEqual(json.load(h)["schema"], "aqd-phase-3.3-stage1-record-v1")
            with open(paths["b"], "w") as h:
                json.dump({}, h)
            os.remove(out)
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
