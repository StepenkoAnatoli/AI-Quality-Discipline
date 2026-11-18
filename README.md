# AI-Quality-Discipline

AI should produce quality work, not slop—and should be able to show what it actually did.

A small, testable collection of agent skills and instructions for improving code, pull requests, research, and writing quality without adding unnecessary process.

## Proposed components

- **code-discipline** — prevent incomplete implementations, unnecessary scope, and unsupported completion claims.
- **pr-hygiene** — keep pull requests focused, reviewable, and honest about checks and risks.
- **source-verification** — verify source identity, integrity, claim support, and qualifications.
- **writing-specificity** — catch vague or empty prose while preserving the author's meaning and voice.
- **Reply discipline** — a short always-on instruction for direct, appropriately sized responses. This is an instruction, not a skill.

The skills are intended to remain narrow and independently installable. Existing tools such as Break Test, Fetchproof, Holdshort, and humanizers should be reused where they already solve the problem rather than duplicated.

## Quality receipts

For substantial work, agents should be able to provide a compact **quality receipt** that distinguishes what was requested, what was delivered, and what can actually be evidenced.

The receipt format is:

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

A receipt is an audit trail, not a claim of correctness. It must never invent checks or evidence, treat an executed check as a passing check, or hide skipped verification. Use it for meaningful code changes, research, factual writing, and pull requests—not every trivial reply.

See [docs/QUALITY-RECEIPTS.md](docs/QUALITY-RECEIPTS.md) for field definitions, integrity rules, an example, and integration guidance.

## Evaluation principle

Every skill must be tested against the same tasks with and without the skill, under equivalent conditions. Keep it only when the measured improvement is meaningful and regressions are acceptable. If it does not improve the result, revise or remove it.

## Status

This repository is being established. The components above are a proposed architecture, not a claim that all skills or benchmarks are implemented.
