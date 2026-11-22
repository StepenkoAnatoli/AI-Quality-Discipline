# Phase 3.3: does the benefit of `code-discipline` change with task difficulty? (design draft)

**Status (2026-11-22): DRAFT, not ratified, nothing frozen, no runs, no spend approved.** This design supplements Phase 3.2; it does not replace its results or its harness. The four Phase 3.2 tasks (NEW-01..04) and their A/B results stay as historical records in `evaluations/phase-3.2/`, unchanged. The 36-run Phase 3.2 pilot (2 models × 3 tasks × 3 repetitions × 2 conditions, SPECIFICATION.md §2) was never run. The four 2-run A/Bs on Claude replaced it in practice. This design supersedes the pilot for Claude; a Grok cell would reuse this design once Grok is unblocked (SPECIFICATION.md C4).

Implemented offline in this change: the difficulty rubric (`difficulty-rubric.json`), post-hoc ratings of the historical tasks (`ratings-historical.json`), the task-level tier analysis (`../phase-3.2/harness/difficulty.py`, reached through `analyze.py --difficulty-plan`), its tests (`../phase-3.2/tests/test_difficulty.py`), and the power simulation (`power_sim.py`). Everything else below is a proposal.

## 1. Question, hypotheses and estimands

For one model M, interface version V and frozen skill S (`skills/code-discipline/SKILL.md`, SHA-256 `d050d00f…7ebc842`):

- **Per-task effect** `d_t` = mean primary outcome of treatment runs − mean of control runs on task t.
- **Tier effect** `D_k` = mean of `d_t` over the tasks in tier k (equal task weight).
- **Interaction** `D_hard − D_easy` (and the other tier pairs).

Competing hypotheses, all tested by the same intervals:

| | Claim | Evidence that would support it |
|---|---|---|
| H1 | The skill prevents meaningful errors, more so on harder tasks | `D_hard` decision "benefit" and the interval for `D_hard − D_easy` above 0 |
| H0 | No useful effect | `D_k` intervals inside (−harm, +MID) in every tier with discriminating tasks |
| H2 | The skill harms (hesitation, over-process, scope suppression) | any tier decision "harm", or overhead or critical-regression limits exceeded |

A higher control error rate on hard tasks is **not** evidence for H1. Only treatment − control, and its change across tiers, is.

## 2. Why Phase 3.2 hit the ceiling

Section 3 of the audit report (`AUDIT-2026-11-22.md`) has the evidence. In short: the prompts are near-complete specifications (NEW-03 and NEW-04 enumerate 18 clauses each, including error precedence and tie-breaks). Each task changes one file. Every hidden check traces to a stated sentence. The NEW-04 "hard" task took both agent sessions together 6 min 45 s of a 45-min-per-run budget. With one run per arm and 4 tasks, a 100% vs 100% result cannot distinguish H0 from a small H1 or H2. Under the rubric below, all four historical tasks rate **medium**, and none is easy or hard.

## 3. Difficulty rubric

`difficulty-rubric.json` (machine-checked by `difficulty.py`). Eight factors, each scored 0–3 against written anchors, equal weight (composite 0–24):

| Factor | What is measured |
|---|---|
| F1 interacting requirements | requirements that constrain each other's implementation |
| F2 state space | persistent states and legal transitions, including legacy states |
| F3 cross-module | modules whose behaviour is load-bearing or that must change |
| F4 concurrency / failure | concurrent callers, partial failure, crash recovery, expiry |
| F5 compatibility | legacy data, formats, public interfaces, callers |
| F6 requirement discovery | share of obligations established by the repository rather than the prompt |
| F7 verification demand | how hard it is for the agent to establish correctness itself |
| F8 existing coverage (inverse) | how little the visible tests protect the regression surface |

Tiers: easy ≤ 7, medium 8–14, hard ≥ 15 **and** F6 ≥ 2. Below the gate a task is demoted to medium.

Not factors, on purpose: file count, lines of code, number of hidden checks, prompt length.

