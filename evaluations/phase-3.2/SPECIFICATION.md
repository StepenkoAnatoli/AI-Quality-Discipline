# Phase 3.2 — Final Specification v2

**Experiment:** does the `code-discipline` skill measurably change OpenCode coding-agent outcomes on three synthetic tasks?
**Status:** specification and implementation-preparation files only. Nothing in this directory has been executed against OpenCode, a model endpoint or a Codespace. See [READINESS](#21-readiness) and [VALIDATION-CHECKLIST.md](VALIDATION-CHECKLIST.md).
**Repository / branch:** `StepenkoAnatoli/AI-Quality-Discipline`, `phase-3/benchmark-foundation`, prepared on top of commit `8cfecb9`.
**Date of documentation checks:** 2026-11-21.

This document is normative. Where it and a script disagree, the disagreement is a defect: fix one of them and record the change in [CHANGE-REPORT.md](CHANGE-REPORT.md).

## Contents

1. [Document history](#1-document-history)
2. [Decisions](#2-decisions)
3. [Verified external facts](#3-verified-external-facts)
4. [Architecture](#4-architecture)
5. [Control/treatment isolation](#5-controltreatment-isolation)
6. [OpenCode configuration, model and authentication](#6-opencode-configuration-model-and-authentication)
7. [Skill activation](#7-skill-activation)
8. [Tasks and test oracles](#8-tasks-and-test-oracles)
9. [Immutable baseline tests](#9-immutable-baseline-tests)
10. [Workspace construction, manifests and integrity](#10-workspace-construction-manifests-and-integrity)
11. [Per-run procedure](#11-per-run-procedure)
12. [Run validity, exclusions and reruns](#12-run-validity-exclusions-and-reruns)
13. [Evidence and blind evaluation](#13-evidence-and-blind-evaluation)
14. [Statistical interpretation](#14-statistical-interpretation)
15. [GitHub Codespaces resources and preflight](#15-github-codespaces-resources-and-preflight)
16. [Privacy and repository protection](#16-privacy-and-repository-protection)
17. [Execution runbook](#17-execution-runbook)
18. [Runtime gates](#18-runtime-gates)
19. [Stop rules](#19-stop-rules)
20. [Known limitations](#20-known-limitations)
21. [Readiness](#21-readiness)

---

## 1. Document history

| Version | Location | Status |
|---|---|---|
| Phase 3.2 specification, revised specification, final specification, "final specification v2" and v2 change report (2026-11-19) | Loose files in the operator's local `E:\Claude\` folder; **never committed to this repository** | Superseded by this document. The audited defects are listed in [CHANGE-REPORT.md](CHANGE-REPORT.md) §2. |
| **Final Specification v2 (this document)** | `evaluations/phase-3.2/` on `phase-3/benchmark-foundation` | Current. Not committed: committing requires separate authorisation. |

The earlier drafts are not reproduced here. The repository previously contained no Phase 3.2 material; the existing Phase 3 pilot (`evaluations/pilot/`, `evaluations/fixtures/`) is unrelated to NEW-01/02/03 and is not reused.

## 2. Decisions

### 2.1 Preserved decisions (unchanged)

| # | Decision | Where implemented |
|---|---|---|
| P1 | Agent: OpenCode | §6 |
| P2 | Preferred model: Nemotron 3.5 Super VL Free through the OpenCode gateway | §6.3 (`opencode/nemotron-3.5-super-vl-free`) |
| P3 | Reasoning effort `xhigh` is mandatory; no silent change of model or variant | §6.4, §18, §19 |
| P4 | Three new synthetic tasks: NEW-01 webhook idempotency, NEW-02 concurrent inventory reservations, NEW-03 CSV import compatibility | §8, `tasks/` |
| P5 | Three repetitions per task per group; 9 control + 9 treatment = 18 runs | `harness/schedule.py` |
| P6 | Two isolated environments (control and treatment) | §5 |
| P7 | Allowlist-based file construction; no repository clone and no `.git` in agent workspaces | §10, `allowlist.json` |
| P8 | Blind scoring; evaluator material outside agent-accessible locations | §13 |
| P9 | Outbound internet accepted; tasks contain synthetic data only | §16 |
| P10 | The public pilot scoring key (`evaluations/pilot/scoring-key.md`) is a documented limitation; old public tasks are not reused | §16, §20 |

### 2.2 New design decisions in this version (need user approval)

None of these changes a preserved decision; each fills a gap the previous drafts left open. They are listed so that approval is explicit.

| # | Decision | Why | Alternative rejected |
|---|---|---|---|
| N1 | **Activation by API skill attachment with byte-identical prompt text** (`session.prompt` with `skills: [{"id": "code-discipline"}]`) — default mode `api-attachment` | Removes the prompt-text difference that an `@code-discipline` mention creates (§7) | `@code-discipline` in the prompt via `opencode run` is implemented as fallback mode `cli-mention` and needs separate approval |
| N2 | Each group runs as its own unprivileged Linux user (`aqd-a`, `aqd-b`, assignment random and sealed), and **every run gets a fresh HOME/XDG/database** | Permission rules cannot isolate the agent's shell; OS users can | Same user with separate directories (agent shell can read the other group's files) |
| N3 | Identical tool restrictions in both groups: `webfetch`, `websearch`, `question`, `subagent` denied; reads/edits outside the project denied | Self-contained tasks; prevents non-interactive stalls; keeps the whole transcript in one session; reduces casual web discovery of the public skill | Leaving them on (internet is still reachable from the shell; see §16) |
| N4 | OpenCode **V2** CLI pinned: npm `@opencode/cli@2.3.2` in `/opt/aqd-opencode` | Current documentation describes V2; the operator PC has V1 `opencode-ai` 1.18.35, whose flags differ | Unpinned or V1 |
| N5 | Hidden tests and the private scoring key enter the Codespace only after all 18 agent runs, and run as a third user `aqd-eval` | They cannot leak to an agent that no longer runs | Keeping them in the Codespace during runs |
| N6 | 45-minute agent time limit per run; a timeout is a valid, scored outcome | Bounded cost; no selective reruns | Unlimited time |
| N7 | At most one rerun per slot, only for pre-registered infrastructure causes (§12.3), decided by a human | Prevents result shopping | Automatic retries |
| N8 | Scoring uses only the task's mutable file and `tests/additive/` from the agent result | The contract forbids other changes; scoring what the contract allows is deterministic | Scoring arbitrary extra modules |
| N9 | A never-scored SMOKE task verifies the runtime gates before run 1 | Some behaviour cannot be verified without execution (§18) | Discovering harness defects inside scored runs |
| N10 | 2-core Codespace (`basicLinux32gb`), default image, idle timeout 60 minutes | Fits the free allowance with margin (§15) | Larger machines |
| N11 | **Publication timing.** This directory (specification, task contracts, harness, but never hidden tests) becomes public when pushed. Because agents have internet access, pushing *before* the runs lets an agent find the specification. Recommended: accept this, since the contract is given to the agent anyway and hidden inputs stay private. Alternative: keep it unpushed, create the Codespace from the branch without these files, and copy `evaluations/phase-3.2/` in with `gh codespace cp` | Makes the exposure an explicit choice | Silent publication |

## 3. Verified external facts

Checked on 2026-11-21. "Docs" = official documentation fetched on that date. "Catalog" = OpenCode's own model catalog as exposed to an authenticated OpenCode instance on the operator PC. Nothing below was verified by running OpenCode.

| # | Fact | Basis |
|---|---|---|
| F1 | Project config: `opencode.json(c)` or `.opencode/opencode.json(c)` in the working directory **or any ancestor up to the filesystem root**; global `~/.config/opencode/opencode.json(c)`; system directory `/etc/opencode` (Linux) applies to every user, with highest precedence. Schema URL `https://opencode.ai/config.json` | Docs: [config](https://opencode.ai/docs/config/) |
| F2 | V2 permission rules are a `permissions` array of `{action, resource, effect}`; last match wins; built-in actions include `skill`, `question`, `subagent`, `webfetch`, `websearch`, `external_directory`, `read`, `edit`, `shell`. `shell` "runs with the host user's filesystem, process, and network authority" | Docs: [permissions](https://opencode.ai/docs/permissions/); `permission` (singular) is the deprecated V1 key in the schema |
| F3 | Skill discovery: global `~/.config/opencode/skills`, `~/.claude/skills`, `~/.agents/skills`; project `.opencode/skills`, `.claude/skills`, `.agents/skills` from the current directory up to the project root; built-in skills; `skills` config entries; system directory `skills/` | Docs: [skills](https://opencode.ai/docs/skills/), [config](https://opencode.ai/docs/config/) |
| F4 | A skill is loaded by the model through the `skill` tool, or by the user with an `@skill-id` mention. The skill body is added without frontmatter | Docs: [skills](https://opencode.ai/docs/skills/) |
| F5 | `OPENCODE_DISABLE_CLAUDE_CODE=1` skips every `CLAUDE.md` and `.claude` skills | Docs: [instructions](https://opencode.ai/docs/instructions/) |
| F6 | By default every client uses **one shared background server per user account**; `opencode serve` runs a foreground server; `OPENCODE_PASSWORD` sets its password; other HTTP clients use Basic auth with user `opencode` | Docs: [CLI](https://opencode.ai/docs/cli/), [web](https://opencode.ai/docs/cli/web/) |
| F7 | CLI: `opencode models`, `opencode run` (`--model`, `--agent`, `--format json`, `--auto`, `--standalone`), `opencode session export <id>`, `opencode debug paths`, `opencode serve --hostname --port` | Docs: [CLI commands](https://opencode.ai/docs/cli/commands/) |
| F8 | Model selector `provider/model#variant`; the root `model` config **does not retain a variant**; unknown variants produce a model-resolution error; variant names come from catalog metadata | Docs: [models](https://opencode.ai/docs/models/) |
| F9 | Model ID `nemotron-3.5-super-vl-free`, selected as `opencode/nemotron-3.5-super-vl-free`; OpenAI-compatible chat endpoint; price "Free"; "available for a limited time"; NVIDIA trial terms: "do not submit personal or confidential data. Your use is logged" | Docs: [Console models](https://opencode.ai/docs/console/models/) |
| F10 | "Signed out, the `opencode` provider is absent until you connect an OpenCode Console account or set `OPENCODE_API_KEY`, which restores its paid models." The sentence appears in the free-models section of the Models page; whether free models are available to a signed-out, credential-free install is **not stated unambiguously** | Docs: [models](https://opencode.ai/docs/models/) |
| F11 | Catalog variants for `opencode/nemotron-3.5-super-vl-free`: `none, minimal, low, medium, high, xhigh` | Catalog (authenticated operator instance, 2026-11-21). Not proof that a signed-out install sees the same list, nor that the endpoint honours `xhigh` |
| F12 | API (OpenAPI reference): `POST /api/session` takes `model: {providerID, id, variant}` and `location: {directory}`; `POST /api/session/{id}/prompt` takes `text` and `skills: [{id, mention?}]` and "durably admit[s] one session input and schedule[s] agent-loop execution"; `GET /api/skill`, `/api/model`, `/api/provider`, `/api/config` accept `location[directory]`; `GET /api/experimental/session/{id}/export` returns `{info, messages}`; message types include `user` (with `skills[]`), `skill` (`skill`, `text`), `assistant` (`model{providerID,id,variant}`, `content[]`, `tokens{input,output,reasoning}`) | Docs: [API](https://opencode.ai/docs/api/), [openapi.json](https://opencode.ai/docs/openapi.json) |
| F13 | npm packages: V2 `@opencode/cli` latest `2.3.2`; V1 `opencode-ai` latest `1.19.6`. Operator PC has V1 `1.18.35` (flags `--variant`, `--dir`, no `--standalone`) | `npm view`, `opencode run --help` (help text only) |
| F14 | Codespaces: personal Free plan includes 120 core-hours/month compute (2-core machine consumes 2 core-hours per hour) and 15 GB-month storage; without a payment method, usage is **blocked** at the quota; with one, it is **billed**. Storage accrues hourly; deleting a codespace stops further accrual but **does not reduce** the month's accrued usage. Default idle timeout 30 minutes (5–240 configurable); **maximum lifetime 12 hours**; default retention 30 days | Docs: [billing](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces), [included usage](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-included-usage), [timeout](https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces) |
| F15 | `gh codespace create` supports `-R`, `-b`, `-m`, `--idle-timeout`, `--retention-period`; `gh codespace delete -c <name>` (`-f` skips the unsaved-changes prompt; there is no `--confirm` flag) | `gh` 2.100.0 help text |

## 4. Architecture

```text
GitHub Codespace (Linux, default image, 2 cores)            evaluator PC (outside)
┌────────────────────────────────────────────────────────┐  ┌───────────────────────┐
│ operator user "codespace" (sudo)                       │  │ private evaluator pack│
│  /workspaces/AI-Quality-Discipline   checkout  0700*   │  │  hidden tests         │
│  /workspaces/.aqd-operator           0700              │  │  reference solutions  │
│     pristine/  allowlisted copies + JSON manifests     │  │  mutants, scoring key │
│     sealed/    schedule (group map), gates, billing    │  └──────────┬────────────┘
│     captures/  per-run evidence (outside agent reach)  │     uploaded only after
│     evaluator/ hidden tests (only after all runs)      │◄────all 18 runs (§13.4)
│  /opt/aqd-opencode  pinned OpenCode V2, root-owned     │
│                                                        │
│  /aqd (root 0755)                                      │
│   ├─ env-a/ (aqd-a 0700) ─ runs/ (root 0711)           │  scorer (blind)
│   │     └─ r-<id>/ (root 0711)                         │  receives packets only:
│   │          ├─ home/    per-run HOME/XDG/DB           │  no group, no skill,
│   │          ├─ project/ allowlisted task files        │  no tokens, no paths
│   │          └─ tmp/     per-run TMPDIR                │
│   └─ env-b/ (aqd-b 0700)  same layout                  │
│  Model traffic: opencode serve (as aqd-a|aqd-b)        │
│     ──HTTPS──► opencode.ai gateway ─► NVIDIA endpoint  │
└────────────────────────────────────────────────────────┘
* plus a deny ACL for the agent users on /workspaces where setfacl exists
```

**Access matrix** (enforced by the kernel unless noted):

| Path | operator | agent user of this run | other agent user | aqd-eval |
|---|---|---|---|---|
| `/workspaces/.aqd-operator/**` | rw | none | none | none |
| repository checkout | rw | none | none | none |
| operator `$HOME` | rw | none (0700) | none | none |
| `/aqd/env-X/runs/r-<id>/project` | via sudo | per §10.3 | none (`env-*` 0700) | none |
| `/aqd/env-X/runs/r-<id>/home` | via sudo | rw except root-owned config/skill | none | none |
| `/opt/aqd-opencode` | r | r, x | r, x | r, x |
| Internet | yes | yes (not restricted; §16) | — | yes |

Runs execute **strictly sequentially**. Before a run starts, no process of either agent user may exist. After it ends, all of that user's processes are killed and its run root is deleted, so a later run of the same group cannot read an earlier attempt.

## 5. Control/treatment isolation

### 5.1 Layers

1. **Separate OS users per group.** `aqd-a` and `aqd-b` own `/aqd/env-a` and `/aqd/env-b` (mode 0700). Which one is control is random (`schedule.py`) and recorded only in `sealed/schedule.json`. The agent's shell cannot read the other group's tree, the operator store, the checkout or the operator's home. Neither user has a password, sudo or supplementary groups (checked by `preflight.sh`).
2. **Fresh per-run state.** Every run gets its own HOME and XDG directories and its own OpenCode database. No session history, saved approval, cache or configuration survives from one run to the next. The environment is built from scratch with `env -i`; the full list is in §5.2.
3. **Private foreground server per run.** `opencode serve` runs as the agent user with that run's environment, on a random localhost port with a random password. The shared background service (F6) is never used. Server discovery files would live in the run's own HOME anyway.
4. **The skill exists only in treatment HOMEs.** It is installed as `home/.config/opencode/skills/code-discipline/SKILL.md`, root-owned and 0444. Control HOMEs never contain it, and no project directory ever contains it, so project trees are byte-identical across groups.
5. **Identical configuration.** Project `opencode.jsonc` and global `opencode.jsonc` are the same bytes in both groups (§6.1). The rules `skill * deny` followed by `skill code-discipline allow` deny every other skill (including built-ins) in both groups, so the only difference is whether `code-discipline` exists.
6. **No inherited discovery sources.** Before each run, `assert_clean_ancestors` fails if any ancestor of the project contains `AGENTS.md`, `CLAUDE.md`, `opencode.json(c)`, `.opencode`, `.claude` or `.agents`, or if `/etc/opencode` exists. `OPENCODE_DISABLE_CLAUDE_CODE=1` is set for both groups.

Isolation never relies on deleting the skill after a run: control HOMEs are created without it.

### 5.2 Environment of every agent process

Built by `make_agent_env` in `harness/lib.sh`; nothing else is inherited (no `GITHUB_TOKEN`, no Codespaces secrets, no operator PATH).

| Variable | Value |
|---|---|
| `HOME` | `/aqd/<env>/runs/<run_id>/home` |
| `XDG_CONFIG_HOME` / `XDG_DATA_HOME` / `XDG_STATE_HOME` / `XDG_CACHE_HOME` | `$HOME/.config`, `$HOME/.local/share`, `$HOME/.local/state`, `$HOME/.cache` |
| `OPENCODE_DB` | `$HOME/.local/share/opencode/opencode.db` |
| `TMPDIR` | `/aqd/<env>/runs/<run_id>/tmp` |
| `PATH` | `/opt/aqd-opencode/bin`, node's directory, python3's directory, `/usr/local/bin:/usr/bin:/bin` |
| `SHELL`, `LANG`, `LC_ALL`, `TERM` | `/bin/bash`, `C.UTF-8`, `C.UTF-8`, `dumb` |
| `PYTHONDONTWRITEBYTECODE` | `1` |
| `OPENCODE_DISABLE_CLAUDE_CODE` | `1` |
| `OPENCODE_PASSWORD` | random per run (the agent's shell can read it; it only grants access to this run's own server) |

### 5.3 Proof that control cannot discover the skill

All of these must pass before the prompt is sent; any failure stops the run.

| Check | Mechanism | Script |
|---|---|---|
| No skill file in any discovery path above or inside the project | `assert_clean_ancestors`; pre-run manifest verification (exact file set) | `lib.sh`, `manifest.py verify --phase pre` |
| HOME contains only the expected configuration files | `find home/.config` listing compared with the expected listing before and after the run | `launch-run.sh`, `run_status.py` |
| OpenCode resolves all paths inside the run | `opencode debug paths` output: every path under the run root | `launch-run.sh` |
| **The running server does not register `code-discipline`** | `GET /api/skill?location[directory]=<project>`: control must list no skill with that ID and no skill whose content contains the skill's sentinel lines; every skill path must be inside the run or `/opt/aqd-opencode` | `api_checks.py` (exit 13 = isolation failure, benchmark stops) |
| Configuration loaded only from inside the run | `GET /api/config`: every existing filesystem path reported must be inside the run or the install prefix | `api_checks.py` |
| Agent user cannot read operator material or the other environment | `sudo -u <agent> test -r/-x` must fail | `assert_unreadable_by` |
| After the run: no skill text reached the control session | `export_checks.py`: any sentinel line, any `skill` tool call or attachment for `code-discipline` → contamination → run invalid | `export_checks.py` |

## 6. OpenCode configuration, model and authentication

### 6.1 Configuration files

`config/opencode.jsonc` is copied into every project as `opencode.jsonc` (the documented project location), root-owned and read-only. It contains only `$schema` and `permissions`. It sets no model, because the root `model` cannot carry a variant (F8). No provider block is configured: the built-in `opencode` provider and its catalog are used as shipped, and no provider fields are invented.

`config/global-opencode.jsonc` becomes `$XDG_CONFIG_HOME/opencode/opencode.jsonc` in every run HOME and sets only `"update": "disable"`, which is honoured only globally.

There are no `ask` rules, so a non-interactive run cannot stall on an approval. A test enforces this. The driver also interrupts and invalidates a run if a permission request is ever pending.

### 6.2 Model selection

The model is selected per session, never through the root config:

- **api-attachment mode:** `POST /api/session` with `model: {"providerID": "opencode", "id": "nemotron-3.5-super-vl-free", "variant": "xhigh"}`, `agent: "build"`, `location: {"directory": <project>}`.
- **cli-mention mode:** `opencode run --server <url> --model opencode/nemotron-3.5-super-vl-free#xhigh --agent build --format json --auto`.

### 6.3 Authentication status — BLOCKER B1

The `opencode` gateway may be unavailable to a signed-out install (F10), and the documentation does not settle whether free models are exempt. The benchmark uses fresh, credential-free HOMEs. **No account, API key or credential may be created or configured.**

`preflight.sh` resolves this without a model request. It starts a credential-free server under a fresh HOME and asks `GET /api/provider` and `GET /api/model`.

- If `opencode` is absent (exit 10), the model is absent (11) or `xhigh` is not offered (12), the benchmark is **BLOCKED** and a user decision is required.
- Supplying `OPENCODE_API_KEY` would also expose that key to the agent's shell (§5.2), so any such decision must include a key-exposure mitigation.

### 6.4 `xhigh` verification — gates

| Gate | Evidence | Verifiable how | Status now |
|---|---|---|---|
| X1 variant in catalog | `xhigh` in `GET /api/model` variants for the model | Preflight, no model request | Catalog shows it (F11) for an authenticated instance; **signed-out: requires runtime verification** |
| X2 accepted by OpenCode | every assistant message in the export has `model.variant == "xhigh"` | `export_checks.py` per run | Requires runtime verification (R3) |
| X3 transmitted to the endpoint | the outgoing request carries the variant's reasoning setting | Smoke run with `OPENCODE_LOG_LEVEL=DEBUG` on the server; inspect `serve.log` and OpenCode's log for the request options | **Requires runtime verification (R4); may be unobservable from client logs** |
| X4 honoured by the endpoint | no error; `tokens.reasoning > 0` | `export_checks.py` (`reasoning_tokens_observed`) | Requires runtime verification. Reasoning tokens show reasoning, **not** that the effort level was `xhigh` |

If X1 or X2 fails, the benchmark stops (no fallback to `high` or any other variant). If X3 cannot be observed, the result is reported as "variant accepted by OpenCode; transmission unverified", and the user decides whether that is sufficient before run 1. X4 cannot prove the effort level from the client side; this is a stated limitation (§20).

## 7. Skill activation

### 7.1 Options considered

| Option | Prompt identical? | Activation guaranteed? | Problem |
|---|---|---|---|
| Implicit discovery only (skill advertised; model decides) | yes | no | Activation is itself a model decision; a null result could mean "never loaded" |
| `@code-discipline` mention in treatment prompt (documented, F4) | **no** | yes, if the mention resolves | The words in the prompt are a cue in themselves, so treatment gets extra instruction text besides the skill content |
| Same `@code-discipline` text in both groups | yes | treatment only | Control sees an instruction to use a skill it cannot load; invites searching the public internet for it (contamination) |
| **API skill attachment, `mention` omitted (chosen)** | **yes** | yes (mechanical, not a model decision) | Uses the HTTP API rather than `opencode run`; must be verified once at runtime (R2) |
| Experimental `POST /api/experimental/session/{id}/skill` | yes | yes | Experimental endpoint; no advantage over the stable attachment |

### 7.2 Controlled approach (mode `api-attachment`)

- Both groups receive **exactly the bytes of the task's `TASK.md`** as the prompt text. A test verifies that the request bodies are identical apart from the attachment.
- Treatment adds `skills: [{"id": "code-discipline"}]` to `session.prompt`. OpenCode then adds the skill body to the conversation, the same mechanism an `@` mention triggers, without any words in the prompt text.
- The skill is also advertised to the treatment model at every step, because it is installed and allowed. That is inherent to "having the skill" and is part of the treatment.
- The comparison therefore estimates the effect of **having the code-discipline content loaded and available**, not the effect of telling the model to be disciplined.

Mode `cli-mention` is implemented for the case where R2 fails. It prefixes the treatment prompt with `@code-discipline`. It may be used only with explicit user approval, for all 18 runs, and its prompt difference must be reported as a confound. The launcher refuses to mix modes across runs.

### 7.3 Activation verification (independent of outcome scoring)

`export_checks.py` reads the exported session (F12). Treatment activation is **CONFIRMED** only if the canonical skill text is demonstrably in the session: a `skill` message or a `user.skills[]` attachment for `code-discipline` whose text contains all three sentinel lines of `SKILL.md`, or a completed `skill` tool call whose output contains them. Anything else is NOT_CONFIRMED, and the run is invalid as an infrastructure failure (§12).

This verdict is written to the operator-only capture. The scorer never sees it, the skill text, the skill hash or token counts (which would differ by the skill's size).

## 8. Tasks and test oracles

Each task is a small Python package (standard library only, Python ≥ 3.10) with one mutable file. The agent-visible contract is the task's `TASK.md`, which is the prompt text and is normative. The summaries below do not replace it.

All expected behaviour was fixed before any agent run. The reference solutions, hidden tests and mutants live in the private evaluator pack, **outside this repository** (§13.4).

### 8.1 NEW-01 — Duplicate webhook processing (idempotency)

- **Architecture.** `webhooks/app.py` is the HTTP entry point: each call opens its own connection, and several worker processes run it concurrently. `handler.py` (mutable) holds the business logic. `store.py` provides SQLite in WAL mode, autocommit connections and a 5 s busy timeout. The schema has `orders`, `ledger`, `outbox`, and `processed_events(event_id PRIMARY KEY)`. `outbox.py` is a separate dispatcher process.
- **Existing behaviour (planted defects).** Every delivery writes another ledger row and outbox row. The three writes are separate autocommit statements, so a failure can leave partial state. `processed_events` is unused.
- **Required behaviour.** The key is `event_id`, and validation is unchanged. The first delivery commits the status update, ledger row, outbox row and `processed_events` row atomically. Redelivery returns `duplicate` and writes nothing. Any failure leaves nothing behind and propagates (HTTP 500), and a later retry succeeds. Concurrent deliveries from separate processes produce exactly one `processed` and no 500s. The connection is left without an open transaction. A process-local lock gives no credit.
- **Side-effect boundary.** The handler writes an outbox row in the same transaction (transactional outbox). Email delivery by `outbox.py` is at-least-once, with downstream deduplication on `dedupe_key = event_id`. **Exactly-once email is neither required nor possible here.** Claiming it is an overclaim (scored, §13.5).
- **Storage, transaction and concurrency assumptions.** Processes are on one host and share one SQLite file. A correct design takes the write lock before reading (`BEGIN IMMEDIATE`) or lets the `processed_events` primary key decide inside the transaction.
- **Hidden oracle.** 13 checks covering: sequential and payload-variant duplicates; 8 threads and 8 processes delivering concurrently; failure injection at each of four write points via SQLite triggers (independent of agent code structure); 500-then-retry; connection state; independent events; validation; one email after duplicates. Concurrency checks use a connection proxy that sleeps after every `SELECT`, so check-then-act races reproduce deterministically.

### 8.2 NEW-02 — Concurrent inventory reservations

- **Architecture.** `inventory/worker.py` is the entry point (one connection per request; several processes on one host). `service.py` (mutable) holds `reserve()`. `db.py` provides SQLite in WAL mode, autocommit and a 5 s busy timeout. The tables are `stock(sku, available)`, `reservations`, and `reservation_lines` with primary key `(reservation_id, sku)`.
- **Existing behaviour (planted defects).** A process-local `threading.Lock` guards a read-then-write with an absolute `UPDATE`, which is a lost update across processes. The reservation row is inserted before validation. There is no transaction, so a multi-line failure leaves partial state. Quantities are not validated (a negative quantity increases stock). Repeated SKUs violate the primary key after partial writes.
- **Required behaviour.**
  - Validate before writing (`InvalidRequest`, `UnknownSku`), with a defined check order.
  - Combine repeated SKUs, and make the reservation all-or-nothing.
  - Raise `InsufficientStock(sku, requested, available)` with the value read inside the deciding transaction.
  - Never oversell: with up to 8 concurrent processes, every call ends in success or `InsufficientStock`, never `database is locked`.
  - Leave the connection without an open transaction, and return a 32-hex ID.
  - The report must state the guarantee's scope (one host). **A process-local lock gets no credit**; the hidden checks fail it.
- **Hidden oracle.** 12 checks: last unit and partial exhaustion across 8 processes; 8 threads; multi-line rollback; unknown SKU in a later line; ten invalid-request forms; SKU combination; check order; trigger-injected failure; connection state; ID format; consistency. The slow-`SELECT` proxy is used in the concurrency checks.

### 8.3 NEW-03 — CSV import compatibility

- **Architecture.** `importer/csv_import.py` (mutable) implements `import_contacts(data: bytes) -> ImportResult`. `models.py` defines `Contact`, `RowError`, `ImportResult`, `CsvFormatError(code, message, line)` and all error codes. Two customer sample files are provided, one with a space in its name.
- **Existing behaviour (planted defects).** Naive `split(",")` and `splitlines()`; no BOM handling; fixed column order; crashes on short rows; quoted fields broken.
- **Required behaviour.** Fully determined by `TASK.md` clauses 1–18:
  - UTF-8 input with an optional BOM; invalid bytes raise `encoding`.
  - `\n`, `\r\n` and `\r` line endings.
  - Empty or whitespace-only input raises `empty_file`.
  - The delimiter is chosen from the header line alone (`,` or `;`, quote-aware count; a tie raises `ambiguous_delimiter`).
  - RFC 4180 quoting exactly as Python `csv` with `strict=True`; malformed quoting raises `malformed_csv` with the record's start line.
  - 1-based physical line numbering, where embedded newlines shift later records.
  - Header rules: trimmed and case-insensitive; `email` and `name` required, `phone` optional; any column order; duplicates raise `duplicate_column`; other columns are listed in `ignored_columns`.
  - Values are trimmed, and embedded newlines are normalised to `\n`.
  - Blank records are skipped.
  - Per-row checks run in a fixed order: `missing_fields`/`extra_fields` (trailing empty extras tolerated), `invalid_email` (exact rule), `missing_name`, `duplicate_email` (case-insensitive; first kept).
  - Partial import, results in input order, and a fixed precedence among file-level errors.
- **Hidden oracle.** 16 checks, one or more per clause group, including both sample files. H06 (line endings) and H16 (a literal quote inside an unquoted field) are regression guards that the original code already passes.

### 8.4 Oracle validation (done locally, see checklist)

`check_oracles.py` (private pack) proved on 2026-11-21, on Windows with Python 3.14.7, three consecutive passes:

- Every fixture passes its baseline tests and fails the hidden checks that target its planted defects.
- Every reference solution passes all 41 hidden checks and all baseline tests.
- Nine plausible wrong solutions ("mutants") are each caught. These are: autocommit check-then-insert, deferred transaction with read-then-write, swallowed failures, deferred check-then-act inventory, per-line atomic without a transaction, bool accepted as a quantity, `csv.Sniffer` delimiter detection, record-index line numbers, and no BOM stripping.

The Linux run inside the Codespace is runtime gate R7.

### 8.5 Scoring criteria per task

The shared rubric (`evaluations/shared-rubric.md`) applies with these pre-registered rules:

| Dimension | Rule |
|---|---|
| Correctness (30 %) | Derived from the hidden-check pass fraction: 100 % → 4; ≥ 85 % → 3; ≥ 60 % → 2; ≥ 30 % → 1; else 0. If the pristine baseline tests fail against the agent's code, the score is capped at 2 |
| Request compliance (25 %) | Scorer: contract clauses followed, only permitted files changed (workspace findings in the packet), signature preserved |
| Evidence and verification (20 %) | Scorer: every verification claim in the final report must match a command and its output in the transcript. The private key lists task-specific overclaims (e.g. "exactly-once email", "safe across hosts", "all tests pass" when they did not) |
| Scope and economy (15 %) | Scorer: unexpected files, unrelated edits, unnecessary abstractions |
| Clarity (10 %) | Scorer: report usable and accurate |

Critical failures cap the total at 49, per the shared rubric: fabricated test execution, a claim that contradicts the hidden results on a contract clause the agent says it verified, or an unauthorised destructive action.

## 9. Immutable baseline tests

- `tests/baseline/` is a root-owned 0755 directory containing root-owned 0444 files. The agent user cannot modify, delete, rename, `chmod` or add files there (kernel-enforced; the agent has no sudo).
- The permission rule `edit tests/baseline/* deny` additionally stops OpenCode's edit tools before the kernel would.
- The agent may add tests only in `tests/additive/`, which the agent user owns.
- Pre-run and post-run SHA-256 verification against the JSON manifest. Any change to an immutable file means the protection failed: the run is invalidated as an infrastructure failure, and attempts visible in the transcript are scored as constraint violations.
- Scoring never relies on tests the agent can modify. The pristine baseline tests and the hidden tests are run against a scoring tree rebuilt from the pristine project plus only the agent's mutable file and additive tests (N8). Agent-written tests are reported but never scored as correctness evidence.

## 10. Workspace construction, manifests and integrity

### 10.1 Allowlist

`allowlist.json` is the single, exhaustive list of files that may enter an agent project, with a category per file (`immutable`, `mutable`, `additive`), plus `additive_dirs`, `protected_dirs` and `tolerated_artifacts`. `manifest.py check-sources` fails if a task source directory contains any file not listed, or lacks one that is listed (tested). Nothing else from the repository is ever copied: no `.git`, no other evaluations, no skills except the single treatment `SKILL.md` into the HOME.

### 10.2 Manifest

`manifest.py build` writes a **JSON** manifest (`kind: aqd-phase-3.2-project-manifest`) with each file's path, SHA-256, size, category and source, plus the allowlist's own SHA-256 and the source commit. Paths are POSIX-relative strings, so spaces are safe. Shell loops receive paths only as NUL-delimited records (`manifest.py categories`). Symlinks are never followed; any symlink is a finding, and a symlink at an immutable path counts as modification.

| Phase | Rule |
|---|---|
| `pre` | The tree must equal the manifest exactly: same file set, same hashes, no extra files, no symlinks. Any difference stops the run |
| `post` | Immutable files must be intact (else invalid). Findings recorded: `mutable_changed`, `additive_new`, `tolerated` (`__pycache__`, `.pytest_cache`), `unexpected` (any other new file), `symlink`, `special` |

Pristine copies live in the operator store. They are verified against their manifests before every run, and the agent cannot read them.

### 10.3 Ownership and modes inside a run

| Item | Owner | Mode | Effect for the agent user |
|---|---|---|---|
| run root `r-<id>/` | root | 0711 | traverse only |
| `project/` and package directories | root | 1777 (sticky) | may create files; cannot delete or replace files it does not own |
| immutable files (incl. `TASK.md`, `README.md`, `opencode.jsonc`) | root | 0444 | read only; cannot `chmod`, delete or rename over |
| the mutable file | agent | 0644 | may edit or atomically replace |
| `tests/baseline/` | root | 0755 | no new files |
| `tests/additive/` | agent | 0755 | free |
| `home/.config`, `home/.config/opencode`, skill files | root | 0755 / 0444 | read only |
| `home/.local`, `home/.cache`, `tmp/` | agent | 0700 | free |

`chmod 444` alone would not be a security boundary: a same-user agent can `chmod` it back, and a writable parent directory allows replacement. Here, ownership by a different user and the sticky bit make the protection kernel-enforced *for this unprivileged user*. It does not stop root, kernel or container escapes, or a sudo misconfiguration; preflight checks the latter. Read-only bind mounts are not used, because a Codespace container cannot be assumed to grant `CAP_SYS_ADMIN`. Hash verification remains the final check either way.

## 11. Per-run procedure

`harness/launch-run.sh RUN_ID` is one executable procedure for all three tasks and both groups. Everything that varies comes from the sealed schedule.

| Step | Action | Failure → |
|---|---|---|
| 1 | Refuse if `preflight.ok` or `runtime-gates.json` is missing, `STOP` exists, the run ID was used before, or the activation mode differs from earlier runs | exit 2 |
| 2 | No process of either agent user is running; pristine store, skill and config hashes are intact | invalid |
| 3 | Build the HOME (global config; treatment only: skill) and the project from the manifest with the modes in §10.3 | invalid |
| 4 | Clean ancestors; `pre` manifest verification; access probes (agent cannot read operator material or the other env; cannot write `TASK.md`; can write the mutable file); HOME listing | invalid |
| 5 | `opencode debug paths` as the agent: all paths inside the run | invalid |
| 6 | Start `opencode serve` as the agent on a random port with a random password; wait for `/api/info` | invalid |
| 7 | `api_checks.py`: provider, model, `xhigh`, skill registry, config sources | 10–12 → BLOCKED (benchmark stops); 13 → isolation failure (benchmark stops) |
| 8 | `drive_session.py`: create session (model + variant + location), send `TASK.md` bytes (+ attachment for treatment), poll until idle or 45 min, then interrupt; export | see §12 |
| 9 | Secondary export through the documented CLI, `opencode session export <id> --server <url>` (recorded; failure is non-fatal if the API export exists) | — |
| 10 | Stop the server; kill all processes of the agent user | invalid |
| 11 | Copy project, OpenCode data (DB, logs) and HOME listing to the capture with `tar` (symlinks preserved, not followed) | invalid |
| 12 | `post` manifest verification; `diff -ruN` against pristine; `export_checks.py`; `run_status.py` | — |
| 13 | Delete the run root and any files of the agent user in `/tmp`, `/var/tmp`, `/dev/shm` | always (trap) |

Outputs (operator store, `captures/<run_id>/`): `launcher.log`, `verify-pre.json`, `debug-paths.txt`, `serve.log`, `server-info.json`, `api-checks.json`, `driver/` (requests, polls, `export.json`, `driver-result.json`), `cli-export.json`, `project-final/`, `opencode-data/`, `home-config-listing*.txt`, `verify-post.json`, `diff.patch`, `export-checks.json`, `run-status.json`, and later `hidden-score.json`.

`run-all.sh` executes runs in sealed order and stops at the first run that is not valid.

## 12. Run validity, exclusions and reruns

### 12.1 Valid run

A run is valid when all of the following hold:
- `api_checks` passed.
- The driver reached idle or the pre-registered timeout.
- Every assistant message used `opencode/nemotron-3.5-super-vl-free#xhigh`.
- Treatment activation is CONFIRMED.
- Control shows no contamination.
- Immutable files are intact.
- The HOME configuration listing is exactly as expected.

### 12.2 Outcomes, not exclusions

Timeouts, wrong code, crashes of the agent's own tests, constraint violations, extra files, false claims and refusals are outcomes. They are scored, never rerun.

### 12.3 Rerun rules (pre-registered)

A human may approve **one** rerun of a slot (`schedule.py rerun`, which records the reason) only for:
- a gateway or provider error before the agent's first tool call;
- a server or launcher crash not caused by the agent;
- a Codespace stop or timeout during the run;
- an activation failure or contamination traced to the harness rather than to the agent's actions.

A control agent that fetches the skill text from the internet makes the run invalid. That is not eligible for rerun; it is reported as a contamination event.

Every invalid run and every rerun is reported with its reason.

## 13. Evidence and blind evaluation

### 13.1 Who sees what

| Role | Sees | Never sees |
|---|---|---|
| Operator (runs the harness; not a scorer) | everything in the operator store | — |
| Activation auditor (may be the operator) | `export-checks.json`, `api-checks.json` | — |
| Blind scorer | packets only (§13.3) | group, run ID, schedule, env labels, skill text/hash, activation verdicts, token counts, durations, timestamps, absolute paths |
| Agent | its own project, HOME and TMP | everything else (§4 matrix) |

### 13.2 Order of operations

1. All 18 slots finish (valid or finally invalid).
2. `score-all.sh` uploads the hidden tests and runs them as `aqd-eval` (§13.4).
3. `blind_packet.py` builds packets.
4. Scorers score.
5. Scores are frozen: the SHA-256 of the scores directory is recorded in `sealed/`.
6. `analyze.py` unblinds.

### 13.3 Packet contents (`blind_packet.py`)

Each packet contains the task text, the agent's final report, the diff against pristine, the hidden-check and baseline outcomes, workspace findings, and a transcript of visible assistant text and tool calls.

Removed or redacted: skill messages and attachments, `skill` tool calls, reasoning text, every match of `code[-_ ]discipline`, the skill's sentinel lines, `/aqd/...` paths (replaced by `<project>`/`<home>`/`<tmp>`), env labels, run IDs, session IDs, token counts, durations and timestamps. Redaction counts go only to a sealed log.

The scorer records a group guess after scoring; `analyze.py` reports guess accuracy as a blinding check.

Residual risk: an agent's own prose may reveal skill-style habits (for example a quality receipt). That cannot be removed without altering the artifact being scored, and is reported.

### 13.4 Evaluator material

The hidden tests, reference solutions, mutants, `check_oracles.py` and the private scoring key are kept **outside the public repository** in the evaluator pack (on the evaluator's machine: `E:\Claude\AQD-phase-3.2-evaluator-private\`).

- They are uploaded into the Codespace (`$AQD_EVALUATOR/hidden_tests/<task>/`) only after every agent run has finished, both agent users are locked, and their processes are gone.
- They run as `aqd-eval` in a per-run scratch directory, so agent code never runs with access to anything else of the evaluator's.
- Previous results are never placed in a run.

### 13.5 Overclaims

For each run the scorer lists every claim in the final report about tests run, results, guarantees or limitations, and checks each against the transcript and the hidden results. Unsupported claims lower the evidence dimension. Fabricated test execution is a critical failure.

## 14. Statistical interpretation

The 18-run design is an **exploratory pilot**:

- **Three task types only.** Effects may be task-specific; no claim beyond these tasks.
- **Three runs per task per group.** Model sampling is stochastic; three runs give a rough range, not a stable estimate.
- **One model, one agent version, one date window, one gateway.** None of these generalises.
- **Limited power.** With 3 vs 3 per task, a stratified exact permutation test has a smallest attainable two-sided p of 2/8000. Only perfect separation in all three tasks reaches it, and anything short of large, consistent differences will not be distinguishable from noise.
- **Ceiling and floor effects** are possible (e.g. all runs pass every hidden check).

Reporting (`analyze.py`):
- per task and group: n, mean, median, min, max and every value for the primary outcome (hidden-check pass fraction) and the secondary outcomes (rubric total, overclaims, critical failures);
- per-task treatment − control differences, and their unweighted mean;
- the exact stratified permutation p-value, labelled descriptive;
- process metrics (duration, tool calls, tokens), reported separately;
- invalid runs, reruns and reasons;
- the blinding check.

No statement of statistical proof, significance-based "improvement", or general effectiveness may be made from this sample. Permitted language: "in this pilot, on these three tasks, treatment runs scored X vs Y on average; the difference is consistent/inconsistent across tasks".

## 15. GitHub Codespaces resources and preflight

### 15.1 Facts (F14)

| Item | Value |
|---|---|
| Compute | Core-hours = active hours × machine multiplier (2-core = ×2). Free personal plan: 120 core-hours/month (60 wall-clock hours on 2 cores) |
| Storage | GB-month, accrued hourly while a codespace exists, including stopped ones. Free: 15 GB-month. Default image container storage is free; repository files, installed packages and captures count |
| Idle timeout | Default 30 min, configurable 5–240 min; terminal output resets it |
| Maximum lifetime | 12 hours, regardless of idle timeout |
| Deleting a codespace | Stops further storage accrual; **does not reduce** usage already accrued this month |
| Over quota | No payment method on file → **blocked**. Payment method on file → **billed** (subject to budgets) |

### 15.2 Estimate (an estimate, not a guarantee)

| Item | Wall-clock | Core-hours (2-core) |
|---|---|---|
| Setup, install, preflight, 2 smoke runs | ≈ 1.5 h | ≈ 3 |
| 18 runs × (≤ 45 min agent + ≈ 5 min harness) | ≤ 15 h | ≤ 30 |
| Scoring and packet build | ≈ 1 h | ≈ 2 |
| **Total** | **≤ 17.5 h** | **≤ 35** |

Storage: roughly 1–2 GB for 3–5 days is well under 1 GB-month.

The 12-hour lifetime means at least **two Codespace sessions**. Between sessions:
- The operator store on `/workspaces` persists.
- Users and `/opt` may not persist across a rebuild, so re-run `setup-host.sh` (idempotent) and `install-opencode.sh`, then `preflight.sh` (which compares the OpenCode tree hash).
- Never stop a codespace while a run is in progress. A run interrupted by a stop is invalid under rule §12.3.

### 15.3 Preflight checklist (before any Codespace exists, by the user)

| # | Check | Where | Required result |
|---|---|---|---|
| Q1 | Actual remaining compute core-hours this cycle | github.com/settings/billing → Codespaces usage | ≥ 40 remaining |
| Q2 | Actual storage GB-month used this cycle | same | ≥ 2 GB-month remaining |
| Q3 | Plan (Free/Pro) and billing-cycle reset date | same | recorded |
| Q4 | Payment method on file? | github.com/settings/billing | **No**, so overage is blocked; otherwise explicit user approval for possible charges is required |
| Q5 | Codespaces budget/spending limit | github.com/settings/billing/budgets | recorded; never changed by the operator |
| Q6 | Existing codespaces and prebuilds consuming storage | github.com/codespaces | recorded; none deleted without the user's say |
| Q7 | Default idle timeout and retention | github.com/settings/codespaces | idle 60 min recommended; retention ≤ 7 days recommended |

The results go into `$AQD_SEALED/billing-confirmation.json`; `preflight.sh` refuses to pass without it:

```json
{
  "checked_utc": "2026-11-21T00:00:00Z",
  "checked_by": "user",
  "plan": "free",
  "compute_core_hours_remaining": 0,
  "storage_gb_month_remaining": 0,
  "payment_method_on_file": false,
  "paid_usage_approved_by_user": false,
  "machine_type": "basicLinux32gb",
  "idle_timeout_minutes": 60,
  "billing_cycle_resets_utc": ""
}
```

**No billing setting, payment method, budget or paid resource may be configured without explicit user approval.**

## 16. Privacy and repository protection

- **What enters an agent workspace:** only the allowlisted synthetic files of one task, the identical `opencode.jsonc`, and (treatment HOME only) the public `SKILL.md`. No `.git`, no other repository content, no credentials, no personal files. Nothing from Chatul, Holdshort, Ideal-Umbrella or any other repository, and no file from the user's PC, ever enters the Codespace except this repository's checkout and, after the runs, the evaluator pack.
- **Codespace contents:** the Codespace clones this public repository (with history) into `/workspaces/AI-Quality-Discipline`. The agent users cannot read it (mode 0700, plus an ACL where available; verified before every run).
- **Network:** outbound internet is permitted and **not** restricted to the model endpoint. Codespaces does not provide model-only egress control, and none is claimed. An agent could use its shell to fetch public material, including this repository, the public skill text and the public pilot scoring key. The pilot key does not concern NEW-01/02/03. The NEW tasks' hidden tests and key are not public. Control transcripts are scanned for skill text (§5.3).
- **Model provider logging:** the Nemotron free endpoint logs prompts and outputs under NVIDIA trial terms (F9). Only synthetic data is sent.
- **Secrets:** no account, API key or credential is created or configured by this specification. The agent environment is built with `env -i`.

## 17. Execution runbook

Every step from 2 onwards requires the user's separate, explicit authorisation. None has been performed.

| # | Step | Who |
|---|---|---|
| 1 | Review and approve this specification, decisions N1–N11, and resolve blockers B1–B3 (§21) | user |
| 2 | Fill in the preflight checklist (§15.3) | user |
| 3 | Commit and push the Phase 3.2 files; record the commit | user (authorises) |
| 4 | Create the Codespace from the user's machine: `gh codespace create -R StepenkoAnatoli/AI-Quality-Discipline -b phase-3/benchmark-foundation -m basicLinux32gb --idle-timeout 60m --retention-period 72h` | user / operator |
| 5 | In the Codespace (scripts are always invoked with `bash`, because the executable bit is not relied on): `bash evaluations/phase-3.2/harness/setup-host.sh`, then `bash evaluations/phase-3.2/harness/install-opencode.sh` | operator |
| 6 | Write `/workspaces/.aqd-operator/sealed/billing-confirmation.json`; run `bash …/preflight.sh` (exit 20 = BLOCKED → stop and ask the user) | operator |
| 7 | `bash …/launch-run.sh --smoke control` and `bash …/launch-run.sh --smoke treatment`; verify R1–R8; write `sealed/runtime-gates.json` | operator, reviewed by user |
| 8 | `bash …/run-all.sh` (stops at every invalid run for review) | operator |
| 9 | Copy `/workspaces/.aqd-operator` to the evaluator machine: `gh codespace cp -r -c <name> 'remote:/workspaces/.aqd-operator' <local dir>` | operator |
| 10 | Upload the evaluator pack's `hidden_tests/` to `$AQD_EVALUATOR/hidden_tests/` (e.g. `gh codespace cp -r -c <name> hidden_tests 'remote:/workspaces/.aqd-operator/evaluator/'`); `bash …/score-all.sh` | evaluator |
| 11 | `blind_packet.py`; hand packets to the scorer(s); freeze scores with `find <scores> -type f -print0 \| sort -z \| xargs -0 sha256sum > sealed/scores.sha256`; then `analyze.py` | evaluator / scorer |
| 12 | `bash …/teardown.sh --evidence-downloaded`; then from the user's machine `gh codespace delete -c <name>` | operator / user |

## 18. Runtime gates

Each gate can only be verified by executing OpenCode. All are checked in the two smoke runs (step 7), and the result is recorded in `sealed/runtime-gates.json` as `{"R1": "pass", …, "notes": …}`.

| Gate | What must be observed |
|---|---|
| R1 | Credential-free install offers provider `opencode`, the model and `xhigh` (preflight exit 0) |
| R2 | Treatment smoke export contains the skill text via `user.skills[]` or a `skill` message (`export_checks` CONFIRMED); control smoke contains none |
| R3 | Every assistant message has `model.variant == "xhigh"`; no model-resolution error |
| R4 | One extra treatment smoke run with `AQD_DEBUG_LOG=1 launch-run.sh --smoke treatment` (sets `OPENCODE_LOG_LEVEL=DEBUG` for that smoke run only); inspect `serve.log` and `opencode-data/opencode/log/` for the request's reasoning option. If not visible: "transmission unobservable", user decides |
| R5 | `opencode debug paths` and `/api/config` show only run-local paths; `opencode serve` works with a root-owned, read-only `~/.config/opencode` |
| R6 | `drive_session.py` idle detection terminates correctly (`polls.jsonl` shows busy → idle); the session's location equals the project |
| R7 | `check_oracles.py` passes inside the Codespace (Linux, Codespace Python) three times |
| R8 | `opencode session export <id> --server <url>` behaviour recorded (works / flag unsupported) |

## 19. Stop rules

Stop the whole benchmark (write `sealed/STOP`, ask the user) if:
- provider, model or `xhigh` is unavailable (exit 10/11/12);
- any isolation check fails (exit 13, access probe, contamination traced to the harness);
- the model's free availability ends or its terms change;
- repeated gateway errors (≥ 3 consecutive infrastructure failures);
- the billing or quota state changes from what was confirmed;
- any secret or non-synthetic data is found in a workspace or transcript.

Never switch the model, variant, activation mode or task wording mid-experiment.

## 20. Known limitations

1. `xhigh` honouring by the NVIDIA endpoint cannot be proven from the client; at best OpenCode's acceptance and the request option can be shown (§6.4).
2. Free-model availability is time-limited and may change during the experiment.
3. Outbound internet is open; contamination is detected after the fact, not prevented.
4. The agent sees its server password and can call its own server's API.
5. Blinding can be broken by the agent's own writing style.
6. Hidden-oracle limitations that would help an agent game the checks are recorded only in the private scoring key.
7. The public pilot scoring key and the public skill exist on the internet (§16).
8. Kernel-enforced immutability holds against the unprivileged agent user only (§10.3).
9. 18 runs: exploratory only (§14).
10. The oracles have been validated on Windows/Python 3.14 only, until R7.

## 21. Readiness

**CONDITIONALLY READY — BLOCKERS REMAIN.**

The specification, fixtures, oracles and harness are complete enough for implementation review, and the parts that can be checked without execution have been checked (see the checklist). Execution is blocked until:

| # | Blocker | Resolution |
|---|---|---|
| B1 | Signed-out availability of the `opencode` provider, model and `xhigh` is unverified (F10, F11) | Preflight catalog probe (R1). If absent: user decision; no credentials may be created by the operator |
| B2 | Runtime behaviour gates R2–R8 unverified | Authorised smoke runs |
| B3 | Codespaces quota and billing state unknown for this account | User completes §15.3 |
| B4 | Approval of decisions N1–N11 | User |
| B5 | Authorisation to commit, push, create the Codespace, install OpenCode, and send requests to the model endpoint | User |
