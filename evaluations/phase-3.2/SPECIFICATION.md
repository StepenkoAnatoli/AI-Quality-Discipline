# Phase 3.2 — Specification v3

**Question.** Does giving a coding agent the `code-discipline` skill produce objectively better working software than the same agent, model and settings without it?

**Evidence that counts.** The behaviour of the code each run leaves behind, measured by hidden tests the agent never sees, and checked against the original (baseline) tests for regressions. What the agent *says* about its work never counts toward the result.

**Models in scope.** Claude and Grok only. Nemotron and the free OpenCode gateway are out of scope (decision 2026-11-21). The v2 specification that used them is in git history (`3ec3b32`).

**Date:** 2026-11-21. **Branch:** `phase-3/benchmark-foundation`, base commit `3ec3b32`.

## 1. Status

Only rows marked *tested locally* were run, on Windows with Python 3.14.7. Nothing has been tested in CI, independently audited or run against a model.

| Component | Implemented | Tested locally | Tested in CI | Independently audited | Status |
|---|---|---|---|---|---|
| Tasks NEW-01/02/03, revised prompts | yes | baseline tests pass; prompt/workspace hashes pinned by a test | no | no | ready for a smoke test |
| Hidden oracles (41 checks), references, 11 mutants (private pack) | yes | `check_oracles.py`: ORACLES OK, all mutants killed | never (private) | no | ready |
| Fail-closed scoring (`score_run.py`, `run_checks.py`, inventories) | yes | 30 adversarial tests (`test_scoring.py`) | no | no | ready apart from the sandbox |
| Docker scoring sandbox | yes | **no** (no Docker on the operator PC; tests skip) | job added, not yet run | no | **NOT DEMONSTRATED → hidden evaluation of real agent code is NOT READY** |
| Fail-closed analysis (`analyze.py`), model-aware schedule | yes | unit tests (`test_harness.py`) | no | no | ready |
| OpenCode run launcher (`launch-run.sh`, `preflight.sh`, driver, checks) | yes, model now a parameter | Python parts unit-tested with a fake server; shell syntax only | no | no | **never executed** |
| Live Claude / Grok runs | — | — | — | — | **not executed** (§9) |

## 2. Design

| Factor | Levels | Rule |
|---|---|---|
| Skill | control (no skill), treatment (skill loaded) | The only intended difference inside a block |
| Model | Claude, Grok | Analysed separately. Claude-with-skill is never compared with Grok-without-skill |
| Task | NEW-01, NEW-02, NEW-03 | Same prompt and starting files for every condition |

A block is one control run and one treatment run of the same model and task, in random order (`schedule.py`). Within a block, everything is identical: prompt bytes, starting workspace, tests visible to the agent, tools and permissions, time limit (45 min), model ID and variant, interface version.

1. **Smoke test (4 runs):** both models × both conditions on one task (NEW-02), one repetition: `schedule.py create --models <claude>,<grok> --tasks NEW-02 --repetitions 1`. It checks that the prompt, workflow and scoring work. It is not evidence about the skill.
2. **Controlled pilot (36 runs):** 2 models × 3 tasks × 3 repetitions × 2 conditions. It starts only after the smoke test has been reviewed and the user approves it. It is exploratory (§8).

**Run record** (`run-record.json`, written by the launcher before the prompt is sent): run ID, task, condition, model reference `provider/model[#variant]` as given to the interface, interface and version (`opencode <version>`), activation mode, skill SHA-256 or `null`, prompt SHA-256, workspace SHA-256, start time. `export_checks.py` also records every model and variant the session actually reported (`observed_models`); a mismatch with the run's model invalidates the run. Substitution is never silent.

## 3. Execution interface

The model and the interface are separate variables. The recommendation is to keep the interface constant across both models:

