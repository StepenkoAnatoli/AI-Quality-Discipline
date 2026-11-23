"""Tests for check_results.py, the dry-run gate. The committed results are the positive fixture.

    python3 -m unittest discover -s evaluations/phase-3.3/dryrun -p "test_check_results.py" -v
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_results  # noqa: E402

RESULTS = os.path.join(HERE, "results-2026-11-23")
FILES = [os.path.join(RESULTS, n) for n in ("dryrun-results-full.ndjson", "dryrun-results-preflight-only.ndjson")]


def rows():
    out = []
    for path in FILES:
        with open(path, encoding="utf-8") as handle:
            out.append([json.loads(line) for line in handle if line.strip()])
    return out


class CheckResultsTests(unittest.TestCase):
    def run_check(self, full, preflight_only):
        paths = []
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in (("full", full), ("pf", preflight_only)):
                if data is None:
                    continue
                path = os.path.join(tmp, f"{name}.ndjson")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("".join(json.dumps(r) + "\n" for r in data))
                paths.append(path)
            return check_results.main(paths)

    def test_the_committed_results_pass(self):
        self.assertEqual(self.run_check(*rows()), 0)

    def test_the_expected_scenarios_are_exactly_26(self):
        self.assertEqual(len(check_results.EXPECTED), 26)
        self.assertEqual(set(check_results.EXPECTED), set(check_results.REASONS))

    def test_a_missing_scenario_fails(self):
        full, pf = rows()
        self.assertEqual(self.run_check([r for r in full if r.get("scenario") != "leaked-token"], pf), 1)

    def test_a_duplicated_scenario_fails(self):
        full, pf = rows()
        dup = next(r for r in full if r.get("scenario") == "control-ok")
        self.assertEqual(self.run_check(full + [dup], pf), 1)

    def test_an_unexpected_scenario_fails(self):
        full, pf = rows()
        extra = dict(next(r for r in full if r.get("scenario") == "control-ok"), scenario="surprise", run_id="r-x")
        self.assertEqual(self.run_check(full + [extra], pf), 1)

    def test_a_scenario_with_the_wrong_expectation_fails(self):
        full, pf = rows()
        for r in full:
            if r.get("scenario") == "wrong-cwd":
                r["expect"] = "refused"
        self.assertEqual(self.run_check(full, pf), 1)

    def test_a_missing_or_duplicated_cleanup_record_fails(self):
        full, pf = rows()
        run = next(r["run_id"] for r in full if r.get("scenario") == "timeout")
        self.assertEqual(self.run_check([r for r in full if r.get("cleanup_for") != run], pf), 1)
        cleanup = next(r for r in full if r.get("cleanup_for") == run)
        self.assertEqual(self.run_check(full + [cleanup], pf), 1)

    def test_a_missing_mode_or_probe_row_fails(self):
        full, pf = rows()
        self.assertEqual(self.run_check(full, None), 1)
        self.assertEqual(self.run_check(full, [r for r in pf if "bwrap_userns_as_agent" not in r]), 1)
        self.assertEqual(self.run_check([r for r in full if "proc_probe" not in r], pf), 1)
        self.assertEqual(self.run_check([r for r in full if "out_dir_token_scan" not in r], pf), 1)

    def test_an_empty_input_fails(self):
        self.assertEqual(self.run_check([], []), 1)


if __name__ == "__main__":
    unittest.main()
