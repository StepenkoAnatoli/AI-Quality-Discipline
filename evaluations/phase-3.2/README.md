# Phase 3.2 — OpenCode pilot for `code-discipline`

Controlled, exploratory pilot: does the `code-discipline` skill change OpenCode outcomes on three synthetic coding tasks? 18 runs: 3 tasks × 3 repetitions × {control, treatment}.

**Status: specification and preparation only. Nothing here has been executed.** Readiness: *conditionally ready — blockers remain* (see [SPECIFICATION.md §21](SPECIFICATION.md#21-readiness)).

| File | Purpose |
|---|---|
| [SPECIFICATION.md](SPECIFICATION.md) | Final Specification v2 (normative) |
| [VALIDATION-CHECKLIST.md](VALIDATION-CHECKLIST.md) | Every critical requirement with its verification status |
| [RISK-REGISTER.md](RISK-REGISTER.md) | Remaining risks and mitigations |
| [CHANGE-REPORT.md](CHANGE-REPORT.md) | What changed from the earlier drafts, and every file touched |
| `allowlist.json` | The only files that may enter an agent workspace |
| `config/` | OpenCode project and global configuration (identical for both groups) |
| `tasks/NEW-01..03/project/` | Synthetic task projects; `TASK.md` is the exact prompt text |
| `tasks/SMOKE/project/` | Never-scored task for runtime gate checks |
| `harness/` | Setup, preflight, launcher, driver, checks, scoring, blinding, analysis, teardown |
| `tests/test_harness.py` | Local tests; no OpenCode, no network |

Hidden tests, reference solutions and the NEW-task scoring key are deliberately **not** in this repository (SPECIFICATION.md §13.4).

Local verification:

```sh
python evaluations/phase-3.2/harness/manifest.py check-sources --phase-root evaluations/phase-3.2
python -m unittest discover -s evaluations/phase-3.2/tests -v
```
