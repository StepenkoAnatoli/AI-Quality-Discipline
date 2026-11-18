# Codex adapter

Canonical skill files remain in `skills/`. The installer copies them to:

- Project: `.agents/skills/<skill-name>/SKILL.md`
- Personal: `~/.agents/skills/<skill-name>/SKILL.md`

Install with `python scripts/install.py --target codex --scope project` (or `--scope user`). See [installation](../../docs/INSTALLATION.md) and [compatibility notes](../../docs/AGENT-COMPATIBILITY.md).

These paths are documented by Codex. Actual discovery and invocation should be tested in the Codex build and environment being supported; runtime tests are not claimed here.
