# Phase 3.3 — difficulty-aware evaluation of `code-discipline` (draft)

**Status 2026-11-22: DRAFT design. Nothing frozen, no task built, no run, no spend approved.** Phase 3.2 (`../phase-3.2/`) and its four ceiling A/B results stay as historical records, unchanged.

| File | Purpose |
|---|---|
| [AUDIT-2026-11-22.md](AUDIT-2026-11-22.md) | Verified state of Phase 3, contradicted documentation, why the four tasks hit the ceiling, evaluator gaps, risks |
| [DESIGN.md](DESIGN.md) | Proposed design: hypotheses, rubric, 18-task portfolio, stages and stop rules, precision, metrics, thresholds, analysis, budget |
| `difficulty-rubric.json` | Eight-factor difficulty rubric v1.1 (0–3 anchors, equal weights), machine-checked. Two axes: seven intrinsic factors set the tier; F6 (requirement discovery) is a separate level |
| `ratings-historical.json` | **Post-hoc, exploratory**, single-rater ratings of NEW-01..04 (NEW-01..03 medium, NEW-04 hard; all "specified"). Historical description only |
| `analysis-plan-historical.json` | Draft plan pinning the rubric and ratings by SHA-256, for an exploratory tier report of the Phase 3.2 data |
| [RESULTS-RETENTION.md](RESULTS-RETENTION.md), `patches/main-phase3-ab-run-retention.patch` | The public results record, the archive procedure and the 90-day retention change for the workflow on `main` (prepared, not applied) |
| `power_sim.py` | Operating characteristics of the real decision code (all guards, two tiers, interaction) under several variance assumptions; the share sweep behind `min_discriminating_share`; the stop-rule table |
| `sim-output-2026-11-22.txt` | Output of the four `power_sim.py` reports quoted in DESIGN.md §6–§7 |
| `stress_decisions.py`, `stress-output-2026-11-22.txt` | Stress tests of the decision rules: null identification, robustness of the 0.45 threshold beyond its grid, and how far simulated power moves under invalid slots, ceiling share and skew (DESIGN.md §6–§7) |

The analysis code lives with the existing harness, so there is one evaluator and one analysis entry point:

```sh
python evaluations/phase-3.2/harness/analyze.py --schedule S --captures C --scores D --out R.json \
    --difficulty-plan evaluations/phase-3.3/analysis-plan-historical.json
python -m unittest discover -s evaluations/phase-3.2/tests -p "test_difficulty.py" -v
python evaluations/phase-3.3/power_sim.py designs      # also: share-sweep, scale, stop-rule
python evaluations/phase-3.2/harness/schedule.py create --counterbalance ...   # Phase 3.3 schedules
```

Changing the rubric or a ratings file changes its SHA-256, and the plan then refuses to load until the pin is updated deliberately.
