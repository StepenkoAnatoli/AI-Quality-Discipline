"""Adversarial tests for score_run.py: the evaluation must fail closed.

A synthetic task (the real hidden tests are private) with one mutable file,
calc/core.py, whose pristine version is wrong. Candidate solutions below try to
break the evaluator. Standard library only; no network, no Docker.

    python -m unittest discover -s evaluations/phase-3.2/tests -p "test_scoring.py" -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PHASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HARNESS = os.path.join(PHASE, "harness")
sys.path.insert(0, HARNESS)

import score_run  # noqa: E402

ALLOWLIST = {
    "schema_version": 1,
    "additive_dirs": ["tests/additive"],
    "protected_dirs": ["tests/baseline"],
    "tolerated_artifacts": ["__pycache__"],
    "common_files": {},
    "tasks": {"SYN": {"title": "synthetic", "source_dir": "tasks/SYN/project", "files": {
        "calc/__init__.py": "immutable",
        "calc/core.py": "mutable",
        "tests/__init__.py": "immutable",
        "tests/baseline/__init__.py": "immutable",
        "tests/baseline/test_base.py": "immutable",
        "tests/additive/__init__.py": "additive",
    }}},
}

PRISTINE = {
    "calc/__init__.py": "",
    "calc/core.py": "def add(a, b):\n    return a - b\n",
    "tests/__init__.py": "",
    "tests/baseline/__init__.py": "",
    "tests/baseline/test_base.py": (
        "import unittest\nfrom calc.core import add\n"
        "class Base(unittest.TestCase):\n"
        "    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n"
    ),
    "tests/additive/__init__.py": "",
}

HIDDEN = {
    "hidden_tests/__init__.py": "",
    "hidden_tests/test_syn_hidden.py": (
        "import unittest\nfrom calc.core import add\n"
        "class Hidden(unittest.TestCase):\n"
        "    def test_H01_positive(self):\n        self.assertEqual(add(2, 3), 5)\n"
        "    def test_H02_mixed(self):\n        self.assertEqual(add(-1, 1), 0)\n"
    ),
}

CORRECT = "def add(a, b):\n    return a + b\n"


def write_files(root, files):
    for rel, text in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)


class ScoringTest(unittest.TestCase):
    timeout = 60

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aqd-scoring-")
        self.phase = os.path.join(self.tmp, "phase")
        os.makedirs(self.phase)
        with open(os.path.join(self.phase, "allowlist.json"), "w", encoding="utf-8") as handle:
            json.dump(ALLOWLIST, handle)
        self.pristine = os.path.join(self.tmp, "pristine")
        write_files(self.pristine, PRISTINE)
        self.hidden = os.path.join(self.tmp, "hidden")
        write_files(self.hidden, HIDDEN)
        self.inventory = score_run.build_inventory(self.phase, "SYN", self.pristine, self.hidden)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def agent(self, core=CORRECT, extra=None):
        agent = os.path.join(self.tmp, "agent")
        shutil.rmtree(agent, ignore_errors=True)
        shutil.copytree(self.pristine, agent)
        write_files(agent, dict({"calc/core.py": core}, **(extra or {})))
        return agent

    def score(self, core=CORRECT, extra=None, inventory=None, timeout=None):
        return score_run.score(self.phase, "SYN", self.pristine, self.agent(core, extra), self.hidden,
                               self.inventory if inventory is None else inventory,
                               score_run.LocalRunner(timeout or self.timeout))

    def assertInvalid(self, report, fragment):
        self.assertEqual(report["evaluation_status"], "invalid", report)
        self.assertIsNone(report["primary"])
        self.assertNotIn("hidden_passed", report)
        self.assertTrue(any(fragment in r for r in report["invalid_reasons"]), report["invalid_reasons"])


class InventoryTests(ScoringTest):
    def test_inventory_lists_exact_ids_and_hashes(self):
        self.assertEqual(self.inventory["hidden_ids"], [
            "hidden_tests.test_syn_hidden.Hidden.test_H01_positive",
            "hidden_tests.test_syn_hidden.Hidden.test_H02_mixed",
        ])
        self.assertEqual(self.inventory["baseline_ids"], ["tests.baseline.test_base.Base.test_zero"])
        self.assertEqual(set(self.inventory["hidden_files"]), {"hidden_tests/__init__.py", "hidden_tests/test_syn_hidden.py"})

    def test_inventory_refuses_a_hidden_package_without_tests(self):
        write_files(self.hidden, {"hidden_tests/test_syn_hidden.py": "import unittest\n"})
        with self.assertRaises(score_run.Invalid):
            score_run.build_inventory(self.phase, "SYN", self.pristine, self.hidden)

    def test_inventory_refuses_a_hidden_package_that_does_not_load(self):
        write_files(self.hidden, {"hidden_tests/test_syn_hidden.py": "import unittest\nthis is not python\n"})
        with self.assertRaises(score_run.Invalid):
            score_run.build_inventory(self.phase, "SYN", self.pristine, self.hidden)


class ValidOutcomeTests(ScoringTest):
    def test_correct_solution(self):
        report = self.score()
        self.assertEqual(report["evaluation_status"], "valid", report["invalid_reasons"])
        self.assertEqual(report["hidden_checks"], {"H01": "pass", "H02": "pass"})
        self.assertEqual(report["primary"], {"hidden_pass_fraction": 1.0, "fully_correct": True})
        self.assertFalse(report["requires_review"])

    def test_unchanged_wrong_code_is_a_valid_partial_result(self):
        report = self.score(core=PRISTINE["calc/core.py"])
        self.assertEqual(report["evaluation_status"], "valid")
        self.assertEqual(report["hidden_checks"], {"H01": "fail", "H02": "fail"})
        self.assertEqual(report["primary"]["hidden_pass_fraction"], 0.0)

    def test_syntax_error_is_a_valid_zero_not_an_invalid_evaluation(self):
        report = self.score(core="def add(a, b) return a + b\n")
        self.assertEqual(report["evaluation_status"], "valid", report["invalid_reasons"])
        self.assertEqual(report["hidden_checks"], {"H01": "error", "H02": "error"})
        self.assertEqual(report["primary"], {"hidden_pass_fraction": 0.0, "fully_correct": False})
        self.assertIn("import failed", report["details"]["hidden"][self.inventory["hidden_ids"][0]]["detail"])

    def test_hang_is_a_timeout_failure(self):
        report = self.score(core="def add(a, b):\n    while True:\n        pass\n", timeout=3)
        self.assertEqual(report["evaluation_status"], "valid", report["invalid_reasons"])
        self.assertEqual(report["hidden_checks"], {"H01": "timeout", "H02": "timeout"})
        self.assertEqual(report["primary"]["hidden_pass_fraction"], 0.0)

    def test_baseline_regression_prevents_fully_correct(self):
        report = self.score(core="def add(a, b):\n    return a + b if (a, b) != (0, 0) else 1\n")
        self.assertEqual(report["hidden_passed"], 2)
        self.assertFalse(report["baseline_all_pass"])
        self.assertFalse(report["primary"]["fully_correct"])

    def test_only_mutable_file_and_additive_tests_are_taken(self):
        agent_extra = {"calc/__init__.py": "raise RuntimeError('immutable file edited')\n"}
        report = self.score(extra=agent_extra)
        self.assertEqual(report["primary"]["hidden_pass_fraction"], 1.0)
        self.assertEqual(report["taken_from_agent"], ["calc/core.py", "tests/additive/"])

    def test_broken_agent_tests_never_invalidate_the_evaluation(self):
        crash = {"tests/additive/test_mine.py": "import os\nos._exit(3)\n"}
        report = self.score(extra=crash)
        self.assertEqual(report["evaluation_status"], "valid", report["invalid_reasons"])
        self.assertEqual(report["primary"]["hidden_pass_fraction"], 1.0)


class FailClosedTests(ScoringTest):
    def test_skip_raised_by_candidate_is_invalid(self):
        report = self.score(core="import unittest\ndef add(a, b):\n    raise unittest.SkipTest('not today')\n")
        self.assertInvalid(report, "skipped")

    def test_skip_raised_at_import_is_invalid(self):
        report = self.score(core="import unittest\nraise unittest.SkipTest('nothing to see')\n")
        self.assertInvalid(report, "skipped")

    def test_process_killed_before_result_is_invalid(self):
        report = self.score(core="import os\ndef add(a, b):\n    os._exit(0)\n")
        self.assertInvalid(report, "no result file")

    def test_forged_result_without_nonce_is_invalid(self):
        forge = (
            "import json, os, sys\n"
            "if len(sys.argv) >= 4 and sys.argv[1] == 'run':\n"
            "    with open(sys.argv[2], 'w') as h:\n"
            "        json.dump({'nonce': 'guess', 'requested_id': sys.argv[3], 'tests_run': 1, 'outcome': 'pass', 'detail': ''}, h)\n"
            "    os._exit(0)\n"
            "def add(a, b):\n    return 0\n"
        )
        self.assertInvalid(self.score(core=forge), "nonce")

    def test_malformed_result_is_invalid(self):
        forge = ("import os, sys\nopen(sys.argv[2], 'w').write('not json')\nos._exit(0)\n")
        self.assertInvalid(self.score(core=forge), "malformed")

    def test_extra_file_in_result_directory_is_invalid(self):
        sneaky = ("import os, sys\nopen(os.path.join(os.path.dirname(sys.argv[2]), 'other.json'), 'w').write('{}')\n"
                  "def add(a, b):\n    return a + b\n")
        self.assertInvalid(self.score(core=sneaky), "unexpected files")

    def test_nonzero_exit_after_result_is_invalid(self):
        late = "import atexit, os\natexit.register(lambda: os._exit(7))\ndef add(a, b):\n    return a + b\n"
        self.assertInvalid(self.score(core=late), "runner exited with 7")

    def test_inventory_missing_a_test_is_invalid(self):
        inv = dict(self.inventory, hidden_ids=self.inventory["hidden_ids"][:1])
        self.assertInvalid(self.score(inventory=inv), "does not match the inventory")

    def test_inventory_with_unknown_test_is_invalid(self):
        ids = self.inventory["hidden_ids"] + ["hidden_tests.test_syn_hidden.Hidden.test_H03_gone"]
        self.assertInvalid(self.score(inventory=dict(self.inventory, hidden_ids=ids)), "does not match the inventory")

    def test_inventory_with_duplicates_or_no_tests_is_invalid(self):
        dup = dict(self.inventory, hidden_ids=self.inventory["hidden_ids"] * 2)
        self.assertInvalid(self.score(inventory=dup), "duplicates")
        self.assertInvalid(self.score(inventory=dict(self.inventory, hidden_ids=[])), "non-empty")
        self.assertInvalid(self.score(inventory={"error": "unreadable"}), "kind or task")

    def test_changed_hidden_file_is_invalid(self):
        write_files(self.hidden, {"hidden_tests/test_syn_hidden.py": HIDDEN["hidden_tests/test_syn_hidden.py"] + "\n"})
        self.assertInvalid(self.score(), "differ from the inventory")

    def test_hidden_tests_that_do_not_load_are_invalid_even_if_hashes_are_updated(self):
        broken = "import unittest\nthis is not python\n"
        write_files(self.hidden, {"hidden_tests/test_syn_hidden.py": broken})
        inv = dict(self.inventory, hidden_files=score_run.hidden_file_hashes(self.hidden))
        self.assertInvalid(self.score(inventory=inv), "does not match the inventory")

    def test_empty_hidden_package_is_invalid(self):
        os.remove(os.path.join(self.hidden, "hidden_tests", "test_syn_hidden.py"))
        self.assertInvalid(self.score(), "differ from the inventory")

    def test_missing_hidden_package_is_invalid(self):
        shutil.rmtree(os.path.join(self.hidden, "hidden_tests"))
        self.assertInvalid(self.score(), "hidden test package not found")


class ResidualRiskTests(ScoringTest):
    """In-process tampering cannot be prevented, only flagged for review."""

    def test_monkeypatching_unittest_is_flagged_for_review(self):
        cheat = ("import unittest\nunittest.TestCase.assertEqual = lambda *a, **k: None\n"
                 "def add(a, b):\n    return 0\n")
        report = self.score(core=cheat)
        self.assertEqual(report["evaluation_status"], "valid")
        self.assertEqual(report["hidden_passed"], 2)  # the cheat works in-process ...
        self.assertTrue(report["requires_review"])     # ... and is flagged
        self.assertIn(r"\bunittest\b", report["review_flags"]["calc/core.py"])

    def test_comments_do_not_trigger_review_flags(self):
        report = self.score(core="# inspect the subprocess output\n" + CORRECT)
        self.assertFalse(report["requires_review"])


class CliTests(ScoringTest):
    def run_cli(self, *extra):
        out = os.path.join(self.tmp, "score.json")
        inv = os.path.join(self.tmp, "inventory.json")
        with open(inv, "w", encoding="utf-8") as handle:
            json.dump(self.inventory, handle)
        proc = subprocess.run([sys.executable, os.path.join(HARNESS, "score_run.py"), "score", "--phase-root", self.phase,
                               "--task", "SYN", "--pristine", self.pristine, "--agent", self.agent(), "--hidden", self.hidden,
                               "--inventory", inv, "--out", out, *extra],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return proc, out

    def test_refuses_candidate_code_without_sandbox(self):
        proc, out = self.run_cli("--sandbox", "none")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertFalse(os.path.exists(out))

    def test_refuses_unpinned_image(self):
        proc, _ = self.run_cli("--sandbox", "docker", "--image", "python:3.12-slim")
        self.assertEqual(proc.returncode, 2, proc.stdout)

    def test_exit_codes_distinguish_valid_and_invalid(self):
        proc, out = self.run_cli("--sandbox", "none", "--trusted-code")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        os.remove(os.path.join(self.hidden, "hidden_tests", "test_syn_hidden.py"))
        proc, out = self.run_cli("--sandbox", "none", "--trusted-code")
        self.assertEqual(proc.returncode, 3, proc.stdout)
        with open(out, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["evaluation_status"], "invalid")

    def test_docker_command_has_the_isolation_flags(self):
        cmd = score_run.DockerRunner(10, "python@sha256:" + "0" * 64).command("/t", "/o", ["run", "{out}/r.json", "x"], "c1")
        joined = " ".join(cmd)
        for flag in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--user 65534:65534",
                     "/t:/work:ro", "/o:/out:rw"):
            self.assertIn(flag, joined)
        self.assertNotIn("--env-file", joined)
        self.assertEqual(cmd[-3:], ["run", "/out/r.json", "x"])


if __name__ == "__main__":
    unittest.main()
