"""Local tests for the Phase 3.2 harness (standard library only).

Run from the repository root:
    python -m unittest discover -s evaluations/phase-3.2/tests -v
These tests never start OpenCode and never contact a model endpoint.
"""
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout

PHASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HARNESS = os.path.join(PHASE, "harness")
REPO = os.path.abspath(os.path.join(PHASE, "..", ".."))
sys.path.insert(0, HARNESS)

import aqd_common  # noqa: E402
import analyze  # noqa: E402
import api_checks  # noqa: E402
import blind_packet  # noqa: E402
import drive_session  # noqa: E402
import export_checks  # noqa: E402
import manifest  # noqa: E402
import run_status  # noqa: E402
import schedule  # noqa: E402
import score_run  # noqa: E402

CLAUDE = "anthropic/claude-sonnet-5-5"
GROK = "xai/grok-test#high"

SKILL_MD = open(os.path.join(REPO, "skills", "code-discipline", "SKILL.md"), encoding="utf-8").read()
SKILL_BODY = aqd_common.skill_body(SKILL_MD)


def strip_jsonc(text):
    return json.loads("\n".join(line for line in text.splitlines() if not line.strip().startswith("//")))


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aqd-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ConfigTests(unittest.TestCase):
    def test_project_config_shape(self):
        with open(os.path.join(PHASE, "config", "opencode.jsonc"), encoding="utf-8") as h:
            config = strip_jsonc(h.read())
        self.assertEqual(config["$schema"], "https://opencode.ai/config.json")
        self.assertEqual(set(config), {"$schema", "permissions"})
        for rule in config["permissions"]:
            self.assertEqual(set(rule), {"action", "resource", "effect"})
            self.assertIn(rule["effect"], ("allow", "deny", "ask"))
        self.assertNotIn("ask", [r["effect"] for r in config["permissions"]], "an ask rule would stall a non-interactive run")
        skill_rules = [(r["resource"], r["effect"]) for r in config["permissions"] if r["action"] == "skill"]
        self.assertEqual(skill_rules, [("*", "deny")])
        # The control agent reads this file: it must not name the skill under test.
        self.assertNotIn("discipline", json.dumps(config).lower())

    def test_global_config_shape(self):
        with open(os.path.join(PHASE, "config", "global-opencode.jsonc"), encoding="utf-8") as h:
            self.assertEqual(strip_jsonc(h.read()), {"$schema": "https://opencode.ai/config.json", "update": "disable"})

    def test_skill_sentinels_are_in_the_canonical_skill(self):
        self.assertTrue(aqd_common.contains_all_sentinels(SKILL_BODY))
        self.assertFalse(SKILL_BODY.startswith("---"))


