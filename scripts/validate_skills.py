#!/usr/bin/env python3
"""Validate canonical skill package structure; not full spec/runtime conformance."""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

EXPECTED = ("code-discipline", "writing-specificity", "source-verification", "pr-hygiene")
REQUIRED_SECTIONS = ("Use When", "Don't Use When", "Workflow", "Rules", "Examples", "Edge Cases", "References")

def validate_skill(skill_dir: Path, expected_name: str) -> list[str]:
    errors, path = [], skill_dir / "SKILL.md"
    if not path.is_file(): return [f"{expected_name}: missing SKILL.md"]
    try: content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc: return [f"{expected_name}: cannot read SKILL.md: {exc}"]
    if not content.startswith("---\n"): return [f"{expected_name}: missing YAML frontmatter opening delimiter"]
    end = content.find("\n---\n", 4)
    if end < 0: return [f"{expected_name}: missing YAML frontmatter closing delimiter"]
    fields = {}
    for line in content[4:end].splitlines():
        if not line.strip(): continue
        if ":" not in line: errors.append(f"{expected_name}: malformed frontmatter line: {line!r}"); continue
        key, value = line.split(":", 1); fields[key.strip()] = value.strip().strip('"').strip("'")
    if fields.get("name") != expected_name: errors.append(f"{expected_name}: frontmatter name must be {expected_name!r}")
    description = fields.get("description", "")
    if not description: errors.append(f"{expected_name}: missing description")
    elif len(description) > 1024: errors.append(f"{expected_name}: description exceeds 1024 characters")
    if re.search(r"[^a-z0-9-]", fields.get("name", "")): errors.append(f"{expected_name}: name must use lowercase letters, digits, and hyphens")
    for section in REQUIRED_SECTIONS:
        if not re.search(rf"^## {re.escape(section)}\s*$", content, re.MULTILINE):
            errors.append(f"{expected_name}: missing section '## {section}'")
    if content.count("\n---\n") != 1: errors.append(f"{expected_name}: unexpected additional frontmatter delimiter")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(); skills_root = args.root / "skills"
    if not skills_root.is_dir(): print(f"ERROR: skills directory not found: {skills_root}", file=sys.stderr); return 2
    errors = []
    for name in EXPECTED: errors.extend(validate_skill(skills_root / name, name))
    for name in sorted(p.name for p in skills_root.iterdir() if p.is_dir() and p.name not in EXPECTED):
        print(f"INFO: unregistered skill directory: {name}")
    if errors:
        for error in errors: print(f"FAIL: {error}")
        print(f"Skill package validation failed ({len(errors)} issue(s))."); return 1
    print(f"PASS: {len(EXPECTED)} canonical skills have expected metadata and sections.")
    print("LIMITATION: does not prove full specification conformance or runtime discovery."); return 0

if __name__ == "__main__":
    raise SystemExit(main())
