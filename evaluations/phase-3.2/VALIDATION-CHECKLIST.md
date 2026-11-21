# Phase 3.2 — Validation checklist

Status labels (exactly one per row):

- **DOC** — verified against official documentation on 2026-11-21 (source in SPECIFICATION.md §3)
- **STATIC** — verified by static inspection of the files in this directory
- **LOCAL** — verified by local tests on the operator PC (Windows 11, Python 3.14.7, Git Bash 5.3 for `bash -n`); command shown
- **RUNTIME** — requires actual runtime verification inside the Codespace (gate in SPECIFICATION.md §18)
- **BLOCKED** — blocked pending user authorisation or decision

Local commands used:
- `L1` = `python -m unittest discover -s evaluations/phase-3.2/tests -v` → 29 tests, OK
- `L2` = `python <private pack>/check_oracles.py evaluations/phase-3.2` → `ORACLES OK`, three consecutive runs
- `L3` = `python evaluations/phase-3.2/harness/manifest.py check-sources --phase-root evaluations/phase-3.2` → `sources OK`
- `L4` = `bash -n` on every `harness/*.sh` (inside L1) → OK

## A. Control/treatment isolation

| # | Requirement | Status | Evidence |
|---|---|---|---|
| A1 | Separate control and treatment roots (`/aqd/env-a`, `/aqd/env-b`, random sealed mapping) | STATIC | `setup-host.sh`, `schedule.py`; balance and mapping tested in L1 (`ScheduleTests`) |
| A2 | Separate OS users without sudo or groups | STATIC → RUNTIME | `setup-host.sh`; `preflight.sh` checks groups and `sudo -l` (R5 run) |
| A3 | Separate HOME/XDG/DB/TMPDIR per run; `env -i` | STATIC | `lib.sh make_agent_env` |
| A4 | OpenCode resolves only run-local paths | RUNTIME | `opencode debug paths` check in `launch-run.sh` (R5) |
| A5 | No shared background service | DOC + STATIC | F6; private `opencode serve` per run |
| A6 | No skill in any control discovery path (project, ancestors, HOME, system dir) | STATIC | `assert_clean_ancestors`, pre-run manifest (exact file set, L1 `ManifestTests`), HOME listing |
| A7 | Running server registers no `code-discipline` in control | RUNTIME | `api_checks.py` logic tested in L1 (`ApiCheckTests`); real server behaviour R2/R5 |
| A8 | Control transcript free of skill text | LOCAL (logic) / RUNTIME (data) | L1 `ExportCheckTests`; real exports per run |
| A9 | Isolation does not rely on deleting the skill | STATIC | Control HOMEs are created without it (`launch-run.sh` build-home) |
| A10 | Agent cannot read operator store, checkout, operator home, other env | RUNTIME | `assert_unreadable_by` before every run |

## B. Launcher

| # | Requirement | Status | Evidence |
|---|---|---|---|
| B1 | One executable launcher for all tasks and groups; no placeholders | STATIC + LOCAL | `launch-run.sh`; `bash -n` (L4) |
| B2 | Fresh run root, unique run ID, never reused | STATIC | ID regex, capture-exists and run-root-exists refusals |
| B3 | Fixture copied exactly from the manifest with correct ownership | STATIC + LOCAL | NUL-safe `categories` (L1); pre-run `verify --phase pre` |
| B4 | Correct instruction: exact `TASK.md` bytes | LOCAL | L1 `DriveSessionTests` compares request text with `TASK.md` |
| B5 | Correct working directory (agent process `cd`s itself) | STATIC → RUNTIME | `as_agent`; R6 |
| B6 | Correct model and variant per session | LOCAL (request body) / RUNTIME (accepted) | L1 asserts `model` object; R3 |
| B7 | Independent output and log destinations outside the workspace | STATIC | `captures/<run_id>/`, operator-only |
| B8 | Every path verified before OpenCode starts | STATIC | steps 2–5 of §11 |
| B9 | Cleanup of run root and agent temp files | STATIC | `finish` trap |

## C. Skill activation

| # | Requirement | Status | Evidence |
|---|---|---|---|
| C1 | Documented mechanism | DOC | F4 (`@` mention, `skill` tool), F12 (`skills[]` attachment) |
| C2 | Identical prompt text in both groups (api-attachment) | LOCAL | L1 `DriveSessionTests` |
| C3 | Attachment actually puts the skill text in context | RUNTIME | R2 |
| C4 | Activation verified independently of scoring | LOCAL (logic) | L1 `ExportCheckTests`; verdict never in packets (L1 `BlindPacketTests`) |
| C5 | cli-mention fallback implemented, needs approval | STATIC / BLOCKED | `launch-run.sh`; N1 |

## D. OpenCode configuration and model