class ManifestTests(TempDirTest):
    def build(self, task):
        data = manifest.build(PHASE, task, "deadbeef")
        dest = os.path.join(self.tmp, task)
        manifest.materialize(PHASE, data, dest)
        return data, dest

    def test_sources_match_allowlist(self):
        self.assertEqual(manifest.check_sources(PHASE), [])

    def test_manifest_is_valid_json_with_categories(self):
        data, _ = self.build("NEW-03")
        text = json.dumps(data)
        self.assertEqual(json.loads(text)["kind"], "aqd-phase-3.2-project-manifest")
        paths = {f["path"]: f["category"] for f in data["files"]}
        self.assertEqual(paths["importer/csv_import.py"], "mutable")
        self.assertEqual(paths["sample_data/excel export (semicolon).csv"], "immutable")
        self.assertEqual(paths["opencode.jsonc"], "immutable")
        self.assertIn("tests/baseline", data["protected_dirs"])

    def test_pre_phase_is_exact_and_post_phase_classifies(self):
        data, tree = self.build("NEW-03")
        self.assertTrue(manifest.verify(data, tree, "pre")["integrity_ok"])
        with open(os.path.join(tree, "importer", "csv_import.py"), "a", encoding="utf-8") as h:
            h.write("# changed\n")
        os.makedirs(os.path.join(tree, "tests", "additive", "__pycache__"))
        open(os.path.join(tree, "tests", "additive", "test_new.py"), "w").close()
        open(os.path.join(tree, "tests", "additive", "__pycache__", "x.pyc"), "w").close()
        open(os.path.join(tree, "scratch notes.txt"), "w").close()
        self.assertFalse(manifest.verify(data, tree, "pre")["integrity_ok"])
        report = manifest.verify(data, tree, "post")
        self.assertTrue(report["integrity_ok"])
        f = report["findings"]
        self.assertEqual(f["mutable_changed"], ["importer/csv_import.py"])
        self.assertIn("tests/additive/test_new.py", f["additive_new"])
        self.assertEqual(f["unexpected"], ["scratch notes.txt"])

    def test_post_phase_detects_immutable_change_deletion_and_symlink(self):
        data, tree = self.build("NEW-03")
        sample = os.path.join(tree, "sample_data", "excel export (semicolon).csv")
        with open(sample, "ab") as h:
            h.write(b"x")
        os.remove(os.path.join(tree, "tests", "baseline", "test_import_baseline.py"))
        report = manifest.verify(data, tree, "post")
        self.assertFalse(report["integrity_ok"])
        self.assertEqual(report["findings"]["immutable_modified"], ["sample_data/excel export (semicolon).csv"])
        self.assertEqual(report["findings"]["immutable_missing"], ["tests/baseline/test_import_baseline.py"])
        if hasattr(os, "symlink"):
            data2, tree2 = self.build("NEW-01")
            target = os.path.join(tree2, "webhooks", "store.py")
            os.remove(target)
            try:
                os.symlink(os.path.join(tree2, "webhooks", "handler.py"), target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not permitted on this platform")
            report2 = manifest.verify(data2, tree2, "post")
            self.assertFalse(report2["integrity_ok"])
            self.assertIn("webhooks/store.py", report2["findings"]["symlink"])

    def test_categories_output_is_nul_delimited_dirs_first(self):
        data = manifest.build(PHASE, "NEW-03")
        path = os.path.join(self.tmp, "m.json")
        with open(path, "w", encoding="utf-8") as h:
            json.dump(data, h)
        out = subprocess.run([sys.executable, os.path.join(HARNESS, "manifest.py"), "categories", "--manifest", path],
                             stdout=subprocess.PIPE, check=True).stdout
        fields = out.split(b"\0")[:-1]
        pairs = list(zip(fields[0::2], fields[1::2]))
        kinds = [k.decode() for k, _ in pairs]
        first_file = next(i for i, k in enumerate(kinds) if not k.startswith("dir"))
        self.assertTrue(all(k.startswith("dir") for k in kinds[:first_file]))
        self.assertTrue(all(not k.startswith("dir") for k in kinds[first_file:]))
        self.assertIn((b"dir-protected", b"tests/baseline"), pairs)
        self.assertIn((b"dir-additive", b"tests/additive"), pairs)
        self.assertIn((b"immutable", "sample_data/excel export (semicolon).csv".encode()), pairs)

    def test_unsafe_allowlist_path_rejected(self):
        with self.assertRaises(manifest.UsageError):
            manifest._safe_rel("../outside")


class PreregisteredInputsTests(unittest.TestCase):
    """The prompts and starting workspaces are frozen; changing one must be a recorded decision."""

    EXPECTED = {
        "NEW-01": ("c64501497fc0a83d2d5236685dd26425ba92deb5f5b4bf5dadd5f06e70c9875c", "f14175ed14d5086a770b98b4bfd7b4e309b94d9d8a16a5a7aad4307550ae3f65"),
        "NEW-02": ("9c4bde140efbacabf564f3307aa16955efb869d0dc6a3b354bb8322a727a543f", "ae420d1d9c621e4ad259dd1e2837245cd7f720a55bce08b74e1e21163eb96d58"),
        "NEW-03": ("a5764db416e9848f7b6d51f06948b5110a6785013903260892942d3a042f649b", "cd61f2a29fd90040dc048b44fa424dd6fe8368f6cd7dac491b8ccdf917b4cf04"),
        "NEW-04": ("a50a09d169767c51111c1dbd7729c2ee401791541ba21b9ce5237e6240594b93", "b8ee898b84df9754e2b6b991e347835889e864550470599e68c699155589ceb2"),
    }

    def test_prompt_and_workspace_hashes(self):
        for task, (prompt, workspace) in self.EXPECTED.items():
            with self.subTest(task=task):
                data = manifest.build(PHASE, task)
                self.assertEqual(next(f["sha256"] for f in data["files"] if f["path"] == "TASK.md"), prompt)
                self.assertEqual(data["workspace_sha256"], workspace)

    def test_prompts_do_not_leak_evaluator_material_or_interface(self):
        for task in self.EXPECTED:
            with open(os.path.join(PHASE, "tasks", task, "project", "TASK.md"), encoding="utf-8") as h:
                text = h.read()
            for leak in ("hidden", "H0", "H1", "mutant", "reference solution", "opencode", "code-discipline", "skill",
                         "strict=True", "BEGIN IMMEDIATE", "threading.Lock"):
                self.assertNotIn(leak.lower(), text.lower(), f"{task} mentions {leak!r}")


class FixtureBaselineTests(TempDirTest):
    def test_baseline_tests_pass_on_every_fixture(self):
        for task in ("NEW-01", "NEW-02", "NEW-03", "NEW-04"):
            with self.subTest(task=task):
                data = manifest.build(PHASE, task)
                dest = os.path.join(self.tmp, task)
                manifest.materialize(PHASE, data, dest)
                proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                                      cwd=dest, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                      env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                self.assertEqual(proc.returncode, 0, proc.stdout)
                self.assertRegex(proc.stdout, r"Ran [1-9]\d* tests?")


class ScoreRunTests(TempDirTest):
    """Mechanics only, with a synthetic hidden package (the real one is private)."""

    def test_score_run_counts_checks_and_restores_pristine_files(self):
        data = manifest.build(PHASE, "NEW-03")
        pristine = os.path.join(self.tmp, "pristine")
        agent = os.path.join(self.tmp, "agent")
        manifest.materialize(PHASE, data, pristine)
        shutil.copytree(pristine, agent)
        with open(os.path.join(agent, "importer", "models.py"), "a", encoding="utf-8") as h:
            h.write("\nraise RuntimeError('tampered immutable file must not be used')\n")
        hidden = os.path.join(self.tmp, "hidden", "hidden_tests")
        os.makedirs(hidden)
        open(os.path.join(hidden, "__init__.py"), "w").close()
        with open(os.path.join(hidden, "test_synthetic.py"), "w", encoding="utf-8") as h:
            h.write(
                "import unittest\nfrom importer.csv_import import import_contacts\n"
                "class T(unittest.TestCase):\n"
                "    def test_H01_header_only(self):\n        self.assertEqual(import_contacts(b'email,name\\n').contacts, [])\n"
                "    def test_H02_bom(self):\n        self.assertEqual(import_contacts(b'\\xef\\xbb\\xbfemail,name\\nx@y.io,A\\n').contacts[0].email, 'x@y.io')\n"
            )
        out = os.path.join(self.tmp, "score.json")
        inventory = os.path.join(self.tmp, "inventory.json")
        with open(inventory, "w", encoding="utf-8") as h:
            json.dump(score_run.build_inventory(PHASE, "NEW-03", pristine, os.path.dirname(hidden)), h)
        proc = subprocess.run([sys.executable, os.path.join(HARNESS, "score_run.py"), "score", "--phase-root", PHASE, "--task", "NEW-03",
                               "--pristine", pristine, "--agent", agent, "--hidden", os.path.dirname(hidden), "--inventory", inventory,
                               "--out", out, "--timeout", "120", "--sandbox", "none", "--trusted-code"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        with open(out, encoding="utf-8") as h:
            report = json.load(h)
        # The fixture raises on a BOM header, which unittest reports as an error.
        self.assertEqual(report["evaluation_status"], "valid")
        self.assertEqual(report["hidden_checks"], {"H01": "pass", "H02": "error"})
        self.assertEqual((report["hidden_passed"], report["hidden_total"]), (1, 2))
        self.assertEqual((report["baseline_passed"], report["baseline_total"]), (4, 4))
        self.assertIn("importer/csv_import.py", report["taken_from_agent"])


class ScheduleTests(TempDirTest):
    def test_blocked_balanced_and_deterministic(self):
        a, b = schedule.make_schedule("ab" * 16, [CLAUDE, GROK]), schedule.make_schedule("ab" * 16, [CLAUDE, GROK])
        self.assertEqual([r["run_id"] for r in a["runs"]], [r["run_id"] for r in b["runs"]])
        self.assertEqual(schedule.validate(a), [])
        self.assertEqual(len(a["runs"]), 36)
        for block in range(1, 19):
            members = [r for r in a["runs"] if r["block"] == block]
            self.assertEqual(sorted(r["group"] for r in members), ["control", "treatment"])
            self.assertEqual(len({(r["model"], r["task"]) for r in members}), 1)
        for r in a["runs"]:
            self.assertRegex(r["run_id"], r"^r-[0-9a-f]{10}$")
            self.assertRegex(r["blind_id"], r"^b-[0-9a-f]{8}$")

    def test_smoke_pilot_is_a_2x2(self):
        s = schedule.make_schedule("cd" * 16, [CLAUDE, GROK], ["NEW-02"], 1)
        self.assertEqual(schedule.validate(s), [])
        self.assertEqual(sorted((r["model"], r["group"]) for r in s["runs"]),
                         sorted((m, g) for m in (CLAUDE, GROK) for g in ("control", "treatment")))

    def test_out_of_scope_or_malformed_models_rejected(self):
        for bad in (["opencode/nemotron-3.5-super-vl-free#xhigh"], ["claude"], [CLAUDE, CLAUDE], []):
            with self.assertRaises(ValueError):
                schedule.make_schedule("ab" * 16, bad)

    def test_validate_detects_mixed_blocks(self):
        s = schedule.make_schedule("ab" * 16, [CLAUDE, GROK], ["NEW-01"], 1)
        s["runs"][0]["model"] = GROK if s["runs"][0]["model"] == CLAUDE else CLAUDE
        self.assertTrue(schedule.validate(s))

    def test_rerun_appends_once_per_slot_and_next_skips_finished(self):
        s = schedule.make_schedule("01" * 16, [CLAUDE])
        first = s["runs"][0]["run_id"]
        entry = schedule.add_rerun(s, first, "gateway 503 before first tool call")
        self.assertEqual((entry["task"], entry["group"], entry["replaces_run"]), (s["runs"][0]["task"], s["runs"][0]["group"], first))
        with self.assertRaises(ValueError):
            schedule.add_rerun(s, entry["run_id"], "again")
        self.assertEqual(schedule.validate(s), [])
        path = os.path.join(self.tmp, "s.json")
        with open(path, "w", encoding="utf-8") as h:
            json.dump(s, h)
        caps = os.path.join(self.tmp, "caps")
        os.makedirs(os.path.join(caps, first))
        open(os.path.join(caps, first, "run-status.json"), "w").close()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(schedule.main(["next", "--schedule", path, "--captures", caps]), 0)
        self.assertEqual(buf.getvalue().strip(), s["runs"][1]["run_id"])


def skill_info(path, content, skill_id="code-discipline"):
    return {"id": skill_id, "name": skill_id, "path": path, "content": content}


class ApiCheckTests(unittest.TestCase):
    ROOTS = ["/aqd/env-a/runs/r-0123456789", "/opt/aqd-opencode"]

    def test_control_must_not_see_skill(self):
        report = api_checks.check_skills([skill_info("/aqd/env-a/runs/r-0123456789/home/.config/opencode/skills/code-discipline/SKILL.md", SKILL_BODY)], "control", self.ROOTS)
        self.assertFalse(report["ok"])
        self.assertTrue(api_checks.check_skills([], "control", self.ROOTS)["ok"])

    def test_control_rejects_renamed_copy_of_skill_text(self):
        report = api_checks.check_skills([skill_info("/aqd/env-a/runs/r-0123456789/home/x/SKILL.md", SKILL_BODY, "notes")], "control", self.ROOTS)
        self.assertFalse(report["ok"])

    # Shape returned by GET /api/skill on OpenCode 2.3.2 (probed 2026-11-21): the
    # binary ships built-in skills served from skill:// paths in every run.
    BUILTINS = [{"id": name, "name": name.title(), "description": "built-in", "path": f"skill://{name}/SKILL.md",
                 "content": f"# {name}\n\nBuilt-in guide."} for name in ("opencode", "report", "browser")]

    def test_builtin_skills_of_the_pinned_binary_are_recorded_not_failed(self):
        for group in ("control", "treatment"):
            skills = list(self.BUILTINS)
            if group == "treatment":
                skills.append(skill_info("/aqd/env-a/runs/r-0123456789/home/.config/opencode/skills/code-discipline/SKILL.md", SKILL_BODY))
            report = api_checks.check_skills(skills, group, self.ROOTS)
            self.assertTrue(report["ok"], report["problems"])
            self.assertEqual([s["builtin"] for s in report["skills"]][:3], [True, True, True])

    def test_builtin_skill_cannot_carry_code_discipline(self):
        renamed = dict(self.BUILTINS[0], content=SKILL_BODY)
        self.assertFalse(api_checks.check_skills([renamed], "control", self.ROOTS)["ok"])
        builtin_cd = dict(self.BUILTINS[0], id="code-discipline", path="skill://code-discipline/SKILL.md", content=SKILL_BODY)
        self.assertFalse(api_checks.check_skills([builtin_cd], "control", self.ROOTS)["ok"])
        self.assertFalse(api_checks.check_skills([builtin_cd], "treatment", self.ROOTS)["ok"])

    def test_treatment_requires_canonical_content_inside_run(self):
        good = skill_info("/aqd/env-a/runs/r-0123456789/home/.config/opencode/skills/code-discipline/SKILL.md", SKILL_BODY)
        self.assertTrue(api_checks.check_skills([good], "treatment", self.ROOTS)["ok"])
        self.assertFalse(api_checks.check_skills([dict(good, content="other")], "treatment", self.ROOTS)["ok"])
        leaked = dict(good, path="/home/codespace/.agents/skills/code-discipline/SKILL.md")
        self.assertFalse(api_checks.check_skills([leaked], "treatment", self.ROOTS)["ok"])

    def test_model_variant_and_provider(self):
        model = {"providerID": "xai", "id": "grok-test", "enabled": True,
                 "variants": [{"id": v} for v in ("low", "high")]}
        self.assertTrue(api_checks.check_model([model], "xai", "grok-test", "high")["ok"])
        self.assertTrue(api_checks.check_model([model], "xai", "grok-test", None)["ok"])
        self.assertEqual(api_checks.check_model([model], "xai", "grok-test", "max")["reason"], "variant_absent")
        self.assertEqual(api_checks.check_model([model], "anthropic", "grok-test", None)["reason"], "model_absent")
        self.assertTrue(api_checks.check_provider([{"id": "anthropic"}], "anthropic")["ok"])
        self.assertFalse(api_checks.check_provider([{"id": "anthropic"}], "xai")["ok"])

    # Shapes of OpenCode 2.3.2 (OpenAPI and a live server, 2026-11-21): /api/provider,
    # /api/model and /api/skill return {"location": ..., "data": [...]} with both
    # keys required; /api/config returns a bare list of entries.
    RUN = "/aqd/env-a/runs/r-0123456789"
    LOC = {"directory": RUN + "/project"}

    def wrapped_responses(self, group):
        skills = list(self.BUILTINS)
        if group == "treatment":
            skills.append(skill_info(self.RUN + "/home/.config/opencode/skills/code-discipline/SKILL.md", SKILL_BODY))
        return {
            "/api/provider": {"location": self.LOC, "data": [{"id": "anthropic", "name": "Anthropic"}, {"id": "opencode", "name": "OpenCode"}]},
            "/api/model": {"location": self.LOC, "data": [{"providerID": "anthropic", "id": "claude-test", "enabled": True,
                                                           "variants": [{"id": "low"}, {"id": "medium"}]}]},
            "/api/skill": {"location": self.LOC, "data": skills},
            "/api/config": [{"type": "document", "path": self.RUN + "/project/opencode.jsonc", "info": {}},
                            {"type": "directory", "path": self.RUN + "/home/.config/opencode"}],
        }

    @staticmethod
    def stub_client(responses):
        class StubClient:
            def request(self, method, path, body=None, query=None):
                return 200, responses[path]
        return StubClient()

    def test_run_reads_location_scoped_list_envelopes(self):
        for group in ("control", "treatment"):
            report, code = api_checks.run(self.stub_client(self.wrapped_responses(group)), self.LOC["directory"], group,
                                          self.ROOTS, "anthropic/claude-test#medium")
            self.assertEqual(code, 0, report)
            self.assertEqual(report["provider"]["provider_ids"], ["anthropic", "opencode"])
            self.assertEqual(report["model"]["variants"], ["low", "medium"])
            self.assertEqual(len(report["skills"]["skills"]), 4 if group == "treatment" else 3)
        # The same envelope still fails the checks it exists for.
        leaked = self.wrapped_responses("treatment")
        report, code = api_checks.run(self.stub_client(leaked), self.LOC["directory"], "control", self.ROOTS, "anthropic/claude-test#medium")
        self.assertEqual(code, 13)
        absent = self.wrapped_responses("control")
        self.assertEqual(api_checks.run(self.stub_client(absent), self.LOC["directory"], "control", self.ROOTS, "xai/grok-test")[1], 10)

    MALFORMED = {
        "no data": {"location": LOC},
        "data null": {"location": LOC, "data": None},
        "data object": {"location": LOC, "data": {"id": "x"}},
        "entries not objects": {"location": LOC, "data": ["anthropic"]},
        "entry lacks fields": {"location": LOC, "data": [{"name": "no id"}]},
        "extra envelope key": {"location": LOC, "data": [], "error": "x"},
        "empty body": None,
        "bare object": {"id": "anthropic"},
    }

    def test_malformed_or_unexpected_shapes_fail_closed(self):
        for endpoint in ("/api/provider", "/api/model", "/api/skill", "/api/config"):
            for label, bad in self.MALFORMED.items():
                for group in ("control", "treatment"):
                    with self.subTest(endpoint=endpoint, shape=label, group=group):
                        responses = self.wrapped_responses(group)
                        responses[endpoint] = bad
                        with self.assertRaises(drive_session.ApiError):
                            api_checks.run(self.stub_client(responses), self.LOC["directory"], group, self.ROOTS,
                                           "anthropic/claude-test#medium")

    def test_cli_exits_2_and_writes_no_report_on_a_malformed_skill_list(self):
        from unittest import mock
        responses = self.wrapped_responses("control")
        responses["/api/skill"] = {"location": self.LOC, "data": None}
        out = os.path.join(tempfile.mkdtemp(prefix="aqd-test-"), "api-checks.json")
        try:
            with mock.patch.object(api_checks, "Client", lambda server, password: self.stub_client(responses)), \
                    mock.patch.dict(os.environ, {"OPENCODE_PASSWORD": "x"}), redirect_stdout(io.StringIO()):
                stderr = io.StringIO()
                with mock.patch.object(sys, "stderr", stderr):
                    code = api_checks.main(["--server", "http://127.0.0.1:1", "--directory", self.LOC["directory"],
                                            "--group", "control", "--model", "anthropic/claude-test#medium",
                                            "--allowed-root", self.RUN, "--out", out])
            self.assertEqual(code, 2)
            self.assertFalse(os.path.exists(out))
            self.assertIn("/api/skill", stderr.getvalue())
        finally:
            shutil.rmtree(os.path.dirname(out), ignore_errors=True)

    def test_unwrap_only_strips_known_envelopes(self):
        self.assertEqual(drive_session.unwrap({"data": [1]}), [1])
        self.assertEqual(drive_session.unwrap({"location": {}, "data": [1]}), [1])
        for payload in ({"data": [1], "cursor": {}}, {"location": {}}, {"id": "ses_1"}, [1], None):
            self.assertEqual(drive_session.unwrap(payload), payload)

    def test_config_paths_must_stay_inside_run(self):
        entries = [{"path": "/aqd/env-a/runs/r-0123456789/project/opencode.jsonc"}, {"path": "/etc/opencode/opencode.json"}]
        self.assertTrue(api_checks.check_config(entries, self.ROOTS, exists=lambda p: False)["ok"])
        self.assertFalse(api_checks.check_config(entries, self.ROOTS, exists=lambda p: True)["ok"])


class FakeOpenCode(http.server.BaseHTTPRequestHandler):
    requests = []
    polls = 0

    def log_message(self, *args):
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.requests.append(("GET", self.path, None, self.headers.get("Authorization")))
        if self.path == "/api/info":
            return self._send({"version": "test"})
        if self.path.endswith("/permission"):
            return self._send({"data": []})
        if self.path.startswith("/api/experimental/session/"):
            return self._send({"data": {"info": {"id": "ses_test"}, "messages": []}})
        if self.path.startswith("/api/session/"):
            type(self).polls += 1
            idle = 10**13 if self.polls >= 2 else None
            return self._send({"data": {"id": "ses_test", "time": {"created": 1, "busy": 2 if idle else 10**13, "idle": idle}}})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null")
        self.requests.append(("POST", self.path, body, self.headers.get("Authorization")))
        if self.path == "/api/session":
            return self._send({"data": {"id": "ses_test"}})
        if self.path.endswith("/prompt"):
            return self._send({"data": {"id": "msg_1"}})
        self._send({"data": None})


class DriveSessionTests(TempDirTest):
    def run_driver(self, attach):
        FakeOpenCode.requests, FakeOpenCode.polls = [], 0
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenCode)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            message = os.path.join(PHASE, "tasks", "NEW-01", "project", "TASK.md")
            out = os.path.join(self.tmp, "attach" if attach else "plain")
            args = drive_session.parse_args(["--server", f"http://127.0.0.1:{server.server_address[1]}", "--directory", "/aqd/env-a/runs/r-0/project",
                                             "--message-file", message, "--provider", "xai", "--model", "grok-test",
                                             "--variant", "high", "--poll", "0", "--out-dir", out] + (["--attach-skill", "code-discipline"] if attach else []))
            result = drive_session.drive(args, drive_session.Client(args.server, "pw"), sleep=lambda s: None)
        finally:
            server.shutdown()
            server.server_close()
        return result, list(FakeOpenCode.requests)

    def test_prompt_text_identical_and_only_treatment_attaches_skill(self):
        control, control_requests = self.run_driver(attach=False)
        treatment, treatment_requests = self.run_driver(attach=True)
        self.assertEqual((control["status"], treatment["status"]), ("idle", "idle"))
        prompt = lambda reqs: next(body for method, path, body, _ in reqs if path.endswith("/prompt"))
        create = lambda reqs: next(body for method, path, body, _ in reqs if method == "POST" and path == "/api/session")
        self.assertEqual(prompt(control_requests)["text"], prompt(treatment_requests)["text"])
        with open(os.path.join(PHASE, "tasks", "NEW-01", "project", "TASK.md"), encoding="utf-8") as h:
            self.assertEqual(prompt(control_requests)["text"], h.read())
        self.assertNotIn("skills", prompt(control_requests))
        self.assertEqual(prompt(treatment_requests)["skills"], [{"id": "code-discipline"}])
        self.assertEqual(create(control_requests), create(treatment_requests))
        self.assertEqual(create(control_requests)["model"], {"providerID": "xai", "id": "grok-test", "variant": "high"})
        self.assertTrue(all(auth and auth.startswith("Basic ") for *_, auth in control_requests))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "plain", "export.json")))


