"""Tests for check_approval_commit.py: the owner's approval must exist in the EXACT commit the live job checks out.

Regression: at 15069bd the documented procedure filled probe-approval.json in a bootstrap commit on main, while the
live job checks out the earlier, pinned AQD_TEST_SHA, whose approval is the unfilled template. The launcher refuses
that (an unfilled template is not an approval), so the documented procedure could never run. These tests build
throwaway git repositories; no network, no credential, no model.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

LIVE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "..", "..", "phase-3.2", "harness"))
import cc_adapter  # noqa: E402
import check_approval_commit as cac  # noqa: E402

APPROVAL = cac.APPROVAL_PATH
WORKFLOW = cac.WORKFLOW_PATH
COMMITTED = json.load(open(os.path.join(LIVE, "probe-approval.json"), encoding="utf-8"))
# On the reviewed commit P the committed file is the unfilled template. On the owner's approval commit X (the commit
# that the mock dispatch and the live job check out) the same file is filled. These tests need the template either way.
TEMPLATE = dict(COMMITTED, approved_by="", approved_utc="", reviewed_commit="")
WORKFLOW_TEXT = open(os.path.join(LIVE, "..", "..", "..", WORKFLOW), encoding="utf-8").read()


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


def write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as h:
        h.write(text)


def filled(reviewed, **override):
    a = json.loads(json.dumps(TEMPLATE))
    a.update(approved_by="owner-login", approved_utc="2026-11-24T09:00:00Z", reviewed_commit=reviewed)
    a.update(override)
    return json.dumps(a, indent=2) + "\n"


class ApprovalCommitTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        git(self.repo, "init", "-q", "-b", "work")
        write(self.repo, APPROVAL, json.dumps(TEMPLATE, indent=2) + "\n")
        write(self.repo, "evaluations/phase-3.2/tasks/PROBE-CC/project/TASK.md", "run sh probe.sh\n")
        write(self.repo, WORKFLOW, WORKFLOW_TEXT)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "reviewed head")
        self.reviewed = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        shutil.rmtree(self.repo)

    def approve(self, text=None, extra=None):
        write(self.repo, APPROVAL, text if text is not None else filled(self.reviewed))
        for rel, body in (extra or {}).items():
            write(self.repo, rel, body)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "owner approval")
        return git(self.repo, "rev-parse", "HEAD")

    def check(self, pinned, main_workflow=None):
        return cac.check(self.repo, pinned, main_workflow)

    # 1 + 2: the 15069bd procedure, reproduced
    def test_regression_approval_only_on_main_is_refused_at_the_pinned_commit(self):
        # main gets the filled approval; the live job still checks out the reviewed (template) commit
        git(self.repo, "checkout", "-q", "-b", "main")
        self.approve()
        git(self.repo, "checkout", "-q", self.reviewed)
        reasons = self.check(self.reviewed)
        self.assertTrue(any("unfilled" in r for r in reasons), reasons)
        # and the launcher's own check refuses the file it would install from that checkout
        data = json.load(open(os.path.join(self.repo, APPROVAL), encoding="utf-8"))
        entry = data["approved_runs"][0]
        launcher = cc_adapter.check_approval(data, **{k: entry[k] for k in cc_adapter.APPROVAL_KEYS})
        self.assertTrue(launcher and "unfilled template" in launcher[0], launcher)

    def test_the_committed_file_is_the_unfilled_template_or_a_complete_owner_approval(self):
        # P: all three owner fields empty. X: all three filled and well-formed, never half-filled. That X is a one-file
        # child of reviewed_commit is checked by the live job (check_approval_commit.py from the reviewed parent).
        by, utc, reviewed = (COMMITTED[k] for k in cac.OWNER_FIELDS)
        if (by, utc, reviewed) != ("", "", ""):
            self.assertTrue(isinstance(by, str) and by.strip(), "approved_by")
            self.assertRegex(utc, cac.UTC)
            self.assertRegex(reviewed, cac.SHA)
        self.assertEqual(set(COMMITTED), {"approved_runs", "note", *cac.OWNER_FIELDS})

    def test_an_owner_approval_commit_on_the_reviewed_head_passes(self):
        pinned = self.approve()
        self.assertEqual(self.check(pinned), [])
        data = json.load(open(os.path.join(self.repo, APPROVAL), encoding="utf-8"))
        entry = data["approved_runs"][0]
        self.assertEqual(cc_adapter.check_approval(data, **{k: entry[k] for k in cc_adapter.APPROVAL_KEYS}), [])

    def test_checkout_must_be_the_pinned_commit(self):
        self.approve()
        self.assertTrue(any("not the pinned" in r for r in self.check(self.reviewed)))

    # 3: wrong run / changed approved values
    def test_approval_naming_another_run_is_refused(self):
        a = json.loads(filled(self.reviewed))
        a["approved_runs"][0]["run_id"] = "r-fbc73f6490"
        pinned = self.approve(json.dumps(a))
        self.assertTrue(any("approved_runs" in r for r in self.check(pinned)))

    # 4: prompt / workspace / binary hash changed in the approval, or a reviewed file changed alongside it
    def test_changed_hashes_in_the_approval_are_refused(self):
        for key in ("prompt_sha256", "workspace_sha256", "cli_sha256", "model", "group", "task"):
            with self.subTest(key=key):
                git(self.repo, "checkout", "-q", "-B", "work", self.reviewed)
                a = json.loads(filled(self.reviewed))
                a["approved_runs"][0][key] = "0" * 64
                pinned = self.approve(json.dumps(a))
                self.assertTrue(any("approved_runs" in r for r in self.check(pinned)))

    def test_any_other_file_in_the_approval_commit_is_refused(self):
        pinned = self.approve(extra={"evaluations/phase-3.2/tasks/PROBE-CC/project/TASK.md": "cat ~/.claude/*\n"})
        self.assertTrue(any("changes more than" in r for r in self.check(pinned)))

    def test_reviewed_commit_must_be_the_parent(self):
        for bad in ("", "f" * 40, self.reviewed[:12]):
            with self.subTest(bad=bad):
                git(self.repo, "checkout", "-q", "-B", "work", self.reviewed)
                pinned = self.approve(filled(bad))
                self.assertTrue(self.check(pinned))

    def test_two_step_approval_is_refused(self):
        # code change, then approval on top: the approval's parent is not the reviewed commit
        write(self.repo, "evaluations/phase-3.2/tasks/PROBE-CC/project/TASK.md", "changed\n")
        git(self.repo, "commit", "-qam", "unreviewed change")
        pinned = self.approve(filled(self.reviewed))
        self.assertTrue(any("parent" in r for r in self.check(pinned)))

    def test_missing_or_malformed_approver_fields_are_refused(self):
        for override in ({"approved_by": " "}, {"approved_utc": ""}, {"approved_utc": "yesterday"},
                         {"approved_utc": "2026-11-24 09:00"}, {"approved_by": None}):
            with self.subTest(override=override):
                git(self.repo, "checkout", "-q", "-B", "work", self.reviewed)
                pinned = self.approve(filled(self.reviewed, **override))
                self.assertTrue(self.check(pinned))

    def test_unparseable_approval_is_refused(self):
        pinned = self.approve("{not json")
        self.assertTrue(self.check(pinned))

    # the workflow that actually runs (main's copy) must be the reviewed one with only AQD_TEST_SHA pinned
    def test_main_workflow_must_equal_the_reviewed_one_except_the_pin(self):
        pinned = self.approve()
        placeholder = 'AQD_TEST_SHA: "0000000000000000000000000000000000000000"'
        self.assertIn(placeholder, WORKFLOW_TEXT)
        good = WORKFLOW_TEXT.replace(placeholder, f'AQD_TEST_SHA: "{pinned}"')
        self.assertEqual(self.check(pinned, good), [])
        for bad in (WORKFLOW_TEXT,                                                   # not pinned
                    WORKFLOW_TEXT.replace(placeholder, f'AQD_TEST_SHA: "{self.reviewed}"'),  # pinned elsewhere
                    good.replace("github.run_attempt == 1", "true"),                # guard weakened
                    good + "\n# trailing edit\n"):
            with self.subTest():
                self.assertTrue(any("workflow" in r for r in self.check(pinned, bad)))

    def test_cli_exit_codes(self):
        pinned = self.approve()
        ok = subprocess.run([sys.executable, "-I", os.path.join(LIVE, "check_approval_commit.py"), "--repo", self.repo,
                             "--pinned", pinned], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        bad = subprocess.run([sys.executable, "-I", os.path.join(LIVE, "check_approval_commit.py"), "--repo",
                              self.repo, "--pinned", self.reviewed], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertNotIn("owner-login", bad.stdout + bad.stderr)


if __name__ == "__main__":
    unittest.main()