| # | Requirement | Status | Evidence |
|---|---|---|---|
| D1 | Documented project config location and schema URL | DOC + LOCAL | F1; L1 `ConfigTests` |
| D2 | Only documented V2 fields (`permissions`, `update`); no provider fields | DOC + LOCAL | schema property list checked 2026-11-21; L1 |
| D3 | No `ask` rule | LOCAL | L1 `ConfigTests` |
| D4 | Model ID `nemotron-3.5-super-vl-free` exists | DOC | F9 |
| D5 | `xhigh` in catalog | DOC (catalog, authenticated) / RUNTIME (signed out) | F11; R1 |
| D6 | Provider available without credentials | BLOCKED → RUNTIME | F10; preflight probe R1 |
| D7 | Variant accepted by OpenCode | RUNTIME | R3 |
| D8 | Variant transmitted to and honoured by endpoint | RUNTIME (may be unobservable) | R4; limitation 1 |
| D9 | CLI commands: `opencode models`, `run`, `session export`, `serve`, `debug paths` | DOC | F7; flags re-checked by `preflight.sh` against pinned binary (RUNTIME) |
| D10 | V2 pinned (`@opencode/cli@2.3.2`) | DOC + STATIC | F13; `install-opencode.sh`, `preflight.sh` |

## E. Tasks and oracles

| # | Requirement | Status | Evidence |
|---|---|---|---|
| E1 | Architecture, interfaces, assumptions, contract for each task | STATIC | `tasks/*/project/TASK.md`, `README.md`, SPECIFICATION.md §8 |
| E2 | NEW-01 no exactly-once claim; outbox boundary defined | STATIC | TASK clause 8 |
| E3 | NEW-02 cross-process required; process-local lock gets no credit | LOCAL | L2: fixture (thread lock) fails H01/H02/H12; mutant `deferred_txn_check_then_act` killed |
| E4 | NEW-03 contract fully determined before runs | STATIC + LOCAL | clauses 1–18; reference passes 16/16 (L2) |
| E5 | Baseline tests pass on every fixture | LOCAL | L1 `FixtureBaselineTests`; L2 |
| E6 | Hidden checks detect planted defects | LOCAL | L2 |
| E7 | Reference solutions pass every check | LOCAL | L2 (41/41) |
| E8 | Plausible wrong solutions are caught | LOCAL | L2 (9/9 mutants) |
| E9 | Oracles behave identically on Linux | RUNTIME | R7 |
| E10 | Hidden tests and key not in public repo | STATIC | private pack outside the repository; `git status` shows no such files |

## F. Immutable baseline tests

| # | Requirement | Status | Evidence |
|---|---|---|---|
| F1 | Baseline tests kernel-protected | STATIC → RUNTIME | §10.3 modes; `test -w` probe before each run |
| F2 | Agent may add only under `tests/additive/` | STATIC | modes; `edit tests/baseline/*` deny |
| F3 | Pre/post integrity | LOCAL | L1 `ManifestTests` |
| F4 | Scoring independent of agent-modifiable tests | LOCAL | L1 `ScoreRunTests` (tampered immutable file not used) |

## G. Manifests

| # | Requirement | Status | Evidence |
|---|---|---|---|
| G1 | Valid JSON manifest (not checksum text) | LOCAL | L1 |
| G2 | Exact allowlist; no unlisted files | LOCAL | L3 |
| G3 | Filenames with spaces | LOCAL | NEW-03 sample `excel export (semicolon).csv` through build, materialize, verify, categories (L1) |
| G4 | Unexpected files, symlinks, deletions detected | LOCAL | L1 (symlink case skips where Windows forbids symlinks) |
| G5 | `chmod 444` limitation documented; stronger enforcement used | STATIC | SPECIFICATION.md §10.3 |

## H. Blind evaluation

| # | Requirement | Status | Evidence |
|---|---|---|---|
| H1 | Group mapping, activation evidence, hidden tests outside agent reach | STATIC | §4 access matrix, §13 |
| H2 | Packets free of group-revealing content | LOCAL | L1 `BlindPacketTests` |
| H3 | Separate blind IDs | LOCAL | L1 `ScheduleTests` |
| H4 | Blinding check recorded | LOCAL | `analyze.py` (L1 `AnalyzeTests` covers scoring maths) |

## I. Statistics

| # | Requirement | Status | Evidence |
|---|---|---|---|
| I1 | Exploratory framing, limitations, permitted language | STATIC | §14 |
| I2 | Descriptive and permutation computations correct | LOCAL | L1 `AnalyzeTests` (exact p = 2/8000 for perfect separation) |

## J. Codespaces

| # | Requirement | Status | Evidence |
|---|---|---|---|
| J1 | Core-hours vs GB-month, idle timeout, 12-hour lifetime, deletion effect | DOC | F14 |
| J2 | Actual remaining allowance and billing state | BLOCKED | user completes §15.3 (B3) |
| J3 | Commands `gh codespace create/delete/cp` flags | DOC (CLI help) | F15 |
| J4 | No paid resources or billing changes | STATIC | §15.3; `preflight.sh` refuses a payment method without recorded approval |

## K. Privacy

| # | Requirement | Status | Evidence |
|---|---|---|---|
| K1 | Only allowlisted synthetic files enter workspaces | LOCAL | L3; L1 |
| K2 | No other repositories, personal files, credentials, `.git` | STATIC | allowlist; `env -i`; access probes |
| K3 | Internet and public-key exposure documented, not hidden | STATIC | §16, §20 |

## Not authorised and not done

Committing, pushing, creating a Codespace, installing OpenCode in a Codespace, contacting the model endpoint, running any smoke or benchmark run, and any billing change are all **BLOCKED** pending separate authorisation.
