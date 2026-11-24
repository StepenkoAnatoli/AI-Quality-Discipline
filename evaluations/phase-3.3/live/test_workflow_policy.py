"""Static and executable checks of the live job in .github/workflows/phase3-cc-smoke.yml. No dispatch, no secret.

The guard step's own shell is executed with unexpected events, branches and attempts; the job condition, secret
placement, step order, evidence packaging and upload settings are asserted on the parsed workflow."""
import json
import os
import re
import subprocess
import tempfile
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


def step(prefix, steps=None):
    found = [s for s in (STEPS if steps is None else steps) if s.get("name", "").startswith(prefix)]
    assert len(found) == 1, prefix
    return found[0]


def index(prefix, steps=None):
    steps = STEPS if steps is None else steps
    return [s.get("name", "") for s in steps].index(step(prefix, steps)["name"])


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


class VerifyEnvironmentJobTests(unittest.TestCase):
    """verify-environment reads the settings with its own job token (anonymous reads were refused, 403, in live
    dispatches 22 and 23). The token is in one step that runs no checkout code; the checker step holds no token."""
    JOB = WF["jobs"]["verify-environment"]

    def steps(self):
        return self.JOB["steps"]

    def test_permissions_are_read_only_and_minimal(self):
        self.assertEqual(self.JOB["permissions"], {"contents": "read", "actions": "read"})

    def test_each_live_mode_checks_its_own_environment(self):
        self.assertIn("inputs.mode == 'live-security-probe' || inputs.mode == 'live-smoke' || "
                      "inputs.mode == 'live-pilot'", self.JOB["if"])
        self.assertEqual(self.JOB["env"]["AQD_ENV_NAME"],
                         "${{ inputs.mode == 'live-smoke' && 'aqd-cc-live-smoke' || inputs.mode == 'live-pilot' && "
                         "'aqd-cc-live-pilot' || 'aqd-cc-live-probe' }}")
        self.assertIn('--name "$AQD_ENV_NAME"', self.steps()[2]["run"])
        self.assertIn('environments/$AQD_ENV_NAME"', self.steps()[0]["run"])

    def test_job_token_only_in_the_read_step_before_any_checkout(self):
        steps = self.steps()
        with_token = [s.get("name") for s in steps if "github.token" in str(s) or "GH_TOKEN" in str(s)]
        self.assertEqual(with_token, [steps[0]["name"]])
        self.assertNotIn("uses", steps[0])
        self.assertNotIn("evaluations/", steps[0]["run"])  # runs no code from the checkout
        self.assertNotIn("secrets.", str(self.JOB))
        self.assertTrue(str(steps[1].get("uses", "")).startswith("actions/checkout@"))
        self.assertIn("check_environment.py", steps[2]["run"])

    def run_read_step(self, code, body):
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "bin")
            os.mkdir(fake)
            with open(os.path.join(fake, "curl"), "w") as h:  # writes the body to -o, prints the code for -w
                h.write('#!/bin/bash\nprintf "%s\\n" "$*" >>"$RUNNER_TEMP/curl-args"\n'
                        'while [[ $# -gt 0 ]]; do [[ "$1" == -o ]] && { printf %s "$FAKE_BODY" >"$2"; shift; }; '
                        'shift; done\nprintf %s "$FAKE_CODE"\n')
            os.chmod(os.path.join(fake, "curl"), 0o755)
            env = {"PATH": fake + ":/usr/bin:/bin", "RUNNER_TEMP": tmp, "GH_TOKEN": "ghs_fake", "REPO": "o/r",
                   "AQD_ENV_NAME": "aqd-cc-live-probe",
                   "FAKE_CODE": code, "FAKE_BODY": body}
            out = subprocess.run(["bash", "-c", self.steps()[0]["run"]], env=env, capture_output=True, text=True)
            files = {n: open(os.path.join(tmp, "aqd-env", n)).read() for n in ("env.json", "policies.json")}
            calls = open(os.path.join(tmp, "curl-args")).read().splitlines()
            self.assertEqual(len(calls), 2)
            for c in calls:  # both reads authenticated with the job token
                self.assertIn("Authorization: Bearer ghs_fake", c)
            self.assertTrue(calls[0].endswith("/repos/o/r/environments/aqd-cc-live-probe"))
            self.assertTrue(calls[1].endswith("/environments/aqd-cc-live-probe/deployment-branch-policies"))
            return out, files

    def test_a_refused_read_leaves_an_empty_object_and_says_why(self):
        out, files = self.run_read_step("403", '{"message":"API rate limit exceeded"}')
        self.assertEqual(out.returncode, 0)
        self.assertEqual(files, {"env.json": "{}\n", "policies.json": "{}\n"})
        self.assertIn("HTTP 403", out.stdout)
        self.assertIn("rate limit", out.stdout)

    def test_a_200_read_keeps_the_body(self):
        out, files = self.run_read_step("200", '{"name":"aqd-cc-live-probe"}')
        self.assertEqual(out.returncode, 0)
        self.assertEqual(files["env.json"], '{"name":"aqd-cc-live-probe"}')
        self.assertNotIn("ghs_fake", out.stdout + out.stderr)


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
        # once in each live job: probe, SMOKE and pilot (each job's own environment holds its own secrets)
        self.assertEqual(sorted(re.findall(r"secrets\.([A-Z_]+)", TEXT)),
                         ["AQD_CC_OAUTH_TOKEN"] * 3 + ["AQD_RESULTS_PASSPHRASE"] * 3)
        self.assertEqual(sorted(WF["jobs"]), ["live-pilot", "live-security-probe", "live-smoke", "mock",
                                              "verify-environment"])
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


