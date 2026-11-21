# Project Brain — AI-Quality-Discipline

> Durable project brief. Read before architectural or implementation changes. Update when a decision changes, a milestone is completed, or a new constraint is established. The README is the public entry point; this file preserves the working plan and rationale.

## 1. Mission

Build an open-source, portable, measurable quality framework that helps different AI agents produce better code, pull requests, research, and writing—and accurately communicate what they did and did not verify.

It should be easy to adopt, useful across AI environments, lightweight by default, and honest about its limitations.

**Core principle:** An AI agent must distinguish between what it intended to do, what it actually did, and what it can prove it did.

## 2. Product definition

This is not merely a prompt collection or a universal AI model wrapper. It is a small framework with complementary layers:

1. Shared quality standards.
2. Portable, task-specific Agent Skills.
3. Platform adapters and an installer.
4. Deterministic local validators.
5. An optional MCP interface.
6. Evaluations that measure actual outcomes.

Each layer should be independently useful. A user should be able to install one skill without adopting the entire framework.

## 3. Non-negotiable principles

- **Portable first:** use an established Agent Skills format as the canonical skill format where supported. Do not invent a competing format without a demonstrated need.
- **One source of truth:** canonical rules live once. Adapters reference, package, or minimally translate them rather than maintain divergent copies.
- **Local-first:** core functionality requires no account, API key, hosted service, or paid subscription.
- **Optional MCP:** MCP adds callable tools and structured access; it is not the source of behavioral authority and cannot guarantee compliance.
- **Small and scoped:** each skill has a clear trigger, bounded responsibility, and minimal instructions.
- **Evidence over assertion:** never claim a check ran, passed, or proved something unless the corresponding evidence exists.
- **No fake certainty:** distinguish implemented, tested, verified, partially verified, and unverified.
- **No unnecessary friction:** do not force receipts, audits, or elaborate workflows onto trivial tasks.
- **Respect user intent:** do not expand scope or silently change the requested outcome.
- **Measured value:** revise or remove components that fail to improve outcomes.
- **Transparent execution:** local validators must disclose external dependencies and side effects.
- **Security by default:** never execute untrusted repository scripts automatically during installation or validation.

## 4. Architecture

### 4.1 Core standards

Planned canonical documents:

- `core/PRINCIPLES.md` — canonical shared quality principles.
- `docs/QUALITY-RECEIPTS.md` — current canonical receipt specification. Do not create a competing copy.
- `core/REPLY-DISCIPLINE.md` — short always-on response guidance.
- `docs/AGENT-COMPATIBILITY.md` — dated record of the Agent Skills specification and official integration paths.

### 4.2 Canonical Agent Skills

Four narrow, independently installable skills:

**code-discipline**
- Trigger: creating, modifying, debugging, or refactoring code.
- Implement requested behavior; avoid unrelated refactors, unnecessary dependencies, empty handlers, fake implementations, placeholder success, narrative comments, and swallowed errors.
- Map the request to the actual diff.
- Run relevant checks where possible.
- Inspect final state and report exactly what was and was not verified.
- Coordinate with Break Test for adversarial regression testing; do not duplicate its full workflow.

**pr-hygiene**
- Trigger only when creating, preparing, reviewing, or updating a pull request.
- Read repository contribution guidance and templates.
- Inspect the complete branch diff, not just the latest commit.
- Keep unrelated changes out.
- Disclose actual tests, CI status, skipped checks, risks, and relevant policy requirements.
- Do not impose a universal one-open-PR rule; follow repository-specific policy.

**source-verification**
- Trigger when material factual claims depend on sources: citations, papers, links, statistics, quotations, named entities, or research findings.
- Check existence, identity, integrity, support, and qualification.
- Distinguish Verified, Partially verified, Unverified, and Contradicted.
- Do not silently upgrade uncertain claims to verified ones.
- Complement Fetchproof: use it for evidence collection and provenance where available, then validate whether the evidence supports the claim.

