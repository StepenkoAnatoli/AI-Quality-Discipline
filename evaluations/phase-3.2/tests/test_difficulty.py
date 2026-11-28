"""Offline tests for difficulty.py (tier analysis) and analyze.py --difficulty-plan.

    python -m unittest discover -s evaluations/phase-3.2/tests -p "test_difficulty.py" -v

No network, no model, no Docker. Synthetic slots only; the committed Phase 3.3
rubric, historical ratings and plan are loaded to pin them.
"""
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "..", "harness")
PHASE33 = os.path.normpath(os.path.join(HERE, "..", "..", "phase-3.3"))
sys.path.insert(0, HARNESS)
sys.path.insert(0, HERE)

import analyze  # noqa: E402
import difficulty as d  # noqa: E402
import schedule  # noqa: E402
import test_harness as th  # noqa: E402  (fixture helpers only; its TestCase classes are not re-collected)

MODEL = "anthropic/claude-opus-5-5#medium"
FACTORS = ["F1", "F2", "F3"]


def rubric():
    anchors = {"0": "a", "1": "b", "2": "c", "3": "d"}
    return {"kind": d.RUBRIC_KIND, "schema_version": 1, "scale": [0, 3],
            "factors": [{"id": f, "weight": 1, "anchors": dict(anchors)} for f in FACTORS],
            "tiers": [{"name": "easy", "max_score": 3}, {"name": "medium", "max_score": 6},
                      {"name": "hard", "max_score": 9, "require_min": {"F3": 2}}]}


def scores(a, b, c):
    return {"F1": a, "F2": b, "F3": c}


def rated(tier_scores, provenance="prospective", task_set="confirmatory", raters=2):
    entry = {"provenance": provenance, "set": task_set, "consensus": tier_scores,
             "raters": [{"rater_id": f"r{i}", "scores": dict(tier_scores)} for i in range(raters)]}
    entry["tier"] = d.tier_for(rubric(), tier_scores)[0]
    return entry


def row(task, group, value, model=MODEL, frac=None):
    return {"model": model, "task": task, "group": group, "run_id": f"{task}-{group}-{value}",
            "fully_correct": float(value), "hidden_pass_fraction": float(value if frac is None else frac)}


def problem(task, group, status="invalid", model=MODEL):
    return {"model": model, "task": task, "group": group, "status": status, "problem": "x"}


def loaded(tasks, status="frozen", sets=("confirmatory",), mid=0.2, harm=0.1):
    return {"plan": {"status": status, "inference_sets": list(sets), "primary_outcome": "fully_correct",
                     "secondary_outcomes": ["hidden_pass_fraction"], "confidence": 0.95, "mid": mid, "harm": harm,
                     "tier_order": ["easy", "medium", "hard"]},
            "rubric_sha256": "00" * 32,
            "tasks": {k: {"tier": v["tier"], "set": v["set"], "provenance": v["provenance"], "agreement": None}
                      for k, v in tasks.items()}}


class TDistributionTests(unittest.TestCase):
    def test_quantiles_match_published_values(self):
        for df, expected in ((1, 12.706205), (3, 3.182446), (5, 2.570582), (10, 2.228139), (30, 2.042272)):
            self.assertAlmostEqual(d.t_quantile(0.975, df), expected, places=5)
        self.assertAlmostEqual(d.t_quantile(0.5, 7), 0.0, places=6)
        self.assertAlmostEqual(d.t_quantile(0.025, 3), -3.182446, places=5)

    def test_extreme_quantiles_are_not_clamped(self):
        self.assertAlmostEqual(d.t_quantile(0.9995, 1), 636.619, places=2)

    def test_rejects_bad_arguments(self):
        for p, df in ((0, 3), (1, 3), (0.5, 0)):
            with self.assertRaises(ValueError):
                d.t_quantile(p, df)


class RubricTests(unittest.TestCase):
    def test_valid_rubric_and_gate_demotes(self):
        r = d.validate_rubric(rubric())
        self.assertEqual(d.tier_for(r, scores(0, 1, 1)), ("easy", 2))
        self.assertEqual(d.tier_for(r, scores(2, 2, 1)), ("medium", 5))
        self.assertEqual(d.tier_for(r, scores(3, 3, 2)), ("hard", 8))
        # Composite 7 is in the hard range, but F3 < 2 fails the hard gate.
        self.assertEqual(d.tier_for(r, scores(3, 3, 1)), ("medium", 7))

    def test_broken_rubrics_are_refused(self):
        def broken(change):
            r = rubric()
            change(r)
            with self.assertRaises(d.DifficultyError):
                d.validate_rubric(r)
        broken(lambda r: r.update(factors=[]))
        broken(lambda r: r.update(scale=[3, 0]))
        broken(lambda r: r["factors"][0]["anchors"].pop("2"))
        broken(lambda r: r["factors"][1].update(id="F1"))
        broken(lambda r: r["factors"][0].update(weight=0))
        broken(lambda r: r["tiers"][1].update(max_score=2))
        broken(lambda r: r["tiers"][2].update(max_score=8))  # does not cover the maximum 9
        broken(lambda r: r["tiers"][2].update(require_min={"F9": 1}))
        broken(lambda r: r["tiers"][2].update(require_min=["F3"]))


class RatingsTests(unittest.TestCase):
    def setUp(self):
        self.r = d.validate_rubric(rubric())

    def ratings(self, **tasks):
        return {"kind": d.RATINGS_KIND, "schema_version": 1, "rubric_sha256": "ab" * 32, "tasks": tasks}

    def refused(self, entry, message):
        with self.assertRaisesRegex(d.DifficultyError, message):
            d.validate_ratings(self.ratings(T=entry), self.r, "ab" * 32)

    def test_valid_ratings_report_agreement(self):
        entry = rated(scores(1, 1, 1))
        entry["raters"][1]["scores"] = scores(1, 2, 0)
        entry["consensus"] = scores(1, 1, 1)
        out = d.validate_ratings(self.ratings(T=entry), self.r, "ab" * 32)
        self.assertEqual(out["T"]["tier"], "easy")
        self.assertEqual(out["T"]["gaps"], {"F1": [0], "F2": [1], "F3": [1]})

    def test_agreement_is_reported_per_factor_so_one_bad_factor_is_visible(self):
        tasks = {}
        for name in ("A", "B"):
            entry = rated(scores(1, 1, 0))
            entry["raters"][1]["scores"] = scores(1, 1, 3)
            entry["consensus"] = scores(1, 1, 0)
            entry["tier"] = d.tier_for(self.r, entry["consensus"])[0]
            tasks[name] = entry
        info = d.validate_ratings(self.ratings(**tasks), self.r, "ab" * 32)
        report = d.analyse([], [], {"plan": loaded({})["plan"] | {"status": "draft"}, "rubric_sha256": "ab" * 32,
                                    "tasks": info})
        by_factor = report["rating_agreement_by_factor"]
        self.assertEqual(by_factor["F1"], {"pairs": 2, "exact": 1.0, "within_one": 1.0})
        self.assertEqual(by_factor["F3"], {"pairs": 2, "exact": 0.0, "within_one": 0.0})

    def test_post_hoc_rating_cannot_be_confirmatory_or_calibration(self):
        for task_set in ("confirmatory", "calibration"):
            self.refused(rated(scores(1, 1, 1), provenance="post_hoc", task_set=task_set), "historical set")

    def test_confirmatory_needs_two_raters(self):
        self.refused(rated(scores(1, 1, 1), raters=1), "two independent raters")

    def test_tier_is_computed_never_overridden(self):
        entry = rated(scores(3, 3, 1))  # computed: medium (gate)
        entry["tier"] = "hard"
        self.refused(entry, "tiers are computed")

    def test_consensus_must_lie_within_the_raters_range(self):
        entry = rated(scores(1, 1, 1))
        entry["consensus"] = scores(2, 1, 1)
        entry["tier"] = d.tier_for(self.r, entry["consensus"])[0]
        self.refused(entry, "outside the raters' range")

    def test_bad_scores_are_refused(self):
        for bad in (scores(True, 1, 1), scores(4, 1, 1), scores(1.0, 1, 1), {"F1": 1, "F2": 1}):
            entry = rated(scores(1, 1, 1))
            entry["raters"][0]["scores"] = bad
            self.refused(entry, "rater r0")

    def test_rubric_hash_must_match(self):
        with self.assertRaisesRegex(d.DifficultyError, "different rubric"):
            d.validate_ratings(self.ratings(T=rated(scores(1, 1, 1))), self.r, "cd" * 32)