class ApprovalGateTests(unittest.TestCase):
    def test_checker_comes_from_the_reviewed_parent(self):
        run = step("Verify the owner's approval commit")["run"]
        self.assertIn('git show "$AQD_TEST_SHA^:evaluations/phase-3.3/live/check_approval_commit.py"', run)
        self.assertNotIn("python3 -I evaluations/phase-3.3/live/check_approval_commit.py", run)

    def test_packaging_with_the_passphrase_requires_the_verified_marker(self):
        approve = step("Verify the owner's approval commit")["run"]
        lines = [l.strip() for l in approve.splitlines() if l.strip() and not l.strip().startswith("#")]
        self.assertTrue(lines[-1].startswith("printf") and "aqd-approval-verified" in lines[-1])  # last: only on success
        pack = step("Package and encrypt the evidence")["run"]
        gate, run_packer = pack.index("aqd-approval-verified"), pack.index("sudo python3")
        self.assertLess(gate, run_packer)

    def test_packaging_step_refuses_without_the_marker(self):
        run = step("Package and encrypt the evidence")["run"]
        head = run[:run.index("p=\"$RUNNER_TEMP/aqd-pack\"")]
        with tempfile.TemporaryDirectory() as t:
            env = {"PATH": "/usr/bin:/bin", "AQD_PASS": "x" * 40, "AQD_TEST_SHA": PIN, "RUNNER_TEMP": t,
                   "GITHUB_WORKSPACE": t}
            self.assertEqual(subprocess.run(["bash", "-c", head], env=env, capture_output=True).returncode, 1)
            with open(os.path.join(t, "aqd-approval-verified"), "w") as h:
                h.write("0" * 40 + "\n")           # marker for another commit
            self.assertEqual(subprocess.run(["bash", "-c", head], env=env, capture_output=True).returncode, 1)


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


SMOKE = WF["jobs"]["live-smoke"]
SMOKE_STEPS = SMOKE["steps"]
SMOKE_RUN_IDS = WF["env"]["AQD_SMOKE_RUN_IDS"]
SMOKE_SCHEDULE = json.load(open(os.path.join(ROOT, "evaluations", "phase-3.3", "live", "smoke-schedule.json"),
                                encoding="utf-8"))


def sstep(prefix):
    return step(prefix, SMOKE_STEPS)


def sindex(prefix):
    return index(prefix, SMOKE_STEPS)


