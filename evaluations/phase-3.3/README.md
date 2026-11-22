# Phase 3.3 — difficulty-aware evaluation of `code-discipline` (draft)

**Status 2026-11-22: DRAFT design. Nothing frozen, no task built, no run, no spend approved.** Phase 3.2 (`../phase-3.2/`) and its four ceiling A/B results stay as historical records, unchanged.

| File | Purpose |
|---|---|
| [AUDIT-2026-11-22.md](AUDIT-2026-11-22.md) | Verified state of Phase 3, contradicted documentation, why the four tasks hit the ceiling, evaluator gaps, risks |
| [DESIGN.md](DESIGN.md) | Proposed design: hypotheses, rubric, 18-task portfolio, stages and stop rules, precision, metrics, thresholds, analysis, budget |
| `difficulty-rubric.json` | Eight-factor difficulty rubric (0–3 anchors, equal weights, tier cut-points), machine-checked |
| `ratings-historical.json` | **Post-hoc**, single-rater ratings of NEW-01..04 (all rate medium). Historical description only |
| `analysis-plan-historical.json` | Draft plan pinning the rubric and ratings by SHA-256, for an exploratory tier report of the Phase 3.2 data |
| `power_sim.py` | Precision and power of the task-level analysis under stated assumptions |

The analysis code lives with the existing harness, so there is one evaluator and one analysis entry point:

```sh
python evaluations/phase-3.2/harness/analyze.py --schedule S --captures C --scores D --out R.json \
    --difficulty-plan evaluations/phase-3.3/analysis-plan-historical.json
python -m unittest discover -s evaluations/phase-3.2/tests -p "test_difficulty.py" -v
python evaluations/phase-3.3/power_sim.py
```

Changing the rubric or a ratings file changes its SHA-256, and the plan then refuses to load until the pin is updated deliberately.
