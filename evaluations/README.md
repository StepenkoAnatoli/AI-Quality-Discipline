# Evaluations

This directory contains reproducible, skill-specific evaluations. A benchmark result is evidence about a defined task set, model, agent surface, and configuration—not a universal claim about AI quality.

## Structure

- `protocol.md` — controlled with/without procedure and reporting requirements.
- `shared-rubric.md` — common scoring framework and domain-specific adjustments.
- `pilot/tasks.md` — initial 12-task pilot (three tasks per skill).
- `pilot/scoring-key.md` — evaluator-only expected outcomes and failure indicators.
- `fixtures/` — synthetic task inputs and baseline checks.
- `run-record-template.json` — per-run metadata and blinded scoring record.
- `results/` — raw run records and analyzed results.
- `phase-3.2/` — specification, synthetic tasks (NEW-01/02/03) and harness for the 18-run OpenCode with/without `code-discipline` pilot. Specification and preparation only; nothing has been run. Start with `phase-3.2/README.md`.

## Pilot status

The pilot is a benchmark-design and calibration exercise. It is deliberately not large enough to justify keeping, removing, or claiming the effectiveness of a skill. See `fixtures/RUNNING.md` before preparing any scored run. The target full evaluation remains 10 tasks per skill, with three runs per condition where practical.

Do not publish a skill win from the pilot alone. First validate task difficulty, scoring consistency, and whether the rubric distinguishes competent baseline behavior from skill-assisted behavior.