def analyse_export(export, group, model=GROK):
    return export_checks.analyse(export, group, model)


def assistant(text="done", variant="high", tools=(), reasoning=5):
    content = [{"type": "text", "text": text}] + list(tools)
    return {"type": "assistant", "id": "m", "time": {"created": 1}, "agent": "build",
            "model": {"providerID": "xai", "id": "grok-test", "variant": variant},
            "content": content, "tokens": {"input": 10, "output": 5, "reasoning": reasoning, "cache": {"read": 0, "write": 0}}}


def tool(name, input_, output="ok"):
    return {"type": "tool", "id": "t", "name": name, "time": {"created": 1},
            "state": {"status": "completed", "input": input_, "content": [{"type": "text", "text": output}]}}


class ExportCheckTests(unittest.TestCase):
    def export(self, *messages):
        return {"info": {"id": "ses_x"}, "messages": [{"type": "user", "id": "u", "time": {"created": 0}, "text": "task"}] + list(messages)}

    def test_treatment_confirmed_by_skill_message(self):
        skill_msg = {"type": "skill", "id": "s", "time": {"created": 1}, "skill": "code-discipline", "name": "code-discipline", "text": SKILL_BODY}
        report = analyse_export(self.export(skill_msg, assistant()), "treatment")
        self.assertEqual((report["activation"], report["valid"]), ("CONFIRMED", True))

    def test_treatment_confirmed_by_attachment_text(self):
        export = self.export(assistant())
        export["messages"][0]["skills"] = [{"id": "code-discipline", "name": "code-discipline", "text": SKILL_BODY}]
        self.assertEqual(analyse_export(export, "treatment")["activation"], "CONFIRMED")

    def test_treatment_without_skill_text_is_invalid(self):
        report = analyse_export(self.export(assistant()), "treatment")
        self.assertEqual(report["activation"], "NOT_CONFIRMED")
        self.assertFalse(report["valid"])

    def test_control_clean_and_contaminated(self):
        self.assertTrue(analyse_export(self.export(assistant(tools=[tool("shell", {"command": "python -m unittest"})])), "control")["valid"])
        leaked = assistant(tools=[tool("shell", {"command": "curl https://example.invalid/SKILL.md"}, output=SKILL_BODY)])
        report = analyse_export(self.export(leaked), "control")
        self.assertTrue(report["contamination"])
        self.assertFalse(report["valid"])
        tried = assistant(tools=[tool("skill", {"id": "code-discipline"}, output="not found")])
        self.assertTrue(analyse_export(self.export(tried), "control")["contamination"])

    def test_variant_mismatch_invalidates(self):
        report = analyse_export(self.export(assistant(variant="low")), "control")
        self.assertFalse(report["model_ok"])
        self.assertFalse(report["valid"])
        self.assertFalse(analyse_export(self.export(), "control")["model_ok"])

    def test_model_substitution_invalidates_and_observed_variant_is_recorded(self):
        report = analyse_export(self.export(assistant()), "control", model="anthropic/claude-sonnet-5-5")
        self.assertFalse(report["model_ok"])
        report = analyse_export(self.export(assistant()), "control", model="xai/grok-test")
        self.assertTrue(report["model_ok"])
        self.assertEqual(report["observed_models"], [{"providerID": "xai", "id": "grok-test", "variant": "high"}])


