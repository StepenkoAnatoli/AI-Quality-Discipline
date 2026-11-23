"""Tests for check_environment.py (shapes per GitHub's REST docs for environments and deployment branch policies)."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_environment as ce  # noqa: E402

OWNER = "owner-login"
ENV = {"id": 1, "name": "aqd-cc-live-probe", "can_admins_bypass": False,
       "protection_rules": [{"id": 2, "type": "required_reviewers", "prevent_self_review": False,
                             "reviewers": [{"type": "User", "reviewer": {"login": OWNER, "id": 9}}]},
                            {"id": 3, "type": "branch_policy"}],
       "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
POLICIES = {"total_count": 1, "branch_policies": [{"id": 4, "name": "main", "type": "branch"}]}


class CheckEnvironmentTests(unittest.TestCase):
    def test_the_required_configuration_passes(self):
        self.assertEqual(ce.check(ENV, POLICIES, OWNER), [])

    def test_admin_bypass_fails(self):
        for value in (True, None):
            env = dict(ENV, can_admins_bypass=value)
            self.assertTrue(ce.check(env, POLICIES, OWNER))

    def test_self_review_prevented_with_the_dispatcher_as_only_reviewer_fails(self):
        env = copy.deepcopy(ENV)
        env["protection_rules"][0]["prevent_self_review"] = True
        self.assertTrue(any("nobody could approve" in r for r in ce.check(env, POLICIES, OWNER)))
        env["protection_rules"][0]["reviewers"].append({"type": "User", "reviewer": {"login": "second-reviewer"}})
        self.assertEqual(ce.check(env, POLICIES, OWNER), [])

    def test_missing_reviewers_or_rule_fails(self):
        env = copy.deepcopy(ENV)
        env["protection_rules"][0]["reviewers"] = []
        self.assertTrue(ce.check(env, POLICIES, OWNER))
        env = dict(ENV, protection_rules=[{"type": "branch_policy"}])
        self.assertTrue(ce.check(env, POLICIES, OWNER))

    def test_any_branch_or_more_than_main_fails(self):
        for policy in (None, {"protected_branches": True, "custom_branch_policies": False},
                       {"protected_branches": False, "custom_branch_policies": False}):
            with self.subTest(policy=policy):
                self.assertTrue(ce.check(dict(ENV, deployment_branch_policy=policy), POLICIES, OWNER))
        for entries in ([], [{"name": "main"}, {"name": "release/*"}], [{"name": "*"}],
                        [{"name": "main", "type": "tag"}]):
            with self.subTest(entries=entries):
                self.assertTrue(ce.check(ENV, {"branch_policies": entries}, OWNER))

    def test_missing_or_foreign_environment_fails(self):
        self.assertTrue(ce.check(None, POLICIES, OWNER))
        self.assertTrue(ce.check(dict(ENV, name="production"), POLICIES, OWNER))
        self.assertTrue(ce.check(ENV, None, OWNER))


if __name__ == "__main__":
    unittest.main()
