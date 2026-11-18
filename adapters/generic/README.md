# Generic Agent Skills adapter

For consumers implementing the open Agent Skills convention, the installer copies canonical skills to:

- Project: `.agents/skills/<skill-name>/SKILL.md`
- Personal: `~/.agents/skills/<skill-name>/SKILL.md`

Install with `python scripts/install.py --target generic --scope project` (or `--scope user`). A consumer must support this discovery convention; the path alone cannot make an incompatible agent load skills. See [installation](../../docs/INSTALLATION.md).
