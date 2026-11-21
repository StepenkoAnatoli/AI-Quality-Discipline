# Phase 3.2 — Change report v3 (2026-11-21)

Base: `3ec3b32` (specification v2, Nemotron/OpenCode gateway pilot). The v2 documents are in git history.

## Why

v2 was a benchmark *infrastructure* for one model that is now out of scope. An independent audit and the inventory below found that its evaluator could fail open: it could report a score when no tests ran. Candidate code could also influence scoring, and correctness was blended into a rubric that documentation quality could offset. The prompts also gave away key solution choices.

## Inventory of v2 (inspected from the files, not from earlier reports)

| | Findings |
|---|---|
| Correct, preserved | Tasks and planted defects; hidden oracles (41 checks; references pass, mutants killed); allowlist and JSON manifests; per-condition OS users and fresh HOME per run; API skill attachment with byte-identical prompts; activation and contamination checks on exported sessions; blind packets with redaction |
| Broken | `score_run.py`: `hidden_total` = number of tests *discovered*, so 0 discovered gave 0/0 with exit 0; load errors and skips still produced a score; result files were trusted without validation; candidate code ran as the same OS user as the scoring logic, with network access, and could rewrite result files. `analyze.py`: missing runs and missing or invalid scores were silently dropped; two valid runs in one slot were double-counted; the correctness dimension (30 %) could be offset by documentation dimensions |
| Unnecessary complexity | Gates for the reasoning variant of a free model; Codespaces billing gates made mandatory; a separate `aqd-eval` scoring user (replaced by the sandbox) |
| Missing | A model factor (Claude vs. Grok, analysed separately); a run record with model, interface, prompt and workspace hashes; any isolation for scoring; a smoke-test procedure using the real prompts |

## Changed files

| File | Change |
|---|---|
| `harness/run_checks.py` | Runs exactly one test per process. Reads a nonce before importing project code, imports the test module itself so an import failure is recorded as a candidate failure, and treats skips, expected failures and unexpected successes as non-passes |
| `harness/score_run.py` | Rewritten to fail closed: `inventory` and `score` subcommands; hidden-file hashes; pristine canary listing; per-result validation; VALID/INVALID with exit codes 0 and 3; Docker sandbox runner; refuses unsandboxed candidate code; tamper-pattern review flags; primary outcome block |
| `harness/analyze.py` | Rewritten: slot accounting, INCOMPLETE status and exit 3, duplicate-run and task-mismatch errors, primary outcomes only from valid evaluations, secondary dimensions separate (no correctness), effects within model |
| `harness/schedule.py` | Model is a design factor (`--models`, `--tasks`, `--repetitions`); blocks pair control and treatment of one model and task; providers limited to `anthropic` and `xai` |
| `harness/aqd_common.py` | Nemotron constants removed; `parse_model()` |
| `harness/api_checks.py`, `export_checks.py`, `drive_session.py` | Model and variant taken from the run; observed models recorded; variant optional |
| `harness/manifest.py` | Stable `workspace_sha256` |
| `harness/blind_packet.py` | Shows an invalid evaluation as such; no correctness dimension; tamper-review field |
| `harness/lib.sh`, `launch-run.sh`, `preflight.sh`, `setup-host.sh`, `run-all.sh`, `run_status.py`, `teardown.sh` | Model from the schedule; per-provider key from an operator-only file; `run-record.json`; billing gate only on Codespaces; catalog probe per scheduled model; stale references fixed. **Not executed** |
| `harness/score-all.sh` | Scoring logic stays with the operator; tests run in the Docker sandbox; refuses to score unless `test_sandbox.py` passes with no skips; invalid evaluations are recorded, not dropped |
| `tasks/NEW-01/02/03/project/TASK.md` | Solution hints and interface references removed (SPECIFICATION.md §5); requirements unchanged |
| `tests/test_scoring.py` (new) | 30 adversarial and fail-closed tests |
| `tests/test_sandbox.py` (new) | Docker isolation probes; skip = NOT DEMONSTRATED |
| `tests/test_harness.py` | Updated for models; pinned prompt and workspace hashes; prompt leak check; analysis tests |
| `.gitattributes` | LF for task files and config, so hashes match on every platform |
| `.github/workflows/phase3-validation.yml` | Runs `test_scoring.py`; new sandbox job that fails on skips |
| `SPECIFICATION.md`, `README.md`, `PROMPT-SMOKE-TEST.md` (new), `VALIDATION-CHECKLIST.md`, `RISK-REGISTER.md`, this file | Rewritten for v3 |
| Repository `README.md`, `BRAIN.md`, `evaluations/README.md` | Stale Phase 3.2 statements corrected |

