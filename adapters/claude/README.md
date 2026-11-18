# Claude Code adapter

Canonical skill files remain in `skills/`. The installer copies them to:

- Project: `.claude/skills/<skill-name>/SKILL.md`
- Personal: `~/.claude/skills/<skill-name>/SKILL.md`

Install with `python scripts/install.py --target claude --scope project` (or `--scope user`). See [installation](../../docs/INSTALLATION.md) and [compatibility notes](../../docs/AGENT-COMPATIBILITY.md).

These paths are documented by Claude Code. Local installation does not imply availability in cloud/Cowork sessions. Test discovery and invocation in the product surface being supported.
