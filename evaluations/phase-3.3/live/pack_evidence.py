#!/usr/bin/env python3
"""Package the live probe's operator-side evidence into ONE archive, with a manifest, and say honestly whether it
is complete. Replaces `tar ... 2>/dev/null || true`, which could hide a missing or unreadable file.

    python3 -I pack_evidence.py --operator DIR --run-id RUN --out ARCHIVE.tar.gz

What is collected (as before): DIR/preflight.log, DIR/launcher.log, DIR/sealed/**, DIR/captures/**. Every file is
read once; the archive holds exactly the bytes that were checked, plus evidence-manifest.json (path, size, SHA-256
and problem of each file; never content). Symlinks are recorded, never followed.

REQUIRED (the evidence of one run that reached its verdict; see REQUIRED below): each must exist, be a readable
regular file and be non-empty; JSON files must parse; transcript.ndjson must be one JSON object per non-empty line
(a cut-off last line is corruption).

Exit codes (the archive is written in every case except 1, so partial evidence is never lost or invented):
  0  complete: every required file present and well-formed
  3  INCOMPLETE: something required is missing, empty, unreadable or malformed
  4  NO EVIDENCE: the operator store does not exist (the job stopped before the probe created anything)
  5  EXPOSURE SUSPECTED: a token-shaped string is in a collected file (kept, encrypted, as evidence; counted only)
  1  the archive could not be written or did not verify
Public output: one status line and counts. Never a path's content, never a token.
"""
import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile
import time

TOKEN_SHAPE = re.compile(rb"sk-ant-(?:oat|api|ort)\d\d-[A-Za-z0-9_-]{20,}")
TOP = ("preflight.log", "launcher.log")
TREES = ("sealed", "captures")
REQUIRED_TOP = ("preflight.log", "launcher.log", "sealed/schedule.json", "sealed/cc-run-approved.json",
                "sealed/preflight-cc.json")
REQUIRED_CAPTURE = ("launcher.log", "run-record.json", "run-status.json", "cc-env", "cc-settings.json",
                    "auth-check.json", "verify-pre.json", "verify-post.json", "export-checks.json", "live-probe.json",
                    "driver/transcript.ndjson", "driver/driver-result.json")
MAX_FILE = 64 * 1024 * 1024


def required(run_id):
    return list(REQUIRED_TOP) + [f"captures/{run_id}/{p}" for p in REQUIRED_CAPTURE]


def _walk(operator):
    """Relative paths of candidate entries (files, symlinks, others), sorted; directories are not listed."""
    out = []
    for name in TOP:
        if os.path.lexists(os.path.join(operator, name)):
            out.append(name)
    for tree in TREES:
        root = os.path.join(operator, tree)
        if os.path.islink(root):
            out.append(tree)
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            for d in list(dirnames):
                if os.path.islink(os.path.join(dirpath, d)):
                    out.append(os.path.relpath(os.path.join(dirpath, d), operator))
                    dirnames.remove(d)
            for f in filenames:
                out.append(os.path.relpath(os.path.join(dirpath, f), operator))
    return sorted(set(out))


def _read(path):
    """(bytes|None, problem|None) without following a symlink."""
    try:
        st = os.lstat(path)
    except OSError:
        return None, "missing"
    if stat.S_ISLNK(st.st_mode):
        return None, "symlink (not followed)"
    if not stat.S_ISREG(st.st_mode):
        return None, "not a regular file"
    if st.st_size > MAX_FILE:
        return None, "too large"
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as h:
            data = h.read()
    except OSError:
        return None, "unreadable"
    return data, None


def _malformed(rel, data):
    if not data:
        return "empty"
    if rel.endswith(".json"):
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return "not valid JSON (truncated or corrupt)"
    if rel.endswith(".ndjson"):
        lines = [l for l in data.split(b"\n") if l.strip()]
        if not lines:
            return "no events"
        for line in lines:
            try:
                if not isinstance(json.loads(line.decode("utf-8")), dict):
                    return "a line is not a JSON object"
            except (UnicodeDecodeError, ValueError):
                return "a line is not JSON (truncated or corrupt)"
    return None