**writing-specificity**
- Trigger when drafting, editing, or reviewing prose.
- Identify vague claims, filler, generic conclusions, unsupported generalizations, and fabricated specificity.
- Support two modes: detect (report issues without rewriting) and edit (make minimal targeted changes).
- Preserve meaning, voice, and requested tone.
- Do not force every paragraph to contain a number, claim, or decision; every paragraph should have a clear purpose.

Each skill needs concise metadata and activation conditions, clear steps and boundaries, and only useful examples. Avoid duplicated global policy.

### 4.3 Reply discipline

Reply discipline is a short instruction, not a skill:

- Answer the actual question first.
- Match response length to task complexity; prefer concise answers.
- Do not repeat the request or recap established context unnecessarily.
- Avoid filler, generic closings, and unsolicited next steps.
- When the user asks for depth, provide depth.

Distribute it through supported project/user instruction mechanisms. Do not claim a universal global installation exists across all AI products.

### 4.4 Adapters and installer

Initial targets:
- Codex
- Claude Code
- GitHub Copilot
- Generic compatible Agent Skills consumers

Possible target layout (adapt after verifying current official documentation):

```text
skills/
  code-discipline/SKILL.md
  pr-hygiene/SKILL.md
  source-verification/SKILL.md
  writing-specificity/SKILL.md
core/
  PRINCIPLES.md
  REPLY-DISCIPLINE.md
adapters/
  codex/
  claude/
  copilot/
  generic/
scripts/
  install.py
  validate_receipt.py
  validate_skills.py
evaluations/
  shared-rubric.md
  code/
  pr/
  research/
  writing/
results/
  benchmark-results.md
docs/
  QUALITY-RECEIPTS.md
```

This is a target layout, not a claim that these files exist.

Installer requirements:
- Select one skill or all skills.
- Support user-level and project-level installation where supported.
- Confirm each agent's current official discovery path and format before implementing its adapter.
- Preview changes (dry-run).
- Never overwrite user files silently; detect conflicts and offer safe choices.
- Be idempotent; repeated runs must not create duplicates.
- Report every file created, updated, skipped, or untouched.
- Avoid elevated privileges.
- Do not run installed skills or arbitrary repository scripts during installation.
- Provide uninstall instructions that remove only files created by this installer.
- Test path handling, repeated installation, conflicts, and removal.
- Explain platform-specific limitations.

Fallbacks:
- Provide concise project-level instruction examples such as AGENTS.md and platform-specific equivalents for environments that cannot load Agent Skills.
- Link to canonical rules where possible.
- Document manual installation.

### 4.5 Deterministic validators

Start with objectively checkable local properties:
- Receipt structure and required headings.
- Empty or malformed receipt fields.
- Skill metadata/frontmatter and required files.
- Broken internal links and missing referenced files.
- Installer dry-run and conflict behavior.

A validator can check structure and consistency; it cannot establish factual truth unless given an explicit verification source or procedure. Never present a structural pass as proof of overall quality.

### 4.6 Optional MCP server

Build MCP only after the core standards, skills, and local validators are useful and stable.

Potential tools/resources:
- `get_quality_guidance` — return canonical instructions relevant to a task type and mode.
- `validate_quality_receipt` — validate supplied receipt structure and required fields.
- `review_change_scope` — compare a supplied request and change summary; disclose that this is not independent repository inspection.
- `verify_source_record` — validate a structured source record against supplied metadata or an explicitly configured retrieval capability.
- `run_quality_check` — run supported, safe, deterministic checks in a clearly defined workspace.
- `get_benchmark_results` — retrieve published evaluation results.

MCP constraints:
- Narrow schemas and explicit input/output contracts.
- Read-only tools by default.
- Filesystem or command execution must be opt-in, scoped, and documented.
- Never assume MCP can see local files, diffs, browser sessions, or repositories unless the client explicitly supplies or authorizes access.
- Return evidence and limitations with results.
- MCP responses must not imply that an agent complied with instructions.
- Do not create one tool per skill by default; add tools only where structured invocation beats reading a skill or running a local script.
- The framework must remain fully usable without MCP.

### 4.7 Quality modes

Planned optional modes:

- **Standard:** apply relevant principles with minimal process.
- **Strict:** use relevant skills, inspect final results, run meaningful checks where feasible, and create receipts for substantial work.
- **Audit:** independently challenge important claims, inspect available evidence, identify omissions and uncertainty, and report findings.

