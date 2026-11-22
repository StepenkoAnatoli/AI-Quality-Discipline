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

    def test_historical_plan_loads_and_all_four_tasks_are_post_hoc_medium(self):
        out = d.load_plan(os.path.join(PHASE33, "analysis-plan-historical.json"))
        self.assertEqual(out["plan"]["status"], "draft")
        self.assertEqual(sorted(out["tasks"]), ["NEW-01", "NEW-02", "NEW-03", "NEW-04"])
        for info in out["tasks"].values():
            self.assertEqual((info["tier"], info["set"], info["provenance"]), ("medium", "historical", "post_hoc"))

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
        self.assertEqual(easy["decisions"]["valid_only"], "no_meaningful_effect")
        self.assertEqual(easy["decision"], "inconclusive")
        self.assertIn("ceiling or floor", easy["reason"])
        # The easy tier is at the ceiling, so the interaction cannot be read even though hard shows a benefit.
        inter = out["interaction"]["hard - easy"]
        self.assertGreater(inter["estimate"], 0)
        self.assertEqual(inter["conclusion"], "inconclusive")
        self.assertIn("ceiling or floor", inter["reason"])
        self.assertEqual(out["by_tier"]["medium"], {"tasks": 0, "decision": "inconclusive", "missing_tasks": [],
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
        self.assertEqual(hard["decisions"]["valid_only"], "benefit")
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
        self.assertEqual(d.analyse(rows, [], loaded(one))["label"], "confirmatory")
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
        for i in range(4):  # hard: control fails, one treatment pass, two treatment slots excluded
            rows += [row(f"H{i}", "control", 0)] * 2 + [row(f"H{i}", "treatment", 1)]
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
        self.assertEqual(hard["decisions"]["valid_only"], "benefit")
        self.assertEqual(hard["decision"], "inconclusive")
        self.assertIn("no slots", hard["reason"])
        with self.assertRaisesRegex(d.DifficultyError, "no slot exists"):
            d.analyse([], [], loaded(tasks))

    def test_decide(self):
        self.assertEqual(d.decide({"mean": 0.3, "ci": [0.05, 0.55]}, 0.2, 0.1), "benefit")
        self.assertEqual(d.decide({"mean": 0.1, "ci": [0.05, 0.15]}, 0.2, 0.1), "no_meaningful_effect")
        self.assertEqual(d.decide({"mean": 0.1, "ci": [0.01, 0.25]}, 0.2, 0.1), "inconclusive")
        self.assertEqual(d.decide({"mean": -0.3, "ci": [-0.5, -0.1]}, 0.2, 0.1), "harm")
        self.assertEqual(d.decide({"mean": 0.0, "ci": [-0.6, 0.6]}, 0.2, 0.1), "inconclusive")
        self.assertEqual(d.decide({"mean": 0.5, "ci": None}, 0.2, 0.1), "inconclusive")


class AnalyzeIntegrationTests(th.TempDirTest):
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

    def test_ceiling_result_is_reported_as_inconclusive_not_as_no_effect(self):
        for run in self.sched["runs"]:
            self.helper.put(run, fraction=1.0)
        code, _ = self.run_analyze("--difficulty-plan", self.plan)
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as h:
            report = json.load(h)
        diff = report["difficulty"]
        self.assertEqual(diff["label"], "exploratory")
        self.assertEqual(diff["tiers"]["medium"], ["NEW-01", "NEW-02", "NEW-03", "NEW-04"])
        medium = diff["by_model"][MODEL]["primary:fully_correct"]["by_tier"]["medium"]
        self.assertEqual((medium["tasks"], medium["mean_task_difference"], medium["sd"]), (4, 0.0, 0.0))
        # The four-task ceiling (every run passed in both arms) must never read as "no effect".
        self.assertEqual(medium["decisions"]["valid_only"], "no_meaningful_effect")
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


if __name__ == "__main__":
    unittest.main()
