"""Tests for pack_evidence.py: an incomplete, truncated, unreadable or partial capture can never be packaged as
complete, and nothing is invented when there is no capture. Synthetic trees only; the token is synthetic."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

LIVE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIVE)
import pack_evidence as pe  # noqa: E402

RUN = "r-e8e1d02634"
SYNTHETIC = "sk-ant-oat01-REHEARSAL-SYNTHETIC-" + "0123456789abcdef" * 2


def full_store(root):
    files = {
        "preflight.log": "preflight passed\n",
        "launcher.log": "[probe] run valid\n",
        "sealed/schedule.json": "{}",
        "sealed/cc-run-approved.json": '{"approved_runs": []}',
        "sealed/preflight-cc.json": '{"ok": true}',
        "sealed/STOP": "PROBE FAILED\n",
    }
    for rel in pe.REQUIRED_CAPTURE:
        body = '{"type": "system"}\n{"type": "result"}\n' if rel.endswith(".ndjson") else (
            '{"valid": true}' if rel.endswith(".json") else "x\n")
        files[f"captures/{RUN}/{rel}"] = body
    files[f"captures/{RUN}/driver/stderr.txt"] = ""
    for rel, body in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as h:
            h.write(body)
    return files


class PackEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.op = os.path.join(self.tmp, "operator")
        self.out = os.path.join(self.tmp, "capture.tar.gz")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def members(self):
        with tarfile.open(self.out, "r:gz") as tar:
            return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}

    def test_complete_store_packs_exactly_the_checked_bytes(self):
        files = full_store(self.op)
        code, m = pe.pack(self.op, RUN, self.out)
        self.assertEqual((code, m["status"]), (0, "complete"))
        got = self.members()
        self.assertEqual(set(got), set(files) | {"evidence-manifest.json"})
        for rel, body in files.items():
            self.assertEqual(got[rel], body.encode())
        manifest = json.loads(got["evidence-manifest.json"])
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual({e["path"]: e["sha256"] for e in manifest["files"]},
                         {rel: hashlib.sha256(b.encode()).hexdigest() for rel, b in files.items()})

    def test_every_missing_required_file_makes_it_incomplete(self):
        for rel in pe.required(RUN):
            with self.subTest(rel=rel):
                shutil.rmtree(self.op, ignore_errors=True)
                full_store(self.op)
                os.unlink(os.path.join(self.op, rel))
                code, m = pe.pack(self.op, RUN, self.out)
                self.assertEqual((code, m["status"], m["missing"]), (3, "incomplete", [rel]))
                self.assertIn("evidence-manifest.json", self.members())  # partial evidence still kept

    def test_truncated_and_corrupt_files_are_detected(self):
        cases = {f"captures/{RUN}/run-status.json": '{"valid": tr',
                 f"captures/{RUN}/live-probe.json": "",
                 f"captures/{RUN}/driver/transcript.ndjson": '{"type": "system"}\n{"type": "res',
                 "sealed/cc-run-approved.json": "\x00\x01garbage"}
        for rel, body in cases.items():
            with self.subTest(rel=rel):
                shutil.rmtree(self.op, ignore_errors=True)
                full_store(self.op)
                with open(os.path.join(self.op, rel), "w", encoding="utf-8") as h:
                    h.write(body)
                code, m = pe.pack(self.op, RUN, self.out)
                self.assertEqual(code, 3)
                self.assertEqual([p["path"] for p in m["problems"]], [rel])

    def test_unreadable_files_are_detected_required_or_not(self):
        full_store(self.op)
        real_open = os.open
        blocked = {os.path.join(self.op, f"captures/{RUN}/run-status.json"), os.path.join(self.op, "sealed/STOP")}

        def fake_open(path, *a, **k):
            if path in blocked:
                raise PermissionError(13, "denied")
            return real_open(path, *a, **k)
        with mock.patch.object(pe.os, "open", fake_open):
            code, m = pe.pack(self.op, RUN, self.out)
        self.assertEqual(code, 3)
        self.assertEqual(sorted(p["path"] for p in m["problems"]), sorted([f"captures/{RUN}/run-status.json",
                                                                          "sealed/STOP"]))

    def test_a_failed_run_with_partial_captures_is_packed_as_incomplete(self):
        # e.g. the launcher refused at the auth check: capture dir exists with only a few files
        full_store(self.op)
        cap = os.path.join(self.op, "captures", RUN)
        for rel in ("driver/transcript.ndjson", "driver/driver-result.json", "export-checks.json", "verify-post.json",
                    "live-probe.json"):
            os.unlink(os.path.join(cap, rel))
        code, m = pe.pack(self.op, RUN, self.out)
        self.assertEqual((code, m["status"], len(m["missing"])), (3, "incomplete", 5))
        self.assertIn(f"captures/{RUN}/run-status.json", self.members())

    def test_no_operator_store_invents_nothing(self):
        code, m = pe.pack(self.op, RUN, self.out)
        self.assertEqual((code, m["status"], m["files"]), (4, "no-evidence", []))
        self.assertEqual(set(self.members()), {"evidence-manifest.json"})

    def test_failure_before_the_capture_was_created(self):
        # setup and preflight ran, the launcher never created a capture
        os.makedirs(os.path.join(self.op, "sealed"))
        with open(os.path.join(self.op, "preflight.log"), "w") as h:
            h.write("preflight FAILED\n")
        code, m = pe.pack(self.op, RUN, self.out)
        self.assertEqual((code, m["status"]), (3, "incomplete"))
        self.assertEqual(set(self.members()), {"preflight.log", "evidence-manifest.json"})

    def test_symlinks_are_recorded_not_followed(self):
        full_store(self.op)
        secret = os.path.join(self.tmp, "outside-secret")
        with open(secret, "w") as h:
            h.write(SYNTHETIC)
        os.symlink(secret, os.path.join(self.op, "captures", RUN, "link"))
        os.symlink(self.tmp, os.path.join(self.op, "captures", RUN, "dirlink"))
        code, m = pe.pack(self.op, RUN, self.out)
        self.assertEqual(code, 0)
        self.assertEqual(m["token_shaped_files"], 0)
        self.assertNotIn(f"captures/{RUN}/link", self.members())
        self.assertTrue(all(SYNTHETIC.encode() not in b for b in self.members().values()))

    def test_a_token_shaped_string_is_flagged_and_kept_encrypted_never_printed(self):
        full_store(self.op)
        with open(os.path.join(self.op, "captures", RUN, "driver", "stderr.txt"), "w") as h:
            h.write("leak " + SYNTHETIC + "\n")
        r = subprocess.run([sys.executable, "-I", os.path.join(LIVE, "pack_evidence.py"), "--operator", self.op,
                            "--run-id", RUN, "--out", self.out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 5)
        self.assertIn("token_shaped_files=1", r.stdout)
        self.assertNotIn("sk-ant-oat01-", r.stdout + r.stderr)
        self.assertIn(SYNTHETIC.encode(), self.members()[f"captures/{RUN}/driver/stderr.txt"])

    def test_archive_write_failure_is_exit_1_and_leaves_nothing(self):
        full_store(self.op)
        bad_out = os.path.join(self.tmp, "no-such-dir", "capture.tar.gz")
        code, _ = pe.pack(self.op, RUN, bad_out)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(bad_out))

    def test_archive_that_does_not_read_back_is_rejected(self):
        full_store(self.op)
        real = pe.tarfile.TarFile.addfile

        def corrupting(self_, info, fileobj=None):
            if info.name.endswith("run-status.json"):
                fileobj = __import__("io").BytesIO(b"X" * info.size)
            return real(self_, info, fileobj)
        with mock.patch.object(pe.tarfile.TarFile, "addfile", corrupting):
            code, _ = pe.pack(self.op, RUN, self.out)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.out))

    def test_cli_rejects_bad_run_id(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(LIVE, "pack_evidence.py"), "--operator", self.op,
                            "--run-id", "../x", "--out", self.out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
