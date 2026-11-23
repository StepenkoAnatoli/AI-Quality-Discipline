"""Static and executable checks of the live job in .github/workflows/phase3-cc-smoke.yml. No dispatch, no secret.

The guard step's own shell is executed with unexpected events, branches and attempts; the job condition, secret
placement, step order, evidence packaging and upload settings are asserted on the parsed workflow."""
import os
import re
import subprocess
import unittest

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
PATH = os.path.join(ROOT, ".github", "workflows", "phase3-cc-smoke.yml")
TEXT = open(PATH, encoding="utf-8").read()
WF = yaml.safe_load(TEXT)
LIVE = WF["jobs"]["live-security-probe"]
STEPS = LIVE["steps"]
NAMES = [s.get("name", "") for s in STEPS]
PIN = "1234567890abcdef1234567890abcdef12345678"
RUN = WF["env"]["AQD_PROBE_RUN_ID"]


def step(prefix):
    found = [s for s in STEPS if s.get("name", "").startswith(prefix)]
    assert len(found) == 1, prefix
    return found[0]


def index(prefix):
    return NAMES.index(step(prefix)["name"])


class LiveJobConditionTests(unittest.TestCase):
    def test_job_condition(self):
        cond = LIVE["if"]
        for part in ("github.event_name == 'workflow_dispatch'", "inputs.mode == 'live-security-probe'",
                     "github.ref == 'refs/heads/main'", "github.run_attempt == 1"):
            self.assertIn(part, cond)
        self.assertNotIn("||", cond)
        self.assertEqual(LIVE["environment"], "aqd-cc-live-probe")
        self.assertEqual(sorted(LIVE["needs"]), ["mock", "verify-environment"])

    def test_triggers_are_only_dispatch_and_pull_request(self):
        self.assertEqual(sorted(WF[True]), ["pull_request", "workflow_dispatch"])  # PyYAML reads `on` as True
        self.assertNotIn("pull_request_target", TEXT)

    def test_permissions_are_read_only(self):
        self.assertEqual(WF["permissions"], {"contents": "read"})
        self.assertEqual(LIVE["permissions"], {"contents": "read", "deployments": "read"})
        self.assertNotIn("write", str(LIVE["permissions"]))

    def test_placeholder_pin_on_this_branch(self):
        self.assertEqual(WF["env"]["AQD_TEST_SHA"], "0" * 40)
        self.assertEqual(TEXT.count('AQD_TEST_SHA: "0000000000000000000000000000000000000000"'), 1)


class GuardScriptTests(unittest.TestCase):
    """Runs the guard step's own bash with the values GitHub would pass."""

    def run_guard(self, event="workflow_dispatch", ref="refs/heads/main", attempt="1", run_id=RUN,
                  confirm=f"RUN-LIVE-PROBE {RUN}", pin=PIN):
        g = step("Guard")
        env = {"PATH": "/usr/bin:/bin", "EVENT": event, "REF": ref, "ATTEMPT": attempt, "RUN_INPUT": run_id,
               "CONFIRM": confirm, "AQD_TEST_SHA": pin, "AQD_PROBE_RUN_ID": RUN}
        self.assertNotIn("secrets.", str(g))
        return subprocess.run(["bash", "-c", g["run"]], env=env, capture_output=True, text=True).returncode

    def test_the_expected_dispatch_passes(self):
        self.assertEqual(self.run_guard(), 0)

    def test_unexpected_event_branch_or_attempt_stops(self):
        for kw in ({"event": "pull_request"}, {"event": "push"}, {"event": "pull_request_target"},
                   {"event": "workflow_run"}, {"ref": "refs/heads/feature"}, {"ref": "refs/pull/3/merge"},
                   {"ref": "refs/tags/main"}, {"ref": "refs/heads/main2"}, {"attempt": "2"}, {"attempt": "10"},
                   {"run_id": "r-fbc73f6490"}, {"confirm": "RUN-LIVE-PROBE r-fbc73f6490"}, {"confirm": ""},
                   {"pin": "0" * 40}, {"pin": "main"}, {"pin": PIN[:12]}):
            with self.subTest(kw=kw):
                self.assertEqual(self.run_guard(**kw), 1)


class SecretPlacementTests(unittest.TestCase):
    def test_each_secret_in_exactly_one_step_and_only_in_the_live_job(self):
        self.assertEqual(sorted(re.findall(r"secrets\.([A-Z_]+)", TEXT)), ["AQD_CC_OAUTH_TOKEN", "AQD_RESULTS_PASSPHRASE"])
        token = [s["name"] for s in STEPS if "secrets.AQD_CC_OAUTH_TOKEN" in str(s)]
        passphrase = [s["name"] for s in STEPS if "secrets.AQD_RESULTS_PASSPHRASE" in str(s)]
        self.assertEqual(token, [step("Write the credentials file")["name"]])
        self.assertEqual(passphrase, [step("Package and encrypt the evidence")["name"]])
        for job in ("mock", "verify-environment"):
            self.assertNotIn("secrets.", str(WF["jobs"][job]))

    def test_every_check_runs_before_the_token_is_written(self):
        creds = index("Write the credentials file")
        for prefix in ("Guard", "Check out exactly the pinned commit", "Verify the owner's approval commit",
                       "Single use of the approval", "Verify the commit, the canonical skill"):
            self.assertLess(index(prefix), creds, prefix)

    def test_checkouts_persist_no_credentials_and_the_live_one_has_the_parent(self):
        for job in WF["jobs"].values():
            for s in job["steps"]:
                if str(s.get("uses", "")).startswith("actions/checkout@"):
                    self.assertIs(s["with"]["persist-credentials"], False)
        self.assertEqual(step("Check out exactly the pinned commit")["with"]["fetch-depth"], 2)
        self.assertIn("--main-workflow", step("Verify the owner's approval commit")["run"])


class EvidenceStepTests(unittest.TestCase):
    def test_no_suppressed_archive_failure(self):
        run = step("Package and encrypt the evidence")["run"]
        self.assertNotIn("|| true", run)
        self.assertNotIn("tar -", run)
        self.assertIn("pack_evidence.py", run)
        self.assertIn("evidence encrypted: COMPLETE", run)
        # the only exit-0 path is the "complete" case
        self.assertRegex(run, r'0\) echo "evidence encrypted: COMPLETE" ;;')
        for code in ("4)", "5)", "*)"):
            line = [l for l in run.splitlines() if l.strip().startswith(code)][0]
            self.assertIn("exit 1", line)

    def test_cleanup_and_upload_run_on_failure_and_upload_only_ciphertext(self):
        for prefix in ("Remove the credentials file", "Package and encrypt the evidence", "Upload the encrypted capture",
                       "Restore the AppArmor"):
            self.assertEqual(step(prefix).get("if"), "always()", prefix)
        self.assertLess(index("Remove the credentials file"), index("Package and encrypt the evidence"))
        up = step("Upload the encrypted capture")["with"]
        self.assertTrue(up["path"].endswith(".gpg"))
        self.assertEqual(up["retention-days"], 1)
        self.assertEqual(WF["jobs"]["mock"]["steps"][-2]["with"]["retention-days"], 3)


if __name__ == "__main__":
    unittest.main()
