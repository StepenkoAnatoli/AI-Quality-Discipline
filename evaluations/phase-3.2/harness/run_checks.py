#!/usr/bin/env python3
"""Run unittest checks and record one outcome per test in a JSON file.

Executed inside a scratch copy of a project by score_run.py, with the scratch
directory as the working directory:

    python run_checks.py list <start_dir> <output.json>
    python run_checks.py run  <start_dir> <output.json> [test_id ...]

`list` writes the discovered test ids. `run` runs the given ids (or every
discovered test) and writes outcomes "pass", "fail", "error" or "skip".
Scoring reads the JSON, never the exit code.
"""
import json
import sys
import unittest


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.setdefault(test.id(), "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[test.id()] = "fail"

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[test.id()] = "error"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[test.id()] = "skip"

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            failed = issubclass(err[0], test.failureException)
            self.outcomes[test.id()] = "fail" if failed else "error"


def _iter_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _write(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def main(argv):
    if len(argv) < 4 or argv[1] not in ("list", "run"):
        print(__doc__, file=sys.stderr)
        return 2
    mode, start_dir, output, ids = argv[1], argv[2], argv[3], argv[4:]
    loader = unittest.TestLoader()
    discovered = loader.discover(start_dir, top_level_dir=".")
    load_errors = [str(e) for e in getattr(loader, "errors", [])]
    if mode == "list":
        _write(output, {"ids": sorted(t.id() for t in _iter_tests(discovered)), "load_errors": load_errors})
        return 0
    suite = loader.loadTestsFromNames(ids) if ids else discovered
    # unittest releases tests from the suite as they run, so collect ids first.
    expected_ids = [test.id() for test in _iter_tests(suite)]
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
    for test_id in expected_ids:
        result.outcomes.setdefault(test_id, "error")
    _write(output, {"tests_run": result.testsRun, "load_errors": load_errors, "outcomes": result.outcomes})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
