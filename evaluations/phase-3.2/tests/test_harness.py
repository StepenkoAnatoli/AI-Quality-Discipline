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
        self.assertEqual(skill_rules, [("*", "deny"), ("code-discipline", "allow")])

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
        "NEW-01": ("c64501497fc0a83d2d5236685dd26425ba92deb5f5b4bf5dadd5f06e70c9875c", "48a0081713b1dd9824f6960d43e6f958dc1ac532c47653f247deafadb2da3287"),
        "NEW-02": ("9c4bde140efbacabf564f3307aa16955efb869d0dc6a3b354bb8322a727a543f", "cf0fea1a45be98860c0121b5e3b9d6b066bcf6530128140eef85e7067b2d2ed5"),
        "NEW-03": ("a5764db416e9848f7b6d51f06948b5110a6785013903260892942d3a042f649b", "4fd45747f8cc96cbbe7ebd20f0410f42930e5df8f9978bb389696606ab4740c4"),
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
        for task in ("NEW-01", "NEW-02", "NEW-03"):
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


class RunStatusTests(TempDirTest):
    def write(self, rel, data):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as h:
            if isinstance(data, str):
                h.write(data)
            else:
                json.dump(data, h)

    def test_valid_and_invalid(self):
        self.write("driver/driver-result.json", {"status": "idle", "session_id": "ses_1"})
        self.write("export-checks.json", {"valid": True, "activation": "CONFIRMED", "tool_counts": {"shell": 3}, "tokens": {}})
        self.write("verify-post.json", {"integrity_ok": True, "findings": {"unexpected": []}})
        self.write("home-config-listing.txt", "\n".join(run_status.expected_home_listing("treatment")) + "\n")
        good = run_status.build_status(self.tmp, "treatment", 0, 100, 0, 0, "done")
        self.assertTrue(good["valid"], good["invalid_reasons"])
        self.assertEqual(good["tool_calls"], 3)
        bad = run_status.build_status(self.tmp, "control", 0, 100, 0, 0, "done")
        self.assertFalse(bad["valid"])
        self.assertIn("unexpected HOME configuration entries", bad["invalid_reasons"][0])


class AnalyzeTests(TempDirTest):
    def setUp(self):
        super().setUp()
        self.sched = schedule.make_schedule("ef" * 16, [CLAUDE, GROK], ["NEW-02"], 1)
        self.caps = os.path.join(self.tmp, "caps")
        self.scores = os.path.join(self.tmp, "scores")

    def put(self, run, valid=True, evaluation="valid", fraction=1.0, score=None):
        cap = os.path.join(self.caps, run["run_id"])
        os.makedirs(cap, exist_ok=True)
        with open(os.path.join(cap, "run-status.json"), "w", encoding="utf-8") as h:
            json.dump({"valid": valid, "invalid_reasons": [] if valid else ["gateway error"]}, h)
        if evaluation is not None:
            hidden = {"task": run["task"], "evaluation_status": evaluation, "invalid_reasons": [] if evaluation == "valid" else ["no result file"],
                      "primary": {"hidden_pass_fraction": fraction, "fully_correct": fraction == 1.0} if evaluation == "valid" else None}
            with open(os.path.join(cap, "hidden-score.json"), "w", encoding="utf-8") as h:
                json.dump(hidden, h)
        if score is not None:
            os.makedirs(os.path.join(self.scores, run["blind_id"]), exist_ok=True)
            with open(os.path.join(self.scores, run["blind_id"], "score.json"), "w", encoding="utf-8") as h:
                json.dump(score, h)

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
        self.put(run)
        with open(os.path.join(self.caps, run["run_id"], "hidden-score.json"), "w", encoding="utf-8") as h:
            json.dump({"task": "NEW-01", "evaluation_status": "valid", "primary": {"hidden_pass_fraction": 1.0}}, h)
        with self.assertRaises(analyze.AnalysisError):
            self.resolve()

    def test_permutation_exact_for_perfect_separation(self):
        by_task = {t: {"control": [0.0, 0.0, 0.0], "treatment": [1.0, 1.0, 1.0]} for t in ("A", "B", "C")}
        result = analyze.permutation_p(by_task)
        self.assertEqual(result["permutations"], 20 ** 3)
        self.assertAlmostEqual(result["p_two_sided"], 2 / 8000)
        diffs, overall = analyze.effect(by_task)
        self.assertEqual(overall, 1.0)


class ShellSyntaxTests(unittest.TestCase):
    def test_bash_scripts_parse(self):
        bash = shutil.which("bash")
        if bash is None and os.path.exists(r"C:\Program Files\Git\bin\bash.exe"):
            bash = r"C:\Program Files\Git\bin\bash.exe"
        if bash is None:
            self.skipTest("bash not available")
        for name in sorted(os.listdir(HARNESS)):
            if name.endswith(".sh"):
                with self.subTest(script=name):
                    proc = subprocess.run([bash, "-n", os.path.join(HARNESS, name)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    self.assertEqual(proc.returncode, 0, proc.stdout)


if __name__ == "__main__":
    unittest.main()
