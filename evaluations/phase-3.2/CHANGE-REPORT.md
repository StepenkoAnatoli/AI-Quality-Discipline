# Phase 3.2 — Change report (Final Specification v2, repository revision)

Date: 2026-11-21. Branch `phase-3/benchmark-foundation`, base commit `8cfecb90fb5b4bb3abe9f2f2c937478fb6e02560`. Nothing was committed, pushed or executed against OpenCode, a model endpoint or a Codespace.

## 1. What was found before editing

- The branch exists and was checked out as specified (`git branch --show-current` → `phase-3/benchmark-foundation`).
- **No Phase 3.2 specification existed in the repository.** `git grep` over all 99 commits on both branches found no mention of Phase 3.2, NEW-01/02/03, Nemotron, `xhigh`, Codespaces or OpenCode. There are no issues or pull requests.
- The previous drafts were loose files on the operator PC, outside any repository:
  - `E:\Claude\benchmark-phase3-2-specification.md`
  - `E:\Claude\benchmark-phase3-2-revised-specification.md`
  - `E:\Claude\benchmark-phase3-2-final-specification.md`
  - `E:\Claude\benchmark-phase3-2-final-specification-v2.md`
  - `E:\Claude\benchmark-phase3-2-v2-change-report.md`

  The latest draft ("final specification v2") and its change report were read in full and audited; §2 lists their defects. The three earlier drafts are superseded by that draft and were not re-audited line by line. All five files were left untouched.
- The existing Phase 3 pilot (`evaluations/pilot`, `evaluations/fixtures`, CD/WS/SV/PH tasks) is unrelated to NEW-01/02/03 and was not reused, per the preserved decision.

## 2. Defects in the previous draft and their corrections

