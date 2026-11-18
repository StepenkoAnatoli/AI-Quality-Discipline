# CD-03 fixture

Python 3.10+. Run targeted tests: `python -m unittest tests.test_parser -v`. Run full suite: `python -m unittest discover -s tests -v`. Baseline: targeted tests fail because the empty timezone currently raises `ValueError`; the full suite has that same target failure plus one known unrelated failure in `tests/test_legacy.py`. Do not edit that file.