class BlindPacketTests(unittest.TestCase):
    def test_redaction_and_rendering(self):
        redact = blind_packet.Redactor()
        export = {"messages": [
            {"type": "skill", "skill": "code-discipline", "text": SKILL_BODY},
            {"type": "assistant", "content": [
                {"type": "reasoning", "text": "I will follow code-discipline"},
                tool("skill", {"id": "code-discipline"}, SKILL_BODY),
                tool("shell", {"command": "cd /aqd/env-b/runs/r-0123456789/project && python -m unittest"}, "OK"),
                {"type": "text", "text": "Done per the Code Discipline skill; see r-0123456789 in env-b."},
            ]},
        ]}
        transcript, final = blind_packet.render_transcript(export, redact)
        combined = transcript + final
        self.assertNotRegex(combined, re.compile("code[- ]discipline", re.IGNORECASE))
        self.assertNotIn("env-b", combined)
        self.assertNotIn("r-0123456789", combined)
        self.assertNotIn("I will follow", combined)
        self.assertNotIn("TOOL skill", combined)
        self.assertIn("cd <project> && python -m unittest", combined)
        self.assertGreater(redact.count, 0)

    def test_packet_has_task_text_and_a_review_template_bound_to_the_scored_code(self):
        tmp = tempfile.mkdtemp(prefix="aqd-packet-")
        self.addCleanup(shutil.rmtree, tmp, True)
        capture, pristine, out = (os.path.join(tmp, d) for d in ("cap", "pristine", "out"))
        os.makedirs(os.path.join(capture, "driver"))
        os.makedirs(os.path.join(pristine, "NEW-02", "project"))
        with open(os.path.join(pristine, "NEW-02", "project", "TASK.md"), "w", encoding="utf-8") as h:
            h.write("# Task: reserve stock\n")
        hidden = AnalyzeTests.hidden_score("NEW-02", flags={"inventory/service.py": ["name:exec"]}, subject="12" * 32)
        for rel, data in (("driver/export.json", {"messages": []}), ("verify-post.json", {"findings": {}}),
                          ("hidden-score.json", hidden)):
            with open(os.path.join(capture, rel), "w", encoding="utf-8") as h:
                json.dump(data, h)
        run = {"blind_id": "b-01234567", "task": "NEW-02"}
        blind_packet.build_packet(run, capture, pristine, out, blind_packet.Redactor())
        with open(os.path.join(out, "packet.md"), encoding="utf-8") as h:
            packet = h.read()
        self.assertIn("# Task: reserve stock", packet)
        self.assertIn("TAMPER REVIEW REQUIRED", packet)
        with open(os.path.join(out, "score.json"), encoding="utf-8") as h:
            template = json.load(h)
        self.assertEqual(template["tamper_review_subject"], "12" * 32)
        self.assertNotIn(template["tamper_review"], analyze.REVIEW_VERDICTS)  # a placeholder never counts
        with self.assertRaises(FileNotFoundError):
            blind_packet.build_packet(run, capture, os.path.join(tmp, "nowhere"), out, blind_packet.Redactor())