Modes change rigor, not the truth standard. No mode permits invented evidence or false completion claims.

## 5. Quality receipts

The canonical template is maintained in `docs/QUALITY-RECEIPTS.md`:

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

Use for substantial code changes, research, factual writing, and pull requests. Do not force it into every small response.

Integrity rules:
- Executed does not mean passed.
- Proposed does not mean executed.
- Generated tests do not mean passing tests.
- Evidence must support the exact claim.
- Partial delivery and skipped checks must be visible.
- Uncertainty must be explicit and bounded.
- A receipt is not a guarantee of correctness.

## 6. Relationship to existing projects

Avoid overlapping responsibilities:

- **Break Test:** adversarial reliability and regression probing. Code-discipline can invoke it where suitable, not recreate its workflow.
- **Fetchproof:** evidence collection, research contracts, provenance, and unknowns. Source-verification validates support and qualification rather than duplicating evidence storage.
- **Holdshort:** routing, execution limits, eligibility, bounded recovery, and stopping conditions. This framework supplies quality requirements; Holdshort may enforce execution boundaries.
- **Ideal-Umbrella:** context management, persistent learnings, handoffs, and skill/instruction overhead. It may carry reply discipline in an appropriate setup.

These are complementary projects, not mandatory dependencies. AI-Quality-Discipline must work independently.

## 7. Evaluation and benchmarks

Evaluate each skill with and without it under equivalent conditions.

Initial protocol:
- 10 representative tasks per skill.
- Each task with and without the skill.
- Same model, tools, permissions, context, and task wording.
- Repeat each condition three times where practical.
- Blind reviewers to condition when scoring.
- Record model/version, environment, date, skill revision, tool availability, and execution failures.
- Publish task definitions and rubric where licensing and privacy permit.

Shared starting rubric:
- Correctness: 30%
- Request compliance: 25%
- Evidence and verification: 20%
- Scope control and unnecessary content: 15%
- Readability: 10%

Adjust weights by domain. Writing must measure voice preservation and meaning retention; source verification must measure citation correctness and claim support.

Track regressions:
- Unnecessary refusal or hesitation.
- Omission of useful work.
- Excessive verbosity or process.
- False confidence.
- Latency and tool-call overhead.
- Compatibility and installation failures.

Decision:
- **Keep:** measurable benefit with acceptable regressions.
- **Revise:** promising benefit with a fixable weakness.
- **Remove:** no meaningful improvement, harmful regressions, or excessive maintenance cost.

Do not claim benchmark wins from anecdotes.

## 8. Roadmap and completion gates

### Phase 0 — Foundation
- [x] Establish repository and initial README.
- [x] Define quality receipt format.
- [x] Record architecture and project plan in this file.
- [x] Define canonical quality principles in `core/PRINCIPLES.md`.
- [x] Review the living Agent Skills specification and document official Codex, Claude Code, and Copilot paths in `docs/AGENT-COMPATIBILITY.md`.
- [x] Record the review date and the fact that the public specification has no conventional semantic version in the reviewed document.

### Phase 1 — Core skills
- [x] Implement code-discipline.
- [x] Implement writing-specificity.
- [x] Implement source-verification.
- [x] Implement pr-hygiene.
- [x] Review scope, triggers, length, overlap, and examples.

Exit gate: each skill has clear metadata, narrow scope, useful examples/tests, and no unsupported capability claims. The four initial SKILL.md files are drafted and structurally reviewed; live discovery/invocation tests and automated conformance validation remain for the validation phase.

### Phase 2 — Adoption
- [x] Build installer with dry-run and safe conflict handling.
- [x] Add Codex support.
- [x] Add Claude Code support.
- [x] Add GitHub Copilot support.
- [x] Add generic/manual fallback guidance.
- [x] Test installation, repeat installation, conflicts, and removal.

Exit gate: a new user can install one or all skills without silently losing existing files. The local installer and target-path adapters are implemented; 14 automated installer tests pass. Live discovery/invocation testing in Codex, Claude Code, and Copilot remains unverified and is not claimed.

