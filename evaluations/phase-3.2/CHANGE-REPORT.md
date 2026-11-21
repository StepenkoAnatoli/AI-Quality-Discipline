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