class RunStatusTests(TempDirTest):
    def write(self, rel, data):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as h:
            if isinstance(data, str):
                h.write(data)
            else:
                json.dump(data, h)

    MODEL = "anthropic/claude-opus-5-5#medium"

    def record(self, group="treatment", **changes):
        record = {"schema_version": 2, "run_id": "r-0123456789", "task": "NEW-02", "group": group, "model": self.MODEL,
                  "model_provider": "anthropic", "model_id": "claude-opus-5-5", "model_variant": "medium",
                  "interface": "opencode 2.3.2", "activation_mode": "api-attachment",
                  "skill": {"installed": group == "treatment", "sha256": "aa" * 32 if group == "treatment" else None},
                  "prompt_sha256": "bb" * 32, "workspace_sha256": "cc" * 32, "global_config_sha256": "dd" * 32}
        record.update(changes)
        return record

    def complete_run(self, group="treatment"):
        self.write("driver/driver-result.json", {"status": "idle", "session_id": "ses_1"})
        self.write("export-checks.json", {"valid": True, "activation": "CONFIRMED", "tool_counts": {"shell": 3}, "tokens": {},
                                          "model_ref": self.MODEL})
        self.write("verify-post.json", {"integrity_ok": True, "findings": {"unexpected": []}})
        self.write("home-config-listing.txt", "\n".join(run_status.expected_home_listing(group)) + "\n")
        self.write("run-record.json", self.record(group))

    def test_valid_and_invalid(self):
        self.complete_run()
        good = run_status.build_status(self.tmp, "treatment", 0, 100, 0, 0, "done")
        self.assertTrue(good["valid"], good["invalid_reasons"])
        self.assertEqual(good["tool_calls"], 3)
        bad = run_status.build_status(self.tmp, "control", 0, 100, 0, 0, "done")
        self.assertFalse(bad["valid"])
        self.assertIn("unexpected HOME configuration entries", bad["invalid_reasons"][0])

    def test_provider_error_is_an_infrastructure_failure_not_a_valid_zero(self):
        error = {"index": 1, "error": {"type": "auth", "message": "invalid x-api-key", "status": 401}, "finish": "error"}
        for driver, export_errors in (({"status": "idle", "session_id": "ses_1", "outcome": "failed"}, []),
                                      ({"status": "idle", "session_id": "ses_1", "outcome": "succeeded"}, [error])):
            with self.subTest(driver=driver, errors=export_errors):
                self.complete_run()
                self.write("driver/driver-result.json", driver)
                self.write("export-checks.json", {"valid": True, "activation": "CONFIRMED", "tool_counts": {}, "tokens": {},
                                                  "model_ref": self.MODEL, "errors": export_errors})
                status = run_status.build_status(self.tmp, "treatment", 0, 100, 0, 0, "done")
                self.assertFalse(status["valid"])
                self.assertTrue(any("provider/API error" in r for r in status["invalid_reasons"]), status["invalid_reasons"])
        # A pre-registered timeout interrupts the session; that stays a valid outcome.
        self.complete_run()
        self.write("driver/driver-result.json", {"status": "timeout", "session_id": "ses_1"})
        self.write("export-checks.json", {"valid": True, "activation": "CONFIRMED", "tool_counts": {}, "tokens": {},
                                          "model_ref": self.MODEL, "errors": [error]})
        self.assertTrue(run_status.build_status(self.tmp, "treatment", 0, 100, 0, 0, "done")["valid"])

    def test_run_record_must_be_complete_and_consistent(self):
        cases = {
            "missing prompt hash": self.record(prompt_sha256=None),
            "missing workspace hash": self.record(workspace_sha256="x"),
            "missing config hash": {k: v for k, v in self.record().items() if k != "global_config_sha256"},
            "no interface version": self.record(interface="opencode "),
            "raw V2 --version output": self.record(interface="opencode opencodev2.3.2"),
            "variant disagrees": self.record(model_variant="high"),
            "other model than export": self.record(model="anthropic/claude-sonnet-5-5", model_id="claude-sonnet-5-5"),
            "treatment without skill hash": self.record(skill={"installed": True, "sha256": None}),
            "wrong group": self.record(group="control"),
        }
        for name, record in cases.items():
            with self.subTest(case=name):
                self.complete_run()
                self.write("run-record.json", record)
                status = run_status.build_status(self.tmp, "treatment", 0, 100, 0, 0, "done")
                self.assertFalse(status["valid"], name)
        self.complete_run("control")
        self.write("run-record.json", self.record("control", skill={"installed": True, "sha256": "aa" * 32}))
        self.assertIn("control run record says a skill was installed",
                      run_status.build_status(self.tmp, "control", 0, 100, 0, 0, "done")["invalid_reasons"])
        os.remove(os.path.join(self.tmp, "run-record.json"))
        self.assertIn("no run-record.json", run_status.build_status(self.tmp, "control", 0, 100, 0, 0, "done")["invalid_reasons"])

    def test_malformed_capture_file_invalidates_instead_of_crashing(self):
        self.complete_run()
        self.write("export-checks.json", "{broken")
        status = run_status.build_status(self.tmp, "treatment", 0, 100, 0, 0, "done")
        self.assertFalse(status["valid"])
        self.assertIn("no export analysed", status["invalid_reasons"])