| Option | Assessment |
|---|---|
| **OpenCode for both models (recommended)** | Documented providers for Anthropic and xAI ([providers docs](https://opencode.ai/docs/providers/), checked 2026-11-21: native `@opencode/ai/providers/anthropic` and `@opencode/ai/providers/xai` packages). Native skill loading. The existing launcher already isolates runs and attaches the skill. One interface means a model comparison is not confounded by the agent loop |
| Claude Code for Claude, a Grok CLI for Grok | Valid for the within-model skill effect, but the interface then differs between models. Grok CLI behaviour, skill support and isolation were not verified |
| A custom agent loop over both APIs | Maximum control, but it is a new, untested agent, unlike the agents people actually use, and more code to audit |
| Running agents on the operator's own PC | **Rejected.** The user's global skills (for example a `careful-coding` skill very close to `code-discipline`), `CLAUDE.md` and the private evaluator pack are all readable by an agent's shell there |

**Host.** Use a disposable Linux machine (a VM, or a Codespace if the user authorises one) that holds only this public checkout. The private evaluator pack must never be on the agent host while agents run. The launcher needs `sudo` (for the per-group OS users) and Docker (for scoring).

**Credentials.** The user creates dedicated, spend-capped `ANTHROPIC_API_KEY` and `XAI_API_KEY` values and stores them in `$AQD_SEALED/credentials.env` (mode 0600). Each run receives only its own provider's key. The agent's shell can read that key, because it runs as the same OS user as the OpenCode server. Revoke the keys after the pilot. Nobody else creates accounts, keys or billing settings.

**Model IDs.** Read the exact IDs with `opencode models` on the run host and record them in the schedule. They are not guessed here. On 2026-11-21 the operator's own OpenCode catalog listed `anthropic/claude-opus-5-5`, `anthropic/claude-sonnet-5-5` and `anthropic/claude-haiku-5-5`, and no xAI provider was configured.

## 4. Contamination controls (agent runs)

These are implemented in the existing launcher but have **never been executed**:

- Each condition runs as its own unprivileged OS user. Every run gets a fresh HOME, XDG directories and OpenCode database, built with `env -i`; `OPENCODE_DISABLE_CLAUDE_CODE=1` is set.
- The skill file exists only in treatment HOMEs, as a root-owned read-only copy of `skills/code-discipline/SKILL.md` (SHA-256 `919d4d29…d2e6a3` at this commit; the run record holds the exact hash). Project trees are identical across conditions.
- Before the prompt is sent, `api_checks.py` asks the running server which skills it can see. A control run whose server can see `code-discipline` stops the benchmark.
- Activation: the treatment prompt is byte-identical to control and the skill is attached through the API (`skills: [{"id": "code-discipline"}]`). After the run, `export_checks.py` marks a treatment run valid only if the skill text is demonstrably in the session. It marks a control run invalid if any skill sentinel text, skill-tool call or attachment appears.
- Only allowlisted files enter a workspace: no `.git`, no hidden tests, no references, no results from other runs. Run roots are deleted after capture.
- Agents can reach the internet through the shell, so the public skill text and this public specification can be fetched. Control transcripts are scanned for skill text; contamination is detected after the fact, not prevented.

## 5. Tasks and prompts

`tasks/<ID>/project/TASK.md` is the exact prompt text, identical for every condition. The full final prompts are in those files; their hashes are pinned by `PreregisteredInputsTests`.

| Task | Prompt SHA-256 | Workspace SHA-256 | Hidden checks | Baseline tests |
|---|---|---|---|---|
| NEW-01 webhook idempotency | `c6450149…0c9875c` | `48a00817…2da3287` | 13 | 3 |
| NEW-02 concurrent reservations | `9c4bde14…a727a543f` | `cf0fea1a…2b2d2ed5` | 12 | 4 |
| NEW-03 CSV import | `a5764db4…3a042f649b` | `4fd45747…ab4740c4` | 16 | 4 |

Changes made in v3, and why:

- **Solution hints removed.** The sentence "a lock that exists only inside one Python process does not satisfy this requirement" was removed from NEW-01 and NEW-02. NEW-02's "value read inside the same transaction" became "the stock level the decision was based on". NEW-03's "Python's `csv` module with `strict=True` implements exactly these rules" was removed. Each of these told the agent the key engineering decision. The behaviour they imply is still stated as a requirement (separate processes, one database file, never oversell), so the task is not easier and the hidden checks are unchanged.
- **Interface references removed.** `opencode.jsonc` is no longer named. Constraints now read "change only X; you may add new test files under `tests/additive/`; do not modify any other file".
- **Kept explicit** because the hidden checks test them and an agent could not infer them otherwise: recording the event in `processed_events`, no open transaction left on the connection, the order in which errors are reported, the reservation ID format, and the full NEW-03 import contract.
- **Not weakened.** No requirement was dropped and no hidden check was changed.

Every hidden check traces to a stated requirement (private key, "Hidden-check map"). Baseline tests pass on the original defective code, so the original code is genuinely broken but not trivially so. Each reference solution passes all hidden and baseline checks. Eleven plausible wrong solutions are each caught: autocommit check-then-insert; read-then-write in a deferred transaction; swallowed failures; `with conn:` on an autocommit connection; deferred check-then-act; per-line atomic updates without a transaction; `bool` accepted as a quantity; `csv.Sniffer`; record-index line numbers; no BOM stripping; and the `csv` module without `strict`. Hard-coding cannot pass: hidden inputs differ from every visible example. Known limitations of the oracles are listed in the private key.

## 6. Scoring

### 6.1 Evaluation validity (`score_run.py`)

- **The inventory is defined without candidate code.** `score_run.py inventory` lists the exact hidden and baseline test IDs from the pristine project plus the hidden tests, and records the SHA-256 of every hidden file. Inventories live in the private pack, and `check_oracles.py` verifies that they still match.
- **The evaluator is checked first.** The hidden files must match the inventory hashes, and the pristine project must list exactly the inventoried tests with no load errors. Only then does candidate code run.
- **One process per test.** The runner reads a random nonce before any project code is imported and writes `{nonce, requested_id, tests_run, outcome, detail}`.
- **INVALID evaluation (no score produced, exit 3)** in any of these cases: hidden files differ from the inventory; a test is missing, unexpected, duplicated or fails to load in the pristine canary run; the result file is missing (crash, `os._exit`), malformed, has extra fields or files, carries the wrong nonce or test ID, or reports other than one executed test; a check was skipped; the runner exited non-zero after writing its result; any evaluator exception.
- **VALID failure of a check:** the test fails, errors, times out, or cannot import the candidate's code (for example a syntax error). An evaluation where every check fails is a valid zero, which is different from an invalid evaluation.
- **What is scored:** the pristine project plus only the task's mutable file and `tests/additive/` from the agent result. Agent-written tests are run and reported, but never scored and never able to invalidate an evaluation.
- **Candidate code never runs unsandboxed.** `--sandbox none` is refused unless `--trusted-code` is given; that flag is for reference solutions, mutants and synthetic tests only.

### 6.2 Outcomes and aggregation (`analyze.py`)

- **Primary:** `hidden_pass_fraction`, and `fully_correct` (every hidden and every baseline check passes). Both come only from valid evaluations.
- **Secondary, reported separately:** blind-scorer ratings (0–4) for request compliance, evidence and verification, scope and economy, and clarity, plus overclaim and critical-failure counts. Correctness is no longer a scorer dimension. Secondary scores are never added to the primary outcome or allowed to offset it, so excellent documentation cannot compensate for failing code. A test proves this.
- **Slot accounting:** every scheduled slot must resolve to exactly one valid run with a valid evaluation. Missing runs, invalid runs, and missing or invalid evaluations are listed, the report is labelled INCOMPLETE, and the exit code is 3 unless `--allow-incomplete` is given. Two valid runs in one slot, duplicate IDs, or a task mismatch are errors.
- **Reruns:** at most one per slot, only for pre-registered infrastructure causes (gateway error before the first tool call, launcher or server crash, host stop, harness-caused activation failure), decided by a human and recorded with its reason. Wrong code, timeouts and false claims are outcomes, never rerun.
- **Effects:** treatment minus control per (model, task), their mean per model, and an exact permutation p-value within model. The p-value is descriptive only.
- **Blind scoring:** the packets hide the condition and run identity. The hidden results are shown as fact. If a run's code is flagged for tamper review, the scorer must record a verdict.

## 7. Security assessment (scoring)

The boundary is a fresh Docker container per test with `--network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 --pids-limit 256 --memory 1g`, no host environment, the code mounted read-only at `/work`, and only an empty `/out` writable. The image must be pinned by digest. Scoring logic, inventories, the scoring key and other runs' data stay with the host-side `score_run.py`.

| Candidate code during scoring | Can it? | Basis |
|---|---|---|
| Reach the network or exfiltrate | No | `--network none`; probed by `test_sandbox.py` |
| Modify hidden tests, the runner or its own code | No | read-only mount; probed |
| Read scoring logic, inventories, scoring key, other runs, host secrets | No | not mounted; host environment not passed; probed |
| Persist anything to a later test or run | No | container removed after each test; fresh `/out` per test |
| Read the hidden test source of the task being scored | **Yes** | In-process unit tests must import alongside the code they test. This cannot feed back into the agent's work: the agent session has ended, and there is no network or persistence |
| Forge its own result in-process (for example by monkeypatching `unittest`, or reading the nonce from memory) | **Yes, detectable only** | Naive forging (no nonce, wrong ID, crash, extra files) is rejected by tests. Deliberate in-process tampering cannot be prevented. The code is scanned for constructs a solution has no reason to use (`unittest`, `sys.modules`, `os._exit`, `inspect`, `gc`, `subprocess`, `socket`, …); a match forces a human tamper review of the diff, which is small (one file) |

**Status: NOT DEMONSTRATED.** The isolation tests were skipped on the operator PC (no Docker, no WSL). `score-all.sh` refuses to score unless `test_sandbox.py` passes, with no skips, on the scoring host. Until then, hidden evaluation of real agent output is **NOT READY**. Directory permissions alone are not relied on.

## 8. Interpretation

The smoke test answers only one question: does the workflow produce valid, interpretable runs? The 36-run pilot is exploratory. With 3 runs per cell, only large and consistent differences can be told apart from sampling noise, and ceiling effects are possible: a strong model may pass everything without the skill. If the result is "no measurable difference", report exactly that. Permitted language: "In this pilot, on these tasks, with model M through OpenCode V, treatment runs passed X% of hidden checks versus Y% for control." Do not claim significance or general improvement.

## 9. Live execution

No Claude or Grok run was executed for v3. This environment has no xAI provider, no isolated Claude access (the only Claude access is the operator's own agent session, which carries global skills and instructions and would contaminate a control run), no Docker and no Linux host. Running the smoke test needs the user to provide a host and keys. The procedure and copy-paste commands are in [PROMPT-SMOKE-TEST.md](PROMPT-SMOKE-TEST.md).

## 10. Readiness

**NOT READY.** No known defect remains in the scoring code. The blockers are that nothing on the execution path has been demonstrated:

| # | Blocker | Resolved by |
|---|---|---|
| B1 | Docker isolation not demonstrated | `test_sandbox.py` passing with no skips on the scoring host, or in CI once the branch is pushed (needs approval) |
| B2 | Launcher never executed against OpenCode, Claude or Grok | Host, OpenCode install, SMOKE-task runs per model (runtime gates in PROMPT-SMOKE-TEST.md) |
| B3 | No model access | The user supplies spend-capped Anthropic and xAI keys and the exact model IDs and variants |
| B4 | Smoke test not run or reviewed | The four-run 2×2 on NEW-02, reviewed before the pilot is approved |
