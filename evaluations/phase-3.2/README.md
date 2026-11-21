# Phase 3.2 — Does `code-discipline` make Claude and Grok build better working software?

A controlled comparison of the same coding agent with and without the `code-discipline` skill, run separately for Claude and for Grok, on three synthetic tasks. The primary outcome is objective: hidden tests run against the code each agent leaves behind.

**Status (corrected 2026-11-21, after CI on `3d522f5`): smoke test CONDITIONALLY READY (needs a Linux VM and an Anthropic key; Grok BLOCKED until the user's xAI configuration, an `XAI_API_KEY`, is confirmed and the user confirms the candidate `xai/grok-4.7#medium`); pilot NOT READY.** Until this correction the line read "needs ... the v3.2 fixes committed with CI green"; that condition is now met. The scoring code is tested locally and in CI, including the Docker scoring sandbox (synthetic probes). The harness's API calls were checked against the real OpenCode 2.3.2 server without sending a prompt (v3.2). The run launcher has **not** been executed on Linux, no live model run has happened, and no model has produced code for any task. See [SPECIFICATION.md §1 and §10](SPECIFICATION.md#1-status).

| Item | State on 2026-11-21 |
|---|---|
| v3.2 implementation | Committed as `3d522f5` and pushed to `phase-3/benchmark-foundation` (PR #1, open, not merged) |
| GitHub Actions on `3d522f5` | Passed: run 44892816556 (push, #22) and run 44892821220 (PR #1, #23); both jobs, `structural-and-fixture-checks` and `phase-3-2-scoring-sandbox`, succeeded. CI runs offline unit tests, structural checks and synthetic Docker-sandbox probes only. It does not install or start OpenCode, does not run the launcher and sends no model request, so it is **not** evidence that the Linux launcher works or that the benchmark is ready to run |
| Documentation correction | Commit `13c91f808ec8e62a065139b7f2a37ea95548ac2c` (`13c91f8`, parent `3d522f5`) changed eight Markdown files and nothing else. An earlier report gave this SHA with an extra `8` (`13c91f88…`, 41 characters); that value is not a commit |
| GitHub Actions on `13c91f8` | Passed: run 44894181211 (push, #24) and run 44894185206 (PR #1, #25); both jobs succeeded. The workflow has no documentation-only mode: these runs repeated the full suite of #22/#23 on an implementation identical to `3d522f5`, so they confirm only that the documentation commit broke no check and add no evidence about the launcher or the benchmark. Later Markdown-only commits are shown in the PR's checks, not here |
| OpenCode 2.3.2 compatibility | Checked locally on the operator PC (Windows): the harness's HTTP calls against a real 2.3.2 server, no prompt sent ([SPECIFICATION.md §4](SPECIFICATION.md#4-contamination-controls-agent-runs), V31) |
| Linux launcher, end to end | **Not verified** (outstanding) |
| Four-run smoke test | **Not executed** |
| 36-run pilot | **NOT READY** |
| Grok | **BLOCKED** until the user's xAI configuration (`XAI_API_KEY`) is confirmed and the user confirms the model |
| Benchmark model runs | **None** have taken place |

| File | Purpose |
|---|---|
| [SPECIFICATION.md](SPECIFICATION.md) | Specification v3.2 (normative): design, interface, contamination controls, scoring, security, readiness |
| [PROMPT-SMOKE-TEST.md](PROMPT-SMOKE-TEST.md) | Procedure for the 2 models × 2 conditions smoke test: exactly four agent runs (not yet run) |
| [VALIDATION-CHECKLIST.md](VALIDATION-CHECKLIST.md) | Each requirement and how it was verified, or that it was not |
| [RISK-REGISTER.md](RISK-REGISTER.md) | Remaining risks |
| [CHANGE-REPORT.md](CHANGE-REPORT.md) | What changed from v2 (and in v3.1, v3.2) and why |
| `allowlist.json` | The only files that may enter an agent workspace |
| `tasks/NEW-01..03/project/` | Task projects; `TASK.md` is the exact prompt text |
| `harness/` | Launcher (OpenCode), fail-closed scoring, blind packets, analysis |
| `tests/` | `test_harness.py`, `test_scoring.py` (offline); `test_sandbox.py` (needs Docker) |

Hidden tests, reference solutions, mutants, test inventories and the scoring key are deliberately **not** in this repository.

Local verification (no network, no model):

```sh
python evaluations/phase-3.2/harness/manifest.py check-sources --phase-root evaluations/phase-3.2
python -m unittest discover -s evaluations/phase-3.2/tests -p "test_harness.py" -v
python -m unittest discover -s evaluations/phase-3.2/tests -p "test_scoring.py" -v
AQD_SANDBOX_IMAGE=python:3.12-slim@sha256:... python -m unittest discover -s evaluations/phase-3.2/tests -p "test_sandbox.py" -v   # Linux + Docker
```
