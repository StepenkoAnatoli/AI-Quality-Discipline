# Phase 3.2 — Does `code-discipline` make Claude and Grok build better working software?

A controlled comparison of the same coding agent with and without the `code-discipline` skill, run separately for Claude and for Grok, on three synthetic tasks. The primary outcome is objective: hidden tests run against the code each agent leaves behind.

**Status: NOT READY for a pilot.** The scoring code has been corrected and tested offline. The scoring sandbox, the run launcher and every live model run have **not** been executed. See [SPECIFICATION.md §1 and §10](SPECIFICATION.md#1-status).

| File | Purpose |
|---|---|
| [SPECIFICATION.md](SPECIFICATION.md) | Specification v3 (normative): design, interface, contamination controls, scoring, security, readiness |
| [PROMPT-SMOKE-TEST.md](PROMPT-SMOKE-TEST.md) | Procedure for the 2 models × 2 conditions smoke test (not yet run) |
| [VALIDATION-CHECKLIST.md](VALIDATION-CHECKLIST.md) | Each requirement and how it was verified, or that it was not |
| [RISK-REGISTER.md](RISK-REGISTER.md) | Remaining risks |
| [CHANGE-REPORT.md](CHANGE-REPORT.md) | What changed from v2 and why |
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