class AnalyzeTests(TempDirTest):
    def setUp(self):
        super().setUp()
        self.sched = schedule.make_schedule("ef" * 16, [CLAUDE, GROK], ["NEW-02"], 1)
        self.caps = os.path.join(self.tmp, "caps")
        self.scores = os.path.join(self.tmp, "scores")

    @staticmethod
    def hidden_score(task, evaluation="valid", fraction=1.0, flags=None, subject="ab" * 32):
        """A self-consistent hidden-score.json as score_run.py writes it (4 hidden checks, 2 baseline)."""
        report = {"schema_version": score_run.SCORE_SCHEMA_VERSION, "kind": score_run.SCORE_KIND, "task": task,
                  "evaluation_status": evaluation, "invalid_reasons": [], "primary": None}
        if evaluation != "valid":
            report["invalid_reasons"] = ["no result file"]
            return report
        passed = int(round(fraction * 4))
        checks = {f"H{i:02d}": "pass" if i <= passed else "fail" for i in range(1, 5)}
        report.update({"inventory_sha256": "cd" * 32, "review_subject_sha256": subject,
                       "review_flags": flags or {}, "requires_review": bool(flags),
                       "hidden_checks": checks, "hidden_passed": passed, "hidden_total": 4,
                       "baseline_outcomes": {"b1": "pass", "b2": "pass"}, "baseline_passed": 2, "baseline_total": 2,
                       "baseline_all_pass": True,
                       "primary": {"hidden_pass_fraction": round(passed / 4, 6), "fully_correct": passed == 4}})
        return report

    @staticmethod
    def run_record(run, **changes):
        treatment = run["group"] == "treatment"
        record = {"run_id": run["run_id"], "task": run["task"], "group": run["group"], "model": run["model"],
                  "interface": "opencode 2.3.2", "activation_mode": "api-attachment", "agent": "build",
                  "timeout_seconds": 2700, "opencode_install_tree_sha256": "11" * 32,
                  "skill": {"installed": treatment, "sha256": "22" * 32 if treatment else None},
                  "prompt_sha256": "33" * 32, "workspace_sha256": "44" * 32, "global_config_sha256": "55" * 32}
        record.update(changes)
        return record

    def put(self, run, valid=True, evaluation="valid", fraction=1.0, score=None, flags=None, hidden=None, record=None):
        cap = os.path.join(self.caps, run["run_id"])
        os.makedirs(cap, exist_ok=True)
        with open(os.path.join(cap, "run-status.json"), "w", encoding="utf-8") as h:
            json.dump({"valid": valid, "invalid_reasons": [] if valid else ["gateway error"]}, h)
        with open(os.path.join(cap, "run-record.json"), "w", encoding="utf-8") as h:
            json.dump(record or self.run_record(run), h)
        if hidden is None and evaluation is not None:
            hidden = self.hidden_score(run["task"], evaluation, fraction, flags)
        if hidden is not None:
            with open(os.path.join(cap, "hidden-score.json"), "w", encoding="utf-8") as h:
                json.dump(hidden, h)
        if score is not None:
            os.makedirs(os.path.join(self.scores, run["blind_id"]), exist_ok=True)
            with open(os.path.join(self.scores, run["blind_id"], "score.json"), "w", encoding="utf-8") as h:
                json.dump(dict({"blind_id": run["blind_id"]}, **score), h)

    def resolve(self):
        return analyze.resolve_slots(self.sched, self.caps, self.scores)

    def test_complete_pilot_effects_are_within_model(self):
        for run in self.sched["runs"]:
            self.put(run, fraction=1.0 if run["group"] == "treatment" else 0.5)
        rows, problems = self.resolve()
        self.assertEqual(problems, [])
        report = analyze.analyse(rows, problems)
        self.assertEqual(report["status"], "COMPLETE")
        for model in (CLAUDE, GROK):
            self.assertEqual(report["primary"]["hidden_pass_fraction"][model]["difference_by_task"], {"NEW-02": 0.5})

    def test_missing_invalid_and_unevaluated_runs_make_the_report_incomplete(self):
        runs = self.sched["runs"]
        self.put(runs[0], valid=False)
        self.put(runs[1], evaluation="invalid")
        self.put(runs[2], evaluation=None)
        rows, problems = self.resolve()
        self.assertEqual(len(rows), 0)
        self.assertEqual(sorted(p["problem"].split(":")[0] for p in problems),
                         ["evaluation invalid", "evaluation missing", "run invalid", "run missing"])
        self.assertEqual(analyze.analyse(rows, problems)["status"], "INCOMPLETE")
        out = os.path.join(self.tmp, "report.json")
        path = os.path.join(self.tmp, "s.json")
        with open(path, "w", encoding="utf-8") as h:
            json.dump(self.sched, h)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(analyze.main(["--schedule", path, "--captures", self.caps, "--scores", self.scores, "--out", out]), 3)
            self.assertEqual(analyze.main(["--schedule", path, "--captures", self.caps, "--scores", self.scores, "--out", out,
                                           "--allow-incomplete"]), 0)

    def test_two_valid_runs_in_one_slot_is_an_error(self):
        first = self.sched["runs"][0]
        rerun = schedule.add_rerun(self.sched, first["run_id"], "test")
        self.put(first)
        self.put(rerun)
        with self.assertRaises(analyze.AnalysisError):
            self.resolve()

    def test_rerun_replaces_an_invalid_attempt(self):
        first = self.sched["runs"][0]
        rerun = schedule.add_rerun(self.sched, first["run_id"], "gateway 503")
        self.put(first, valid=False)
        self.put(rerun, fraction=0.25)
        rows, _ = self.resolve()
        self.assertEqual([(r["run_id"], r["hidden_pass_fraction"]) for r in rows], [(rerun["run_id"], 0.25)])

    def test_documentation_scores_never_enter_the_primary_outcome(self):
        excellent = {"dimensions": {k: 4 for k in analyze.SECONDARY_DIMENSIONS}, "group_guess": "control"}
        for run in self.sched["runs"]:
            self.put(run, fraction=0.0, score=excellent)
        rows, problems = self.resolve()
        report = analyze.analyse(rows, problems)
        for model in (CLAUDE, GROK):
            cells = report["primary"]["hidden_pass_fraction"][model]["by_task"]["NEW-02"]
            self.assertEqual({g: c["mean"] for g, c in cells.items()}, {"control": 0.0, "treatment": 0.0})
            self.assertEqual(report["primary"]["fully_correct"][model]["by_task"]["NEW-02"]["treatment"]["mean"], 0.0)
        self.assertNotIn("correctness", analyze.SECONDARY_DIMENSIONS)

    def test_task_mismatch_is_an_error(self):
        run = self.sched["runs"][0]
        self.put(run, hidden=self.hidden_score("NEW-01"))
        with self.assertRaisesRegex(analyze.AnalysisError, "schedule says NEW-02"):
            self.resolve()

    # --- review gating (the run must not count until a verdict names the scored code)

    def flagged_pilot(self, score_for_flagged):
        runs = self.sched["runs"]
        for run in runs[1:]:
            self.put(run, fraction=0.5)
        self.put(runs[0], fraction=1.0, flags={"x/y.py": [r"\bunittest\b"]}, score=score_for_flagged)
        rows, problems = self.resolve()
        return runs[0], rows, problems

    def test_flagged_run_without_verdict_is_unresolved_and_not_counted(self):
        # Before the fix, a flagged run entered the primary outcome unconditionally.
        flagged, rows, problems = self.flagged_pilot(None)
        self.assertNotIn(flagged["run_id"], [r["run_id"] for r in rows])
        self.assertEqual([(p["run_id"], p["status"]) for p in problems], [(flagged["run_id"], "unresolved")])
        report = analyze.analyse(rows, problems)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["runs_flagged_for_review"]["unresolved"], [flagged["run_id"]])
        cell = report["primary"]["hidden_pass_fraction"][flagged["model"]]["by_task"]["NEW-02"]
        self.assertNotIn(flagged["group"], cell)  # the 1.0 is not there

    def test_placeholder_or_unknown_verdict_is_unresolved(self):
        for verdict in ("REQUIRED: none|suspected|confirmed", "None", "ok", None, ""):
            with self.subTest(verdict=verdict):
                shutil.rmtree(self.caps, ignore_errors=True)
                shutil.rmtree(self.scores, ignore_errors=True)
                _, _, problems = self.flagged_pilot({"tamper_review": verdict, "tamper_review_subject": "ab" * 32,
                                                     "scorer_id": "s1"})
                self.assertEqual([p["status"] for p in problems], ["unresolved"])

    def test_verdict_for_different_code_or_without_scorer_is_unresolved(self):
        _, _, problems = self.flagged_pilot({"tamper_review": "none", "tamper_review_subject": "ef" * 32, "scorer_id": "s1"})
        self.assertEqual([p["status"] for p in problems], ["unresolved"])
        self.assertIn("does not name the scored code", problems[0]["problem"])
        shutil.rmtree(self.caps)
        shutil.rmtree(self.scores)
        _, _, problems = self.flagged_pilot({"tamper_review": "none", "tamper_review_subject": "ab" * 32, "scorer_id": " "})
        self.assertEqual([p["status"] for p in problems], ["unresolved"])

    def test_clean_verdict_on_the_scored_code_counts_the_run(self):
        flagged, rows, problems = self.flagged_pilot({"tamper_review": "none", "tamper_review_subject": "ab" * 32,
                                                      "scorer_id": "s1"})
        self.assertEqual(problems, [])
        self.assertIn(flagged["run_id"], analyze.analyse(rows, problems)["runs_flagged_for_review"]["counted_after_review"])

    def test_suspected_or_confirmed_tampering_is_excluded_even_without_flags(self):
        for verdict in ("suspected", "confirmed"):
            with self.subTest(verdict=verdict):
                shutil.rmtree(self.caps, ignore_errors=True)
                shutil.rmtree(self.scores, ignore_errors=True)
                runs = self.sched["runs"]
                for run in runs:
                    self.put(run, score={"tamper_review": verdict if run is runs[2] else "not required"})
                rows, problems = self.resolve()
                self.assertEqual([(p["run_id"], p["status"]) for p in problems], [(runs[2]["run_id"], "excluded")])
                report = analyze.analyse(rows, problems)
                self.assertEqual(report["slot_accounting"]["by_status"]["excluded"], 1)
                self.assertEqual(report["slot_accounting"]["by_model_and_condition"][runs[2]["model"]][runs[2]["group"]]["excluded"], 1)

    # --- integrity of the score files (fail closed, never "missing data")

    def test_inconsistent_hidden_scores_are_errors(self):
        run = self.sched["runs"][0]
        base = self.hidden_score(run["task"], fraction=0.25)
        tampered = {
            "fraction raised": dict(base, primary={"hidden_pass_fraction": 1.0, "fully_correct": False}),
            "fully_correct forged": dict(base, primary={"hidden_pass_fraction": 0.25, "fully_correct": True}),
            "count forged": dict(base, hidden_passed=4),
            "string fraction": dict(base, primary={"hidden_pass_fraction": "0.25", "fully_correct": False}),
            "review flag dropped": dict(base, review_flags={"a.py": ["x"]}, requires_review=False),
            "review field missing": {k: v for k, v in base.items() if k != "requires_review"},
            "subject missing": {k: v for k, v in base.items() if k != "review_subject_sha256"},
            "old schema": dict(base, schema_version=2),
            "wrong kind": dict(base, kind="something-else"),
            "unknown status": dict(base, evaluation_status="partial"),
            "valid with reasons": dict(base, invalid_reasons=["x"]),
            "invalid with primary": dict(self.hidden_score(run["task"], "invalid"), primary={"hidden_pass_fraction": 1.0}),
            "invalid without reason": dict(self.hidden_score(run["task"], "invalid"), invalid_reasons=[]),
            "no checks": dict(base, hidden_checks={}, hidden_passed=0, hidden_total=0),
            "baseline forged": dict(base, baseline_outcomes={"b1": "fail", "b2": "pass"}),
            "unknown outcome": dict(base, hidden_checks=dict(base["hidden_checks"], H01="skip")),
        }
        for name, hidden in tampered.items():
            with self.subTest(case=name):
                shutil.rmtree(self.caps, ignore_errors=True)
                self.put(run, hidden=hidden)
                with self.assertRaises(analyze.AnalysisError):
                    self.resolve()

    def test_malformed_files_are_errors_not_missing_data(self):
        run = self.sched["runs"][0]
        for name, content in (("hidden-score.json", "{not json"), ("hidden-score.json", "[]"),
                              ("run-status.json", "{\"valid\": \"yes\"}"), ("run-status.json", "")):
            with self.subTest(file=name, content=content):
                shutil.rmtree(self.caps, ignore_errors=True)
                self.put(run)
                with open(os.path.join(self.caps, run["run_id"], name), "w", encoding="utf-8") as h:
                    h.write(content)
                with self.assertRaises(analyze.AnalysisError):
                    self.resolve()

    def test_invalid_evaluation_is_reported_as_invalid_not_missing(self):
        runs = self.sched["runs"]
        self.put(runs[0], evaluation="invalid")
        self.put(runs[1], evaluation=None)
        _, problems = self.resolve()
        status = {p["slot"]: p["status"] for p in problems}
        self.assertEqual(status[runs[0]["run_id"]], "invalid")
        self.assertEqual(status[runs[1]["run_id"]], "missing")

    def test_different_inventories_for_one_task_are_an_error(self):
        runs = self.sched["runs"]
        self.put(runs[0])
        self.put(runs[1], hidden=dict(self.hidden_score(runs[1]["task"]), inventory_sha256="99" * 32))
        with self.assertRaisesRegex(analyze.AnalysisError, "different inventory"):
            self.resolve()

    def test_stray_results_and_mismatched_score_files_are_errors(self):
        run = self.sched["runs"][0]
        self.put(run)
        stray = os.path.join(self.caps, "r-ffffffffff")
        os.makedirs(stray)
        with open(os.path.join(stray, "hidden-score.json"), "w", encoding="utf-8") as h:
            json.dump(self.hidden_score(run["task"]), h)
        with self.assertRaisesRegex(analyze.AnalysisError, "not in the schedule"):
            self.resolve()
        shutil.rmtree(stray)
        os.makedirs(os.path.join(self.scores, run["blind_id"]))
        with open(os.path.join(self.scores, run["blind_id"], "score.json"), "w", encoding="utf-8") as h:
            json.dump({"blind_id": "b-00000000"}, h)
        with self.assertRaisesRegex(analyze.AnalysisError, "does not match its directory"):
            self.resolve()
        os.makedirs(os.path.join(self.scores, "b-12345678"))
        with open(os.path.join(self.scores, "b-12345678", "score.json"), "w", encoding="utf-8") as h:
            json.dump({"blind_id": "b-12345678"}, h)
        with self.assertRaisesRegex(analyze.AnalysisError, "not a scheduled blind id"):
            self.resolve()

    def test_conditions_must_differ_only_in_the_skill(self):
        runs = self.sched["runs"]
        control = next(r for r in runs if r["group"] == "control")
        treatment = next(r for r in runs if r["group"] == "treatment" and r["model"] == control["model"])
        cases = {
            "prompt": (control, {"prompt_sha256": "99" * 32}),
            "workspace": (control, {"workspace_sha256": "99" * 32}),
            "config": (treatment, {"global_config_sha256": "99" * 32}),
            "time limit": (control, {"timeout_seconds": 3600}),
            "interface": (treatment, {"interface": "opencode 2.3.3"}),
            "model": (control, {"model": "anthropic/claude-opus-5-5#high"}),
            "skill in control": (control, {"skill": {"installed": True, "sha256": "22" * 32}}),
            "other skill text": (treatment, {"skill": {"installed": True, "sha256": "98" * 32}}),  # vs the other model's treatment
            "missing field": (control, {"global_config_sha256": None}),
        }
        for name, (target, change) in cases.items():
            with self.subTest(case=name):
                shutil.rmtree(self.caps, ignore_errors=True)
                for run in runs:
                    record = None
                    if run is target:
                        record = {k: v for k, v in self.run_record(run, **change).items() if v is not None}
                    self.put(run, record=record)
                with self.assertRaises(analyze.AnalysisError):
                    self.resolve()
        shutil.rmtree(self.caps)
        for run in runs:
            self.put(run)
        os.remove(os.path.join(self.caps, runs[0]["run_id"], "run-record.json"))
        with self.assertRaisesRegex(analyze.AnalysisError, "without run-record.json"):
            self.resolve()

    def test_report_separates_every_status(self):
        runs = self.sched["runs"]
        self.put(runs[0])
        self.put(runs[1], valid=False)
        self.put(runs[2], flags={"a.py": ["x"]})
        self.put(runs[3], evaluation="invalid")
        report = analyze.analyse(*self.resolve())
        self.assertEqual(report["slot_accounting"]["by_status"],
                         {"valid": 1, "invalid": 2, "excluded": 0, "unresolved": 1, "missing": 0})
        self.assertEqual(report["slot_accounting"]["total"], 4)

    def test_hidden_score_written_by_score_run_passes_the_integrity_check(self):
        # Guards against analyze.py and score_run.py drifting apart.
        sys.path.insert(0, os.path.dirname(__file__))
        import test_scoring  # noqa: E402
        case = test_scoring.ScoringTest("run")
        case.setUp()
        try:
            for core in (test_scoring.CORRECT, test_scoring.PRISTINE["calc/core.py"], "import unittest\n" + test_scoring.CORRECT):
                report = json.loads(json.dumps(case.score(core=core)))
                analyze.check_hidden_score(report, "SYN", "real score_run output")
            invalid = json.loads(json.dumps(case.score(inventory={"error": "x"})))
            analyze.check_hidden_score(invalid, "SYN", "real score_run output")
        finally:
            case.tearDown()

    def test_permutation_exact_for_perfect_separation(self):
        by_task = {t: {"control": [0.0, 0.0, 0.0], "treatment": [1.0, 1.0, 1.0]} for t in ("A", "B", "C")}
        result = analyze.permutation_p(by_task)
        self.assertEqual(result["permutations"], 20 ** 3)
        self.assertAlmostEqual(result["p_two_sided"], 2 / 8000)
        diffs, overall = analyze.effect(by_task)
        self.assertEqual(overall, 1.0)


