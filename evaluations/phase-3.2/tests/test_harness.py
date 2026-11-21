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
        proc = subprocess.run([sys.executable, os.path.join(HARNESS, "score_run.py"), "--phase-root", PHASE, "--task", "NEW-03",
                               "--pristine", pristine, "--agent", agent, "--hidden", os.path.dirname(hidden), "--out", out, "--timeout", "120"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        with open(out, encoding="utf-8") as h:
            report = json.load(h)
        # The fixture raises on a BOM header, which unittest reports as an error.
        self.assertEqual(report["hidden_checks"], {"H01": "pass", "H02": "error"})
        self.assertEqual((report["hidden_passed"], report["hidden_total"]), (1, 2))
        self.assertTrue(report["baseline_all_pass"])
        self.assertIn("importer/csv_import.py", report["taken_from_agent"])


class ScheduleTests(TempDirTest):
    def test_blocked_balanced_and_deterministic(self):
        a, b = schedule.make_schedule("ab" * 16), schedule.make_schedule("ab" * 16)
        self.assertEqual([r["run_id"] for r in a["runs"]], [r["run_id"] for r in b["runs"]])
        self.assertEqual(schedule.validate(a), [])
        for block in range(1, 10):
            groups = sorted(r["group"] for r in a["runs"] if r["block"] == block)
            tasks = {r["task"] for r in a["runs"] if r["block"] == block}
            self.assertEqual(groups, ["control", "treatment"])
            self.assertEqual(len(tasks), 1)
        for r in a["runs"]:
            self.assertRegex(r["run_id"], r"^r-[0-9a-f]{10}$")
            self.assertRegex(r["blind_id"], r"^b-[0-9a-f]{8}$")

    def test_rerun_appends_once_per_slot_and_next_skips_finished(self):
        s = schedule.make_schedule("01" * 16)
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
        model = {"providerID": "opencode", "id": "nemotron-3.5-super-vl-free", "enabled": True,
                 "variants": [{"id": v} for v in ("none", "low", "high", "xhigh")]}
        self.assertTrue(api_checks.check_model([model])["ok"])
        self.assertEqual(api_checks.check_model([dict(model, variants=[{"id": "high"}])])["reason"], "variant_absent")
        self.assertEqual(api_checks.check_model([])["reason"], "model_absent")
        self.assertFalse(api_checks.check_provider([{"id": "anthropic"}])["ok"])

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
                                             "--message-file", message, "--provider", "opencode", "--model", "nemotron-3.5-super-vl-free",
                                             "--variant", "xhigh", "--poll", "0", "--out-dir", out] + (["--attach-skill", "code-discipline"] if attach else []))
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
        self.assertEqual(create(control_requests)["model"], {"providerID": "opencode", "id": "nemotron-3.5-super-vl-free", "variant": "xhigh"})
        self.assertTrue(all(auth and auth.startswith("Basic ") for *_, auth in control_requests))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "plain", "export.json")))


def assistant(text="done", variant="xhigh", tools=(), reasoning=5):
    content = [{"type": "text", "text": text}] + list(tools)
    return {"type": "assistant", "id": "m", "time": {"created": 1}, "agent": "build",
            "model": {"providerID": "opencode", "id": "nemotron-3.5-super-vl-free", "variant": variant},
            "content": content, "tokens": {"input": 10, "output": 5, "reasoning": reasoning, "cache": {"read": 0, "write": 0}}}


def tool(name, input_, output="ok"):
    return {"type": "tool", "id": "t", "name": name, "time": {"created": 1},
            "state": {"status": "completed", "input": input_, "content": [{"type": "text", "text": output}]}}


class ExportCheckTests(unittest.TestCase):
    def export(self, *messages):
        return {"info": {"id": "ses_x"}, "messages": [{"type": "user", "id": "u", "time": {"created": 0}, "text": "task"}] + list(messages)}

    def test_treatment_confirmed_by_skill_message(self):
        skill_msg = {"type": "skill", "id": "s", "time": {"created": 1}, "skill": "code-discipline", "name": "code-discipline", "text": SKILL_BODY}
        report = export_checks.analyse(self.export(skill_msg, assistant()), "treatment")
        self.assertEqual((report["activation"], report["valid"]), ("CONFIRMED", True))

    def test_treatment_confirmed_by_attachment_text(self):
        export = self.export(assistant())
        export["messages"][0]["skills"] = [{"id": "code-discipline", "name": "code-discipline", "text": SKILL_BODY}]
        self.assertEqual(export_checks.analyse(export, "treatment")["activation"], "CONFIRMED")

    def test_treatment_without_skill_text_is_invalid(self):
        report = export_checks.analyse(self.export(assistant()), "treatment")
        self.assertEqual(report["activation"], "NOT_CONFIRMED")
        self.assertFalse(report["valid"])

    def test_control_clean_and_contaminated(self):
        self.assertTrue(export_checks.analyse(self.export(assistant(tools=[tool("shell", {"command": "python -m unittest"})])), "control")["valid"])
        leaked = assistant(tools=[tool("shell", {"command": "curl https://example.invalid/SKILL.md"}, output=SKILL_BODY)])
        report = export_checks.analyse(self.export(leaked), "control")
        self.assertTrue(report["contamination"])
        self.assertFalse(report["valid"])
        tried = assistant(tools=[tool("skill", {"id": "code-discipline"}, output="not found")])
        self.assertTrue(export_checks.analyse(self.export(tried), "control")["contamination"])

    def test_variant_mismatch_invalidates(self):
        report = export_checks.analyse(self.export(assistant(variant="high")), "control")
        self.assertFalse(report["model_ok"])
        self.assertFalse(report["valid"])
        self.assertFalse(export_checks.analyse(self.export(), "control")["model_ok"])


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


class AnalyzeTests(unittest.TestCase):
    def test_rubric_total_and_cap(self):
        full = {"dimensions": {k: 4 for k in analyze.WEIGHTS}}
        self.assertEqual(analyze.rubric_total(full), 100)
        self.assertEqual(analyze.rubric_total(dict(full, critical_failures=["fabricated test run"])), 49)
        self.assertIsNone(analyze.rubric_total({"dimensions": {}}))

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
