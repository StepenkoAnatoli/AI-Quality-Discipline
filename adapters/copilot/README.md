# GitHub Copilot adapter

Canonical skill files remain in `skills/`. The installer copies them to:

- Project: `.github/skills/<skill-name>/SKILL.md`
- Personal: `~/.copilot/skills/<skill-name>/SKILL.md`

Install with `python scripts/install.py --target copilot --scope project` (or `--scope user`). See [installation](../../docs/INSTALLATION.md) and [compatibility notes](../../docs/AGENT-COMPATIBILITY.md).

Copilot discovery differs across IDE, CLI, cloud agent, code review, and app surfaces and may change by version. The documented paths do not prove universal surface support. Test each surface before declaring it supported.
