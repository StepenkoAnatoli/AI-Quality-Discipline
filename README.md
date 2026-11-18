# AI-Quality-Discipline

**A portable, measurable quality framework for AI agents.**

AI should produce quality work, not slop—and should be able to show what it actually did.

AI-Quality-Discipline is an open-source framework for practical quality standards across coding, pull requests, research, and writing. The goal is broad adoption: one shared set of principles, easy installation, integrations for multiple agent environments, and evidence that the framework improves results.

## How we are building it

The project uses a layered architecture:

| Layer | Responsibility |
|---|---|
| **Core standards** | Shared principles, quality receipts, and reply discipline. |
| **Agent Skills** | Portable, task-specific instructions for compatible agents. |
| **Adapters and installer** | Make canonical skills easy to discover and install in different environments. |
| **Deterministic validators** | Check machine-verifiable properties, such as receipt structure. |
| **MCP server (planned)** | Expose structured quality tools and resources to compatible clients. |
| **Evaluations** | Measure improvements and regressions across tasks, agents, and models. |

**Design rule: one source of truth, multiple integrations.** Avoid separate, drifting copies of the same quality rules for each AI platform.

## Quality skills

The planned skills are narrow and independently installable:

- **code-discipline** — implement requested behavior, control scope, inspect changes, and report verification honestly.
- **pr-hygiene** — keep pull requests focused and disclose tests, skipped checks, risks, and repository policies.
- **source-verification** — verify source identity, integrity, claim support, and qualifications.
- **writing-specificity** — identify vague or empty prose while preserving meaning and voice; support detection and minimal editing.

A short **reply-discipline** instruction will provide sensible defaults for ordinary responses. It is an always-on instruction, not a skill.

See [BRAIN.md](BRAIN.md) for the complete architecture, decisions, roadmap, and acceptance criteria.

## Quality receipts

For substantial work, agents should distinguish what was requested, what was delivered, and what can actually be evidenced.

```text
Requested:
Delivered:
Scope deviations:
Checks executed:
Checks passed:
Checks skipped:
Evidence:
Remaining uncertainty:
```

A receipt is an audit trail, not proof of correctness. It must never invent checks or evidence, treat an executed check as a passing check, or hide skipped verification. Use it for meaningful work—not every trivial reply.

See [docs/QUALITY-RECEIPTS.md](docs/QUALITY-RECEIPTS.md) for field definitions, integrity rules, and examples.

## Compatibility and adoption

The intended adoption paths are:

1. **Agent Skills** as the primary format wherever an agent supports the convention.
2. **Native adapters** for popular environments, initially Codex, Claude Code, and GitHub Copilot, subject to each product's current discovery and installation requirements.
3. **Project-level fallback instructions**, such as `AGENTS.md` or platform-specific equivalents, for environments that cannot load skills.
4. **Optional MCP integration** for clients that benefit from structured tools and validation. MCP supplements instructions; it does not force an agent to obey them.
5. **Manual installation** so users can adopt one skill without installing the entire framework.

The framework should remain useful without MCP, an account, API key, hosted service, or paid subscription. Local installation is the default.

## Quality Mode

Planned operating modes:

- **Standard** — apply relevant principles without unnecessary process.
- **Strict** — apply relevant skills, inspect results, verify meaningful changes, and produce receipts for substantial work.
- **Audit** — independently challenge claims, inspect evidence, identify gaps, and report uncertainty.

Modes must not over-process trivial tasks. A user's explicit request for depth or a particular workflow takes precedence where safe and feasible.

## Evaluation principle

Test every skill and major integration against the same representative tasks with and without the framework, under equivalent conditions. Measure quality improvements and regressions—not just instruction compliance.

Keep a component only when evidence shows meaningful improvement and acceptable regressions. Otherwise revise or remove it.

## Current status

The repository currently contains this README and the quality-receipt specification. The skills, installer, validators, adapters, MCP server, and benchmark suite are planned work; do not describe them as implemented until they exist and have been tested.

## Project roadmap

1. Define and implement shared core standards and four canonical Agent Skills.
2. Add a local installer and initial Codex, Claude Code, and Copilot integration paths.
3. Add deterministic receipt and package validators.
4. Build representative evaluations and publish baseline results.
5. Add an optional MCP server where structured tool access provides demonstrated value.
6. Expand compatibility based on tested demand and maintenance capacity.

## Repository guide

- [BRAIN.md](BRAIN.md) — project brain: architecture, principles, decisions, roadmap, and acceptance criteria.
- [Quality receipts](docs/QUALITY-RECEIPTS.md) — receipt format and integrity rules.

## Guiding principle

**An AI agent must distinguish between what it intended to do, what it actually did, and what it can prove it did.**
