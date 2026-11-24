#!/usr/bin/env python3
"""Run ONE unittest check and record its outcome in a JSON file.

Executed by score_run.py inside a scratch copy of a project (inside the
sandbox for candidate code), with the scratch directory as working directory:

    python run_checks.py list <start_dir> <output.json>
    python run_checks.py run  <output.json> <test_id>      (nonce on stdin)

`list` writes the discovered test ids (used only on the pristine tree, to check
the evaluator itself). `run` reads a one-line nonce from stdin BEFORE any
project code is imported, imports the test's module itself so that an import
failure is recorded as a candidate failure, runs exactly one test and writes
{"nonce", "requested_id", "tests_run", "outcome", "detail"}. Outcomes: "pass",
"fail", "error", "skip". score_run.py validates every field; it never trusts
an exit code, and a missing or malformed file makes the evaluation invalid.
"""
import importlib
import json
import sys
import traceback
import unittest

OUTCOME_RANK = {"pass": 0, "skip": 1, "fail": 2, "error": 3}


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def _set(self, test, outcome):
        current = self.outcomes.get(test.id())
        if current is None or OUTCOME_RANK[outcome] > OUTCOME_RANK[current]:
            self.outcomes[test.id()] = outcome

    def addSuccess(self, test):
        super().addSuccess(test)
        self._set(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._set(test, "fail")

    def addError(self, test, err):
        super().addError(test, err)
        self._set(test, "error")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._set(test, "skip")

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._set(test, "error")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._set(test, "error")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._set(test, "fail" if issubclass(err[0], test.failureException) else "error")


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _write(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def run_one(output, test_id, nonce):
    record = {"nonce": nonce, "requested_id": test_id, "tests_run": 0, "outcome": "error", "detail": ""}
    module_name = test_id.rsplit(".", 2)[0]
    try:
        importlib.import_module(module_name)
    except unittest.SkipTest:
        record["outcome"] = "skip"
        record["detail"] = "SkipTest raised while importing:\n" + traceback.format_exc()[-4000:]
        _write(output, record)
        return 0
    except BaseException:  # candidate code failed to import: a real candidate outcome
        record["detail"] = "import failed:\n" + traceback.format_exc()[-4000:]
        _write(output, record)
        return 0
    try:
        suite = unittest.TestLoader().loadTestsFromName(test_id)
    except Exception:
        record["outcome"] = "missing"
        record["detail"] = traceback.format_exc()[-4000:]
        _write(output, record)
        return 0
    tests = list(_iter_tests(suite))
    if [t.id() for t in tests] != [test_id]:
        record["outcome"] = "missing"
        record["detail"] = f"loader returned {[t.id() for t in tests]}"
        _write(output, record)
        return 0
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
    record["tests_run"] = result.testsRun
    record["outcome"] = result.outcomes.get(test_id, "error")
    _write(output, record)
    return 0


def main(argv):
    if len(argv) == 4 and argv[1] == "list":
        loader = unittest.TestLoader()
        discovered = loader.discover(argv[2], top_level_dir=".")
        ids = [t.id() for t in _iter_tests(discovered)]
        _write(argv[3], {"ids": sorted(ids), "load_errors": [str(e) for e in getattr(loader, "errors", [])]})
        return 0
    if len(argv) == 4 and argv[1] == "run":
        nonce = sys.stdin.readline().strip()
        sys.stdin.close()
        return run_one(argv[2], argv[3], nonce)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