class CommittedPlanTests(unittest.TestCase):
    """Pins the committed Phase 3.3 draft files: they load, hash-match and keep the post-hoc labels."""

    def test_historical_plan_loads_and_all_four_tasks_are_post_hoc_and_specified(self):
        out = d.load_plan(os.path.join(PHASE33, "analysis-plan-historical.json"))
        self.assertEqual(out["plan"]["status"], "draft")
        self.assertEqual(sorted(out["tasks"]), ["NEW-01", "NEW-02", "NEW-03", "NEW-04"])
        tiers = {"NEW-01": "medium", "NEW-02": "medium", "NEW-03": "medium", "NEW-04": "hard"}
        for task, info in out["tasks"].items():
            self.assertEqual((info["tier"], info["discovery"], info["set"], info["provenance"]),
                             (tiers[task], "specified", "historical", "post_hoc"))

    def edited_plan(self, change):
        tmp = tempfile.mkdtemp(prefix="aqd-diff-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("difficulty-rubric.json", "ratings-historical.json"):
            shutil.copy(os.path.join(PHASE33, name), tmp)
        with open(os.path.join(PHASE33, "analysis-plan-historical.json"), encoding="utf-8") as h:
            plan = json.load(h)
        change(plan)
        path = os.path.join(tmp, "plan.json")
        with open(path, "w", encoding="utf-8") as h:
            json.dump(plan, h)
        return path

    def test_malformed_plan_fields_are_difficulty_errors_not_crashes(self):
        for change in (lambda p: p.update(secondary_outcomes=5), lambda p: p.update(schema_version=True),
                       lambda p: p.update(confidence=0.9999), lambda p: p.update(ratings="x"),
                       lambda p: p.update(rubric=[])):
            with self.assertRaises(d.DifficultyError):
                d.load_plan(self.edited_plan(change))

    def test_report_records_plan_rubric_and_ratings_hashes(self):
        path = os.path.join(PHASE33, "analysis-plan-historical.json")
        out = d.load_plan(path)
        with open(path, "rb") as h:
            self.assertEqual(out["plan_sha256"], hashlib.sha256(h.read()).hexdigest())
        report = d.analyse([], [], out)
        self.assertEqual((report["plan_sha256"], report["ratings_sha256"]), (out["plan_sha256"], out["ratings_sha256"]))
        self.assertEqual(len(report["ratings_sha256"]), 1)

    def test_plan_refuses_a_rubric_whose_hash_changed(self):
        tmp = tempfile.mkdtemp(prefix="aqd-diff-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("analysis-plan-historical.json", "difficulty-rubric.json", "ratings-historical.json"):
            shutil.copy(os.path.join(PHASE33, name), tmp)
        with open(os.path.join(tmp, "difficulty-rubric.json"), "a", encoding="utf-8") as h:
            h.write("\n")
        with self.assertRaisesRegex(d.DifficultyError, "plan pins"):
            d.load_plan(os.path.join(tmp, "analysis-plan-historical.json"))


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tasks = {"E1": rated(scores(1, 0, 0)), "E2": rated(scores(0, 1, 0)),
                      "H1": rated(scores(3, 3, 3)), "H2": rated(scores(3, 2, 3))}
        self.assertEqual({k: v["tier"] for k, v in self.tasks.items()},
                         {"E1": "easy", "E2": "easy", "H1": "hard", "H2": "hard"})

    def primary(self, report, model=MODEL):
        return report["by_model"][model]["primary:fully_correct"]

    def test_task_is_the_unit_and_repetitions_do_not_add_weight(self):
        # H1: 3 runs per arm, difference 1.0. H2: 1 run per arm, difference 0.0. Tier mean is 0.5, not 0.75.
        rows = [row("H1", "control", 0)] * 3 + [row("H1", "treatment", 1)] * 3
        rows += [row("H2", "control", 1), row("H2", "treatment", 1)]
        rows += [row("E1", "control", 1), row("E1", "treatment", 1), row("E2", "control", 1), row("E2", "treatment", 1)]
        report = d.analyse(rows, [], loaded(self.tasks))
        hard = self.primary(report)["by_tier"]["hard"]
        self.assertEqual(hard["tasks"], 2)
        self.assertEqual(hard["mean_task_difference"], 0.5)
        half = d.t_quantile(0.975, 1) * math.sqrt(0.5) / math.sqrt(2)
        self.assertEqual(hard["ci"], [round(0.5 - half, 4), round(0.5 + half, 4)])
        self.assertEqual(hard["decision"], "inconclusive")

    def test_hidden_check_count_does_not_weight_tasks(self):
        # Secondary outcome: pass fractions are already per task; a task with many checks has no extra weight.
        rows = [row("H1", "control", 0, frac=0.5), row("H1", "treatment", 0, frac=1.0),
                row("H2", "control", 0, frac=0.9), row("H2", "treatment", 0, frac=0.9)]
        report = d.analyse(rows, [], loaded({k: v for k, v in self.tasks.items() if k.startswith("H")}))
        secondary = report["by_model"][MODEL]["secondary:hidden_pass_fraction"]
        self.assertEqual(secondary["by_tier"]["hard"]["mean_task_difference"], 0.25)

    def test_consistent_large_benefit_on_hard_tasks_and_interaction(self):
        rows = []
        for task, (c, t) in {"E1": (1, 1), "E2": (1, 1), "H1": (0, 1), "H2": (0, 1)}.items():
            rows += [row(task, "control", c)] * 2 + [row(task, "treatment", t)] * 2
        tasks = dict(self.tasks, H3=rated(scores(3, 3, 2)))
        rows += [row("H3", "control", 0), row("H3", "treatment", 0.5 * 2), row("H3", "treatment", 0)]
        out = self.primary(d.analyse(rows, [], loaded(tasks)))
        hard = out["by_tier"]["hard"]
        self.assertEqual(hard["tasks"], 3)
        self.assertGreater(hard["ci"][0], 0)
        self.assertEqual(hard["decision"], "benefit")
        easy = out["by_tier"]["easy"]
        self.assertEqual((easy["mean_task_difference"], easy["sd"]), (0.0, 0.0))
        # Both easy tasks are at the ceiling in both arms: not evidence of no effect.
        self.assertEqual(easy["discriminating_tasks"], 0)
        self.assertEqual(easy["decisions"]["observed"], "no_meaningful_effect")
        self.assertEqual(easy["decision"], "inconclusive")
        self.assertIn("ceiling or floor", easy["reason"])
        # The easy tier is at the ceiling, so the interaction cannot be read even though hard shows a benefit.
        inter = out["interaction"]["hard - easy"]
        self.assertGreater(inter["estimate"], 0)
        self.assertEqual(inter["conclusion"], "inconclusive")
        self.assertIn("ceiling or floor", inter["reason"])
        medium = out["by_tier"]["medium"]
        self.assertEqual({k: medium[k] for k in ("tasks", "decision", "missing_tasks", "reason")},
                         {"tasks": 0, "decision": "inconclusive", "missing_tasks": [],
                          "reason": "no task with valid runs in both arms"})

    def test_harm_is_detected(self):
        rows = []
        for task in ("H1", "H2"):
            rows += [row(task, "control", 1)] * 3 + [row(task, "treatment", 0)] * 3
        tasks = dict({k: v for k, v in self.tasks.items() if k.startswith("H")}, H3=rated(scores(3, 3, 2)))
        rows += [row("H3", "control", 1)] * 2 + [row("H3", "treatment", 0), row("H3", "treatment", 1)]
        self.assertEqual(self.primary(d.analyse(rows, [], loaded(tasks)))["by_tier"]["hard"]["decision"], "harm")

    def test_nonvalid_slots_are_carried_into_bounds_and_can_force_inconclusive(self):
        tasks = dict({k: v for k, v in self.tasks.items() if k.startswith("H")}, H3=rated(scores(3, 3, 2)))
        rows = []
        for task in ("H1", "H2"):
            rows += [row(task, "control", 0)] * 2 + [row(task, "treatment", 1)] * 2
        rows += [row("H3", "control", 0)] * 2 + [row("H3", "treatment", 1), row("H3", "treatment", 0)]
        # Valid runs only: differences 1, 1, 0.5 -> benefit.
        clean = self.primary(d.analyse(rows, [], loaded(tasks)))["by_tier"]["hard"]
        self.assertEqual(clean["decision"], "benefit")
        # Two H3 treatment slots excluded (for example tamper-flagged or a crashed evaluation) are imputed as
        # failures in the worst case and successes in the best case; the benefit does not survive.
        excluded = [problem("H3", "treatment", "excluded"), problem("H3", "treatment", "invalid")]
        out = self.primary(d.analyse(rows, excluded, loaded(tasks)))
        h3 = out["by_task"]["H3"]
        self.assertEqual(h3["nonvalid"], {"control": 0, "treatment": 2})
        self.assertEqual(h3["difference"], 0.5)
        self.assertEqual(h3["bounds"], [0.25, 0.75])
        hard = out["by_tier"]["hard"]
        self.assertEqual(hard["decisions"]["observed"], "benefit")
        self.assertNotEqual(hard["decisions"]["worst_case"], "benefit")
        self.assertFalse(hard["robust_to_nonvalid"])
        self.assertEqual(hard["decision"], "inconclusive")
        self.assertIn("imputed", hard["reason"])

    def test_zero_spread_interval_is_degenerate_not_precise(self):
        rows = []
        for task in ("H1", "H2"):
            rows += [row(task, "control", 1), row(task, "control", 0),
                     row(task, "treatment", 1), row(task, "treatment", 0)]
        hard_tasks = {k: v for k, v in self.tasks.items() if k.startswith("H")}
        hard = self.primary(d.analyse(rows, [], loaded(hard_tasks)))["by_tier"]["hard"]
        self.assertEqual((hard["sd"], hard["ci"]), (0.0, [0.0, 0.0]))
        self.assertEqual(hard["decision"], "inconclusive")
        self.assertIn("degenerate", hard["reason"])

    def test_task_with_only_nonvalid_treatment_still_gets_worst_case_bound(self):
        rows = [row("H1", "control", 1), row("H1", "control", 1)]
        out = self.primary(d.analyse(rows, [problem("H1", "treatment"), problem("H1", "treatment")],
                                     loaded({"H1": self.tasks["H1"]})))
        self.assertIsNone(out["by_task"]["H1"]["difference"])
        self.assertEqual(out["by_task"]["H1"]["bounds"], [-1.0, 0.0])

    def test_unrated_task_is_an_error(self):
        with self.assertRaisesRegex(d.DifficultyError, "no difficulty rating"):
            d.analyse([row("X9", "control", 1)], [], loaded(self.tasks))
        with self.assertRaisesRegex(d.DifficultyError, "no difficulty rating"):
            d.analyse([], [problem("X9", "control")], loaded(self.tasks))

    def test_label_is_exploratory_unless_frozen_confirmatory_and_prospective(self):
        rows = [row("E1", "control", 1), row("E1", "treatment", 1)]
        one = {"E1": self.tasks["E1"]}
        # Frozen, confirmatory set, prospective: "estimation" unless the plan records adequate power (see
        # test_frozen_plan_is_labelled_estimation_unless_it_records_adequate_power).
        self.assertEqual(d.analyse(rows, [], loaded(one))["label"], "estimation")
        self.assertEqual(d.analyse(rows, [], loaded(one, status="draft"))["label"], "exploratory")
        self.assertEqual(d.analyse(rows, [], loaded(one, sets=("confirmatory", "calibration")))["label"],
                         "exploratory")

    def test_tasks_outside_the_inference_sets_are_reported_but_not_inferred(self):
        tasks = {"H1": self.tasks["H1"], "C1": rated(scores(3, 3, 3), task_set="calibration")}
        rows = [row("C1", "control", 0), row("C1", "treatment", 1), row("H1", "control", 1), row("H1", "treatment", 1)]
        out = self.primary(d.analyse(rows, [], loaded(tasks)))
        self.assertFalse(out["by_task"]["C1"]["in_inference"])
        self.assertEqual(out["by_tier"]["hard"]["tasks"], 1)
        self.assertEqual(out["by_tier"]["hard"]["mean_task_difference"], 0.0)

    def test_interaction_needs_discriminating_tiers_and_is_never_degenerate(self):
        rows = [row(t, g, 1) for t in self.tasks for g in ("control", "treatment")]
        inter = self.primary(d.analyse(rows, [], loaded(self.tasks)))["interaction"]["hard - easy"]
        self.assertIsNone(inter["ci"])
        self.assertEqual(inter["conclusion"], "inconclusive")

    def test_interaction_direction_must_survive_the_nonvalid_bounds(self):
        tasks = {f"E{i}": rated(scores(0, 0, i % 2)) for i in range(4)}
        tasks.update({f"H{i}": rated(scores(3, 3, 2 + i % 2)) for i in range(4)})
        rows, problems = [], []
        for i in range(4):  # easy: discriminating, no effect, a little spread
            rows += [row(f"E{i}", "control", 1), row(f"E{i}", "control", 0)]
            rows += [row(f"E{i}", "treatment", 1), row(f"E{i}", "treatment", i % 2)]
        for i in range(4):  # hard: control fails (once passes, for spread), one treatment pass, two excluded
            rows += [row(f"H{i}", "control", 0), row(f"H{i}", "control", int(i == 3)), row(f"H{i}", "treatment", 1)]
            problems += [problem(f"H{i}", "treatment", "excluded")] * 2
        inter = self.primary(d.analyse(rows, problems, loaded(tasks)))["interaction"]["hard - easy"]
        self.assertGreater(inter["ci"][0], 0)  # valid runs alone would suggest a larger effect on hard tasks
        self.assertIn("worst_case", inter["bounds"])
        self.assertEqual(inter["conclusion"], "inconclusive")
        self.assertIn("non-valid", inter["reason"])

    def test_clear_interaction_is_reported(self):
        tasks = {f"E{i}": rated(scores(0, 0, i % 2)) for i in range(4)}
        tasks.update({f"H{i}": rated(scores(3, 3, 2 + i % 2)) for i in range(4)})
        rows = []
        for i in range(4):
            rows += [row(f"E{i}", "control", 1), row(f"E{i}", "control", 0)]
            rows += [row(f"E{i}", "treatment", 1), row(f"E{i}", "treatment", 0)] if i % 2 else \
                    [row(f"E{i}", "treatment", 1), row(f"E{i}", "treatment", 1)]
            rows += [row(f"H{i}", "control", 0)] * 2 + [row(f"H{i}", "treatment", 1)] * 2
        rows[-1] = row("H3", "treatment", 0)
        inter = self.primary(d.analyse(rows, [], loaded(tasks)))["interaction"]["hard - easy"]
        self.assertEqual(inter["conclusion"], "effect_larger_in_hard")

    def test_missing_preregistered_task_fails_confirmatory_and_blocks_exploratory_tiers(self):
        rows = []
        for task in ("H1", "H2"):
            rows += [row(task, "control", 0)] * 2 + [row(task, "treatment", 1)] * 2
        tasks = dict({k: v for k, v in self.tasks.items() if k.startswith("H")}, H3=rated(scores(3, 3, 2)))
        with self.assertRaisesRegex(d.DifficultyError, r"no slots: \['H3'\]"):
            d.analyse(rows, [], loaded(tasks))
        report = d.analyse(rows, [], loaded(tasks, status="draft"))
        self.assertEqual(report["by_model"][MODEL]["missing_inference_tasks"], ["H3"])
        hard = self.primary(report)["by_tier"]["hard"]
        self.assertEqual(hard["decisions"]["observed"], "benefit")
        self.assertEqual(hard["decision"], "inconclusive")
        self.assertIn("no slots", hard["reason"])
        with self.assertRaisesRegex(d.DifficultyError, "no slot exists"):
            d.analyse([], [], loaded(tasks))

    def test_non_inferiority_is_reported_separately_from_the_decision(self):
        # The adoption question "can it be on by default without meaningful harm?" needs a non-inferiority
        # result (lower bound > -harm under every imputation); before this, only "harm" (proof of harm) existed.
        tasks = {f"H{i}": rated(scores(3, 3, 2 + i % 2)) for i in range(8)}
        rows = []
        for i in range(8):
            rows += [row(f"H{i}", "control", v) for v in (1, 0, 1, 0)]
            rows += [row(f"H{i}", "treatment", v) for v in ((1, 1, 1, 0) if i < 4 else (1, 0, 1, 0))]
        hard = self.primary(d.analyse(rows, [], loaded(tasks)))["by_tier"]["hard"]
        self.assertEqual(hard["decision"], "inconclusive")  # not a benefit, not "no meaningful effect" ...
        self.assertGreater(hard["ci"][0], -0.1)
        self.assertEqual(hard["non_inferiority"], {"margin": -0.1, "holds": True})  # ... but not harmful
        with_missing = dict(tasks, H9=rated(scores(3, 3, 3)))  # pre-registered, no slots
        hard = self.primary(d.analyse(rows, [], loaded(with_missing, status="draft")))["by_tier"]["hard"]
        self.assertFalse(hard["non_inferiority"]["holds"])
        # One task's treatment slots all non-valid: the worst case can no longer exclude harm.
        problems = [problem("H7", "treatment")] * 4
        rows = [r for r in rows if not (r["task"] == "H7" and r["group"] == "treatment")]
        hard = self.primary(d.analyse(rows, problems, loaded(tasks)))["by_tier"]["hard"]
        self.assertFalse(hard["non_inferiority"]["holds"])
        out = self.primary(d.analyse([row("H0", "control", 1), row("H0", "treatment", 1)], [],
                                     loaded({"H0": tasks["H0"]}, status="draft")))
        self.assertFalse(out["by_tier"]["hard"]["non_inferiority"]["holds"])  # no interval: nothing is shown
        ceiling = [row(t, g, 1) for t in ("H0", "H1") for g in ("control", "treatment")]
        out = self.primary(d.analyse(ceiling, [], loaded({t: tasks[t] for t in ("H0", "H1")})))
        self.assertEqual(out["by_tier"]["hard"]["ci"], None if out["by_tier"]["hard"]["sd"] is None else [0.0, 0.0])
        self.assertFalse(out["by_tier"]["hard"]["non_inferiority"]["holds"])  # ceiling, zero spread: no evidence

    def test_decide(self):
        self.assertEqual(d.decide({"mean": 0.3, "ci": [0.05, 0.55]}, 0.2, 0.1), "benefit")
        self.assertEqual(d.decide({"mean": 0.1, "ci": [0.05, 0.15]}, 0.2, 0.1), "no_meaningful_effect")
        self.assertEqual(d.decide({"mean": 0.1, "ci": [0.01, 0.25]}, 0.2, 0.1), "inconclusive")
        self.assertEqual(d.decide({"mean": -0.3, "ci": [-0.5, -0.1]}, 0.2, 0.1), "harm")
        self.assertEqual(d.decide({"mean": 0.0, "ci": [-0.6, 0.6]}, 0.2, 0.1), "inconclusive")
        self.assertEqual(d.decide({"mean": 0.5, "ci": None}, 0.2, 0.1), "inconclusive")


class IntegrationBase(th.TempDirTest):
    """analyze.py --difficulty-plan over real slot resolution and the committed historical plan."""

    def setUp(self):
        super().setUp()
        self.sched = schedule.make_schedule("12" * 16, [MODEL], ["NEW-01", "NEW-02", "NEW-03", "NEW-04"], 1)
        self.caps = os.path.join(self.tmp, "caps")
        self.scores = os.path.join(self.tmp, "scores")
        self.helper = th.AnalyzeTests("setUp")
        self.helper.caps, self.helper.scores = self.caps, self.scores
        self.path = os.path.join(self.tmp, "schedule.json")
        with open(self.path, "w", encoding="utf-8") as h:
            json.dump(self.sched, h)
        self.out = os.path.join(self.tmp, "report.json")
        self.plan = os.path.join(PHASE33, "analysis-plan-historical.json")

    def run_analyze(self, *extra):
        with redirect_stdout(io.StringIO()) as buf:
            code = analyze.main(["--schedule", self.path, "--captures", self.caps, "--scores", self.scores,
                                 "--out", self.out, *extra])
        return code, buf.getvalue()


class AnalyzeIntegrationTests(IntegrationBase):
    def test_ceiling_result_is_reported_as_inconclusive_not_as_no_effect(self):
        for run in self.sched["runs"]:
            self.helper.put(run, fraction=1.0)
        code, _ = self.run_analyze("--difficulty-plan", self.plan)
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as h:
            report = json.load(h)
        diff = report["difficulty"]
        self.assertEqual(diff["label"], "exploratory")
        self.assertEqual(diff["tiers"]["medium"], ["NEW-01", "NEW-02", "NEW-03"])
        self.assertEqual(diff["tiers"]["hard"], ["NEW-04"])
        self.assertEqual(diff["discovery_levels"], {"specified": ["NEW-01", "NEW-02", "NEW-03", "NEW-04"],
                                                    "discovered": []})
        medium = diff["by_model"][MODEL]["primary:fully_correct"]["by_tier"]["medium"]
        self.assertEqual((medium["tasks"], medium["mean_task_difference"], medium["sd"]), (3, 0.0, 0.0))
        # The ceiling (every run passed in both arms) must never read as "no effect".
        self.assertEqual(medium["decisions"]["observed"], "no_meaningful_effect")
        self.assertEqual(medium["discriminating_tasks"], 0)
        self.assertEqual(medium["decision"], "inconclusive")
        self.assertIn("ceiling or floor", medium["reason"])
        self.assertTrue(all(t["control_mean"] == 1.0 for t in
                            diff["by_model"][MODEL]["primary:fully_correct"]["by_task"].values()))
        for tier in ("easy", "hard"):
            by_tier = diff["by_model"][MODEL]["primary:fully_correct"]["by_tier"]
            self.assertEqual(by_tier[tier]["decision"], "inconclusive")

    def test_bad_plan_is_an_error_with_no_report(self):
        for run in self.sched["runs"]:
            self.helper.put(run)
        bad = os.path.join(self.tmp, "plan.json")
        with open(self.plan, encoding="utf-8") as h:
            plan = json.load(h)
        plan["rubric"]["sha256"] = "00" * 32
        plan["rubric"]["path"] = os.path.join(PHASE33, "difficulty-rubric.json")
        plan["ratings"][0]["path"] = os.path.join(PHASE33, "ratings-historical.json")
        with open(bad, "w", encoding="utf-8") as h:
            json.dump(plan, h)
        code, output = self.run_analyze("--difficulty-plan", bad)
        self.assertEqual(code, 3)
        self.assertIn("plan pins", output)
        self.assertFalse(os.path.exists(self.out))

    def test_without_the_option_the_report_is_unchanged(self):
        for run in self.sched["runs"]:
            self.helper.put(run)
        code, _ = self.run_analyze()
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as h:
            self.assertNotIn("difficulty", json.load(h))


def scope_violation(task, group, reasons=("immutable files changed or missing",), model=MODEL):
    """A slot exactly as analyze.resolve_slots reports a run that edited a file the prompt forbids."""
    return {"model": model, "task": task, "group": group, "slot": f"{task}-{group}", "status": "invalid",
            "problem": "run invalid: " + "; ".join(reasons),
            "attempts": [{"run_id": f"{task}-{group}", "valid": False, "invalid_reasons": list(reasons)}]}


def tamper(task, group, verdict, model=MODEL, verified=None):
    """An excluded slot as analyze.resolve_slots reports it; tamper_verified means the confirmed verdict names the
    scored code and has a scorer_id."""
    return {"model": model, "task": task, "group": group, "slot": f"{task}-{group}", "run_id": f"{task}-{group}",
            "status": "excluded", "problem": f"tamper review: {verdict}", "review_flags": {},
            "tamper_verified": verdict == "confirmed" if verified is None else verified,
            "attempts": [{"run_id": f"{task}-{group}", "valid": True, "invalid_reasons": []}]}


POWER = {"contrast": "hard - easy", "power": 0.85, "assumed_tasks_per_tier": 2,
         "source": {"path": "power_sim-output.txt", "sha256": "ab" * 32}}


def axis_rubric():
    """F1, F2 intrinsic; F3 requirement discovery (its own axis, never in the tier composite)."""
    r = rubric()
    for f in r["factors"]:
        f["axis"] = "discovery" if f["id"] == "F3" else "intrinsic"
    r["tiers"] = [{"name": "easy", "max_score": 2}, {"name": "medium", "max_score": 4},
                  {"name": "hard", "max_score": 6}]
    r["discovery_levels"] = [{"name": "specified", "max_score": 1}, {"name": "discovered", "max_score": 3}]
    return r


class ReviewDefectRegressionTests(unittest.TestCase):
    """Regression tests for the defects found in the review of 1912c0b (each failed on that commit)."""

    def setUp(self):
        self.hard = {f"H{i:02d}": rated(scores(3, 3, 2 + i % 2)) for i in range(13)}

    def primary(self, report):
        return report["by_model"][MODEL]["primary:fully_correct"]

    # --- P0 1: a tier mostly at the ceiling must not read as "no meaningful effect".
    def test_ceiling_dominated_tier_is_inconclusive_not_no_meaningful_effect(self):
        rows = []
        names = sorted(self.hard)
        for task in names[:10]:  # ten tasks: every run passes in both arms
            rows += [row(task, "control", 1)] * 2 + [row(task, "treatment", 1)] * 2
        # three discriminating tasks: differences +0.5, 0, 0
        rows += [row(names[10], "control", 1), row(names[10], "control", 0)] + [row(names[10], "treatment", 1)] * 2
        for task in names[11:]:
            rows += [row(task, g, v) for g in ("control", "treatment") for v in (1, 0)]
        hard = self.primary(d.analyse(rows, [], loaded(self.hard)))["by_tier"]["hard"]
        self.assertEqual((hard["tasks"], hard["discriminating_tasks"]), (13, 3))
        self.assertEqual(hard["ci"], [-0.0453, 0.1223])  # the interval the review reproduced
        self.assertEqual(hard["decisions"]["observed"], "no_meaningful_effect")
        self.assertEqual(hard["decision"], "inconclusive")
        self.assertIn("ceiling-dominated", hard["reason"])
        self.assertAlmostEqual(hard["discriminating_share"], 3 / 13, places=4)

    def test_discriminating_tier_can_still_conclude_no_meaningful_effect(self):
        # Twelve tasks, all discriminating, differences 0 except two at +0.25 and two at -0.25: a genuine null.
        tasks = {k: v for k, v in sorted(self.hard.items())[:12]}
        treatment = {0: (1, 1, 1, 0), 1: (1, 1, 1, 0), 2: (1, 0, 0, 0), 3: (1, 0, 0, 0)}
        rows = []
        for i, task in enumerate(sorted(tasks)):
            rows += [row(task, "control", v) for v in (1, 0, 1, 0)]
            rows += [row(task, "treatment", v) for v in treatment.get(i, (1, 0, 1, 0))]
        hard = self.primary(d.analyse(rows, [], loaded(tasks)))["by_tier"]["hard"]
        self.assertEqual(hard["discriminating_tasks"], 12)
        self.assertEqual(hard["decision"], "no_meaningful_effect")

    def test_min_discriminating_share_is_a_validated_plan_parameter(self):
        for bad in (0, 1.5, "0.5", True):
            plan = loaded(self.hard)
            plan["plan"]["min_discriminating_share"] = bad
            with self.assertRaises(d.DifficultyError):
                d.check_plan_parameters(plan["plan"], "plan")

    # --- P0 2: the interaction must apply each tier's zero-spread (and share) guard.
    def test_interaction_refuses_a_zero_spread_side(self):
        tasks = {f"E{i}": rated(scores(0, 0, i % 2)) for i in range(4)}
        tasks.update({f"H{i}": rated(scores(3, 3, 2 + i % 2)) for i in range(4)})
        rows = []
        for i in range(4):  # easy: every task discriminates, every difference is exactly 0 -> zero spread
            rows += [row(f"E{i}", g, v) for g in ("control", "treatment") for v in (1, 0)]
            rows += [row(f"H{i}", "control", 0)] * 2 + [row(f"H{i}", "treatment", 1)] * 2
        rows[-1] = row("H3", "treatment", 0)
        out = self.primary(d.analyse(rows, [], loaded(tasks)))
        self.assertIn("degenerate", out["by_tier"]["easy"]["reason"])
        inter = out["interaction"]["hard - easy"]
        self.assertEqual(inter["conclusion"], "inconclusive")
        self.assertIn("zero spread", inter["reason"])

    def test_interaction_refuses_a_ceiling_dominated_side(self):
        tasks = {f"E{i:02d}": rated(scores(0, 0, i % 2)) for i in range(10)}
        tasks.update({f"H{i}": rated(scores(3, 3, 2 + i % 2)) for i in range(4)})
        rows = []
        for i in range(10):
            if i < 2:  # two easy tasks discriminate, a little spread; eight are at the ceiling
                rows += [row(f"E{i:02d}", "control", 1), row(f"E{i:02d}", "control", 0)]
                rows += [row(f"E{i:02d}", "treatment", 1), row(f"E{i:02d}", "treatment", i)]
            else:
                rows += [row(f"E{i:02d}", g, 1) for g in ("control", "treatment")] * 2
        for i in range(4):
            rows += [row(f"H{i}", "control", 0)] * 2 + [row(f"H{i}", "treatment", 1), row(f"H{i}", "treatment", i % 2)]
        inter = self.primary(d.analyse(rows, [], loaded(tasks)))["interaction"]["hard - easy"]
        self.assertEqual(inter["conclusion"], "inconclusive")
        self.assertIn("ceiling-dominated", inter["reason"])

    # --- P0 3: agent-caused failures are outcomes (intention to treat); infrastructure stays in the bounds.
    def test_scope_violation_and_confirmed_tamper_count_as_failures_not_as_missing(self):
        tasks = {"H1": self.hard["H00"], "H2": self.hard["H01"]}
        rows = [row("H1", "control", 1), row("H1", "control", 1), row("H1", "treatment", 1),
                row("H2", "control", 1), row("H2", "treatment", 1), row("H2", "treatment", 1)]
        problems = [scope_violation("H1", "treatment"), tamper("H2", "control", "confirmed")]
        out = self.primary(d.analyse(rows, problems, loaded(tasks)))
        h1, h2 = out["by_task"]["H1"], out["by_task"]["H2"]
        self.assertEqual(h1["agent_failures"], {"control": 0, "treatment": 1})
        self.assertEqual(h1["nonvalid"], {"control": 0, "treatment": 0})
        self.assertEqual(h1["difference"], -0.5)
        self.assertEqual(h1["bounds"], [-0.5, -0.5])  # nothing left to impute
        self.assertEqual(h2["agent_failures"], {"control": 1, "treatment": 0})
        self.assertEqual(h2["difference"], 0.5)
        self.assertEqual(out["by_tier"]["hard"]["agent_failures"], {"control": 1, "treatment": 1})

    def test_infrastructure_and_ambiguous_slots_stay_in_the_bounds(self):
        tasks = {"H1": self.hard["H00"]}
        rows = [row("H1", "control", 1), row("H1", "treatment", 1)]
        ambiguous = [problem("H1", "treatment", "invalid"),  # e.g. a provider error
                     tamper("H1", "treatment", "suspected"),  # not confirmed
                     problem("H1", "treatment", "unresolved"), problem("H1", "treatment", "missing"),
                     scope_violation("H1", "treatment", ("immutable files changed or missing", "api_checks exit 1")),
                     dict(problem("H1", "treatment", "invalid"), problem="evaluation invalid: x",
                          attempts=[{"run_id": "r", "valid": True, "invalid_reasons": []}])]
        out = self.primary(d.analyse(rows, ambiguous, loaded(tasks)))["by_task"]["H1"]
        self.assertEqual(out["agent_failures"], {"control": 0, "treatment": 0})
        self.assertEqual(out["nonvalid"], {"control": 0, "treatment": 6})
        for item in ambiguous:
            self.assertEqual(d.attribution(item), "unattributed", item)

    def test_unverified_confirmed_tamper_is_not_attributed(self):
        # A confirmed verdict that does not name the scored code, or has no scorer_id, is not trusted as an outcome.
        item = tamper("H1", "control", "confirmed", verified=False)
        self.assertEqual(d.attribution(item), "unattributed")
        self.assertEqual(d.attribution(dict(item, tamper_verified="yes")), "unattributed")
        self.assertEqual(d.attribution(tamper("H1", "control", "confirmed")), "agent")

    def test_tamper_dependence_is_reported(self):
        # Valid runs identical in both arms; two verified tamper verdicts per task in control decide the result.
        tasks = {k: self.hard[k] for k in sorted(self.hard)[:6]}
        rows, problems = [], []
        for i, task in enumerate(sorted(tasks)):
            for group in ("control", "treatment"):
                rows += [row(task, group, 1), row(task, group, 1 if i % 2 else 0)]
            problems += [tamper(task, "control", "confirmed")] * 2
        hard = self.primary(d.analyse(rows, problems, loaded(tasks)))["by_tier"]["hard"]
        self.assertEqual(hard["decision"], "benefit")
        self.assertEqual(hard["tamper_failures"], {"control": 12, "treatment": 0})
        self.assertNotEqual(hard["decision_if_tamper_slots_were_dropped"], "benefit")
        self.assertTrue(hard["itt_dependent"])

    def test_interaction_reports_itt_dependence(self):
        tasks = {f"E{i}": rated(scores(0, 0, i % 2)) for i in range(6)}
        tasks.update({f"H{i}": rated(scores(3, 3, 2 + i % 2)) for i in range(6)})
        rows, problems = [], []
        easy_treatment = {0: (1, 1), 1: (0, 0)}  # easy differences +0.5, -0.5, 0, 0, 0, 0: no effect, some spread
        for i in range(6):
            rows += [row(f"E{i}", "control", 1), row(f"E{i}", "control", 0)]
            rows += [row(f"E{i}", "treatment", v) for v in easy_treatment.get(i, (1, 0))]
            for group in ("control", "treatment"):  # hard: identical valid runs in both arms
                rows += [row(f"H{i}", group, 1), row(f"H{i}", group, 1 if i % 2 else 0)]
            problems += [scope_violation(f"H{i}", "control")] * 2
        inter = self.primary(d.analyse(rows, problems, loaded(tasks)))["interaction"]["hard - easy"]
        self.assertEqual(inter["conclusion"], "effect_larger_in_hard")
        self.assertEqual(inter["conclusion_if_scope_violations_were_nonvalid"], "inconclusive")
        self.assertTrue(inter["itt_dependent"])

    def test_tamper_is_never_imputed_as_a_success(self):
        tasks = {"H1": self.hard["H00"]}
        rows = [row("H1", "control", 0)]
        out = self.primary(d.analyse(rows, [tamper("H1", "treatment", "confirmed")], loaded(tasks)))
        self.assertEqual(out["by_task"]["H1"]["bounds"], [0.0, 0.0])

    def test_itt_sensitivity_is_reported_when_agent_failures_change_the_decision(self):
        tasks = {k: self.hard[k] for k in ("H00", "H01", "H02", "H03")}
        rows = []
        for i, task in enumerate(sorted(tasks)):
            rows += [row(task, "control", 0), row(task, "treatment", 1), row(task, "treatment", 1 - i % 2)]
        problems = [scope_violation(t, "control") for t in tasks]
        hard = self.primary(d.analyse(rows, problems, loaded(tasks)))["by_tier"]["hard"]
        self.assertEqual(hard["agent_failures"], {"control": 4, "treatment": 0})
        # Counting the control scope violations as failures gives a benefit; treating them as missing would not.
        self.assertEqual(hard["decision"], "benefit")
        self.assertEqual(hard["decision_if_scope_violations_were_nonvalid"], "inconclusive")
        self.assertTrue(hard["itt_dependent"])

    # --- P1: intrinsic difficulty and requirement discovery are separate axes.
    def test_discovery_is_its_own_axis_and_never_moves_the_tier(self):
        r = d.validate_rubric(axis_rubric())
        self.assertEqual(d.tier_for(r, scores(3, 3, 0)), ("hard", 6))  # maximum complexity, full specification
        self.assertEqual(d.tier_for(r, scores(0, 0, 3)), ("easy", 0))  # trivial, but must be discovered
        self.assertEqual(d.discovery_for(r, scores(3, 3, 0)), ("specified", 0))
        self.assertEqual(d.discovery_for(r, scores(0, 0, 3)), ("discovered", 3))

    def test_a_tier_gate_on_a_discovery_factor_is_refused(self):
        r = axis_rubric()
        r["tiers"][2]["require_min"] = {"F3": 2}
        with self.assertRaisesRegex(d.DifficultyError, "discovery"):
            d.validate_rubric(r)
        r = axis_rubric()
        r["factors"][0]["axis"] = "other"
        with self.assertRaises(d.DifficultyError):
            d.validate_rubric(r)

    def test_committed_rubric_separates_the_axes_and_rates_new04_hard_and_specified(self):
        loaded_plan = d.load_plan(os.path.join(PHASE33, "analysis-plan-historical.json"))
        factors = {f["id"]: f["axis"] for f in loaded_plan["rubric"]["factors"]}
        self.assertEqual(factors.pop("F6_requirement_discovery"), "discovery")
        self.assertEqual(set(factors.values()), {"intrinsic"})
        self.assertFalse(any(t.get("require_min") for t in loaded_plan["rubric"]["tiers"]))
        info = loaded_plan["tasks"]
        self.assertEqual({k: (v["tier"], v["discovery"]) for k, v in info.items()},
                         {"NEW-01": ("medium", "specified"), "NEW-02": ("medium", "specified"),
                          "NEW-03": ("medium", "specified"), "NEW-04": ("hard", "specified")})
        self.assertEqual({v["provenance"] for v in info.values()}, {"post_hoc"})

    def test_effect_is_also_reported_by_discovery_level(self):
        r = d.validate_rubric(axis_rubric())
        tasks = {}
        for i in range(3):
            for level, f3 in (("S", 0), ("D", 3)):
                entry = rated(scores(3, 3, f3))
                entry["tier"] = d.tier_for(r, entry["consensus"])[0]
                tasks[f"H{i}{level}"] = dict(entry, discovery=d.discovery_for(r, entry["consensus"])[0])
        plan = loaded(tasks)
        plan["tasks"] = {k: dict(plan["tasks"][k], discovery=v["discovery"]) for k, v in tasks.items()}
        plan["discovery_order"] = ["specified", "discovered"]
        rows = []
        for i in range(3):
            rows += [row(f"H{i}S", g, v) for g in ("control", "treatment") for v in (1, 0)]
            rows += [row(f"H{i}D", "control", 0)] * 2 + [row(f"H{i}D", "treatment", 1), row(f"H{i}D", "treatment", i % 2)]
        out = self.primary(d.analyse(rows, [], plan))
        self.assertEqual(set(out["by_discovery"]), {"specified", "discovered"})
        self.assertIn("discovered - specified", out["discovery_interaction"])

    # --- P2: an estimation stage is never labelled confirmatory.
    def test_frozen_plan_is_labelled_estimation_unless_it_records_adequate_power(self):
        one = {"E1": rated(scores(1, 0, 0))}
        rows = [row("E1", "control", 1), row("E1", "treatment", 1)]
        self.assertEqual(d.analyse(rows, [], loaded(one))["label"], "estimation")
        plan = loaded(one)
        plan["plan"]["purpose"] = "confirmation"
        with self.assertRaisesRegex(d.DifficultyError, "power"):
            d.check_plan_parameters(plan["plan"], "plan")
        plan["plan"]["power"] = dict(POWER, power=0.5)
        with self.assertRaisesRegex(d.DifficultyError, "0.8"):
            d.check_plan_parameters(plan["plan"], "plan")
        plan["plan"]["power"]["power"] = 0.85
        d.check_plan_parameters(plan["plan"], "plan")
        report = d.analyse(rows, [], plan)
        self.assertEqual((report["label"], report["confirmatory_contrast"]), ("confirmatory", "hard - easy"))

    def test_only_the_powered_contrast_is_confirmatory(self):
        tasks = {f"E{i}": rated(scores(0, 0, i % 2)) for i in range(2)}
        tasks.update({f"H{i}": rated(scores(3, 3, 2 + i % 2)) for i in range(2)})
        rows = [row(t, g, 1) for t in tasks for g in ("control", "treatment")]
        plan = loaded(tasks)
        plan["plan"].update(purpose="confirmation", power=dict(POWER))
        out = self.primary(d.analyse(rows, [], plan))
        self.assertEqual(out["interaction"]["hard - easy"]["inference"], "confirmatory")
        self.assertEqual(out["interaction"]["medium - easy"]["inference"], "estimation")
        self.assertEqual({t["inference"] for t in out["by_tier"].values()}, {"estimation"})
        for bad in ("anything", "hard - medium - easy", "easy - hard", ""):
            plan["plan"]["power"] = dict(POWER, contrast=bad)
            with self.assertRaisesRegex(d.DifficultyError, "contrast"):
                d.analyse(rows, [], plan)
        plan["plan"]["power"] = dict(POWER, contrast="hard")  # a tier on its own is a valid contrast
        out = self.primary(d.analyse(rows, [], plan))
        self.assertEqual(out["by_tier"]["hard"]["inference"], "confirmatory")
        self.assertEqual(out["interaction"]["hard - easy"]["inference"], "estimation")
        for broken in ({"source": "power_sim.py"}, {"assumed_tasks_per_tier": 1}, {"assumed_tasks_per_tier": True}):
            plan["plan"]["power"] = dict(POWER, **broken)
            with self.assertRaises(d.DifficultyError):
                d.check_plan_parameters(plan["plan"], "plan")

    def test_load_plan_pins_the_power_source_and_checks_the_assumed_task_count(self):
        tmp = tempfile.mkdtemp(prefix="aqd-power-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("difficulty-rubric.json", "ratings-historical.json"):
            shutil.copy(os.path.join(PHASE33, name), tmp)
        sim = os.path.join(tmp, "sim.txt")
        with open(sim, "w", encoding="utf-8") as h:
            h.write("simulated\n")
        with open(os.path.join(PHASE33, "analysis-plan-historical.json"), encoding="utf-8") as h:
            base = json.load(h)

        def attempt(power):
            plan = dict(base, purpose="confirmation", power=power)
            path = os.path.join(tmp, "plan.json")
            with open(path, "w", encoding="utf-8") as h:
                json.dump(plan, h)
            return d.load_plan(path)

        good = {"contrast": "medium", "power": 0.9, "assumed_tasks_per_tier": 3,
                "source": {"path": "sim.txt", "sha256": hashlib.sha256(b"simulated\n").hexdigest()}}
        self.assertEqual(attempt(good)["plan"]["power"]["contrast"], "medium")  # three historical medium tasks
        with self.assertRaisesRegex(d.DifficultyError, "pins"):
            attempt(dict(good, source={"path": "sim.txt", "sha256": "00" * 32}))
        with self.assertRaisesRegex(d.DifficultyError, "assumed"):
            attempt(dict(good, assumed_tasks_per_tier=4))
        with self.assertRaisesRegex(d.DifficultyError, "assumed"):
            attempt(dict(good, contrast="hard - medium"))  # NEW-04 alone is the hard tier

    # --- P1: calibration feedback to task authors is control-only.
    def test_calibration_feedback_never_contains_treatment_results(self):
        tasks = {"C1": rated(scores(3, 3, 3), task_set="calibration"), "H1": self.hard["H00"]}
        rows = [row("C1", "control", 0), row("C1", "control", 1), row("C1", "treatment", 1),
                row("H1", "control", 1), row("H1", "treatment", 0)]
        problems = [problem("C1", "treatment", "invalid"), scope_violation("C1", "treatment")]
        feedback = d.calibration_feedback(rows, problems, loaded(tasks))
        self.assertEqual(list(feedback["by_model"][MODEL]), ["C1"])  # calibration tasks only
        c1 = feedback["by_model"][MODEL]["C1"]
        self.assertEqual((c1["control_runs"], c1["control_successes"]), (2, 1))
        text = json.dumps(feedback)
        self.assertNotIn("treatment", text.replace("treatment results are withheld", ""))

    # --- P2: future schedules counterbalance which arm runs first; the default design is unchanged.
    def test_counterbalanced_schedule_balances_first_arm_within_task_and_overall(self):
        tasks = ["NEW-01", "NEW-02", "NEW-03", "NEW-04"]
        for seed in ("12" * 16, "ab" * 16, "07" * 16):
            for reps in (1, 2, 3):
                sched = schedule.make_schedule(seed, [MODEL], tasks, reps, counterbalance=True)
                self.assertEqual(schedule.validate(sched), [])
                first = {}
                for run in sched["runs"]:
                    first.setdefault(run["block"], (run["task"], run["group"]))
                firsts = list(first.values())
                treat_first = sum(g == "treatment" for _, g in firsts)
                self.assertLessEqual(abs(2 * treat_first - len(firsts)), 1)
                for task in tasks:
                    n = sum(g == "treatment" for t, g in firsts if t == task)
                    self.assertLessEqual(abs(2 * n - reps), 1, (seed, reps, task))
                self.assertTrue(sched["design"]["counterbalanced"])

    def test_validate_refuses_an_unbalanced_counterbalanced_schedule(self):
        sched = schedule.make_schedule("12" * 16, [MODEL], ["NEW-01", "NEW-02"], 2, counterbalance=True)
        # Make every block treatment-first by swapping the order of the control-first ones.
        by_block = {}
        for run in sched["runs"]:
            by_block.setdefault(run["block"], []).append(run)
        for first, second in by_block.values():
            if first["group"] == "control":
                first["order"], second["order"] = second["order"], first["order"]
        problems = schedule.validate(sched)
        self.assertTrue(any("not balanced" in p or "more than one" in p for p in problems), problems)

    def test_counterbalance_is_balanced_within_each_model(self):
        models = [MODEL, "xai/grok-4"]
        tasks = ["NEW-01", "NEW-02", "NEW-03", "NEW-04"]
        for seed in range(60):
            sched = schedule.make_schedule(f"{seed:032x}", models, tasks, 3, counterbalance=True)
            self.assertEqual(schedule.validate(sched), [])
            first = {}
            for run in sorted(sched["runs"], key=lambda r: r["order"]):
                first.setdefault(run["block"], run)
            for model in models:
                mine = [r for r in first.values() if r["model"] == model]
                treat = sum(r["group"] == "treatment" for r in mine)
                self.assertLessEqual(abs(2 * treat - len(mine)), 1, (seed, model))

    def test_validate_refuses_imbalance_within_one_model(self):
        models = [MODEL, "xai/grok-4"]
        sched = schedule.make_schedule("12" * 16, models, ["NEW-01", "NEW-02"], 1, counterbalance=True)
        blocks = {}
        for run in sched["runs"]:
            blocks.setdefault(run["block"], []).append(run)
        # Make model 1 all treatment-first and model 2 all control-first: balanced overall, not per model.
        for pair in blocks.values():
            pair.sort(key=lambda r: r["order"])
            want = "treatment" if pair[0]["model"] == MODEL else "control"
            if pair[0]["group"] != want:
                pair[0]["order"], pair[1]["order"] = pair[1]["order"], pair[0]["order"]
        problems = schedule.validate(sched)
        self.assertTrue(any(MODEL in p and "not balanced" in p for p in problems), problems)

    def test_default_schedule_is_byte_for_byte_what_phase_32_produced(self):
        for args, expected in (
                (("12" * 16, [MODEL], ["NEW-01", "NEW-02", "NEW-03", "NEW-04"], 1),
                 "0bb4ce052d7a02b945772c66c1b0fc9f888baae15ffbc48113120df134879a98"),
                (("ab" * 16, [MODEL, "xai/grok-4"], ["NEW-01", "NEW-02", "NEW-03"], 3),
                 "b9cec665bfb3815f8aae88d39c2ca2c8501ad60deaac81c903299ee44e69cc97")):
            sched = schedule.make_schedule(*args)
            sched.pop("created_utc")
            self.assertEqual(hashlib.sha256(json.dumps(sched, sort_keys=True).encode()).hexdigest(), expected)


class ReviewDefectIntegrationTests(IntegrationBase):
    """The same defects through analyze.py's real slot resolution."""

    def test_scope_violation_through_resolve_slots_is_an_agent_failure(self):
        runs = self.sched["runs"]
        for run in runs:
            self.helper.put(run, fraction=1.0)
        target = next(r for r in runs if r["task"] == "NEW-04" and r["group"] == "treatment")
        with open(os.path.join(self.caps, target["run_id"], "run-status.json"), "w", encoding="utf-8") as h:
            json.dump({"valid": False, "invalid_reasons": ["immutable files changed or missing"]}, h)
        rows, problems = analyze.resolve_slots(self.sched, self.caps, self.scores)
        self.assertEqual([d.attribution(p) for p in problems], ["agent"])
        report = d.analyse(rows, problems, d.load_plan(self.plan))
        task = report["by_model"][MODEL]["primary:fully_correct"]["by_task"]["NEW-04"]
        self.assertEqual((task["agent_failures"]["treatment"], task["difference"]), (1, -1.0))

    def test_confirmed_tamper_is_attributed_only_when_it_names_the_scored_code(self):
        runs = self.sched["runs"]
        targets = [r for r in runs if r["group"] == "control" and r["task"] in ("NEW-03", "NEW-04")]
        for run in runs:
            self.helper.put(run, fraction=1.0)
        good, stale = targets
        self.helper.put(good, fraction=1.0, score={"tamper_review": "confirmed", "tamper_review_subject": "ab" * 32,
                                                   "scorer_id": "s1"})
        self.helper.put(stale, fraction=1.0, score={"tamper_review": "confirmed", "tamper_review_subject": "cd" * 32,
                                                    "scorer_id": "s1"})
        _, problems = analyze.resolve_slots(self.sched, self.caps, self.scores)
        by_run = {p["run_id"]: p for p in problems}
        self.assertEqual({p["status"] for p in problems}, {"excluded"})
        self.assertEqual(d.attribution(by_run[good["run_id"]]), "agent")
        self.assertEqual(d.attribution(by_run[stale["run_id"]]), "unattributed")

    def test_calibration_feedback_option_writes_a_control_only_file(self):
        for run in self.sched["runs"]:
            self.helper.put(run, fraction=1.0)
        feedback = os.path.join(self.tmp, "feedback.json")
        self.assertEqual(self.run_analyze("--calibration-feedback", feedback)[0], 3)  # needs a plan
        self.assertFalse(os.path.exists(feedback))
        code, _ = self.run_analyze("--difficulty-plan", self.plan, "--calibration-feedback", feedback)
        self.assertEqual(code, 0)
        with open(feedback, encoding="utf-8") as h:
            data = json.load(h)
        self.assertEqual(data["kind"], "aqd-calibration-feedback")
        self.assertEqual(data["by_model"], {})  # the historical plan has no calibration-set task

    def test_historical_all_valid_records_are_unaffected(self):
        for run in self.sched["runs"]:
            self.helper.put(run, fraction=1.0)
        rows, problems = analyze.resolve_slots(self.sched, self.caps, self.scores)
        self.assertEqual(problems, [])
        base = analyze.analyse(rows, problems)
        self.assertEqual(base["status"], "COMPLETE")
        report = d.analyse(rows, problems, d.load_plan(self.plan))
        out = report["by_model"][MODEL]["primary:fully_correct"]
        self.assertEqual(report["label"], "exploratory")
        for task in out["by_task"].values():
            self.assertEqual((task["difference"], task["agent_failures"], task["nonvalid"]),
                             (0.0, {"control": 0, "treatment": 0}, {"control": 0, "treatment": 0}))
        self.assertTrue(all(t["decision"] == "inconclusive" for t in out["by_tier"].values()))
        self.assertTrue(all(i["conclusion"] == "inconclusive" for i in out["interaction"].values()))


class PowerSimulationTests(unittest.TestCase):
    """power_sim.py runs the real decision rules (difficulty.analyse_outcome), not a simplified copy."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, PHASE33)
        import power_sim
        cls.ps = power_sim

    def test_stop_rule_operating_characteristics(self):
        oc = self.ps.stop_probability
        self.assertAlmostEqual(oc(4, 4, 0.9), 0.6561, places=4)  # "≥ 0.9 of 4" is 4/4: a 0.9 task stops only 66%
        self.assertAlmostEqual(oc(8, 7, 0.9), 0.8131, places=4)
        self.assertAlmostEqual(oc(8, 7, 0.5), 0.0352, places=4)

    def test_simulation_uses_the_real_guards_and_controls_false_positives(self):
        res = self.ps.run_design(self.ps.Scenario("t", (1.5, 1.5), (1.5, 1.5), 0.0, 0.0, 0.0), tasks=6, reps=2,
                                 sims=150, seed=1)
        self.assertLessEqual(res["hard"]["benefit"], 0.06)
        self.assertLessEqual(res["interaction"]["larger_in_hard"], 0.06)
        self.assertIn("inconclusive", res["hard"])
        again = self.ps.run_design(self.ps.Scenario("t", (1.5, 1.5), (1.5, 1.5), 0.0, 0.0, 0.0), tasks=6, reps=2,
                                   sims=150, seed=1)
        self.assertEqual(res, again)

    def test_realized_effect_accounts_for_clipping(self):
        res = self.ps.run_design(self.ps.Scenario("t", (1.5, 1.5), (8, 1), 0.0, 0.2, 0.0), tasks=4, reps=1,
                                 sims=50, seed=2)
        self.assertLess(res["true_effect"]["hard"], 0.2)


if __name__ == "__main__":
    unittest.main()