| Area | Defect in the off-repo "final specification v2" | Correction (where) |
|---|---|---|
| A Isolation | Separate directory names, but no `HOME`/`XDG_*` set, one OS user for both groups, OpenCode's shared per-user background server not considered; the agent shell could read the other group's tree | Separate OS users per group, fresh HOME/XDG/DB/TMPDIR per run, private `opencode serve`, `env -i`, access probes, server-side skill registry check (SPECIFICATION.md §5) |
| A Isolation | Treatment skill placed in project `.opencode/skills`, making project trees differ between groups | Skill only in the treatment run's HOME; projects byte-identical |
| A Isolation | Ancestor and system discovery locations (config up to the filesystem root; `/etc/opencode`) not considered | `assert_clean_ancestors`, `/etc/opencode` check, `/api/config` check |
| B Launcher | Copied `fixtures/$TASK/.` into the project, then `chmod`ed `$PROJECT/fixtures/$TASK/...` (paths that do not exist), with failures hidden by `\|\| true` | Manifest-driven construction; every path verified; no error suppression on setup steps (`launch-run.sh`) |
| B Launcher | Copied the instruction file into a non-existent `$PROJECT/instructions/`; the setup scripts placed instructions in a location that contradicted the documented tree | `TASK.md` is an allowlisted immutable file; the prompt is its exact bytes |
| B Launcher | `exit 1` on an OpenCode error skipped all integrity checks | `finish` trap always records status and cleans up |
| B Launcher | Run metadata including the **group** written to `$RUN_ROOT/evidence/`, the agent project's parent, readable by the agent | All evidence in an operator-only store owned by another user |
| B Launcher | Post-run `git init && git add -A && git diff --cached` produced a whole-tree diff and created `.git` in the workspace | `diff -ruN` against the pristine copy, run on a captured copy |
| B Launcher | Session export commented out; transcript taken from stdout | API export plus the documented `opencode session export` as a second copy |
| C Activation | `@code-discipline` prefixed only to the treatment prompt, with the confound "mitigated" by calling it a mechanism trigger | Identical prompt bytes; skill attached through the documented `skills[]` field; `@` mention kept as an approval-only fallback (§7) |
| C Activation | Activation "verified" from "skill-influenced behavior" in the transcript, which conflates activation with outcome | Mechanical check that the skill text is in the session; verdict hidden from scorers (§7.3) |
| D Config | Project config at `.opencode/opencode.jsonc` with a `providers.opencode.models` override block that has no purpose | Minimal documented config: `$schema` plus `permissions`; no provider block; model chosen per session (§6) |
| D Model | CLI commands marked "[UNVERIFIED]"; OpenCode V1/V2 mismatch unnoticed (PC has V1 1.18.35) | Commands checked against V2 docs; V2 `@opencode/cli@2.3.2` pinned; preflight re-checks flags on the pinned binary |
| D Model | `xhigh` treated as one gate | Gates X1–X4 separate catalog, acceptance, transmission and honouring, and state which are unprovable (§6.4) |
| E Tasks | NEW-01: "concurrent duplicate requests: exactly one side effect" without a side-effect boundary | Transactional outbox; at-least-once email; claiming exactly-once is an overclaim |
| E Tasks | NEW-02: allowed "standard library threading/locking primitives", i.e. process-local locks | Multi-process deployment declared; process-local lock fails hidden checks (verified) |
| E Tasks | NEW-03: "e.g.", "behavior defined", "accepted with warning or rejected" | 18 numbered clauses with every choice made, including precedence |
| E Tasks | Fixtures did not exist; hidden tests only described | Fixtures, baseline tests, hidden tests, references, mutants built; oracles validated locally |
| F Baseline tests | `chmod 444` on wrong paths; same-user ownership | Root-owned files in sticky or root-owned directories; agent has no sudo; hash verification |
| G Manifest | `sha256sum` text written to `workspace-manifest.json`; `awk` re-parse broke on spaces | JSON manifest (`manifest.py`), NUL-delimited shell interface, spaces tested |
| G Manifest | Manifest included mutable and generated files | Categories; pre-run exact, post-run integrity on immutable only |
| H Blinding | Run ID in the agent-visible path reused as the scorer ID; group in metadata next to the workspace | Separate random blind IDs; packets strip paths, IDs, skill content, tokens and timings |
| J Codespaces | `gh codespace delete <name> --confirm` (no such flag) | `gh codespace delete -c <name>` (`-f` optional), from CLI help |
| J Codespaces | Storage row "<18 GB-month if all retained" and "<15 GB-month if deleted after each run" without basis | Hourly GB-month accrual explained; deletion stops accrual but does not reduce it; estimate ≤ 35 core-hours, about 1 GB-month |
| K Privacy | Not mentioned: the Codespace clones the full repository with history; Codespaces secrets on disk | Checkout and `/workspaces` made unreadable to agent users; preflight fails if `/workspaces/.codespaces` is readable |

## 3. Issues found that the task description did not list

1. OpenCode V2 runs **one shared background server per user account** by default. Without per-run HOMEs or a private server, control and treatment would share server state.
2. Project config is discovered up to the filesystem root, and `/etc/opencode` applies to every user with the highest precedence.
3. The root `model` config cannot carry a variant; `xhigh` must be selected per session.
4. The hidden concurrency checks did **not** reproduce the check-then-act race on the buggy NEW-02 fixture. A wrong agent solution could have passed by luck. Fixed with a slow-`SELECT` connection proxy, and mutation testing was added to prove the checks catch plausible wrong solutions.
5. This PC has `core.autocrlf=true`. A commit from it would normalise the intentionally CRLF Excel sample. A scoped `.gitattributes` prevents this.
6. Git on Windows does not record the executable bit, so all scripts are invoked with `bash`.
7. The NVIDIA free endpoint logs prompts (trial terms), so synthetic-only data is a hard requirement, not just a preference.
8. With open internet, pushing this directory before the runs makes the specification readable to agents. That is now explicit decision N11, and oracle details that would help an agent game the checks were moved to the private scoring key.