**Weights.** Equal, because no data exists to estimate weights, and any other choice would be tuned by hand. Reweighting is allowed only before the confirmatory set is rated, and only with the reason recorded.

**The F6 gate was informed by an observed outcome.** NEW-04 scores 15 on intrinsic complexity yet reached the ceiling in both arms, apparently because its prompt specified every obligation. That makes the gate a hypothesis: "a complete specification reduces hard engineering to translation". The calibration stage must test it (§6) before any confirmatory rating.

**F6 must not become hidden information.** For every hidden check the task author records where its obligation is established: a prompt sentence, or a repository artifact (`file:line` of code, a caller, a test, a document). An independent reviewer confirms each mapping before freezing. A check with no source is removed. This is the existing Phase 3.2 rule ("every hidden check traces to a stated requirement"), widened from the prompt to the repository.

**Validating the tiers.**

1. Two raters score each task independently, from the task repository and the private oracle map, before any model run on it and without seeing any model output. `difficulty.py` refuses a confirmatory task with fewer than two raters and reports agreement per factor, pooled over tasks (exact and within one point, `rating_agreement_by_factor`), plus the raw rater gaps per task. Agreement below 0.6 within one point on a factor means rewriting that factor's anchors, not averaging.
2. Feasibility: a competent engineer (not the rater) solves each task from the public material only, within the agent time budget, and the time is recorded. A task nobody solves within budget is dropped.
3. Manipulation check, calibration tasks only: control success should fall from easy to hard. This checks the rubric. It never selects confirmatory tasks.

## 4. Task portfolio

Eighteen tasks: six per tier. After all eighteen are built, oracle-validated, rated and frozen, a sealed random draw (seed recorded in advance, as in `schedule.py`) assigns two per tier to **calibration** and four per tier to **confirmatory**. The author therefore cannot steer hard tasks into either set, and calibration outcomes cannot select confirmatory tasks. If §6 recommends 6 confirmatory tasks per tier, build 8 per tier.

Public briefs only. The defect classes each oracle targets, the hidden checks and the reference solutions belong in the private pack, never here.

| ID | Tier (target) | Problem | Changes |
|---|---|---|---|
| E1 | easy | Pagination cursor skips or repeats an item at page boundaries | one function |
| E2 | easy | `Retry-After` parsing: seconds or HTTP-date, with a cap | one module |
| E3 | easy | Report date formatting mishandles timezone-aware inputs | one module |
| E4 | easy | Config: environment override for one typed setting | one module |
| E5 | easy | Unicode-safe slug generation that keeps existing slugs stable | one function |
| E6 | easy | CLI `--dry-run` for an existing command whose plumbing exists | one module |
| M1 | medium | HTTP client retries: idempotency-aware, backoff, respect server hints | client + caller |
| M2 | medium | Invoice rounding: line vs total rounding, compatible with stored invoices | two modules |
| M3 | medium | Add a column with backfill to an existing migration runner; re-runnable | migration + runner |
| M4 | medium | Read-through cache: TTL, negative caching, invalidation from two writers | cache + writers |
| M5 | medium | Config format v1 → v2 reader that keeps v1 files working | parser + loader |
| M6 | medium | Bulk import with per-row errors and a resumable checkpoint | importer + store |
| H1 | hard | Order placement across inventory, payment and outbox with compensation and restart recovery | several components |
| H2 | hard | Event-sourced account projection: snapshots, concurrent appends, optimistic concurrency | store + projector |
| H3 | hard | Append-only key-value file: crash-safe compaction and recovery from torn writes | storage engine |
| H4 | hard | Recurring scheduler: exactly-once firing across worker processes and DST changes | scheduler + worker |
| H5 | hard | Online schema change: dual-write and backfill while readers and writers run | data layer + migration |
| H6 | hard | Cross-process token-bucket rate limiter in SQLite with fairness under contention | limiter + callers |

Construction rules for every task:

- Python standard library. The public project is a small realistic repository with callers, docs and existing tests, not a single file with a numbered contract.
- The prompt states the goal, the constraints and the observable acceptance criteria. Obligations a competent engineer would learn by reading the code are not restated (F6). No algorithm hints, no test expectations.
- Hard and medium tasks may have several mutable files. `score_run.build_tree` and the allowlist already support several `mutable` entries; the scored set is the union.
- Oracle validation before freezing (stricter than Phase 3.2): the reference passes everything; **at least one alternative correct design** passes everything, which guards against over-strict checks (R09); at least three realistic wrong implementations per task are each caught; and no hidden check can be passed by hard-coding visible examples.
- The prompt wording is identical in both arms and never mentions verification, scope, tests or reporting beyond the Phase 3.2 closing sentence, so the prompt cannot do the skill's job.

## 5. Conditions and controls

Reused unchanged from Phase 3.2 (SPECIFICATION.md §2, §4, §6; `.github/workflows/phase3-ab-run.yml` on main): per-condition OS users, fresh HOME per run, skill only in treatment via API attachment with activation verified from the export, byte-identical prompts and workspaces, the same pinned model, variant, OpenCode version, tools and permissions, network limited to the provider API, a 45-minute limit, a sealed random order per block, hidden tests decoded only after both runs, Docker-sandboxed fail-closed scoring, at most one pre-registered infrastructure rerun per slot, and no rerun for wrong code.

Required harness changes. These are not implemented here, because they change the semantics of run validity, which must stay fixed for the historical Phase 3.2 records. Each needs its own version and tests:

1. **Scope violations become an outcome, not an exclusion.** Today an edit to any immutable file makes the run INVALID (`run_status.py`), so a scope violation leaves the comparison. That is backwards for a skill whose rules include scope control. In 3.3: a valid run with `scope_violation: true` is scored on its mutable files, and `strictly_correct = fully_correct ∧ ¬scope_violation` is reported next to `fully_correct`.
2. **Unexpected new files** (recorded today in `workspace_findings.unexpected` but never reported) become a secondary outcome.
3. **Results retention.** The Phase 3.2 encrypted artifacts have 1-day retention, so the evidence behind AB-RESULTS.md expires within a day of each run. In 3.3 the operator archives each encrypted bundle and records its SHA-256 next to the results, and a machine-readable per-run results file (scores, costs, validity, no code or transcripts) is committed with the report.

Already handled in analysis (this change): a run that crashes the scorer, times out every check, is tamper-flagged, or is otherwise non-valid is carried into worst/best-case bounds. A tier decision that depends on how those slots are treated is reported as inconclusive.

## 6. Stages, precision and gates

**Stage 0: offline, no spend.** Build the eighteen tasks; private oracle packs; oracle validation (§4); two-rater ratings; feasibility runs by an engineer; freeze; sealed calibration/confirmatory draw. Also add the three harness changes (§5) with tests.

**Stage 1: calibration (24 runs).** Two tasks per tier, two runs per arm. Purpose: feasibility, oracle sanity on real agent code, cost per tier, and the manipulation check. It is not evidence about the skill and is never pooled with Stage 2.

Stop rules after Stage 1, written before it runs:

- Calibration hard-task control success ≥ 0.9 (8 control runs on hard tasks): stop. The tasks are not hard for this model. Return to Stage 0 and do not spend on Stage 2.
- Any oracle rejects an agent solution that an independent reviewer judges correct: fix the oracle in a new version, re-score separately (both scores kept, as for NEW-04), and re-validate that task family.
- Any invalid-run rate above 10% from infrastructure: fix the harness before Stage 2.

**Stage 2: confirmatory.** Precision from `power_sim.py` (seed 20261122, 3000 simulations; control success varying widely across hard tasks, Beta(1.5, 1.5); MID 0.20). These are assumptions, not measurements. The simulation omits the ceiling, zero-spread and estimate ≥ MID guards, so its P(lower bound > 0) is an upper bound on the chance of a "benefit" decision:

