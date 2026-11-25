"""Tests for validate_task.py on copies of the TOY package. Offline: no network, no credential, no model."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_task as vt  # noqa: E402

TOY = os.path.join(HERE, "toy-package")
SPLIT = "ledger/split.py"


class ValidateTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aqd-vt-")
        self.pkg = os.path.join(self.tmp, "pkg")
        shutil.copytree(TOY, self.pkg, ignore=shutil.ignore_patterns("__pycache__"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.pkg, *parts)

    def read(self, *parts):
        with open(self.path(*parts), encoding="utf-8") as h:
            return h.read()

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w", encoding="utf-8") as h:
            h.write(text)

    def edit_json(self, rel, change):
        data = json.loads(self.read(rel))
        change(data)
        self.write(rel, json.dumps(data))

    def run_validate(self, max_mutations=0):
        return vt.validate(self.pkg, max_mutations=max_mutations)

    def assertInvalid(self, needle, report=None):
        report = report or self.run_validate()
        self.assertFalse(report["valid"])
        self.assertTrue(any(needle in r for r in report["reasons"]), report["reasons"])
        return report

    def test_the_toy_package_is_valid_and_mechanical_mutation_finds_its_boundary_gap(self):
        report = self.run_validate(max_mutations=25)
        self.assertTrue(report["valid"], report["reasons"])
        self.assertEqual(report["checks"], ["H01", "H02", "H03", "H04"])
        self.assertEqual(report["pristine"]["failed_hidden"], ["H01", "H02", "H03"])
        self.assertEqual({k: v["failed_hidden"] for k, v in report["mutants"].items()},
                         {"no-validation": ["H03"], "remainder-last": ["H02"], "rounded": ["H01", "H02"]})
        mech = report["mechanical_mutation"]
        # No hidden check uses parts == 1, so "parts <= 1" survives: reported, never hidden, never gated.
        self.assertEqual(mech["survivors"], ["ledger/split.py#const4"])
        self.assertEqual((mech["scored"], mech["killed_by_hidden"]), (8, 7))
        self.assertEqual(vt.mechanical_mutants(vt.Package(self.pkg), 25),
                         vt.mechanical_mutants(vt.Package(self.pkg), 25))  # seeded and deterministic

    def test_a_docstring_removal_is_never_generated(self):
        labels = [label for label, files in vt.mechanical_mutants(vt.Package(self.pkg), 100)]
        sources = [files[SPLIT] for _label, files in vt.mechanical_mutants(vt.Package(self.pkg), 100)]
        self.assertTrue(labels)
        self.assertTrue(all('"""Split' in s or "'Split" in s for s in sources))

    def test_a_wrong_reference_or_an_already_solved_pristine_is_invalid(self):
        self.write("oracle/reference/" + SPLIT, self.read("oracle/mutants/rounded", SPLIT))
        self.assertInvalid("reference")
        shutil.rmtree(self.pkg)
        shutil.copytree(TOY, self.pkg)
        self.write(f"tasks/TOY-SPLIT/project/{SPLIT}", self.read("oracle/reference", SPLIT))
        self.assertInvalid("pristine")

    def test_an_alternative_failing_a_check_needs_a_source_only_review(self):
        self.write("oracle/alternatives/loop-ceil/" + SPLIT, self.read("oracle/mutants/remainder-last", SPLIT))
        self.assertInvalid("alternative loop-ceil: fails ['H02'] with no source-only review finding")
        review = {"alternative": "loop-ceil", "check": "H02", "finding": "demands_only_its_source",
                  "reviewer_session": "session-x", "saw_candidate_code": True}
        self.write("oracle/alt-reviews.json", json.dumps({"kind": "aqd-phase-3.3-alt-reviews", "schema_version": 1,
                                                         "reviews": [review]}))
        self.assertInvalid("no source-only review finding")  # the reviewer saw the failing code
        review["saw_candidate_code"] = False
        self.write("oracle/alt-reviews.json", json.dumps({"kind": "aqd-phase-3.3-alt-reviews", "schema_version": 1,
                                                         "reviews": [review]}))
        report = self.run_validate()
        self.assertTrue(report["valid"], report["reasons"])
        self.assertEqual(report["alt_reviewed_checks"], {"loop-ceil": ["H02"]})  # counted and reported (T7)

    def test_an_alternative_failing_a_baseline_check_or_none_at_all_is_invalid(self):
        self.write("oracle/alternatives/loop-ceil/" + SPLIT, "def split_amount(total_cents, parts):\n    return []\n")
        self.assertInvalid("fails a baseline check")
        shutil.rmtree(self.path("oracle", "alternatives"))
        self.assertInvalid("alternatives: none")

    def test_mutants_must_be_caught_and_number_at_least_three(self):
        self.write("oracle/mutants/rounded/" + SPLIT, self.read("oracle/reference", SPLIT))
        self.assertInvalid("mutant rounded: not caught")
        shutil.rmtree(self.path("oracle", "mutants", "rounded"))
        self.assertInvalid("mutants: 2, need at least 3")

    def test_a_shortcut_that_passes_is_invalid(self):
        self.write("oracle/shortcut/" + SPLIT, self.read("oracle/reference", SPLIT))
        self.assertInvalid("shortcut: not caught")

    def test_a_solution_touching_an_immutable_file_cannot_be_scored(self):
        self.write("oracle/mutants/rounded/ledger/report.py", "x = 1\n")
        self.assertInvalid("mutant rounded: not caught")
        self.assertIn("not mutable", self.run_validate()["mutants"]["rounded"]["reasons"][0])

    def test_source_map_problems_are_invalid(self):
        def wrong_quote(d):
            d["checks"]["H01"]["sources"]["S"]["quote"] = "Shares may differ from the total."

        def s_from_repo(d):
            d["checks"]["H02"]["sources"]["S"] = dict(d["checks"]["H02"]["sources"]["D"])

        def wrong_line(d):
            d["checks"]["H03"]["sources"]["D"]["line"] = 2

        def missing_check(d):
            del d["checks"]["H04"]

        def unsafe_path(d):
            d["checks"]["H01"]["sources"]["D"]["path"] = "../allowlist.json"

        for change, needle in ((wrong_quote, "H01/S: quote not found"), (s_from_repo, "H02/S: an S-variant source"),
                               (wrong_line, "H03/D: quote not found at ledger/report.py:2"),
                               (missing_check, "differ from the inventoried checks"),
                               (unsafe_path, "H01/D: unsafe path")):
            with self.subTest(needle=needle):
                original = self.read("oracle/source-map.json")
                self.edit_json("oracle/source-map.json", change)
                pkg = vt.Package(self.pkg)
                problems = vt.check_source_map(pkg, ["H01", "H02", "H03", "H04"])
                self.assertTrue(any(needle in p for p in problems), problems)
                self.write("oracle/source-map.json", original)
        self.assertEqual(vt.check_source_map(vt.Package(self.pkg), ["H01", "H02", "H03", "H04"]), [])

    def test_unreadable_packages_are_refused(self):
        os.remove(self.path("prompts", "D.md"))
        with self.assertRaises(vt.UsageError):
            vt.Package(self.pkg)
        shutil.copyfile(os.path.join(TOY, "prompts", "D.md"), self.path("prompts", "D.md"))
        self.edit_json("task.json", lambda d: d.update(task="OTHER"))
        with self.assertRaises(vt.UsageError):
            vt.Package(self.pkg)

    def test_cli_exit_codes(self):
        out = os.path.join(self.tmp, "report.json")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(vt.main(["--package", self.pkg, "--out", out, "--max-mutations", "0"]), 0)
            self.write("oracle/shortcut/" + SPLIT, self.read("oracle/reference", SPLIT))
            self.assertEqual(vt.main(["--package", self.pkg, "--out", out, "--max-mutations", "0"]), 1)
            os.remove(self.path("task.json"))
            self.assertEqual(vt.main(["--package", self.pkg, "--out", out]), 2)
        with open(out, encoding="utf-8") as h:
            self.assertFalse(json.load(h)["valid"])


if __name__ == "__main__":
    unittest.main()