## 4. Mistakes made during this work, and fixes

| What | Where | Impact if missed | Cause | Fix | How verified |
|---|---|---|---|---|---|
| `run_checks.py` iterated the suite after running it; unittest empties suites, so every check was reported as `error` | `harness/run_checks.py` | All hidden scores wrong | Wrong assumption about `unittest` internals | Collect test IDs before running | Oracle check then passed; L1 `ScoreRunTests` |
| NEW-03 sample's `ë`/`ü` became `?` when generated through a PowerShell pipe | `sample_data/excel export (semicolon).csv` | Sample would not test UTF-8 | Console encoding of piped script | Regenerated from a UTF-8 script file with `\u` escapes | Bytes inspected (`Zo\xc3\xab`); H01 passes on the reference |
| H05 contained a meaningless assertion, and its tab case expected the wrong outcome | private NEW-03 hidden test | Check would not test the clause | Drafting error | Rewritten | Reference passes; mutants are caught |
| H13 input placed a space before a quote (literal under RFC 4180) | private NEW-03 hidden test | Wrong expectation | Drafting error | Input corrected | Reference passes |
| Contract lacked a precedence rule between file-level errors | NEW-03 `TASK.md` | Ambiguous scoring | Omission | Clause 18 added before any run | Static review |
| NEW-02 concurrency checks passed on the buggy fixture | private NEW-02 hidden tests | Oracle unable to detect the defect | Race window too small to hit reliably | Slow-`SELECT` proxy | Fixture now fails H01/H02/H12; mutants killed; three stable passes |
| Preflight started the server with the operator's working directory, which the agent user cannot enter | `preflight.sh` | Server start failure at runtime | sudo keeps the caller's working directory; `--chdir` is disabled by default | `as_agent` helper changes directory inside the agent's process | Static review; `bash -n` |
| Config-source check would fail on locations that were searched but do not exist | `api_checks.py` | False isolation failures | Over-strict check | Only existing paths fail | L1 `ApiCheckTests` |
| An incomplete mutant stub was written | private `mutants/` | none (removed before use) | Started writing the wrong shape | Mutants regenerated as complete files | Oracle check |
| Test expected `fail` where `error` is correct | `tests/test_harness.py` | False test failure | Wrong expectation | Corrected | L1 |

## 5. Files

### Inspected (repository)

`README.md`, `BRAIN.md`, `evaluations/README.md`, `evaluations/protocol.md`, `evaluations/shared-rubric.md`, `evaluations/pilot/tasks.md`, `evaluations/pilot/scoring-key.md`, `evaluations/fixtures/README.md`, `evaluations/fixtures/RUNNING.md`, `evaluations/fixtures/manifest.json`, `evaluations/fixtures/check_fixtures.py`, `evaluations/run-record-template.json`, `evaluations/results/README.md`, `docs/AGENT-COMPATIBILITY.md`, `skills/code-discipline/SKILL.md`, `.github/workflows/phase3-validation.yml`, plus the full `git ls-files` listing.

### Inspected (outside the repository)

The five off-repo drafts listed in §1 (two read in full). Official documentation: opencode.ai/docs (config, skills, models, providers, permissions, instructions, CLI, CLI commands, web, troubleshooting, Console models, OpenAPI, config schema); docs.github.com (Codespaces billing, included usage, timeout). `gh codespace` help text; `npm view` for both OpenCode packages; `opencode run --help` of the local V1 binary.

### Modified (repository)

| File | Change |
|---|---|
| `evaluations/README.md` | Added the `phase-3.2/` entry; removed a duplicated `results/` bullet |
| `BRAIN.md` | Phase 3 checklist item for Phase 3.2; dated decision-log entry; split two decision-log entries that were joined by a literal `\n` |
| `README.md` | One sentence in "Current status" pointing to Phase 3.2 (not executed) |
| `.github/workflows/phase3-validation.yml` | Step running the allowlist check and the Phase 3.2 harness tests (no OpenCode, no network) |