def pack(operator, run_id, out):
    """Returns (exit_code, manifest)."""
    manifest = {"schema": 1, "run_id": run_id, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files": [], "required": required(run_id), "missing": [], "problems": [], "token_shaped_files": 0}
    blobs = {}
    if not os.path.isdir(operator) or os.path.islink(operator):
        manifest["status"] = "no-evidence"
        manifest["note"] = "the operator store does not exist: the job stopped before the probe created anything"
    else:
        for rel in _walk(operator):
            data, problem = _read(os.path.join(operator, rel))
            entry = {"path": rel, "problem": problem}
            if data is not None:
                entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
                if TOKEN_SHAPE.search(data):
                    manifest["token_shaped_files"] += 1
                    entry["token_shaped"] = True
                blobs[rel] = data
            manifest["files"].append(entry)
        by_path = {e["path"]: e for e in manifest["files"]}
        for rel in manifest["required"]:
            e = by_path.get(rel)
            if e is None:
                manifest["missing"].append(rel)
                continue
            problem = e["problem"] or _malformed(rel, blobs.get(rel, b""))
            if problem:
                manifest["problems"].append({"path": rel, "problem": problem})
        unreadable = [e["path"] for e in manifest["files"] if e["problem"] == "unreadable"]
        for rel in unreadable:
            if rel not in manifest["required"]:
                manifest["problems"].append({"path": rel, "problem": "unreadable"})
        if manifest["token_shaped_files"]:
            manifest["status"] = "exposure-suspected"
        elif manifest["missing"] or manifest["problems"]:
            manifest["status"] = "incomplete"
        else:
            manifest["status"] = "complete"
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        tmp = out + ".partial"
        with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            for rel in [*sorted(blobs), "evidence-manifest.json"]:
                data = blobs[rel] if rel in blobs else manifest_bytes
                info = tarfile.TarInfo(rel)
                info.size, info.mode, info.mtime = len(data), 0o600, int(time.time())
                tar.addfile(info, io.BytesIO(data))
        os.replace(tmp, out)
        # read back: every member's bytes equal what was checked, and nothing else is in the archive
        with tarfile.open(out, "r:gz") as tar:
            seen = {}
            for m in tar.getmembers():
                if not m.isfile():
                    raise ValueError("non-file member")
                seen[m.name] = hashlib.sha256(tar.extractfile(m).read()).hexdigest()
        want = {rel: hashlib.sha256(b).hexdigest() for rel, b in blobs.items()}
        want["evidence-manifest.json"] = hashlib.sha256(manifest_bytes).hexdigest()
        if seen != want:
            raise ValueError("archive content differs from the checked files")
    except (OSError, ValueError, tarfile.TarError):
        for p in (out + ".partial", out):
            try:
                os.unlink(p)
            except OSError:
                pass
        return 1, manifest
    return {"complete": 0, "incomplete": 3, "no-evidence": 4, "exposure-suspected": 5}[manifest["status"]], manifest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--operator", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    if not re.match(r"^r-[0-9a-f]{10}$", args.run_id):
        print("evidence: bad run id")
        return 1
    code, m = pack(args.operator, args.run_id, args.out)
    print("evidence: status=%s files=%d required_missing=%d problems=%d token_shaped_files=%d archive=%s" % (
        m.get("status"), len(m["files"]), len(m["missing"]), len(m["problems"]), m["token_shaped_files"],
        "written" if code != 1 else "NOT WRITTEN"))
    if m["token_shaped_files"]:
        print("evidence: TOKEN-SHAPED STRING IN THE CAPTURE: treat the token as compromised and revoke it now")
    return code


if __name__ == "__main__":
    sys.exit(main())