### Phase 3 — Validation and evaluation
- [x] Add receipt validator (structural only; does not verify truth).
- [x] Add skill/package validator (structural checks; not full Agent Skills spec conformance).
- [x] Create representative pilot task suite and rubric (12 prompts, evaluator key, synthetic fixtures, fixture manifest, and run instructions). Full 10-task-per-skill suite remains future work.
- [ ] Run with/without comparisons (not started; fixture baseline checks and the CI workflow pass, latest on `3d522f5`, 2026-11-21; calibration remains).
- [ ] Phase 3.2: does code-discipline make Claude and Grok build better working software? Specification v3 in `evaluations/phase-3.2/`: model × skill design (skill effect within model only), revised NEW-01/02/03 prompts, fail-closed hidden scoring with inventories and a Docker sandbox, fail-closed analysis. Tested locally and in CI (scoring sandbox demonstrated on the CI runner, 2026-11-21). v3.1 (committed `f0c857c`, CI green): flagged runs count only after a review verdict, score files are checked for consistency, the smoke test is exactly four agent runs. v3.2 (committed `3d522f5`, CI green on runs 44892816556 and 44892821220; first recorded here as "local only, not committed", corrected 2026-11-21): a check against the real OpenCode 2.3.2 server on the operator PC (no prompt sent) found that `--version` parsing and built-in `skill://` skills would have stopped `install-opencode.sh`/`preflight.sh` on every host; both fixed, and provider-error sessions are now invalid instead of valid zeros. Smoke test CONDITIONALLY READY (needs a Linux VM and an Anthropic key; the "v3.2 committed with CI green" condition is met); Grok BLOCKED (needs the xAI configuration, an `XAI_API_KEY`, confirmed and the candidate `xai/grok-4.7#medium` from the 2.3.2 catalog confirmed); pilot NOT READY. CI runs no OpenCode, launcher or model: the launcher has never been executed on Linux, the four-run smoke test has not been executed, and there has been no Claude/Grok run yet. Next: the 2×2 smoke test in `PROMPT-SMOKE-TEST.md`.
- [ ] Publish results and limitations.

Exit gate: validators are tested, and benchmark claims are reproducible from published methodology.

### Phase 4 — MCP
- [ ] Confirm use cases not adequately served by skills and scripts.
- [ ] Specify narrow MCP tool contracts.
- [ ] Implement read-only tools first.
- [ ] Add security, permission, and failure tests.
- [ ] Test with multiple compatible MCP clients where feasible.
- [ ] Document that MCP access does not guarantee agent compliance.

Exit gate: MCP demonstrably improves structured access without becoming a required dependency.

### Phase 5 — Adoption and maintenance
- [ ] Publish installation walkthroughs and compatibility matrix.
- [ ] Add contribution and release guidance.
- [ ] Track upstream agent compatibility changes.
- [ ] Re-run evaluations after material skill changes.
- [ ] Remove obsolete adapters and ineffective rules.

## 9. Definition of done

Before reporting an implementation task complete:
1. Re-read the relevant request and this project brief.
2. Inspect existing files; avoid overwriting unrelated work.
3. Make the smallest coherent change.
4. Run relevant available checks.
5. Inspect the final diff or resulting files.
6. Record actual checks, outcomes, skipped checks, evidence, and uncertainty in a receipt when the task is substantial.
7. Update this brain when architecture, decisions, constraints, or milestone status materially change.
8. Do not mark a roadmap item complete merely because files were drafted; require the relevant checks and acceptance gate.

## 10. Decision log