| Tasks/tier × runs/arm | Runs/tier | 95% half-width | P(lower bound > 0), true +0.20 | true +0.40 |
|---|---|---|---|---|
| 4 × 3 (proposed) | 24 | ±0.50 | 0.06 | 0.19 |
| 6 × 2 | 24 | ±0.42 | 0.15 | 0.40 |
| 12 × 1 | 24 | ±0.37 | 0.17 | 0.51 |
| 8 × 3 | 48 | ±0.28 | 0.30 | 0.75 |

What this means:

- The proposed 72-run stage (4 tasks × 3 runs × 2 arms × 3 tiers) **cannot** detect a +20-point effect. Its chance of a positive lower bound is about the false-positive rate. Most outcomes will be "inconclusive", and the interaction interval will be wider still.
- At equal spend, more tasks with fewer repetitions is strictly more precise, because the inference unit is the task and repetitions only reduce noise inside a task.
- A decisive answer for one tier at ±0.15 needs roughly 25–30 tasks in that tier at 2 runs per arm. Building the tasks, not paying for model calls, is the binding constraint.

Recommendation: keep Stage 1 as proposed. Run Stage 2 as **6 tasks × 2 runs per tier (72 runs)**, pre-registered honestly as an *estimation* stage, expected to give intervals of about ±0.4 per tier. A decision-grade claim about hard tasks needs a later hard-only stage of 25+ tasks. Do not describe Stage 2 as powered.

## 7. Outcomes and thresholds (pre-registered when frozen)

Primary: `fully_correct` per run (every hidden and every baseline check passes; from a valid evaluation only), averaged per task then per tier. Secondary, never offsetting the primary:

- `hidden_pass_fraction` (already normalised per task; tasks weigh equally whatever their check count);
- baseline regressions; critical defects (data loss, overselling, duplicate side effects) by severity, from the private oracle map;
- `scope_violation` and unexpected files (after §5 changes);
- verification claimed vs performed: the claims in the final report checked against the commands actually executed in the export, counted as false or exaggerated completion claims;
- agent-written tests: do they fail on the pristine code and pass on the agent's code (relevance), and do they catch the private mutants (quality)? Count alone is never reported as quality;
- tool calls, tokens, wall time and monetary cost per run.

Thresholds (owner to ratify; values in the frozen plan):

| Threshold | Value | Justification |
|---|---|---|
| Minimum important difference (MID) | +0.20 in `fully_correct` | flips one run in five from failure to success. Below that, an instruction costing +13–36% per run (observed, AB-RESULTS.md) is hard to justify |
| Harm threshold | −0.10 | asymmetric on purpose: an always-on instruction should be shown not to hurt |
| Acceptable overhead | median per-task treatment/control cost ratio ≤ 1.5 and wall-time ratio ≤ 1.5 | above that, users pay for process, not results |
| Critical-regression limit | any critical defect class present in treatment and absent in control, on ≥ 2 tasks | flagged as H2 evidence whatever the means say |
| Confidence | 95% two-sided | |

## 8. Analysis

`analyze.py --difficulty-plan PLAN` (implemented). It consumes the existing fail-closed slot resolution, so nothing is re-scored:

- per task: arm means, `d_t`, non-valid slot counts, worst/best-case bounds;
- per tier: mean of `d_t` with a t-interval over tasks (df = tasks − 1);
- interaction: Welch intervals for every tier pair (df floored). It concludes `effect_larger_in_<tier>` or `effect_smaller_in_<tier>` only when the interval excludes 0 under valid runs **and** under both non-valid-slot bounds, and neither tier is at a ceiling or floor or missing a task. Otherwise it is inconclusive;
- missing tasks: every pre-registered inference task must have slots for every model. A frozen confirmatory plan with a missing task is an error. In an exploratory report the tier is inconclusive and the task is listed;
- decision per tier: **benefit** (lower bound > 0 and estimate ≥ MID), **harm** (upper bound < 0 and estimate ≤ −harm), **no_meaningful_effect** (interval inside (−harm, MID)), otherwise **inconclusive**. It is forced to inconclusive when the tier has fewer than two discriminating tasks (a task where every run in both arms is at the same extreme is at the ceiling or floor), when the task differences have zero spread (a degenerate interval), or when the decision changes under the non-valid-slot bounds;
- the report records the SHA-256 of the plan, the rubric and every ratings file;
- label "confirmatory" only for a frozen plan whose inference set is exactly the confirmatory set with prospective ratings, otherwise "exploratory".

