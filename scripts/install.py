#!/usr/bin/env python3
"""Safe, local-first installer for AI-Quality-Discipline Agent Skills."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SKILLS = ("code-discipline", "writing-specificity", "source-verification", "pr-hygiene")
TARGETS = {
    "codex": {"project": ".agents/skills", "user": ".agents/skills"},
    "claude": {"project": ".claude/skills", "user": ".claude/skills"},
    "copilot": {"project": ".github/skills", "user": ".copilot/skills"},
    "generic": {"project": ".agents/skills", "user": ".agents/skills"},
}
MANIFEST_NAME = ".ai-quality-discipline-manifest.json"
MANIFEST_VERSION = 1


class InstallError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def reject_symlink_components(path: Path, root: Path) -> None:
    if not is_within(path, root):
        raise InstallError(f"Refusing path outside installation root: {path}")
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise InstallError(f"Refusing to follow symlink: {current}")


def load_manifest(path: Path, scope: str) -> Dict[str, dict]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise InstallError(f"Manifest path is not a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"Cannot read installer manifest {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != MANIFEST_VERSION or not isinstance(payload.get("files"), dict):
        raise InstallError(f"Unsupported or malformed installer manifest: {path}")
    records = payload["files"]
    for rel, record in records.items():
        candidate = Path(rel)
        if candidate.is_absolute() or ".." in candidate.parts or not isinstance(record, dict):
            raise InstallError(f"Unsafe manifest entry: {rel!r}")
        target = record.get("target")
        skill = record.get("skill")
        expected = TARGETS.get(target, {}).get(scope)
        if skill not in SKILLS or not expected or candidate.as_posix() != f"{expected}/{skill}/SKILL.md":
            raise InstallError(f"Manifest entry is outside a known skill install path: {rel!r}")
        file_hash = record.get("sha256")
        if not isinstance(file_hash, str) or len(file_hash) != 64 or any(ch not in "0123456789abcdef" for ch in file_hash):
            raise InstallError(f"Malformed manifest hash for: {rel!r}")
    return records


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".aqd-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def write_manifest(path: Path, records: Dict[str, dict]) -> None:
    payload = {"version": MANIFEST_VERSION, "files": records}
    atomic_write(path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def installation_root(scope: str, project_dir: Optional[Path]) -> Path:
    if scope == "user":
        return Path.home().resolve()
    root = (project_dir or Path.cwd()).expanduser().resolve()
    if not root.is_dir():
        raise InstallError(f"Project directory does not exist: {root}")
    return root


def source_files(repo_dir: Path, selected: Iterable[str]) -> List[Tuple[str, Path, bytes]]:
    items = []
    for skill in selected:
        source = repo_dir / "skills" / skill / "SKILL.md"
        if source.is_symlink() or not source.is_file():
            raise InstallError(f"Canonical skill file is missing or unsafe: {source}")
        data = source.read_bytes()
        text = data.decode("utf-8")
        if not text.startswith("---\n") or f"name: {skill}\n" not in text:
            raise InstallError(f"Skill metadata is missing or mismatched: {source}")
        items.append((skill, source, data))
    return items


def run_install(args: argparse.Namespace) -> int:
    root = installation_root(args.scope, args.project_dir)
    repo_dir = args.repo_dir.expanduser().resolve()
    if not repo_dir.is_dir():
        raise InstallError(f"Repository directory does not exist: {repo_dir}")
    selected = SKILLS if args.skills == ["all"] else tuple(args.skills)
    unknown = sorted(set(selected) - set(SKILLS))
    if unknown:
        raise InstallError("Unknown skill(s): " + ", ".join(unknown))
    files = source_files(repo_dir, selected)
    destination_base = root / TARGETS[args.target][args.scope]
    manifest_path = root / MANIFEST_NAME
    reject_symlink_components(destination_base, root)
    reject_symlink_components(manifest_path, root)
    records = load_manifest(manifest_path, args.scope)
    next_records = dict(records)
    conflicts = 0
    actions = []

    for skill, _source, data in files:
        destination = destination_base / skill / "SKILL.md"
        reject_symlink_components(destination, root)
        rel = destination.relative_to(root).as_posix()
        new_hash = digest(data)
        previous = records.get(rel)
        if destination.exists():
            if not destination.is_file():
                actions.append(("CONFLICT", rel, "destination is not a regular file"))
                conflicts += 1
                continue
            current_hash = digest(destination.read_bytes())
            if current_hash == new_hash:
                actions.append(("UNCHANGED", rel, "already matches canonical skill"))
                if previous and previous.get("sha256") == current_hash:
                    next_records[rel] = {"sha256": current_hash, "target": args.target, "skill": skill}
                continue
            if not previous:
                actions.append(("CONFLICT", rel, "existing file is not managed by this installer"))
                conflicts += 1
                continue
            if current_hash != previous.get("sha256"):
                actions.append(("CONFLICT", rel, "managed file was modified; preserving user changes"))
                conflicts += 1
                continue
            action = "UPDATE"
        else:
            action = "CREATE"
        actions.append((action, rel, ""))
        next_records[rel] = {"sha256": new_hash, "target": args.target, "skill": skill}

    for action, rel, detail in actions:
        suffix = f" — {detail}" if detail else ""
        print(f"{action:9} {rel}{suffix}")
    if args.dry_run:
        print("Dry run: no files or manifest were changed.")
        return 2 if conflicts else 0

    for action, rel, _detail in actions:
        if action not in ("CREATE", "UPDATE"):
            continue
        destination = root / Path(rel)
        reject_symlink_components(destination, root)
        skill = next(s for s in selected if rel.endswith(f"/{s}/SKILL.md"))
        data = next(item[2] for item in files if item[0] == skill)
        if action == "CREATE" and destination.exists():
            raise InstallError(f"Destination appeared during installation; refusing overwrite: {destination}")
        if action == "UPDATE":
            previous = records.get(rel)
            if not destination.is_file() or digest(destination.read_bytes()) != previous.get("sha256"):
                raise InstallError(f"Managed file changed during installation; refusing overwrite: {destination}")
        atomic_write(destination, data)

    if next_records != records or not manifest_path.exists():
        write_manifest(manifest_path, next_records)
        print(f"MANIFEST  {manifest_path.relative_to(root).as_posix()}")
    if conflicts:
        print(f"Completed with {conflicts} conflict(s); conflicting files were left untouched.", file=sys.stderr)
        return 2
    print("Installation complete. No skill content or repository scripts were executed.")
    return 0


def run_uninstall(args: argparse.Namespace) -> int:
    root = installation_root(args.scope, args.project_dir)
    manifest_path = root / MANIFEST_NAME
    reject_symlink_components(manifest_path, root)
    records = load_manifest(manifest_path, args.scope)
    selected_records = {rel: record for rel, record in records.items() if record.get("target") == args.target}
    if not selected_records:
        print(f"No installer-managed files found for target {args.target}.")
        return 0
    removable = []
    preserved = []
    for rel, record in selected_records.items():
        path = root / Path(rel)
        reject_symlink_components(path, root)
        if not path.exists():
            preserved.append((rel, "already absent"))
        elif not path.is_file():
            preserved.append((rel, "not a regular file"))
        elif digest(path.read_bytes()) != record["sha256"]:
            preserved.append((rel, "modified since installation; preserving"))
        else:
            removable.append((rel, path))
    for rel, _ in removable:
        print(f"REMOVE    {rel}")
    for rel, reason in preserved:
        print(f"PRESERVE  {rel} — {reason}")
    if args.dry_run:
        print("Dry run: no files or manifest were changed.")
        return 0
    for _rel, path in removable:
        path.unlink()
        parent = path.parent
        while parent != root and is_within(parent, root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    remaining = {rel: record for rel, record in records.items() if record.get("target") != args.target}
    if remaining:
        write_manifest(manifest_path, remaining)
    else:
        manifest_path.unlink(missing_ok=True)
    print("Uninstall complete. User-modified files were preserved.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install AI-Quality-Discipline Agent Skills safely.")
    parser.add_argument("--target", choices=sorted(TARGETS), default="codex", help="Agent target (default: codex).")
    parser.add_argument("--scope", choices=("project", "user"), default="project", help="Install scope (default: project).")
    parser.add_argument("--skills", nargs="+", choices=("all",) + SKILLS, default=["all"], help="One or more skills, or all (default).")
    parser.add_argument("--project-dir", type=Path, help="Project root for project installs (default: current directory).")
    parser.add_argument("--repo-dir", type=Path, default=Path(__file__).resolve().parents[1], help="Repository checkout containing skills/.")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without writing files.")
    parser.add_argument("--uninstall", action="store_true", help="Remove only unchanged files recorded by the installer's manifest.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.skills != ["all"] and "all" in args.skills:
        parser.error("'all' cannot be combined with individual skill names")
    try:
        return run_uninstall(args) if args.uninstall else run_install(args)
    except (InstallError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