def find_bash():
    if os.path.exists(r"C:\Program Files\Git\bin\bash.exe"):
        return r"C:\Program Files\Git\bin\bash.exe"
    return shutil.which("bash")


class LauncherGateTests(TempDirTest):
    """The smoke test is the four scheduled runs; nothing may add model calls silently."""

    def launch(self, *args, env_extra=None):
        bash = find_bash()
        if bash is None:
            self.skipTest("bash not available")
        env = {k: v for k, v in os.environ.items() if k != "AQD_EXTRA_MODEL_CALL_APPROVED"}
        env.update(AQD_OPERATOR=self.tmp.replace("\\", "/"), **(env_extra or {}))
        return subprocess.run([bash, os.path.join(HARNESS, "launch-run.sh"), *args], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)

    def test_optional_smoke_task_refuses_without_approval_of_the_extra_call(self):
        proc = self.launch("--smoke", "control", "anthropic/claude-opus-5-5#medium")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("AQD_EXTRA_MODEL_CALL_APPROVED", proc.stdout)

    def test_pilot_schedule_refuses_without_written_approval(self):
        sealed = os.path.join(self.tmp, "sealed")
        os.makedirs(sealed)
        pilot = schedule.make_schedule("ab" * 16, [CLAUDE, GROK])
        with open(os.path.join(sealed, "schedule.json"), "w", encoding="utf-8") as h:
            json.dump(pilot, h)
        proc = self.launch(pilot["runs"][0]["run_id"])
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("pilot-approved.json", proc.stdout)

    def test_scheduled_runs_do_not_require_separate_gate_runs(self):
        with open(os.path.join(HARNESS, "launch-run.sh"), encoding="utf-8") as h:
            self.assertNotIn("runtime-gates.json", h.read())
        with open(os.path.join(PHASE, "PROMPT-SMOKE-TEST.md"), encoding="utf-8") as h:
            procedure = h.read().split("## Optional", 1)[0]
        self.assertNotIn("launch-run.sh --smoke", procedure)
        self.assertIn("run-all.sh", procedure)