### Created (repository, all under `evaluations/phase-3.2/`)

| File | Purpose |
|---|---|
| `README.md`, `SPECIFICATION.md`, `VALIDATION-CHECKLIST.md`, `RISK-REGISTER.md`, `CHANGE-REPORT.md` | Documentation |
| `.gitattributes` | Byte-exact CSV fixtures; LF scripts |
| `allowlist.json` | Exhaustive file allowlist with categories |
| `config/opencode.jsonc`, `config/global-opencode.jsonc` | Identical OpenCode configuration for both groups |
| `tasks/NEW-01/project/**` (12 files) | Webhook idempotency fixture, contract, baseline tests |
| `tasks/NEW-02/project/**` (11 files) | Inventory reservation fixture, contract, baseline tests |
| `tasks/NEW-03/project/**` (11 files) | CSV import fixture, contract, samples, baseline tests |
| `tasks/SMOKE/project/**` (3 files) | Runtime-gate smoke task |
| `harness/lib.sh` | Pinned settings, isolation helpers |
| `harness/setup-host.sh`, `install-opencode.sh`, `preflight.sh` | Host setup, pinned install, preflight (no model request) |
| `harness/launch-run.sh`, `run-all.sh` | Per-run launcher (all tasks, both groups, smoke), sequential runner |
| `harness/drive_session.py`, `api_checks.py`, `export_checks.py`, `run_status.py` | Session driver, pre-run and post-run checks, validity |
| `harness/manifest.py`, `schedule.py` | JSON manifests; sealed randomised schedule and reruns |
| `harness/run_checks.py`, `score_run.py`, `score-all.sh` | Hidden and baseline scoring |
| `harness/blind_packet.py`, `analyze.py` | Blinded packets; exploratory analysis |
| `harness/aqd_common.py`, `teardown.sh` | Shared constants; cleanup |
| `tests/test_harness.py` | 29 local tests |

### Created outside the repository (private evaluator pack, not to be committed)

`E:\Claude\AQD-phase-3.2-evaluator-private\`: `README.md`, `SCORING-KEY.md`, `check_oracles.py`, `make_mutants.py`, `hidden_tests/NEW-01..03/hidden_tests/*` (with `slow_db.py` for NEW-01/02), `reference/NEW-01..03/*`, `mutants/NEW-01..03/*` (9 files). Temporary scratch files in `E:\Temp\opencode` were deleted. `__pycache__` directories created by local test runs were deleted.

### Not touched

Everything else in the repository, including `scripts/`, `tests/`, `skills/`, `evaluations/pilot/`, `evaluations/fixtures/` and the off-repo drafts. No other repository was accessed.

## 6. Verification performed

| Command | Result |
|---|---|
| `python -m unittest discover -s evaluations/phase-3.2/tests -v` | 29 tests OK (includes `bash -n` on all 8 shell scripts via Git Bash 5.3) |
| `python evaluations/phase-3.2/harness/manifest.py check-sources --phase-root evaluations/phase-3.2` | `sources OK` |
| `python E:\Claude\AQD-phase-3.2-evaluator-private\check_oracles.py evaluations/phase-3.2` (three consecutive runs) | `ORACLES OK` each time: planted defects detected, references 41/41, mutants 9/9 killed |
| `python evaluations/fixtures/check_fixtures.py` | Existing pilot fixtures still PASS (unchanged) |
| `python scripts/validate_skills.py` | PASS (unchanged) |
| `python -m unittest discover -s tests` | **9 pre-existing failures** in `test_install.py` on this PC, present before any change (the files involved were not modified). Likely cause: `core.autocrlf=true` checks out CRLF while the index has LF. Not investigated further; out of scope |

Not verified (requires execution, not authorised): everything in SPECIFICATION.md §18.
