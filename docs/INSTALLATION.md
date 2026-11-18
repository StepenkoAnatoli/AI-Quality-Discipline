# Installation

AI-Quality-Discipline is local-first. The installer copies canonical Agent Skills into a supported discovery directory; it does not install dependencies, call a hosted service, require an API key, or execute skill content or repository scripts.

## Requirements

- Python 3.9 or newer.
- A local checkout of this repository.
- Write access to the selected project directory or user home directory.

No administrator/root privileges are required.

## Preview first

Run commands from the repository root. The default target is Codex, the default scope is project, and the default selection is all four skills.

```bash
python scripts/install.py --target codex --scope project --dry-run
```

Review the proposed paths before installing.

## Install all skills

Project-level installation:

```bash
python scripts/install.py --target codex --scope project
python scripts/install.py --target claude --scope project
python scripts/install.py --target copilot --scope project
```

Personal installation:

```bash
python scripts/install.py --target codex --scope user
python scripts/install.py --target claude --scope user
python scripts/install.py --target copilot --scope user
```

Run separately for each target you want. The installer does not claim local files automatically become available in cloud-hosted agent sessions.

## Install one skill

```bash
python scripts/install.py --target codex --scope project --skills code-discipline
python scripts/install.py --target claude --scope user --skills source-verification
```

Valid names: `code-discipline`, `writing-specificity`, `source-verification`, and `pr-hygiene`.

## Target paths

| Target | Project install | Personal install |
|---|---|---|
| Codex | `.agents/skills/` | `~/.agents/skills/` |
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| GitHub Copilot | `.github/skills/` | `~/.copilot/skills/` |
| Generic Agent Skills | `.agents/skills/` | `~/.agents/skills/` |

Copilot support varies by product surface and version. These are documented paths, not a guarantee that every IDE, cloud agent, code review, CLI, or app surface discovers them identically. Consult [the compatibility record](AGENT-COMPATIBILITY.md).

## Conflict and update behavior

- Identical existing files are left unchanged.
- Existing files not recorded as installer-managed are never overwritten.
- Managed files are updated only if their current content still matches the previous installed version.
- If you edited a managed file, the installer preserves it and reports a conflict.
- A manifest named `.ai-quality-discipline-manifest.json` records managed paths and hashes in the project root or user home.
- Re-running the same command is idempotent.
- Conflicts produce exit code `2`. There is intentionally no force-overwrite option.

The installer rejects symlink traversal in target paths. It does not run installed skills, scripts, hooks, or commands.

## Uninstall

Preview:

```bash
python scripts/install.py --target codex --scope project --uninstall --dry-run
```

Remove unchanged installer-managed files:

```bash
python scripts/install.py --target codex --scope project --uninstall
```

Only files whose content still matches the recorded hash are removed. User-modified files are preserved. Repeat with each target/scope combination installed.

## Manual installation

Copy the desired skill directory from `skills/<skill-name>/` into the relevant target path above. Do not rename the skill directory: its name must match the `name` field in `SKILL.md`.

For environments without Agent Skills support, add a concise project instruction file (for example `AGENTS.md`) that points to the canonical principles and relevant skill instructions. Avoid maintaining divergent copies of the full rules.

## Compatibility limits

The installer tests file operations and target path selection. It does not test whether a particular agent build discovers, activates, or follows a skill. Verify discovery in the actual product/version and record it separately. Skills are guidance, not enforcement or a guarantee of model behavior.