- **2026-11-18 — Layered, portable framework:** Agent Skills are the primary skill format where compatible; add adapters and a local installer; defer MCP until the core and validators prove useful.
- **2026-11-18 — Local-first and open:** no mandatory hosted service, account, API key, or paid dependency.
- **2026-11-18 — Quality receipts:** retain the eight-field receipt in `docs/QUALITY-RECEIPTS.md`; receipts are for substantial work, not every response.
- **2026-11-18 — Quality modes:** plan Standard, Strict, and Audit as optional levels of rigor.
- **2026-11-18 — Evaluation before claims:** compare with/without conditions and publish methodology before claiming effectiveness.
- **2026-11-19 — Agent Skills baseline confirmed:** use the living agentskills.io specification as the canonical format; do not invent a spec version number. Record the review date and re-check before compatibility releases.
- **2026-11-19 — Initial integration paths documented:** Codex project/user skills use .agents/skills; Claude Code uses .claude/skills; Copilot supports .github/skills, .agents/skills, and .claude/skills with surface-specific differences. Keep one neutral canonical skills/ tree and copy/package it to target locations.
- **2026-11-19 — First four canonical skills drafted:** Added code-discipline, writing-specificity, source-verification, and pr-hygiene under skills/. Each has a narrow trigger, explicit exclusions, workflow, rules, examples, edge cases, and references. These are instruction drafts; discovery and behavior have not yet been tested in target agents.
- **2026-11-19 — Phase 3 benchmark foundation drafted:** Added an evaluation protocol, shared 100-point rubric, and a 12-task pilot (three tasks per skill) with a separate evaluator scoring key. The pilot explicitly tests ceiling effects, domain-specific regressions, and evidence integrity. These are task designs only: concrete fixtures, calibration, validators, and with/without runs are not yet complete; no effectiveness claim is made.
- **2026-11-19 — Local installer and initial adapters implemented:** Added a Python standard-library installer for project/personal scopes, one/all skill selection, dry-run, idempotent copying, conflict preservation, hash-based managed updates, target-scoped uninstall, and symlink/manifest path checks. Added Codex, Claude Code, Copilot, and generic adapter notes plus installation documentation. Fourteen local installer tests pass; live agent discovery/invocation remains unverified.
- **2026-11-21 — Phase 3.2 pilot design (pending user approval):** Evaluate code-discipline in OpenCode V2 (pinned `@opencode/cli` 2.3.2) with `opencode/nemotron-3.5-super-vl-free#xhigh` on three new synthetic tasks, 9 control and 9 treatment runs. Isolation by separate OS users per group and a fresh HOME/XDG/database per run, not by deleting the skill. Treatment receives the skill through a documented API skill attachment while the prompt text stays byte-identical to control; `@code-discipline` prompting is a fallback needing approval. Hidden tests and the NEW-task scoring key stay outside the public repository and enter the Codespace only after all runs. Results are exploratory only. Rejected: a shared workspace with the skill added and removed (leaks state); a prompt-text difference by default (confounds the skill with the cue). See `evaluations/phase-3.2/SPECIFICATION.md` §2. **Superseded 2026-11-21 (v3)** by the next entry.
- **2026-11-21 — Phase 3.2 v3:** Nemotron is out of scope; only Claude and Grok are evaluated, with the skill effect estimated within each model (never Claude-with-skill vs Grok-without). Recommended interface: OpenCode for both models (one agent loop, native skills, existing isolation), on a disposable Linux host. Never run agents on the operator PC, where global skills, `CLAUDE.md` and the evaluator pack are readable. Primary outcome: hidden-test pass fraction and fully-correct, from fail-closed evaluations only; process and report quality are secondary and never offset it. Hidden scoring runs candidate code in a no-network, read-only, non-root container; in-process tampering can only be flagged for review. Rejected: per-model native CLIs (interface confound across models); a custom agent loop (new, unvalidated agent); scoring as a second OS user (same uid as scoring logic, open network). See `evaluations/phase-3.2/SPECIFICATION.md`.

When a decision changes, add a dated entry explaining why. Do not silently rewrite history.

## 11. Open questions

- Which specific Codex, Claude Code, and Copilot versions/surfaces should be included in hands-on compatibility tests before declaring a release supported?
- What automated conformance checks should run against the living Agent Skills specification?
- Should the installer be Python-only, shell-based, or offer both?
- Should distribution use Git, release archives, a package registry, or multiple channels?
- What is the minimum useful MCP tool set after real workflows are tested?
- Which checks can be implemented safely without broad filesystem or shell permissions?
- How should versioning work across core standards, individual skills, adapters, and installer?

Resolve these with evidence and user value, not assumptions. Remove questions once decided.