class SmokeJobTests(unittest.TestCase):
    """The live-smoke job (SMOKE-PROPOSAL.md): the probe job's gates, its own environment, approval and runs."""

    def test_job_condition_environment_and_permissions(self):
        cond = SMOKE["if"]
        for part in ("github.event_name == 'workflow_dispatch'", "inputs.mode == 'live-smoke'",
                     "github.ref == 'refs/heads/main'", "github.run_attempt == 1"):
            self.assertIn(part, cond)
        self.assertNotIn("||", cond)
        self.assertEqual(SMOKE["environment"], "aqd-cc-live-smoke")
        self.assertEqual(sorted(SMOKE["needs"]), ["mock", "verify-environment"])
        self.assertEqual(SMOKE["permissions"], {"contents": "read", "deployments": "read"})
        self.assertNotIn("aqd-cc-live-probe", str(SMOKE))
        self.assertNotIn("AQD_PROBE_RUN_ID", str(SMOKE))

    def test_same_steps_and_actions_as_the_reviewed_probe_job(self):
        self.assertEqual(len(SMOKE_STEPS), len(STEPS))
        self.assertEqual([s.get("uses") for s in SMOKE_STEPS], [s.get("uses") for s in STEPS])
        self.assertEqual([s.get("if") for s in SMOKE_STEPS], [s.get("if") for s in STEPS])

    def test_the_run_ids_are_the_committed_schedule_in_order(self):
        ordered = [r["run_id"] for r in sorted(SMOKE_SCHEDULE["runs"], key=lambda r: r["order"])]
        self.assertEqual(SMOKE_RUN_IDS.split(" "), ordered)

    def run_guard(self, event="workflow_dispatch", ref="refs/heads/main", attempt="1", run_id=SMOKE_RUN_IDS,
                  confirm=f"RUN-LIVE-SMOKE {SMOKE_RUN_IDS}", pin=PIN):
        g = sstep("Guard")
        env = {"PATH": "/usr/bin:/bin", "EVENT": event, "REF": ref, "ATTEMPT": attempt, "RUN_INPUT": run_id,
               "CONFIRM": confirm, "AQD_TEST_SHA": pin, "AQD_SMOKE_RUN_IDS": SMOKE_RUN_IDS}
        self.assertNotIn("secrets.", str(g))
        return subprocess.run(["bash", "-c", g["run"]], env=env, capture_output=True, text=True).returncode

    def test_guard(self):
        self.assertEqual(self.run_guard(), 0)
        first, second = SMOKE_RUN_IDS.split(" ")
        for kw in ({"event": "pull_request"}, {"ref": "refs/heads/feature"}, {"attempt": "2"}, {"pin": "0" * 40},
                   {"run_id": first}, {"run_id": f"{second} {first}"}, {"run_id": RUN},
                   {"confirm": f"RUN-LIVE-PROBE {RUN}"}, {"confirm": f"RUN-LIVE-SMOKE {first}"}, {"confirm": ""}):
            with self.subTest(kw=kw):
                self.assertEqual(self.run_guard(**kw), 1)

    def test_each_secret_in_exactly_one_step_of_this_job(self):
        token = [s["name"] for s in SMOKE_STEPS if "secrets.AQD_CC_OAUTH_TOKEN" in str(s)]
        passphrase = [s["name"] for s in SMOKE_STEPS if "secrets.AQD_RESULTS_PASSPHRASE" in str(s)]
        self.assertEqual(token, [sstep("Write the credentials file")["name"]])
        self.assertEqual(passphrase, [sstep("Package and encrypt the evidence")["name"]])

    def test_every_check_runs_before_the_token_is_written(self):
        creds = sindex("Write the credentials file")
        for prefix in ("Guard", "Check out exactly the pinned commit", "Verify the owner's approval commit",
                       "Single use of the approval", "Verify the commit, the canonical skill"):
            self.assertLess(sindex(prefix), creds, prefix)
        self.assertEqual(sstep("Check out exactly the pinned commit")["with"]["fetch-depth"], 2)

    def test_the_smoke_approval_file_the_reviewed_checker_and_the_marker(self):
        run = sstep("Verify the owner's approval commit")["run"]
        self.assertIn('git show "$AQD_TEST_SHA^:evaluations/phase-3.3/live/check_approval_commit.py"', run)
        self.assertIn("--main-workflow", run)
        self.assertIn("--approval-path evaluations/phase-3.3/live/smoke-approval.json", run)
        lines = [l.strip() for l in run.splitlines() if l.strip() and not l.strip().startswith("#")]
        self.assertTrue(lines[-1].startswith("printf") and "aqd-approval-verified" in lines[-1])

    def test_single_use_of_the_smoke_environment(self):
        run = sstep("Single use of the approval")["run"]
        self.assertIn("deployments?environment=aqd-cc-live-smoke&per_page=100", run)
        self.assertIn("--name aqd-cc-live-smoke", run)

    def test_runs_the_smoke_script_and_packs_both_runs_behind_the_marker(self):
        self.assertIn("run-live-smoke.sh live", sstep("Run the two approved SMOKE runs")["run"])
        pack = sstep("Package and encrypt the evidence")["run"]
        self.assertIn("--kind smoke", pack)
        self.assertLess(pack.index("aqd-approval-verified"), pack.index("sudo python3"))
        self.assertNotIn("|| true", pack)
        self.assertRegex(pack, r'0\) echo "evidence encrypted: COMPLETE" ;;')
        head = pack[:pack.index("p=\"$RUNNER_TEMP/aqd-pack\"")]
        with tempfile.TemporaryDirectory() as t:
            env = {"PATH": "/usr/bin:/bin", "AQD_PASS": "x" * 40, "AQD_TEST_SHA": PIN, "RUNNER_TEMP": t,
                   "GITHUB_WORKSPACE": t}
            self.assertEqual(subprocess.run(["bash", "-c", head], env=env, capture_output=True).returncode, 1)

    def test_cleanup_and_upload_only_ciphertext(self):
        for prefix in ("Remove the credentials file", "Package and encrypt the evidence", "Upload the encrypted capture",
                       "Restore the AppArmor"):
            self.assertEqual(sstep(prefix).get("if"), "always()", prefix)
        up = sstep("Upload the encrypted capture")["with"]
        self.assertEqual(up["name"], "aqd-cc-live-smoke-encrypted")
        self.assertTrue(up["path"].endswith("aqd-cc-live-smoke.tar.gz.gpg"))
        self.assertEqual(up["retention-days"], 1)

    def test_the_mock_job_rehearses_the_smoke_run(self):
        names = [s.get("name", "") for s in WF["jobs"]["mock"]["steps"]]
        smoke = [n for n in names if n.startswith("Rehearsal of the two-arm SMOKE run")]
        self.assertEqual(len(smoke), 1)
        self.assertLess(names.index(smoke[0]), names.index("Keep only redacted summaries"))


