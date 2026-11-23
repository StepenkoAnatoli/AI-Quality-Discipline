#!/usr/bin/env python3
"""Package the live probe's operator-side evidence into ONE archive, with a manifest, and say honestly whether it
is complete. Replaces `tar ... 2>/dev/null || true`, which could hide a missing or unreadable file.

    python3 -I pack_evidence.py --operator DIR --run-id RUN --out ARCHIVE.tar.gz

What is collected (as before): DIR/preflight.log, DIR/launcher.log, DIR/sealed/**, DIR/captures/**. Each regular
file is opened once (no symlink followed) and streamed into the archive while its SHA-256 is computed and it is
scanned for token-shaped strings, so the archive holds exactly the bytes that were hashed. Nothing is held in
memory beyond one chunk (required JSON files, at most MAX_PARSE bytes, are also parsed). The archive ends with
evidence-manifest.json: path, size, SHA-256 and problem of each entry; never content. The archive is read back and
every member's hash compared with the manifest.

Problems (each makes the archive INCOMPLETE; the bytes are still archived wherever they could be read):
  * a required file (REQUIRED below) missing, not a regular file, unreadable, empty, malformed JSON, or an NDJSON
    line that is not one JSON object (a cut-off last line is corruption), or too large to parse;
  * ANY collected entry that is unreadable, not a regular file (FIFO, device, socket), or that changed size while
    read; any directory that could not be listed;
  * non-required files beyond TOTAL_BUDGET bytes in all (skipped and named; required files are always archived).
Symlinks are recorded and never followed; that alone is not a problem.

Exit codes (the archive is written in every case except 1, so partial evidence is never lost or invented):
  0  complete: every required file present and well-formed, no problem anywhere
  3  INCOMPLETE: at least one problem (see the manifest)
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
OVERLAP = 256          # bytes kept between chunks so a token split across two reads is still found
CHUNK = 1024 * 1024
MAX_PARSE = 64 * 1024 * 1024          # required JSON/NDJSON larger than this is archived but flagged
TOTAL_BUDGET = 2 * 1024 * 1024 * 1024  # non-required bytes; required files are always archived
TOP = ("preflight.log", "launcher.log")
TREES = ("sealed", "captures")
REQUIRED_TOP = ("preflight.log", "launcher.log", "sealed/schedule.json", "sealed/cc-run-approved.json",
                "sealed/preflight-cc.json")
REQUIRED_CAPTURE = ("launcher.log", "run-record.json", "run-status.json", "cc-env", "cc-settings.json",
                    "auth-check.json", "verify-pre.json", "verify-post.json", "export-checks.json", "live-probe.json",
                    "driver/transcript.ndjson", "driver/driver-result.json")
SYMLINK = "symlink (not followed)"


def required(run_id):
    return list(REQUIRED_TOP) + [f"captures/{run_id}/{p}" for p in REQUIRED_CAPTURE]


def _walk(operator, problems):
    """Relative paths of candidate entries (files, symlinks, others), sorted; directories are not listed.
    A directory that cannot be listed is recorded in `problems`."""
    out = []
    for name in TOP:
        if os.path.lexists(os.path.join(operator, name)):
            out.append(name)

    def onerror(exc):
        where = os.path.relpath(exc.filename, operator) if getattr(exc, "filename", None) else "?"
        problems.append({"path": where, "problem": "directory could not be listed"})

    for tree in TREES:
        root = os.path.join(operator, tree)
        if os.path.islink(root):
            out.append(tree)
            continue
        if not os.path.lexists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=onerror):
            for d in list(dirnames):
                if os.path.islink(os.path.join(dirpath, d)):
                    out.append(os.path.relpath(os.path.join(dirpath, d), operator))
                    dirnames.remove(d)
            for f in filenames:
                out.append(os.path.relpath(os.path.join(dirpath, f), operator))
    return sorted(set(out))


class _Hashing:
    """File-like reader for tarfile.addfile: hashes, scans for token shapes, and keeps a bounded copy for parsing."""

    def __init__(self, handle, keep):
        self.h, self.sha, self.tail, self.token, self.n = handle, hashlib.sha256(), b"", False, 0
        self.keep = bytearray() if keep else None

    def read(self, size=-1):
        data = self.h.read(CHUNK if size is None or size < 0 else min(size, CHUNK))
        self.sha.update(data)
        self.n += len(data)
        window = self.tail + data
        if not self.token and TOKEN_SHAPE.search(window):
            self.token = True
        self.tail = window[-OVERLAP:]
        if self.keep is not None and len(self.keep) <= MAX_PARSE:
            self.keep += data[:MAX_PARSE + 1 - len(self.keep)]
        return data


def _malformed(rel, data):
    if not data:
        return "empty"
    if rel.endswith(".json"):
        try:
            json.loads(bytes(data).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return "not valid JSON (truncated or corrupt)"
    if rel.endswith(".ndjson"):
        lines = [l for l in bytes(data).split(b"\n") if l.strip()]
        if not lines:
            return "no events"
        for line in lines:
            try:
                if not isinstance(json.loads(line.decode("utf-8")), dict):
                    return "a line is not a JSON object"
            except (UnicodeDecodeError, ValueError):
                return "a line is not JSON (truncated or corrupt)"
    return None


def _add(tar, operator, rel, is_required):
    """Stream one entry into the archive. Returns its manifest entry (problem None when archived cleanly)."""
    path = os.path.join(operator, rel)
    try:
        st = os.lstat(path)
    except OSError:
        return {"path": rel, "problem": "missing"}
    if stat.S_ISLNK(st.st_mode):
        return {"path": rel, "problem": SYMLINK}
    if not stat.S_ISREG(st.st_mode):
        return {"path": rel, "problem": "not a regular file"}
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return {"path": rel, "problem": "unreadable"}
    with os.fdopen(fd, "rb") as handle:
        fst = os.fstat(handle.fileno())
        if not stat.S_ISREG(fst.st_mode):
            return {"path": rel, "problem": "not a regular file"}
        reader = _Hashing(handle, keep=is_required)
        info = tarfile.TarInfo(rel)
        info.size, info.mode, info.mtime = fst.st_size, 0o600, int(time.time())
        try:
            tar.addfile(info, reader)
        except (OSError, tarfile.TarError) as exc:
            # a file that SHRANK while read: tarfile cannot recover a half-written member, so the archive is abandoned
            # (exit 1). Agent processes are killed before capture, so nothing should write here while packing.
            raise RuntimeError("shrank while read") from exc
        grew = bool(handle.read(1))
    entry = {"path": rel, "problem": "changed while read (archived as first seen)" if grew else None,
             "size": reader.n, "sha256": reader.sha.hexdigest()}
    if reader.token:
        entry["token_shaped"] = True
    if is_required:
        too_big = len(reader.keep) > MAX_PARSE
        entry["_malformed"] = "too large to parse (archived)" if too_big else _malformed(rel, reader.keep)
    return entry


def pack(operator, run_id, out):
    """Returns (exit_code, manifest)."""
    manifest = {"schema": 2, "run_id": run_id, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files": [], "required": required(run_id), "missing": [], "problems": [], "token_shaped_files": 0}
    req = set(manifest["required"])
    tmp = out + ".partial"
    try:
        with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            if not os.path.isdir(operator) or os.path.islink(operator):
                manifest["status"] = "no-evidence"
                manifest["note"] = "the operator store does not exist: the job stopped before the probe created anything"
            else:
                walk_problems = []
                entries = _walk(operator, walk_problems)
                # required files first, so the budget can never push one out
                order = [r for r in entries if r in req] + [r for r in entries if r not in req]
                used = 0
                for rel in order:
                    if rel not in req:
                        try:
                            size = os.lstat(os.path.join(operator, rel)).st_size
                        except OSError:
                            size = 0
                        if used + size > TOTAL_BUDGET:
                            manifest["files"].append({"path": rel, "problem": "skipped: over the total size budget"})
                            continue
                    entry = _add(tar, operator, rel, rel in req)
                    if entry.get("size") is not None and rel not in req:
                        used += entry["size"]
                    manifest["files"].append(entry)
                manifest["files"].sort(key=lambda e: e["path"])
                by_path = {e["path"]: e for e in manifest["files"]}
                for rel in manifest["required"]:
                    e = by_path.get(rel)
                    if e is None:
                        manifest["missing"].append(rel)
                        continue
                    problem = e["problem"] or e.get("_malformed")
                    if problem:
                        manifest["problems"].append({"path": rel, "problem": problem})
                for e in manifest["files"]:
                    e.pop("_malformed", None)
                    if e["path"] not in req and e["problem"] not in (None, SYMLINK):
                        manifest["problems"].append({"path": e["path"], "problem": e["problem"]})
                    if e.get("token_shaped"):
                        manifest["token_shaped_files"] += 1
                manifest["problems"].extend(walk_problems)
                if manifest["token_shaped_files"]:
                    manifest["status"] = "exposure-suspected"
                elif manifest["missing"] or manifest["problems"]:
                    manifest["status"] = "incomplete"
                else:
                    manifest["status"] = "complete"
            data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
            info = tarfile.TarInfo("evidence-manifest.json")
            info.size, info.mode, info.mtime = len(data), 0o600, int(time.time())
            tar.addfile(info, io.BytesIO(data))
            manifest_sha = hashlib.sha256(data).hexdigest()
        # read back: every member's bytes equal what was hashed, and nothing else is in the archive
        want = {e["path"]: e["sha256"] for e in manifest["files"] if e.get("sha256")}
        want["evidence-manifest.json"] = manifest_sha
        seen = {}
        with tarfile.open(tmp, "r:gz") as tar:
            for m in tar.getmembers():
                if not m.isfile() or m.name in seen:
                    raise ValueError("unexpected member")
                h, f = hashlib.sha256(), tar.extractfile(m)
                for chunk in iter(lambda: f.read(CHUNK), b""):
                    h.update(chunk)
                seen[m.name] = h.hexdigest()
        if seen != want:
            raise ValueError("archive content differs from the hashed files")
        os.replace(tmp, out)
    except (OSError, ValueError, RuntimeError, tarfile.TarError):
        for p in (tmp, out):
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
