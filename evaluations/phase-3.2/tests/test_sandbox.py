"""Isolation tests for the Docker scoring sandbox (Linux with Docker only).

Requires `docker` and AQD_SANDBOX_IMAGE set to a Python >= 3.10 image pinned by
digest, for example the output of
    docker pull python:3.12-slim
    docker inspect --format '{{index .RepoDigests 0}}' python:3.12-slim

Without them every test is SKIPPED, which means the isolation boundary is NOT
DEMONSTRATED on that machine. Hidden evaluation of candidate code is ready
only after these tests have passed on the machine that will do the scoring.

The probe candidate returns the right answer only if every isolation property
holds inside the sandbox, so a VALID 2/2 evaluation demonstrates them all and
any leak shows up as a failed hidden check.
"""
import os
import shutil
import subprocess
import unittest

from test_scoring import ScoringTest, score_run

IMAGE = os.environ.get("AQD_SANDBOX_IMAGE", "")
DOCKER = shutil.which("docker")

PROBE = '''import os, socket

def _leaks():
    leaks = []
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3).close()
        leaks.append("network")
    except OSError:
        pass
    try:
        socket.getaddrinfo("example.com", 443)
        leaks.append("dns")
    except OSError:
        pass
    for path in ("/work/calc/core.py", "/work/hidden_tests/test_syn_hidden.py", "/work/run_checks.py", "/work/planted"):
        try:
            with open(path, "a"):
                leaks.append("write:" + path)
        except OSError:
            pass
    if os.getuid() == 0:
        leaks.append("root")
    if os.environ.get("AQD_HOST_SECRET"):
        leaks.append("host-env")
    for name in ("score_run.py", "allowlist.json", "inventory.json"):
        if os.path.exists(os.path.join("/work", name)):
            leaks.append("evaluator-file:" + name)
    return leaks

def add(a, b):
    leaks = _leaks()
    if leaks:
        raise AssertionError("sandbox leaks: " + ", ".join(leaks))
    return a + b
'''


@unittest.skipUnless(DOCKER and "@sha256:" in IMAGE, "Docker or a digest-pinned AQD_SANDBOX_IMAGE is missing: isolation NOT DEMONSTRATED")
class DockerSandboxTests(ScoringTest):
    timeout = 120

    def docker_score(self, core):
        os.environ["AQD_HOST_SECRET"] = "must-not-reach-the-sandbox"
        try:
            return score_run.score(self.phase, "SYN", self.pristine, self.agent(core), self.hidden, self.inventory,
                                   score_run.DockerRunner(self.timeout, IMAGE))
        finally:
            os.environ.pop("AQD_HOST_SECRET", None)

    def test_correct_solution_scores_in_the_sandbox(self):
        report = self.docker_score("def add(a, b):\n    return a + b\n")
        self.assertEqual(report["evaluation_status"], "valid", report["invalid_reasons"])
        self.assertEqual(report["primary"]["hidden_pass_fraction"], 1.0)

    def test_no_network_no_writes_no_root_no_host_env_no_evaluator_files(self):
        report = self.docker_score(PROBE)
        self.assertEqual(report["evaluation_status"], "valid", report["invalid_reasons"])
        details = {k: v["detail"][-400:] for k, v in report["details"]["hidden"].items() if v["outcome"] != "pass"}
        self.assertEqual(report["hidden_checks"], {"H01": "pass", "H02": "pass"}, details)

    def test_container_is_removed_after_each_test(self):
        self.docker_score("def add(a, b):\n    return a + b\n")
        names = subprocess.run([DOCKER, "ps", "-a", "--format", "{{.Names}}"], stdout=subprocess.PIPE, text=True).stdout
        self.assertNotIn("aqd-score-", names)


if __name__ == "__main__":
    unittest.main()
