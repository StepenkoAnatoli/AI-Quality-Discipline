"""Tests for check_single_use.py: a second live dispatch (rerun, re-dispatch, retry after a failure) is refused."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

LIVE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIVE)
import check_single_use as su  # noqa: E402

D = {"id": 1, "sha": "a" * 40, "ref": "main", "environment": "aqd-cc-live-probe", "task": "deploy"}


class SingleUseTests(unittest.TestCase):
    def test_only_this_jobs_deployment_passes(self):
        self.assertEqual(su.check([D]), [])

    def test_an_earlier_deployment_refuses_reuse_of_the_approval(self):
        self.assertTrue(su.check([D, dict(D, id=2)]))
        self.assertTrue(su.check([dict(D, id=i) for i in range(5)]))

    def test_unexpected_shapes_fail_closed(self):
        for bad in (None, {}, {"message": "Bad credentials"}, [], ["x"], [dict(D, environment="other")],
                    [dict(D, id=i) for i in range(100)]):
            with self.subTest(bad=bad):
                self.assertTrue(su.check(bad))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as t:
            for data, code in (([D], 0), ([D, dict(D, id=2)], 1), ("not json", 1)):
                p = os.path.join(t, "d.json")
                with open(p, "w") as h:
                    h.write(json.dumps(data) if data != "not json" else data)
                r = subprocess.run([sys.executable, "-I", os.path.join(LIVE, "check_single_use.py"), "--deployments",
                                    p], capture_output=True, text=True)
                self.assertEqual(r.returncode, code, r.stdout)
            r = subprocess.run([sys.executable, "-I", os.path.join(LIVE, "check_single_use.py"), "--deployments",
                                os.path.join(t, "missing.json")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)


class SingleUseEnvironmentNameTests(unittest.TestCase):
    def test_the_smoke_environment_has_its_own_single_use(self):
        smoke = dict(D, environment="aqd-cc-live-smoke")
        self.assertEqual(su.check([smoke], "aqd-cc-live-smoke"), [])
        self.assertTrue(su.check([smoke, dict(smoke, id=2)], "aqd-cc-live-smoke"))
        self.assertTrue(su.check([smoke]))  # the probe's name refuses another environment's deployment
        self.assertTrue(su.check([D], "aqd-cc-live-smoke"))

    def test_only_the_two_reviewed_names(self):
        self.assertTrue(su.check([dict(D, environment="x")], "x"))
        r = subprocess.run([sys.executable, "-I", os.path.join(LIVE, "check_single_use.py"), "--deployments",
                            os.devnull, "--name", "x"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class SingleUseMessageTests(unittest.TestCase):
    def test_the_success_line_names_the_environment_that_was_checked(self):
        with tempfile.TemporaryDirectory() as t:
            for name in ("aqd-cc-live-probe", "aqd-cc-live-smoke"):
                path = os.path.join(t, "d.json")
                with open(path, "w") as h:
                    json.dump([dict(D, environment=name)], h)
                r = subprocess.run([sys.executable, "-I", os.path.join(LIVE, "check_single_use.py"), "--deployments",
                                    path, "--name", name], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertIn(f"first and only deployment of environment {name}", r.stdout)


if __name__ == "__main__":
    unittest.main()
