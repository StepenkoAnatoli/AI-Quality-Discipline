# Agent Skills compatibility and installation paths

**Last checked:** 2026-11-19  
**Purpose:** Record official documentation used to choose the canonical skill format and initial integration paths. Re-check these sources before releasing installer changes; agent products evolve independently.

## Canonical format

Use the open **Agent Skills** format as the canonical source format.

Official specification: https://agentskills.io/specification

A skill is a directory containing a required SKILL.md with YAML frontmatter and Markdown instructions. Optional resources include scripts/, references/, and assets/.

Required frontmatter:
- name: 1–64 characters; lowercase letters, numbers, and hyphens; no leading/trailing hyphen or consecutive hyphens; must match the skill directory name.
- description: 1–1024 characters; non-empty; says what the skill does and when to use it.

Optional fields include license, compatibility, metadata, and experimental allowed-tools. Do not rely on experimental fields for baseline interoperability.

The specification describes progressive disclosure: agents discover short metadata first, load the full SKILL.md when relevant, and access optional resources as needed. It recommends keeping the main skill file concise (under 500 lines; under 5,000 tokens is a useful target).

**Versioning decision:** the public specification is maintained as a living web specification and does not expose a conventional semantic version in the reviewed document. Do not invent a version number. Record the canonical URL and review date, and use conformance tests to detect breaking changes. Re-check the specification before each compatibility release.

## Verified integration paths

| Agent | Project-level path | Personal path | Official documentation |
|---|---|---|---|
| OpenAI Codex | .agents/skills/<skill-name>/SKILL.md | ~/.agents/skills/<skill-name>/SKILL.md | https://learn.chatgpt.com/docs/build-skills |
| Claude Code | .claude/skills/<skill-name>/SKILL.md | ~/.claude/skills/<skill-name>/SKILL.md | https://code.claude.com/docs/en/skills |
| GitHub Copilot | .github/skills/, .agents/skills/, or .claude/skills/ | ~/.copilot/skills/ or ~/.agents/skills/ | https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills and https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills |

Paths above are documented discovery locations, not a promise that every Copilot surface or IDE version supports every location identically. Copilot's official documentation explicitly notes that support depends on the surface. The installer must expose the target surface and scope, and must not assume personal skills are available to cloud agents.

### Codex notes

- Codex scans project .agents/skills locations from the current working directory up to the repository root.
- Personal skills live under ~/.agents/skills.
- Codex supports explicit skill invocation and implicit selection based on the skill description.
- OpenAI documentation recommends plugins when distributing reusable skills more broadly or bundling skills with connectors. Plugin packaging is a later distribution option, not a prerequisite for local adoption.

### Claude Code notes

- Project skills live under .claude/skills/<skill-name>/SKILL.md.
- Personal skills live under ~/.claude/skills/<skill-name>/SKILL.md.
- Claude Code follows the Agent Skills open standard and adds product-specific extensions. Keep canonical skill files within the common standard; isolate any Claude-only metadata or behavior in an adapter only when necessary.
- Claude Code supports explicit invocation and automatic use when relevant.
- Claude's cloud/Cowork sessions do not necessarily read local machine skill directories. Do not equate local installation with cloud-account availability.

### GitHub Copilot notes

- Project locations documented by GitHub include .github/skills, .claude/skills, and .agents/skills.
- Personal locations include ~/.copilot/skills and ~/.agents/skills.
- Supported surfaces include Copilot cloud agent, code review, CLI, app, and IDE agent modes, but IDE and location support can vary by surface/version.
- The Copilot CLI has its own installation/reload documentation. Validate each supported surface rather than assuming one path proves all surfaces work.

## Repository layout decision

Keep canonical skills in one neutral directory:

    skills/
      code-discipline/SKILL.md
      pr-hygiene/SKILL.md
      source-verification/SKILL.md
      writing-specificity/SKILL.md

The installer or release packaging copies selected skill directories into the target's supported location. Do not check in three copies of each canonical skill merely to satisfy three agents.

For projects that need skills immediately without an installer, provide documented manual copy instructions. Later, the installer should support Codex, Claude Code, and Copilot as separate explicit targets.

## Compatibility rules

1. Do not claim an integration is supported merely because the format looks compatible.
2. Test skill discovery and invocation on each target surface/version before marking it verified.
3. Record the product, version, operating system, scope (project/personal), and test date.
4. Distinguish format conformance from actual agent behavior.
5. Do not add vendor-specific frontmatter to canonical files unless the open specification accepts it.
6. Keep product-specific options optional and isolated.
7. Re-check official documentation before releases and update this file when paths or behavior change.

## Sources

- Agent Skills specification: https://agentskills.io/specification
- OpenAI Codex and ChatGPT skills guide: https://learn.chatgpt.com/docs/build-skills
- Claude Code skills documentation: https://code.claude.com/docs/en/skills
- GitHub Copilot skills guide: https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills
- GitHub Copilot CLI skills guide: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
