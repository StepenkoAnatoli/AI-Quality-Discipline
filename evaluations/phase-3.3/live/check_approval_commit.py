#!/usr/bin/env python3
"""Fail-closed check that the owner's approval exists in the EXACT commit the live job checks out.

    python3 -I check_approval_commit.py --repo DIR --pinned SHA [--main-workflow FILE] [--approval-path PATH]

--approval-path selects the approval file: the probe's (default), SMOKE's (smoke-approval.json, two runs) or the G1
pilot's (pilot-approval.json, six runs). Only these reviewed paths are accepted.

The approval is a one-file commit made by the owner directly on top of the reviewed commit:

    reviewed commit P  (probe-approval.json is the unfilled template; CI green on P)
          |
    approval commit X  (changes ONLY probe-approval.json: approved_by, approved_utc, reviewed_commit = P)

and main's copy of the workflow pins AQD_TEST_SHA = X. Required, or the live job stops before any secret is used:
  * the checkout (HEAD) is X = --pinned;
  * the approval at X is filled: approved_by non-empty, approved_utc "YYYY-MM-DDTHH:MM:SSZ", reviewed_commit 40 hex;
  * X has exactly one parent, and it is reviewed_commit;
  * X changes exactly one path, probe-approval.json, relative to that parent;
  * the approval at the parent is the unfilled template, and its approved_runs (run id, task, arm, model, prompt,
    workspace and CLI SHA-256) are byte-for-byte the values approved at X. The owner fills fields; nothing else;
  * with --main-workflow (main's copy, the file that actually runs): it equals X's copy except that the placeholder
    AQD_TEST_SHA is replaced by X. Any other difference (a weakened guard, a second secret) refuses.
Reasons name fields and paths, never values. Needs the parent commit in the clone (checkout fetch-depth: 2).
"""
import argparse
import json
import re
import subprocess
import sys

APPROVAL_PATH = "evaluations/phase-3.3/live/probe-approval.json"
SMOKE_APPROVAL_PATH = "evaluations/phase-3.3/live/smoke-approval.json"
PILOT_APPROVAL_PATH = "evaluations/phase-3.3/live/pilot-approval.json"
APPROVAL_PATHS = (APPROVAL_PATH, SMOKE_APPROVAL_PATH, PILOT_APPROVAL_PATH)
RUNS_PER_APPROVAL = {APPROVAL_PATH: 1, SMOKE_APPROVAL_PATH: 2, PILOT_APPROVAL_PATH: 6}
WORKFLOW_PATH = ".github/workflows/phase3-cc-smoke.yml"
PLACEHOLDER = 'AQD_TEST_SHA: "0000000000000000000000000000000000000000"'
SHA = re.compile(r"^[0-9a-f]{40}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
OWNER_FIELDS = ("approved_by", "approved_utc", "reviewed_commit")


def _git(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed")
    return out.stdout


def _approval_at(repo, commit, path=APPROVAL_PATH):
    return json.loads(_git(repo, "show", f"{commit}:{path}"))


def check(repo, pinned, main_workflow=None, approval_path=APPROVAL_PATH):
    if approval_path not in APPROVAL_PATHS:
        return ["the approval path is not one of the reviewed approval files"]
    if not isinstance(pinned, str) or not SHA.match(pinned) or pinned == "0" * 40:
        return ["the pinned commit is not a 40-hex SHA"]
    try:
        head = _git(repo, "rev-parse", "HEAD").strip()
        if head != pinned:
            return ["the checkout is not the pinned commit"]
        try:
            approval = _approval_at(repo, head, approval_path)
        except (RuntimeError, ValueError):
            return ["the approval at the pinned commit is missing or not JSON"]
        if not isinstance(approval, dict):
            return ["the approval at the pinned commit is not a JSON object"]
        by, utc, reviewed = (approval.get(k) for k in OWNER_FIELDS)
        reasons = []
        if not isinstance(by, str) or not by.strip():
            reasons.append("approved_by is empty: the pinned commit holds an unfilled template, not an approval")
        if not isinstance(utc, str) or not UTC.match(utc):
            reasons.append("approved_utc is empty or not YYYY-MM-DDTHH:MM:SSZ: unfilled template or malformed")
        if not isinstance(reviewed, str) or not SHA.match(reviewed):
            reasons.append("reviewed_commit is not a 40-hex commit")
        if reasons:
            return reasons
        parents = _git(repo, "rev-list", "--parents", "-n", "1", head).split()[1:]
        if parents != [reviewed]:
            return ["the approval commit's only parent is not reviewed_commit (fetch-depth 2; one-file commit on "
                    "the reviewed head)"]
        changed = [p for p in _git(repo, "diff", "--name-only", "--no-renames", reviewed, head).splitlines() if p]
        if changed != [approval_path]:
            return [f"the approval commit changes more than {approval_path} ({len(changed)} path(s))"]
        try:
            template = _approval_at(repo, reviewed, approval_path)
        except (RuntimeError, ValueError):
            return ["the approval at reviewed_commit is missing or not JSON"]
        if not isinstance(template, dict) or any(template.get(k) not in ("", None) for k in OWNER_FIELDS):
            reasons.append("the approval at reviewed_commit is not the unfilled template")
        want_runs = RUNS_PER_APPROVAL[approval_path]
        if not isinstance(template, dict) or template.get("approved_runs") != approval.get("approved_runs") \
                or not isinstance(approval.get("approved_runs"), list) or len(approval["approved_runs"]) != want_runs:
            reasons.append("approved_runs differ from the reviewed template (run, task, arm, model or a SHA-256)")
        extra = set(approval) - set(template if isinstance(template, dict) else {}) - set(OWNER_FIELDS)
        if extra:
            reasons.append("the approval adds fields that the reviewed template does not have")
        if main_workflow is not None:
            reviewed_wf = _git(repo, "show", f"{head}:{WORKFLOW_PATH}")
            if reviewed_wf.count(PLACEHOLDER) != 1:
                reasons.append("the reviewed workflow does not hold exactly one AQD_TEST_SHA placeholder")
            elif main_workflow != reviewed_wf.replace(PLACEHOLDER, f'AQD_TEST_SHA: "{head}"'):
                reasons.append("main's workflow is not the reviewed workflow with only AQD_TEST_SHA set to the "
                               "pinned commit")
        return reasons
    except RuntimeError as exc:
        return [f"git: {exc}"]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True)
    p.add_argument("--pinned", required=True)
    p.add_argument("--main-workflow")
    p.add_argument("--approval-path", choices=APPROVAL_PATHS, default=APPROVAL_PATH)
    args = p.parse_args(argv)
    main_wf = None
    if args.main_workflow:
        try:
            with open(args.main_workflow, encoding="utf-8") as h:
                main_wf = h.read()
        except OSError:
            print("approval: main's workflow copy is unreadable")
            return 1
    reasons = check(args.repo, args.pinned, main_wf, args.approval_path)
    for r in reasons:
        print(f"approval: {r}")
    print("approval commit: " + ("VERIFIED (one-file owner approval on the reviewed commit)" if not reasons
                                 else "REFUSED"))
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