Run on the historical Phase 3.2 tasks, this rule reports the medium tier as **inconclusive (ceiling)**. It does not report "no effect" (pinned by `test_ceiling_result_is_reported_as_inconclusive_not_as_no_effect`).

Planned sensitivity analysis, not implemented: a mixed-effects logistic model (task random intercept and random treatment slope, tier × condition fixed effects), fitted offline with a standard statistics package and reported next to, never instead of, the task-level analysis. The existing exact permutation p-value in `analyze.py` stays descriptive.

## 9. Freezing procedure

Before the first Stage 2 run, and recorded in one commit:

1. Rubric, ratings (two raters, `prospective`), task projects, prompts and the plan with `status: "frozen"` and `inference_sets: ["confirmatory"]`. The plan pins the rubric and every rating file by SHA-256, and `difficulty.py` refuses any mismatch.
2. Private: hidden tests, inventories, references, alternative designs, mutants and the oracle source map, with their hashes recorded in the private key.
3. Skill SHA-256, model ID and variant, OpenCode version, sandbox image digest.
4. Thresholds (§7), stop rules (§6) and the seeded schedule.

An evaluator defect found later is fixed in a new oracle version. Both scores are kept and the re-score is reported separately (the NEW-04 precedent). Re-scoring both arms is required, and the decision is made blind to the arm.

## 10. Budget estimate (not approved)

Observed: $0.25–$0.68 per run on the medium-rated Phase 3.2 tasks, with treatment 13–36% more expensive than control. Assumed per control run: easy $0.30, medium $0.60, hard $1.50 (multi-module, longer sessions; uncertain by 2× either way). Treatment ×1.4.

| Stage | Runs | Expected | Cap to approve (invalid runs and reruns included) |
|---|---|---|---|
| 1 calibration (2 tasks × 2 runs/arm × 3 tiers) | 24 | ≈ $23 | $50 |
| 2 estimation (6 × 2 × 2 × 3) | 72 | ≈ $69 | $140 |
| Later hard-only stage (25 tasks × 2 × 2) | 100 | ≈ $180 | to be estimated from Stage 1 costs |

No paid invocation without written approval of model, run count and cap. GitHub Actions minutes are not included.

## 11. Threats to validity

- **Selection bias:** prevented by the sealed calibration/confirmatory draw and by never choosing tasks because the control failed.
- **Difficulty misclassification:** two raters, written anchors, agreement reported, manipulation check on calibration tasks only. The F6 gate is a hypothesis informed by NEW-04.
- **Low power:** §6. Stage 2 is an estimation stage; report intervals and "inconclusive" honestly.
- **Model drift:** pinned model ID and variant, both arms of a block run back to back, provider model metadata recorded (R05). Blocks spread over days are a residual risk; report the run dates.
- **Ceiling or floor:** made explicit by the discriminating-task rule.
- **Oracle over-strictness:** an alternative correct design must pass before freezing (R09).
- **Benchmark overfitting of the skill:** a revised skill (§12) is evaluated only on tasks it was not developed on.
- **Prompt leakage:** prompts are public by design (R11). Hidden checks, references and the oracle source map are private.
- **Scorer drift and post-unblinding edits:** oracle changes only by a new version with a separate re-score (§9).

## 12. Follow-up: skill revision and checker tool (only after Stage 2)

If, and only if, Stage 2 suggests a specific fixable weakness:

1. A versioned three-arm comparison on **new** tasks: no skill / current skill (`d050d00f…`) / revised skill.
2. Any executable helper (for example a scope checker such as the historical `scope_check.py`, which is not in this repository and was not inspected) is a tool intervention. It gets its own arm: revised skill text with the tool vs without it. It is never attributed to skill text.
