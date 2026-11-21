#!/usr/bin/env python3
"""Allowlist-driven JSON manifests for Phase 3.2 agent projects.

Subcommands (paths may contain spaces; nothing is passed through a shell):

  check-sources --phase-root DIR
      Every task source directory contains exactly the allowlisted files.
  build --phase-root DIR --task ID --out FILE [--source-commit SHA]
      Hash every allowlisted file for a task into a JSON manifest.
  materialize --phase-root DIR --manifest FILE --dest DIR
      Copy exactly the manifest's files from the allowlisted sources into an
      empty or new directory, verifying each hash after copying.
  categories --manifest FILE
      Print NUL-delimited pairs for shell loops (safe with spaces): first every
      directory, parents before children, as "dir|dir-additive|dir-protected\\0
      <path>\\0", then every file as "<category>\\0<path>\\0".
  verify --manifest FILE --tree DIR --phase pre|post --out FILE
      Compare a project tree with the manifest and write a JSON report.

Exit codes: 0 success / integrity intact, 1 integrity violation or source
mismatch, 2 usage or input error.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import stat
import sys

ALLOWLIST_NAME = "allowlist.json"
SCHEMA_VERSION = 1


class UsageError(Exception):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def load_allowlist(phase_root):
    path = os.path.join(phase_root, ALLOWLIST_NAME)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise UsageError(f"unsupported allowlist schema in {path}")
    return data, sha256_file(path)


def _safe_rel(rel):
    parts = rel.split("/")
    if rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") for p in parts):
        raise UsageError(f"unsafe relative path in allowlist: {rel!r}")
    return rel


def task_entries(allowlist, task):
    """Return [(dest_rel, source_rel_to_phase_root, category)] for one task."""
    tasks = allowlist["tasks"]
    if task not in tasks:
        raise UsageError(f"unknown task {task!r}; expected one of {sorted(tasks)}")
    spec = tasks[task]
    entries = []
    for rel, category in spec["files"].items():
        entries.append((_safe_rel(rel), f"{spec['source_dir']}/{rel}", category))
    for rel, info in allowlist.get("common_files", {}).items():
        entries.append((_safe_rel(rel), info["source"], info["category"]))
    dests = [e[0] for e in entries]
    if len(dests) != len(set(dests)):
        raise UsageError(f"duplicate destination paths for {task}")
    return sorted(entries)


def _walk(tree):
    """Yield (rel_posix, kind) for every entry below tree without following links."""
    for dirpath, dirnames, filenames in os.walk(tree, followlinks=False):
        rel_dir = os.path.relpath(dirpath, tree)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                yield (f"{rel_dir}/{name}" if rel_dir else name), "symlink"
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = f"{rel_dir}/{name}" if rel_dir else name
            mode = os.lstat(full).st_mode
            if stat.S_ISLNK(mode):
                yield rel, "symlink"
            elif stat.S_ISREG(mode):
                yield rel, "file"
            else:
                yield rel, "special"


def check_sources(phase_root):
    allowlist, _ = load_allowlist(phase_root)
    problems = []
    tolerated = set(allowlist.get("tolerated_artifacts", []))
    for task, spec in sorted(allowlist["tasks"].items()):
        source_dir = os.path.join(phase_root, *spec["source_dir"].split("/"))
        listed = set(spec["files"])
        present = {}
        for rel, kind in _walk(source_dir):
            if set(rel.split("/")) & tolerated:
                continue
            present[rel] = kind
        for rel in sorted(listed - set(present)):
            problems.append(f"{task}: allowlisted file missing: {rel}")
        for rel in sorted(set(present) - listed):
            problems.append(f"{task}: file present but not allowlisted: {rel}")
        for rel, kind in sorted(present.items()):
            if kind != "file":
                problems.append(f"{task}: not a regular file: {rel} ({kind})")
    for rel, info in allowlist.get("common_files", {}).items():
        if not os.path.isfile(os.path.join(phase_root, *info["source"].split("/"))):
            problems.append(f"common file missing: {info['source']}")
    return problems


def build(phase_root, task, source_commit=None):
    allowlist, allowlist_hash = load_allowlist(phase_root)
    files = []
    for dest, source, category in task_entries(allowlist, task):
        path = os.path.join(phase_root, *source.split("/"))
        if not os.path.isfile(path) or os.path.islink(path):
            raise UsageError(f"allowlisted source is not a regular file: {source}")
        files.append({"path": dest, "sha256": sha256_file(path), "size": os.path.getsize(path), "category": category, "source": source})
    directories = sorted({"/".join(f["path"].split("/")[:i]) for f in files for i in range(1, len(f["path"].split("/")))})
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "aqd-phase-3.2-project-manifest",
        "task": task,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": source_commit,
        "allowlist_sha256": allowlist_hash,
        "additive_dirs": allowlist.get("additive_dirs", []),
        "protected_dirs": allowlist.get("protected_dirs", []),
        "tolerated_artifacts": allowlist.get("tolerated_artifacts", []),
        "directories": directories,
        "files": files,
    }


def materialize(phase_root, manifest, dest):
    if os.path.lexists(dest) and (not os.path.isdir(dest) or os.listdir(dest)):
        raise UsageError(f"destination must be absent or an empty directory: {dest}")
    os.makedirs(dest, exist_ok=True)
    for rel in manifest["directories"]:
        os.makedirs(os.path.join(dest, *rel.split("/")), exist_ok=True)
    for entry in manifest["files"]:
        source = os.path.join(phase_root, *entry["source"].split("/"))
        target = os.path.join(dest, *entry["path"].split("/"))
        shutil.copyfile(source, target, follow_symlinks=False)
        if sha256_file(target) != entry["sha256"]:
            raise UsageError(f"hash mismatch after copying {entry['path']}")


def _under(rel, prefixes):
    return any(rel == p or rel.startswith(p + "/") for p in prefixes)


def verify(manifest, tree, phase):
    expected = {f["path"]: f for f in manifest["files"]}
    tolerated = set(manifest.get("tolerated_artifacts", []))
    additive = manifest.get("additive_dirs", [])
    findings = {key: [] for key in (
        "immutable_modified", "immutable_missing", "mutable_changed", "mutable_missing",
        "additive_changed", "additive_missing", "additive_new", "tolerated", "unexpected", "symlink", "special",
    )}
    seen = {}
    for rel, kind in _walk(tree):
        seen[rel] = kind
    files = {}
    for rel, kind in sorted(seen.items()):
        if kind == "symlink":
            findings["symlink"].append(rel)
            if rel in expected and expected[rel]["category"] == "immutable":
                findings["immutable_modified"].append(rel)
            continue
        if kind == "special":
            findings["special"].append(rel)
            continue
        digest = sha256_file(os.path.join(tree, *rel.split("/")))
        entry = expected.get(rel)
        if entry is None:
            if _under(rel, additive):
                status = "additive_new"
            elif set(rel.split("/")) & tolerated:
                status = "tolerated"
            else:
                status = "unexpected"
            findings[status].append(rel)
        else:
            changed = digest != entry["sha256"]
            status = {"immutable": "immutable_modified", "mutable": "mutable_changed", "additive": "additive_changed"}[entry["category"]] if changed else "unchanged"
            if changed:
                findings[status].append(rel)
        files[rel] = {"sha256": digest, "status": status}
    for rel, entry in expected.items():
        if rel not in seen:
            findings[f"{entry['category']}_missing"].append(rel)
    if phase == "pre":
        problems = sum(len(v) for v in findings.values())
        integrity_ok = problems == 0
    else:
        integrity_ok = not (findings["immutable_modified"] or findings["immutable_missing"])
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "aqd-phase-3.2-verify-report",
        "phase": phase,
        "task": manifest["task"],
        "integrity_ok": integrity_ok,
        "findings": {k: sorted(set(v)) for k, v in findings.items()},
        "files": files,
    }


def _write_json(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-sources")
    p.add_argument("--phase-root", required=True)
    p = sub.add_parser("build")
    p.add_argument("--phase-root", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--source-commit")
    p = sub.add_parser("materialize")
    p.add_argument("--phase-root", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--dest", required=True)
    p = sub.add_parser("categories")
    p.add_argument("--manifest", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--manifest", required=True)
    p.add_argument("--tree", required=True)
    p.add_argument("--phase", choices=("pre", "post"), required=True)
    p.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check-sources":
            problems = check_sources(args.phase_root)
            for line in problems:
                print(line)
            print("sources OK" if not problems else f"{len(problems)} problem(s)")
            return 1 if problems else 0
        if args.command == "build":
            _write_json(args.out, build(args.phase_root, args.task, args.source_commit))
            return 0
        with open(args.manifest, encoding="utf-8") as handle:
            manifest = json.load(handle)
        if manifest.get("kind") != "aqd-phase-3.2-project-manifest":
            raise UsageError("not a Phase 3.2 project manifest")
        if args.command == "materialize":
            materialize(args.phase_root, manifest, args.dest)
            return 0
        if args.command == "categories":
            out = sys.stdout.buffer
            additive = set(manifest.get("additive_dirs", []))
            protected = set(manifest.get("protected_dirs", []))
            for rel in manifest["directories"]:
                kind = b"dir-additive" if rel in additive else b"dir-protected" if rel in protected else b"dir"
                out.write(kind + b"\0" + rel.encode("utf-8") + b"\0")
            for entry in manifest["files"]:
                out.write(entry["category"].encode() + b"\0" + entry["path"].encode("utf-8") + b"\0")
            return 0
        report = verify(manifest, args.tree, args.phase)
        _write_json(args.out, report)
        print(f"{args.phase}-run integrity {'OK' if report['integrity_ok'] else 'VIOLATED'} for {manifest['task']}")
        return 0 if report["integrity_ok"] else 1
    except (UsageError, OSError, ValueError, KeyError) as exc:
        print(f"manifest.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