PILOT = WF["jobs"]["live-pilot"]
PILOT_STEPS = PILOT["steps"]
PILOT_RUN_IDS = WF["env"]["AQD_PILOT_RUN_IDS"]
PILOT_SCHEDULE = json.load(open(os.path.join(ROOT, "evaluations", "phase-3.3", "live", "pilot-schedule.json"),
                                encoding="utf-8"))


def pstep(prefix):
    return step(prefix, PILOT_STEPS)


def pindex(prefix):
    return index(prefix, PILOT_STEPS)


class PilotJobTests(unittest.TestCase):
    """The live-pilot job (PILOT-G1.md): the same gates, its own environment, approval and six runs."""

    def test_job_condition_environment_and_permissions(self):
        cond = PILOT["if"]
        for part in ("github.event_name == 'workflow_dispatch'", "inputs.mode == 'live-pilot'",
                     "github.ref == 'refs/heads/main'", "github.run_attempt == 1"):
            self.assertIn(part, cond)
        self.assertNotIn("||", cond)
        self.assertEqual(PILOT["environment"], "aqd-cc-live-pilot")
        self.assertEqual(sorted(PILOT["needs"]), ["mock", "verify-environment"])
        self.assertEqual(PILOT["permissions"], {"contents": "read", "deployments": "read"})
        self.assertNotIn("aqd-cc-live-probe", str(PILOT))
        self.assertNotIn("AQD_PROBE_RUN_ID", str(PILOT))

    def test_same_steps_and_actions_as_the_reviewed_probe_job(self):
        self.assertEqual(len(PILOT_STEPS), len(STEPS))
        self.assertEqual([s.get("uses") for s in PILOT_STEPS], [s.get("uses") for s in STEPS])
        self.assertEqual([s.get("if") for s in PILOT_STEPS], [s.get("if") for s in STEPS])

    def test_the_run_ids_are_the_committed_schedule_in_order(self):
        ordered = [r["run_id"] for r in sorted(PILOT_SCHEDULE["runs"], key=lambda r: r["order"])]
        self.assertEqual(PILOT_RUN_IDS.split(" "), ordered)

    def run_guard(self, event="workflow_dispatch", ref="refs/heads/main", attempt="1", run_id=PILOT_RUN_IDS,
                  confirm=f"RUN-LIVE-PILOT {PILOT_RUN_IDS}", pin=PIN):
        g = pstep("Guard")
        env = {"PATH": "/usr/bin:/bin", "EVENT": event, "REF": ref, "ATTEMPT": attempt, "RUN_INPUT": run_id,
               "CONFIRM": confirm, "AQD_TEST_SHA": pin, "AQD_PILOT_RUN_IDS": PILOT_RUN_IDS}
        self.assertNotIn("secrets.", str(g))
        return subprocess.run(["bash", "-c", g["run"]], env=env, capture_output=True, text=True).returncode

    def test_guard(self):
        self.assertEqual(self.run_guard(), 0)
        ids = PILOT_RUN_IDS.split(" ")
        first, second = ids[0], " ".join(reversed(ids))
        for kw in ({"event": "pull_request"}, {"ref": "refs/heads/feature"}, {"attempt": "2"}, {"pin": "0" * 40},
                   {"run_id": first}, {"run_id": second}, {"run_id": RUN},
                   {"confirm": f"RUN-LIVE-PROBE {RUN}"}, {"confirm": f"RUN-LIVE-PILOT {first}"}, {"confirm": ""}):
            with self.subTest(kw=kw):
                self.assertEqual(self.run_guard(**kw), 1)

    def test_each_secret_in_exactly_one_step_of_this_job(self):
        token = [s["name"] for s in PILOT_STEPS if "secrets.AQD_CC_OAUTH_TOKEN" in str(s)]
        passphrase = [s["name"] for s in PILOT_STEPS if "secrets.AQD_RESULTS_PASSPHRASE" in str(s)]
        self.assertEqual(token, [pstep("Write the credentials file")["name"]])
        self.assertEqual(passphrase, [pstep("Package and encrypt the evidence")["name"]])

    def test_every_check_runs_before_the_token_is_written(self):
        creds = pindex("Write the credentials file")
        for prefix in ("Guard", "Check out exactly the pinned commit", "Verify the owner's approval commit",
                       "Single use of the approval", "Verify the commit, the canonical skill"):
            self.assertLess(pindex(prefix), creds, prefix)
        self.assertEqual(pstep("Check out exactly the pinned commit")["with"]["fetch-depth"], 2)

    def test_the_pilot_approval_file_the_reviewed_checker_and_the_marker(self):
        run = pstep("Verify the owner's approval commit")["run"]
        self.assertIn('git show "$AQD_TEST_SHA^:evaluations/phase-3.3/live/check_approval_commit.py"', run)
        self.assertIn("--main-workflow", run)
        self.assertIn("--approval-path evaluations/phase-3.3/live/pilot-approval.json", run)
        lines = [l.strip() for l in run.splitlines() if l.strip() and not l.strip().startswith("#")]
        self.assertTrue(lines[-1].startswith("printf") and "aqd-approval-verified" in lines[-1])

    def test_single_use_of_the_pilot_environment(self):
        run = pstep("Single use of the approval")["run"]
        self.assertIn("deployments?environment=aqd-cc-live-pilot&per_page=100", run)
        self.assertIn("--name aqd-cc-live-pilot", run)

    def test_runs_the_pilot_script_and_packs_all_runs_behind_the_marker(self):
        self.assertIn("run-live-pilot.sh live", pstep("Run the six approved pilot runs")["run"])
        pack = pstep("Package and encrypt the evidence")["run"]
        self.assertIn("--kind pilot", pack)
        self.assertLess(pack.index("aqd-approval-verified"), pack.index("sudo python3"))
        self.assertNotIn("|| true", pack)
        self.assertRegex(pack, r'0\) echo "evidence encrypted: COMPLETE" ;;')
        head = pack[:pack.index("p=\"$RUNNER_TEMP/aqd-pack\"")]
        with tempfile.TemporaryDirectory() as t:
            env = {"PATH": "/usr/bin:/bin", "AQD_PASS": "x" * 40, "AQD_TEST_SHA": PIN, "RUNNER_TEMP": t,
                   "GITHUB_WORKSPACE": t}
            self.assertEqual(subprocess.run(["bash", "-c", head], env=env, capture_output=True).returncode, 1)

    def test_cleanup_and_upload_only_ciphertext(self):
        for prefix in ("Remove the credentials file", "Package and encrypt the evidence", "Upload the encrypted capture",
                       "Restore the AppArmor"):
            self.assertEqual(pstep(prefix).get("if"), "always()", prefix)
        up = pstep("Upload the encrypted capture")["with"]
        self.assertEqual(up["name"], "aqd-cc-live-pilot-encrypted")
        self.assertTrue(up["path"].endswith("aqd-cc-live-pilot.tar.gz.gpg"))
        self.assertEqual(up["retention-days"], 1)

    def test_the_mock_job_rehearses_the_pilot_run(self):
        names = [s.get("name", "") for s in WF["jobs"]["mock"]["steps"]]
        pilot = [n for n in names if n.startswith("Rehearsal of the G1 invocation pilot")]
        self.assertEqual(len(pilot), 1)
        self.assertLess(names.index(pilot[0]), names.index("Keep only redacted summaries"))



    def test_the_pilot_job_has_room_for_six_runs(self):
        self.assertEqual(PILOT["timeout-minutes"], 330)
        self.assertLessEqual(PILOT["timeout-minutes"], 360)  # GitHub-hosted jobs stop at 6 hours


if __name__ == "__main__":
    unittest.main()