Private evaluator pack (outside the repository): inventories added; `check_oracles.py` uses inventories and sandbox-free *trusted* scoring and requires valid evaluations; two new mutants (`with_conn_autocommit`, `csv_not_strict`); scoring key updated.

## v3.1 corrections (2026-11-21, on top of `72fa194`; committed as `f0c857c`, CI green)

Problems, effects and corrections are listed in [SPECIFICATION.md §11](SPECIFICATION.md#11-v31-corrections-2026-11-21). Files:

| File | Change |
|---|---|
| `harness/score_run.py` | Missing agent result is INVALID; agent tests run in a separate tree; structural review scan; `review_subject_sha256`; symlinks never followed or chmod'ed; schema version 3 |
| `harness/analyze.py` | Review gating; five slot statuses with per-model/condition counts; hidden-score consistency check; run-record consistency across conditions; stray-directory and blind-id checks; JSON errors are analysis errors |
| `harness/blind_packet.py` | Score template carries `tamper_review_subject`; scorer may flag tampering without a scan flag; task text path fixed |
| `harness/run_status.py` | Run record must be complete and match the run; malformed capture files invalidate instead of crashing |
| `harness/launch-run.sh` | No `runtime-gates.json`; optional SMOKE task needs `AQD_EXTRA_MODEL_CALL_APPROVED=yes`; pilot needs `pilot-approved.json`; refuses to start with evaluator material on the host; extended run record |
| `harness/preflight.sh` | Final message no longer refers to separate gate runs |
| `tests/test_scoring.py`, `tests/test_harness.py` | Tests for every correction (most fail on the v3 code) |
| `PROMPT-SMOKE-TEST.md` | Four agent runs and nothing else; verified Claude reference; Grok BLOCKED |
| `SPECIFICATION.md`, `README.md`, `VALIDATION-CHECKLIST.md`, `RISK-REGISTER.md`, this file | Updated for v3.1 |

## v3.2 corrections (2026-11-21, on top of `f0c857c`; committed as `3d522f5`, CI green)

*Status correction, 2026-11-21:* this heading read "not yet committed" when the section was written. v3.2 was then committed as `3d522f5` and pushed, and CI passed on it (runs 44892816556 and 44892821220, both jobs). CI covers the offline tests and synthetic sandbox probes only. The Linux launcher is still unverified, the smoke test has not been executed, and the pilot is not ready ([SPECIFICATION.md §1](SPECIFICATION.md#1-status)).

Problems, effects and corrections are listed in [SPECIFICATION.md §12](SPECIFICATION.md#12-v32-corrections-2026-11-21). Found by checking the harness against the real OpenCode 2.3.2 server without sending a prompt. Files:

| File | Change |
|---|---|
| `harness/lib.sh` | `opencode_version`: reads X.Y.Z from `opencode v2.3.2` |
| `harness/install-opencode.sh`, `preflight.sh`, `launch-run.sh` | Use `opencode_version` (the verbatim comparison failed on every host) |
| `harness/api_checks.py` | Built-in `skill://` skills of the pinned binary are recorded, not treated as leaks; a built-in that is or contains `code-discipline` still fails |
| `harness/run_status.py` | A session that ends on a provider/API error is invalid; the run record must name `opencode X.Y.Z` |
| `tests/test_harness.py` | Tests for each correction (all fail on `f0c857c`) |
| `PROMPT-SMOKE-TEST.md` | Host packages and docker group; `models --standalone` with a throwaway HOME; Grok candidate from the 2.3.2 catalog; provider-error rule in G4 |
| `SPECIFICATION.md`, `README.md`, `VALIDATION-CHECKLIST.md`, `RISK-REGISTER.md`, this file | Stale commit/CI statements corrected; skill hash corrected to the LF file; probe results; v3.2 |
