# Phase 3.2: code-discipline A/B results, first four tasks (2026-11-21 to 2026-11-22)

**Status: complete. No measurable effect on correctness.** On all four tasks, the run with the skill and the run without it scored the maximum on the hidden checks. This is a ceiling result from one run per arm. It is not evidence that the skill has no effect.

## Design (as run)

- **Model and interface:** `anthropic/claude-opus-5-5#medium` in both arms, through OpenCode 2.3.2 (`build` agent). The prompt text is identical in both arms.
- **Arms:**
  - The control run has no skill installed and nothing names it.
  - The treatment run gets the canonical `skills/code-discipline/SKILL.md` (SHA-256 `d050d00f…`) attached to the prompt.
- **Workflow:** `.github/workflows/phase3-ab-run.yml`. Each task got one control run and one treatment run, in an order drawn at random and sealed before the runs. There were no reruns. Agents could reach only the Anthropic API.
- **Validity before scoring:** each run was checked first: same model and settings, the skill confirmed only in the treatment session, no provider errors, and workspace integrity. The classification of both runs was recorded before any score was opened.
- **Scoring:** hidden tests and evaluator material reached the runner only after both runs. Each check ran in its own process inside a Docker sandbox with no network. Results were stored only as an encrypted artifact.

## Results

| Task | A/B workflow run | Order | Validity | Control | Treatment | Cost (C / T) |
|---|---|---|---|---|---|---|
| NEW-02 concurrent inventory reservations | 44935143378 | treatment, control | both valid | 12/12 | 12/12 | $0.32 / $0.36 |
| NEW-01 duplicate webhook processing | 44960610733 | treatment, control | both valid | 13/13 | 13/13 | $0.25 / $0.32 |
| NEW-03 CSV import compatibility | 44963571385 | treatment, control | both valid | 16/16 | 16/16 | $0.32 / $0.44 |
| NEW-04 job queue leases (added for this phase) | 44980786824 | treatment, control | both valid | 20/20 * | 20/20 * | $0.53 / $0.68 |

\* As first scored, NEW-04 gave 17/20 in both arms because of an evaluator defect (below). The corrected scores come from a separate re-score of the same, unmodified solutions (run 45017324306). Both the original and the corrected scores are kept.

- **Regressions:** none. Every baseline test passed in all eight runs.
- **Total model spend:** about $3.50, including one invalid run. Figures are OpenCode's per-session costs.

### Dispatches that produced no comparison

- **44929041215:** the API-key secret had extra characters, so the run stopped at the input check. No model request was sent.
- **44931846478:** the runner image's own sudoers file failed `visudo -c`, so the run stopped at host setup. No model request was sent. Fixed on main (`e31f4c9`).
- **44932163011 (NEW-02):** the control run was invalid. The project's `opencode.jsonc` named the skill in a permission rule, and the control agent tried to load it; the load failed and no skill text was received. The treatment run never started. Fixed in `8827a27`: the config no longer names the skill.

### NEW-04 evaluator defect and fix

- **Defect:** the three concurrency checks gave the solution a connection wrapper that was not a `sqlite3.Connection`. Both agents checked the connection type, which the task contract allows, so every concurrent worker was rejected before any race was exercised.
- **Fix:** the corrected checks build the slowed connection through the project's own `db.connect` as a real `sqlite3.Connection`. They were validated with a correct solution that checks the type (which reproduces the defect under the old checks), with deliberately racy solutions, and with evidence that 8 workers really compete.
- **Linux validation:** the corrected checks were validated on Linux in the same job that re-scored the two stored solutions.

## Secondary observations (one run per arm; not attributable to the skill)

| Task | Own tests (C / T) | Tool calls (C / T) | Lines in changed file (C / T) |
|---|---|---|---|
| NEW-02 | 9 / 10 | 8 / 7 | 123 / 125 |
| NEW-01 | 8 / 10 | 7 / 9 | 84 / 69 |
| NEW-03 | 30 / 37 | 6 / 9 | 218 / 208 |
| NEW-04 | 14 / 18 | 6 / 10 | 337 / 331 |

- On every task the treatment run wrote more tests, and it cost 13–36% more.
- On NEW-01 it also checked that its tests fail against a naive implementation.
- In each pair, both runs chose the same design.
- One treatment solution (NEW-02) was flagged for manual review because it used `getattr`. On inspection it was benign: it reads an SQLite error code.

## Conclusion

On these four tasks, Claude Opus 5.5 at medium effort produced fully correct code with and without code-discipline. The benchmark therefore cannot show an effect at this difficulty with one run per arm.

Measuring a real effect would need tasks where the model without the skill demonstrably makes mistakes, and several runs per arm.

## Not published

Hidden tests, reference solutions, deliberately flawed solutions, transcripts and the agents' code are kept private and encrypted. Publishing them would compromise the benchmark.
