#!/usr/bin/env python3
"""Fail-closed check of the GitHub environment that holds the live probe's OAuth secret.

    python3 check_environment.py --environment env.json --branch-policies policies.json --actor LOGIN

Inputs are the public REST responses (GitHub REST "Get an environment" and "List deployment branch policies").
Required, or the live job never starts:
  * administrators cannot bypass the protection rules (can_admins_bypass is false);
  * a required-reviewers rule with at least one reviewer; if self-review is prevented, at least one reviewer must
    be someone other than the person dispatching (or a team), so the run can still be approved;
  * deployments limited to custom branch policies, exactly one: the branch `main`.
Anything missing or of an unexpected shape fails. The report names settings, never secret values.
"""
import argparse
import json
import sys

NAME = "aqd-cc-live-probe"


def check(environment, policies, actor):
    reasons = []
    if not isinstance(environment, dict) or environment.get("name") != NAME:
        return [f"environment {NAME} not found or of an unexpected shape"]
    if environment.get("can_admins_bypass") is not False:
        reasons.append("administrators can bypass the protection rules (turn on 'Prevent administrators from bypassing')")
    rules = environment.get("protection_rules")
    if not isinstance(rules, list):
        return reasons + ["protection_rules missing"]
    review = [r for r in rules if isinstance(r, dict) and r.get("type") == "required_reviewers"]
    if len(review) != 1:
        reasons.append("no required-reviewers rule")
    else:
        reviewers = [r for r in review[0].get("reviewers") or [] if isinstance(r, dict)]
        if not reviewers:
            reasons.append("the required-reviewers rule names no reviewer")
        prevent_self = review[0].get("prevent_self_review")
        if prevent_self is not False and prevent_self is not True:
            reasons.append("prevent_self_review missing")
        others = [r for r in reviewers if r.get("type") == "Team" or
                  (r.get("type") == "User" and (r.get("reviewer") or {}).get("login") not in (None, actor))]
        if prevent_self is True and not others:
            reasons.append("self-review is prevented and the only reviewer is the dispatcher: nobody could approve")
    branch = environment.get("deployment_branch_policy")
    if not isinstance(branch, dict) or branch.get("custom_branch_policies") is not True \
            or branch.get("protected_branches") is not False:
        reasons.append("deployments are not limited to custom branch policies")
    entries = (policies or {}).get("branch_policies") if isinstance(policies, dict) else None
    if not isinstance(entries, list) or [(p.get("name"), p.get("type", "branch")) for p in entries
                                         if isinstance(p, dict)] != [("main", "branch")] or len(entries) != 1:
        reasons.append("the deployment branch policy is not exactly the branch main")
    return reasons


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--environment", required=True)
    p.add_argument("--branch-policies", required=True)
    p.add_argument("--actor", required=True)
    args = p.parse_args(argv)
    loaded = []
    for path in (args.environment, args.branch_policies):
        try:
            with open(path, encoding="utf-8") as h:
                loaded.append(json.load(h))
        except (OSError, ValueError):
            loaded.append(None)
    reasons = check(loaded[0], loaded[1], args.actor)
    for r in reasons:
        print(f"environment: {r}")
    print(f"environment {NAME}: {'protected as required' if not reasons else 'NOT protected as required'}")
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