class ShellSyntaxTests(unittest.TestCase):
    def test_bash_scripts_parse(self):
        bash = find_bash()
        if bash is None:
            self.skipTest("bash not available")
        for name in sorted(os.listdir(HARNESS)):
            if name.endswith(".sh"):
                with self.subTest(script=name):
                    proc = subprocess.run([bash, "-n", os.path.join(HARNESS, name)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    self.assertEqual(proc.returncode, 0, proc.stdout)


class OpenCodeVersionTests(TempDirTest):
    """The V2 CLI prints "opencode v2.3.2" (checked on 2.3.2); the pin compares X.Y.Z."""

    def version_of(self, printed):
        bash = find_bash()
        if bash is None:
            self.skipTest("bash not available")
        fake = os.path.join(self.tmp, "opencode").replace("\\", "/")
        with open(fake, "w", encoding="utf-8", newline="\n") as h:
            h.write(f"#!/usr/bin/env bash\nprintf '%s\\n' '{printed}'\n")
        lib = os.path.join(HARNESS, "lib.sh").replace("\\", "/")
        script = f'source "{lib}"; AQD_OPENCODE_BIN="{fake}"; chmod +x "$AQD_OPENCODE_BIN"; printf "[%s]" "$(opencode_version)"'
        env = dict(os.environ, AQD_OPERATOR=self.tmp.replace("\\", "/"))
        proc = subprocess.run([bash, "-c", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        return proc.stdout.strip().splitlines()[-1]

    def test_v2_cli_version_output_matches_the_pin(self):
        self.assertEqual(self.version_of("opencode v2.3.2"), "[2.3.2]")
        self.assertEqual(self.version_of("2.3.2"), "[2.3.2]")
        self.assertEqual(self.version_of("no version here"), "[]")


if __name__ == "__main__":
    unittest.main()
