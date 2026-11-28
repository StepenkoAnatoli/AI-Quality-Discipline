# Phase 3.3: does the benefit of `code-discipline` change with task difficulty? (design draft)

**Status (2026-11-22): DRAFT, not ratified, nothing frozen, no runs, no spend approved.** This design supplements Phase 3.2; it does not replace its results or its harness. The four Phase 3.2 tasks (NEW-01..04) and their A/B results stay as historical records in `evaluations/phase-3.2/`, unchanged. The 36-run Phase 3.2 pilot (2 models × 3 tasks × 3 repetitions × 2 conditions, SPECIFICATION.md §2) was never run. The four 2-run A/Bs on Claude replaced it in practice. This design supersedes the pilot for Claude; a Grok cell would reuse this design once Grok is unblocked (SPECIFICATION.md C4).

Implemented offline in this change: the difficulty rubric (`difficulty-rubric.json`), post-hoc ratings of the historical tasks (`ratings-historical.json`), the task-level tier analysis (`../phase-3.2/harness/difficulty.py`, reached through `analyze.py --difficulty-plan`), its tests (`../phase-3.2/tests/test_difficulty.py`), and the power simulation (`power_sim.py`). Everything else below is a proposal.

**Revision 2026-11-22 (review of `1912c0b`).** Seven defects were found and fixed, each with a regression test that failed on `1912c0b`:

1. A tier mostly at the ceiling could read as "no meaningful effect". It now needs a minimum share of discriminating tasks, chosen by simulation (§6, §8).
2. The interaction skipped each side's zero-spread guard. Both sides now get every tier guard (§8).
3. Agent-caused failures were pooled with infrastructure failures in the 0/1 bounds. They now count as failures, intention to treat (§5, §8).
4. The rubric mixed intrinsic difficulty and requirement discovery, and gated the hard tier on discovery after seeing NEW-04. These are now separate axes (§3, §4).
5. The Stage 1 stop rule cited 8 control runs where the design had 4. The run count is now real and the rule's error rates are stated (§6).
6. Calibration feedback could expose treatment results. Feedback is now control-only (§6).
7. The power table omitted the decision guards and the interaction. It now runs the real decision code for two tiers under several variance assumptions (§6).

In addition, future schedules can counterbalance run order (§5), and a frozen plan is labelled "estimation" unless it records adequate power (§8).

**Revision 2026-11-22b (stress tests of `002c3cf`).** Four changes:

1. **Three claims corrected.**
   - The 0.45 discrimination threshold is grid-limited (§7).
   - Simulated power is an assumption, not a guarantee (§6).
   - "Benefit" detecting a true MID-sized effect about half the time is a property of the rule, not a power shortfall (§6).
2. **Two estimands distinguished:** the population effect for the default-on decision, and the challenging-task effect for the difficulty hypothesis. Neither selects tasks by observed outcomes (§1).
3. **Terminology.** `no_meaningful_effect` is equivalence within margins, never "no effect".
4. **Non-inferiority is reported**, and an adoption rule is proposed (§7, §8).

The supporting runs are in `stress_decisions.py` and `stress-output-2026-11-22.txt`. The historical Phase 3.2 results are unchanged.

## 1. Question, hypotheses and estimands

For one model M, interface version V and frozen skill S (`skills/code-discipline/SKILL.md`, SHA-256 `d050d00f…7ebc842`):

- **Per-task effect** `d_t` = mean primary outcome of treatment runs − mean of control runs on task t.
- **Tier effect** `D_k` = mean of `d_t` over the tasks in tier k (equal task weight).
- **Interaction** `D_hard − D_easy` (and the other tier pairs).

**Two estimands, for two different questions (revision 2026-11-22b).**

| | E1: population effect | E2: challenging-task effect |
|---|---|---|
| Question | Should code-discipline be **on by default**? | Does the skill help on **challenging** tasks (the difficulty hypothesis)? |
| Definition | Mean of `d_t` over a sample of tasks drawn to represent the work the product is used for, each task weighted by its pre-registered population share | `D_hard`: mean of `d_t` over the tasks **prospectively** rated hard by the rubric (intrinsic axis), before any run on them |
| Ceiling tasks | Count in full. A task both arms always pass is real work where the skill cannot help; leaving it out would overstate the product benefit | Count in full. A hard-rated task that turns out easy for the model is a rating error. It is caught by calibration (§6), never by dropping it afterwards |
| Computed by | Not implemented. With equal population shares it is the equal-weight task mean (`analyze.py` effect, or the tier summary over all tasks); unequal shares need pre-registered weights | `difficulty.py` `by_tier["hard"]` |

- **No outcome-based subgroups.** Neither estimand selects tasks or runs by what happened in a scored run, in either arm. A subset "where the control failed", or "with room to improve", is computed from the outcome itself and would bias the effect upward. It is never an estimand.
- **Guards are not selection.** The discriminating-task counts in §8 use outcomes, but only to *withhold* a conclusion (making it inconclusive). They never change which tasks enter an estimate.
- **Correction.** An earlier private note proposed a "tasks with room" estimand. That proposal is withdrawn for this reason.
- **What a feasibility run can tell us.** The four Phase 3.2 tasks and the planned calibration tasks are not a population sample, so neither can estimate E1. A feasibility run can only show whether E2 is measurable at all.

Competing hypotheses, all tested by the same intervals:

| | Claim | Evidence that would support it |
|---|---|---|
| H1 | The skill prevents meaningful errors, more so on harder tasks | `D_hard` decision "benefit" and the interval for `D_hard − D_easy` above 0 |
| H0 | No effect as large as the margins (equivalence, not "zero effect") | `D_k` intervals inside (−harm, +MID) in every tier with discriminating tasks |
| H2 | The skill harms (hesitation, over-process, scope suppression) | any tier decision "harm", or overhead or critical-regression limits exceeded |

A higher control error rate on hard tasks is **not** evidence for H1. Only treatment − control, and its change across tiers, is.

## 2. Why Phase 3.2 hit the ceiling

Section 3 of the audit report (`AUDIT-2026-11-22.md`) has the evidence. In short: the prompts are near-complete specifications (NEW-03 and NEW-04 enumerate 18 clauses each, including error precedence and tie-breaks). Each task changes one file. Every hidden check traces to a stated sentence. The NEW-04 "hard" task took both agent sessions together 6 min 45 s of a 45-min-per-run budget. With one run per arm and 4 tasks, a 100% vs 100% result cannot distinguish H0 from a small H1 or H2. Under the rubric below (v1.1, post-hoc), NEW-01..03 rate **medium** and NEW-04 rates **hard**. All four are at discovery level **specified**: the prompts state every obligation. The historical data therefore says nothing about tasks where requirements must be discovered.

## 3. Difficulty rubric

`difficulty-rubric.json` (v1.1-draft, machine-checked by `difficulty.py`). Eight factors, each scored 0–3 against written anchors, equal weight. **Two axes:** F1–F5, F7 and F8 measure *intrinsic technical difficulty* (composite 0–21, which alone sets the tier). F6 measures *requirement-discovery burden*, a separate axis that is never added to the composite and never gates a tier:

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

Tiers (intrinsic composite): easy ≤ 6, medium 7–12, hard ≥ 13. These are the v1.0 cut-points (7/24 and 14/24 of the maximum) rescaled to 21, not fitted to data. Discovery level (F6): **specified** (0–1, the prompt states the obligations) or **discovered** (2–3, most obligations must be found in the repository). `difficulty.py` refuses a tier gate on a discovery factor.

Not factors, on purpose: file count, lines of code, number of hidden checks, prompt length.

**Weights.** Equal, because no data exists to estimate weights, and any other choice would be tuned by hand. Reweighting is allowed only before the confirmatory set is rated, and only with the reason recorded.

**Why two axes.** Rubric v1.0-draft counted F6 in the composite *and* required F6 ≥ 2 for the hard tier. That gate was added after NEW-04 (intrinsic 15) reached the ceiling with a complete specification. It mixed two different explanations of difficulty, and it could rate a maximally complex but fully specified task as medium (21 points) and a task with no concurrency and no state machine but F6 = 3 as hard (18 points). The hypothesis behind the gate ("a complete specification reduces hard engineering to translation") is now a contrast the design measures: the effect by discovery level, and its interaction with the intrinsic tier (§4, §8). It is not an assumption built into the tiers.

**Historical ratings are post hoc and exploratory.** NEW-01..04 were rated after their outcomes were known, by one rater, and re-scored against v1.1 without changing any factor score. `difficulty.py` refuses them in any set but "historical". The report lists them under `post_hoc_tasks`, and they never select, calibrate or tune confirmatory tasks.

**F6 must not become hidden information.** For every hidden check the task author records where its obligation is established: a prompt sentence, or a repository artifact (`file:line` of code, a caller, a test, a document). An independent reviewer confirms each mapping before freezing. A check with no source is removed. This is the existing Phase 3.2 rule ("every hidden check traces to a stated requirement"), widened from the prompt to the repository.

**Validating the tiers.**

1. Two raters score each task independently, from the task repository and the private oracle map, before any model run on it and without seeing any model output. `difficulty.py` refuses a confirmatory task with fewer than two raters and reports agreement per factor, pooled over tasks (exact and within one point, `rating_agreement_by_factor`), plus the raw rater gaps per task. Agreement below 0.6 within one point on a factor means rewriting that factor's anchors, not averaging.
2. Feasibility: a competent engineer (not the rater) solves each task from the public material only, within the agent time budget, and the time is recorded. A task nobody solves within budget is dropped.
3. Manipulation check, calibration tasks only: control success should fall from easy to hard. This checks the rubric. It never selects confirmatory tasks.

## 4. Task portfolio

Eighteen tasks: six per tier. After all eighteen are built, oracle-validated, rated and frozen, a sealed random draw (seed recorded in advance, as in `schedule.py`) assigns two per tier to **calibration** and four per tier to **confirmatory**. The author therefore cannot steer hard tasks into either set, and calibration outcomes cannot select confirmatory tasks. If §6 recommends 6 confirmatory tasks per tier, build 8 per tier.

**Discovery crossed with the tier.** Every task is built in two prompt variants over the same repository and the same private oracle:

- **S (specified):** the prompt states every obligation behind a hidden check.
- **D (discovered):** the prompt states the goal, the constraints and the acceptance criteria. Each other obligation is established by a repository artifact recorded in the oracle source map.

Both variants are rated (they differ only in F6). The same sealed draw assigns each task one variant, half S and half D within each tier and set. This gives a balanced tier × discovery design at the task level. The author cannot choose which tasks get the harder prompt, and the effects of intrinsic difficulty (`by_tier`, `interaction`) and of discovery burden (`by_discovery`, `discovery_interaction`) are estimated separately. Running both variants of a task is not proposed: it doubles the runs, and the paired contrast would sit outside the task-level analysis.

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

Required harness changes. They must not change the semantics of run validity for the historical Phase 3.2 records, so each is versioned and tested. Items 1, 2 and the harness part of 4 are implemented (2026-11-28); 3 is not:

1. **Scope violations become an outcome, not an exclusion.** *Implemented 2026-11-28 as the `outcome` scope policy:*
   - `AQD_SCOPE_POLICY=outcome` is sealed per schedule and written into every run record.
   - `run_status.py` keeps such a run valid and reports `scope_violation`, `scope_findings` and `unexpected_files`.
   - `score_run.py` already scores only the mutable files, against pristine immutable files.
   - `analyze.py` reports `strictly_correct`, `scope_violation` and `unexpected_files`, and refuses to pool runs from different policies.
   - `strictly_correct` is accepted as a plan outcome. Pre-register it as the primary outcome for `outcome`-policy runs: it keeps the intention-to-treat meaning.
   - A record without the field keeps the Phase 3.2 `invalidate` rule, which is also the default.

   Original proposal: Today an edit to any immutable file makes the run INVALID (`run_status.py`), so a scope violation leaves the comparison. That is backwards for a skill whose rules include scope control. In 3.3: a valid run with `scope_violation: true` is scored on its mutable files, and `strictly_correct = fully_correct ∧ ¬scope_violation` is reported next to `fully_correct`. (Since the 2026-11-22 revision, the difficulty analysis already counts such a run as a failure of its arm, intention to treat; see below. What remains for the harness is scoring the run's mutable files, so `fully_correct` and `strictly_correct` can be reported separately.)
2. **Unexpected new files** (recorded today in `workspace_findings.unexpected` but never reported) become a secondary outcome. *Implemented: `run-status.json` `unexpected_files`; `analyze.py` scope section. They never invalidate a run.*
3. **Control-only calibration runs.** Stage 1 (§6) needs 4 control-only hard-task runs. `schedule.validate` accepts only blocks of one control and one treatment run, so these runs need a separate, sealed calibration schedule kind, with its own tests. Until that exists, Stage 1 cannot be scheduled as specified.
4. **Results retention.** *Harness part implemented 2026-11-28; workflow part prepared as a patch for `main`, not applied. See [RESULTS-RETENTION.md](RESULTS-RETENTION.md).* The Phase 3.2 encrypted artifacts have 1-day retention, so the evidence behind AB-RESULTS.md expires within a day of each run. In 3.3 the operator archives each encrypted bundle and records its SHA-256 next to the results, and a machine-readable per-run results file (scores, costs, validity, no code or transcripts) is committed with the report.

Already handled in analysis (this change):

- **Agent-caused failures are outcomes, intention to treat.** The prompts say "Do not modify any other file". A slot whose run is invalid *only* because it changed or removed an immutable file counts as a failure (0) of its arm, and so does a run whose code a reviewer *confirmed* as tampering. They count in the estimate and in both bounds, so tampering is never imputed as a success.
- **The ambiguous cases stay non-valid:**
  - a scope violation that comes with any other invalidity reason;
  - a suspected (unconfirmed) tamper verdict;
  - a pending review;
  - a crashed or erroring evaluator;
  - provider or harness failures;
  - missing runs.

  These are carried into the worst/best-case bounds, and a decision that depends on them is inconclusive.
- A confirmed tamper verdict counts only if it names exactly the scored code (`tamper_review_subject` equals the evaluation's `review_subject_sha256`) and has a `scorer_id`. Otherwise the slot stays non-valid. `analyze.py` records this as `tamper_verified`.
- Two sensitivity results are reported for every tier, every discovery level and **every interaction**:
  - with scope violations treated as non-valid (`decision_if_scope_violations_were_nonvalid` for a tier or level, `conclusion_if_scope_violations_were_nonvalid` for an interaction);
  - with tamper-confirmed slots dropped (`decision_if_tamper_slots_were_dropped`, `conclusion_if_tamper_slots_were_dropped`). They are dropped, never imputed as successes.

  `itt_dependent: true` marks a result that changes under either, next to `agent_failures` and `tamper_failures` per arm. A "benefit" or "effect larger in hard" that comes from one arm breaking the file rule, or from reviewers' tamper verdicts, is therefore visible as such.
- Run validity, slot accounting and the Phase 3.2 effects in `analyze.py` are unchanged. The attribution exists only inside the difficulty analysis.

**Counterbalanced run order.** In Phase 3.2 the treatment ran first in 4 of 4 pairs, a 1-in-16 chance under fair draws, so arm and position were confounded. Phase 3.3 schedules are created with `schedule.py create --counterbalance`. For every model and task, the treatment-first blocks number ⌊reps/2⌋ or ⌈reps/2⌉; across the schedule they differ from the control-first blocks by at most one; the assignment to blocks is random. `schedule.validate` refuses a counterbalanced schedule that is not balanced. Without the flag, `schedule.py` reproduces every Phase 3.2 schedule byte for byte (pinned by a test).

## 6. Stages, precision and gates

**Stage 0: offline, no spend.** Build the eighteen tasks; private oracle packs; oracle validation (§4); two-rater ratings; feasibility runs by an engineer; freeze; sealed calibration/confirmatory draw. Also add the four harness changes (§5) with tests.

**Stage 1: calibration (28 runs).** Two tasks per tier, two runs per arm (24 runs), plus two extra **control-only** runs on each hard calibration task (4 runs; these need the control-only schedule kind in §5), so that the stop rule below has 8 hard-task control runs. Purpose: feasibility, oracle sanity on real agent code, cost per tier, and the manipulation check. It is not evidence about the skill and is never pooled with Stage 2.

Stop rules after Stage 1, written before it runs:

- **Hard-task control success in ≥ 7 of the 8 hard control runs: stop.** The tasks are not hard for this model. Return to Stage 0 and do not spend on Stage 2. Operating characteristics (`power_sim.py stop-rule`), as P(stop | true control success p):

  | Rule | p = 0.95 | 0.90 | 0.80 | 0.70 | 0.60 | 0.50 |
  |---|---|---|---|---|---|---|
  | **≥ 7 of 8 (adopted)** | 0.94 | 0.81 | 0.50 | 0.26 | 0.11 | 0.04 |
  | ≥ 0.9 of 4 = 4/4 (the `1912c0b` rule as the runs actually were) | 0.81 | 0.66 | 0.41 | 0.24 | 0.13 | 0.06 |
  | ≥ 0.9 of 8 = 8/8 | 0.66 | 0.43 | 0.17 | 0.06 | 0.02 | 0.00 |

  The `1912c0b` text said "≥ 0.9 (8 control runs on hard tasks)", but Stage 1 had 2 × 2 = 4 hard control runs. With 4 runs, "≥ 0.9" only fires at 4/4, so a task that is really 90% solvable went on to Stage 2 34% of the time. A false stop costs a rebuild of tasks. A false continue spends Stage 2 (cap $140) on tasks that will hit the ceiling. "≥ 7 of 8" goes on with a 90%-solvable task 19% of the time and stops a 60%-solvable one 11% of the time.
- Any oracle rejects an agent solution that an independent reviewer judges correct: fix the oracle in a new version, re-score separately (both scores kept, as for NEW-04), and re-validate that task family. The reviewer sees the code under its `blind_id`, never its arm.
- Any invalid-run rate above 10% from infrastructure: fix the harness before Stage 2.

**Calibration feedback is control-only.** Task authors, and anyone else who can still change a task, see only the file written by `analyze.py --calibration-feedback` (`difficulty.calibration_feedback`):

- what it contains: per calibration task, control runs, successes, mean hidden pass fraction, agent failures and non-valid slots;
- what it never contains: a treatment result, a treatment slot count or a treatment − control contrast.

The full report and the treatment results stay sealed with the operator until the confirmatory analysis is complete. Nobody can therefore tune a task, its oracle or its prompt toward the arm that is winning.

Any change to a task after Stage 1 needs three things:

- a new task version;
- a recorded reason that cites control-only evidence or a blind oracle dispute;
- for a confirmatory task, a re-freeze of the plan before Stage 2, listed in the report.

**Protecting the skill and the unseen tasks:**

- The skill stays frozen at `d050d00f…` for the whole phase, and no Stage 1 result may revise it (§12).
- Confirmatory task repositories, prompts and oracles stay unpublished until their Stage 2 runs are complete. Only the public briefs in §4 are released early.

**Stage 2: estimation.** Operating characteristics from `power_sim.py designs` (seed 20261122, 2000 simulations per row). Every simulated data set goes through the real decision code, `difficulty.analyse_outcome`, with all its guards and on two tiers. The easy tier has no effect; the effect is on the hard tier. Two of the variance assumptions are shown here; the script prints a third, skewed toward easy tasks, where clipping shrinks the effect further:

| Tasks/tier × runs/arm | Runs/tier | 95% half-width | P(benefit), nominal +0.20 / +0.40 | P(interaction "larger in hard"), +0.20 / +0.40 | P(false benefit), effect 0 |
|---|---|---|---|---|---|
| *Control success across tasks Beta(4, 4), heterogeneity τ = 0.15* | | | | | |
| 4 × 3 | 24 | ±0.57 | 0.06 / 0.21 | 0.07 / 0.17 | 0.01 |
| 6 × 2 | 24 | ±0.47 | 0.16 / 0.44 | 0.08 / 0.20 | 0.03 |
| 12 × 1 | 24 | ±0.40 | 0.15 / 0.47 | 0.02 / 0.06 | 0.02 |
| 8 × 3 | 48 | ±0.32 | 0.25 / 0.69 | 0.15 / 0.39 | 0.03 |
| 25 × 2 | 100 | ±0.19 | 0.48 / 0.97 | 0.28 / 0.77 | 0.02 |
| *Control success Beta(1.5, 1.5), τ = 0* | | | | | |
| 4 × 3 | 24 | ±0.50 | 0.05 / 0.16 | 0.07 / 0.15 | 0.01 |
| 6 × 2 | 24 | ±0.42 | 0.14 / 0.38 | 0.07 / 0.17 | 0.02 |
| 12 × 1 | 24 | ±0.37 | 0.18 / 0.50 | 0.01 / 0.03 | 0.03 |
| 8 × 3 | 48 | ±0.28 | 0.28 / 0.74 | 0.16 / 0.43 | 0.03 |
| 25 × 2 | 100 | ±0.17 | 0.48 / 0.97 | 0.32 / 0.78 | 0.01 |

What this means:

- **Clipping.** A nominal +0.20 is a realised +0.14 to +0.20, depending on how close the control is to the ceiling. Every rate is for the realised effect.
- **"Benefit" detects a true effect of exactly MID only about half the time, at any size.** This is by construction, not a lack of power: the rule requires the point estimate to be ≥ MID, and at a true effect equal to MID the estimate falls on either side about equally often (`power_sim.py scale`: 0.34–0.53 at 100 tasks per tier; `stress_decisions.py` A: 0.48–0.51 at 25–100 tasks). So "power at MID" is not a meaningful target for this rule. A design must state the true effect it is powered for, which has to be well above MID: 25 × 2 gives 0.94–0.99 at a realised +0.32 to +0.37, and 0.71–0.80 at +0.23 when control success is skewed toward easy. A rule that needs only a lower bound > 0 would detect smaller effects more often, at the cost of calling effects below MID a "benefit". The choice is the owner's, and must be pre-registered.
- **Simulated power is an assumption, not a guarantee.** Every figure above assumes no non-valid slots, a known spread of control success and no ceiling share. `stress_decisions.py` (section C) moves one assumption at a time on a 25 × 2 design powered at 0.99 for a nominal +0.40:

  | Change | P(benefit) |
  |---|---|
  | 5% of slots invalid from infrastructure | 0.89 |
  | 10% invalid | 0.66 |
  | 30% of tasks turn out at the ceiling | 0.82 |
  | Control success skewed toward easy | 0.78 |
  | Heterogeneity τ = 0.30 | 0.87 |
  | Overdispersion and drift | 0.94–0.96 |
  | Nominal +0.20, no invalid slots | 0.48 |
  | Nominal +0.20, 10% invalid | **0.10** |

  The 0/1 imputation of non-valid slots is the dominant sensitivity, and Phase 3.2 had one invalid run among its scored dispatches. A recorded power figure is therefore valid only together with the scenario it was computed under. `difficulty.py` checks the recorded figure's provenance (pinned output, contrast, task count), not its realism. Before a confirmation plan is frozen, its power must be ≥ 0.8 in **every** scenario of a pre-registered set that includes at least the expected infrastructure-invalid rate, a ceiling share and skewed control success. That remains a review requirement; the code does not enforce it.
- **The difficulty-by-treatment interaction, which is the question, is the hardest part.**
  - At +0.20 it is detected 5–9% of the time with 6 × 2, and 18–33% of the time with 25 × 2, across the three variance assumptions.
  - About 0.8 needs **roughly 100 tasks per tier at 2 runs per arm** (0.82–0.87 in `power_sim.py scale`), which is 800 runs for two tiers.
  - The `1912c0b` statement that "the interaction interval will be wider still" understated this.
- **One run per arm defeats the guards.** With one run per arm, a task "discriminates" only by chance, so the ceiling and floor rules block most interactions (≤ 0.08 even at +0.40). Use at least 2 runs per arm. The `1912c0b` claim that more tasks with fewer repetitions is "strictly more precise" holds for the half-width of a tier, but not for the decisions.
- **"No meaningful effect" is essentially unreachable at these sizes:** P ≤ 0.022 in every simulated design. At feasible sizes a true null will be reported as "inconclusive", and that is the honest report.
- **False positives are controlled.** At zero effect, in every simulated design, P(benefit) ≤ 0.033. P(interaction "larger in hard") and P("smaller in hard") are each ≤ 0.031, and both together ≤ 0.057.

Recommendation:

- Keep Stage 1 as above.
- Run Stage 2 as **6 tasks × 2 runs per tier (72 runs)**, pre-registered as an *estimation* stage: plan `purpose: "estimation"`, so `difficulty.py` labels the report "estimation". Expect intervals of about ±0.4–0.5 per tier, and report the intervals, not the decisions.
- A confirmatory claim needs a plan with `purpose: "confirmation"` whose `power` names one contrast (a tier, or `"<harder> - <easier>"`), its simulated power (≥ 0.8), the `assumed_tasks_per_tier` (each tier of the contrast must have at least that many inference tasks), and the simulation output pinned by SHA-256. `difficulty.py` refuses anything less, and labels **only that contrast on the primary outcome** "confirmatory". Everything else is "estimation". Rough sizes:
  - for a hard-tier benefit, about 25 tasks at 2 runs per arm, if the true effect is about +0.35;
  - for the interaction at +0.20, about 100 tasks per tier.
- Building the tasks, not paying for model calls, is the binding constraint. Do not describe Stage 2 as powered.

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
| Minimum discriminating share for "no meaningful effect" | 0.45 of a tier's tasks (a backstop guard, not a validated property) | **Grid-limited.** `power_sim.py share-sweep` chose 0.45 as the smallest grid value whose worst-case false reassurance was ≤ 0.05. "False reassurance" means "no meaningful effect" while 10–85% of tasks sit at the ceiling and the skill has an effect of MID wherever there is room. The grid covered up to 25 tasks per tier at 2 runs per arm (0.026; 0.40 gave 0.082; without the rule, 0.745). **Outside that grid it does not hold** (`stress_decisions.py` B): at 50 tasks per tier the worst case is 0.17 (confirmed with `power_sim.run_design`: 0.175 at a 30% ceiling share); with 3 runs per arm, 0.55; with τ = 0.15, 0.18. No single threshold fixes this. In these scenarios the true tier effect is +0.10 to +0.14, below MID, so "no meaningful effect" is arguably *correct* for E2 as defined; the rule patches a mismatch between the estimand and the question. The remedy is the estimand definition (§1) and the calibration stop rule (§6), which catches a ceiling-heavy "hard" tier before confirmatory runs. Keep the guard, but do not cite it as controlling false reassurance in general |
| Non-inferiority margin | −0.10 (= harm) | reported per tier as `non_inferiority.holds`: the 95% lower bound > −0.10 under the observed data and both non-valid imputations, with at least two discriminating tasks and non-zero spread. It is the question "is it not harmful?" for a default-on decision |

## 8. Analysis

`analyze.py --difficulty-plan PLAN` (implemented). It consumes the existing fail-closed slot resolution, so nothing is re-scored:

- per task: arm means, `d_t`, non-valid slot counts, worst/best-case bounds;
- per tier: mean of `d_t` with a t-interval over tasks (df = tasks − 1);
- interaction: Welch intervals for every tier pair (df floored). It concludes `effect_larger_in_<tier>` or `effect_smaller_in_<tier>` only when the interval excludes 0 under valid runs **and** under both non-valid-slot bounds, and neither tier is at a ceiling or floor or missing a task. Otherwise it is inconclusive;
- missing tasks: every pre-registered inference task must have slots for every model. A frozen confirmatory plan with a missing task is an error. In an exploratory report the tier is inconclusive and the task is listed;
- decision per tier: **benefit** (lower bound > 0 and estimate ≥ MID), **harm** (upper bound < 0 and estimate ≤ −harm), **no_meaningful_effect** (interval inside (−harm, MID)), otherwise **inconclusive**. **Terminology:** `no_meaningful_effect` means *equivalent within the pre-registered margins (−0.10, +0.20)*. It is never a claim that the effect is zero, and reports must say "no effect as large as the margins" rather than "no effect". The 95% interval inside the margins is a two one-sided tests (TOST) equivalence test at 2.5% per side, more conservative than the usual 5%. It is forced to inconclusive when:
  - the tier has fewer than two discriminating tasks (a task where every run in both arms is at the same extreme is at the ceiling or floor);
  - the task differences have zero spread (a degenerate interval);
  - the decision changes under the non-valid-slot bounds;
  - for "no_meaningful_effect" only, fewer than `min_discriminating_share` (0.45) of the tier's tasks discriminate ("ceiling-dominated"). Zeros from ceiling tasks would otherwise make the interval look precise. A ceiling-heavy tier dilutes "benefit" and "harm" toward 0, so it cannot produce a false one;
- agent-caused failures count as failures (§5). Each tier reports `agent_failures`, `tamper_failures`, `decision_if_scope_violations_were_nonvalid`, `decision_if_tamper_slots_were_dropped` and `itt_dependent`;
- **non-inferiority** per tier (`non_inferiority`, revision 2026-11-22b): it holds when the lower bound exceeds −harm under the observed data and both imputations, with at least two discriminating tasks and non-zero spread. It is separate from the decision and weaker than "benefit";
- **adoption rule for E1 (proposed, to be ratified):** turn code-discipline on by default only if all three hold:
  - the E1 decision is "benefit";
  - non-inferiority holds;
  - the cost and wall-time ratios stay within the overhead limits in §7.

  Otherwise it stays off. "inconclusive" and "no_meaningful_effect" lead to the same action, so the adoption decision never needs a null to be proven, and identifying one (100+ tasks per tier, `stress_decisions.py` A) is not worth the cost of building those tasks. None of this changes the historical Phase 3.2 results, which use none of these rules;
- the interaction applies every tier guard to **each side**: missing tasks, fewer than two discriminating tasks, zero spread, ceiling-dominated. A difference in effect between a ceiling-dominated tier and another tier measures headroom, not difficulty. In `1912c0b`, an easy tier with zero spread still produced `effect_larger_in_hard`;
- discovery: when the rubric has a discovery axis, the same analysis runs by discovery level (`by_discovery`) with the contrast `discovered − specified` (`discovery_interaction`), next to the tiers;
- the report records the SHA-256 of the plan, the rubric and every ratings file;
- label:
  - "confirmatory" only for a frozen plan whose inference set is exactly the confirmatory set with prospective ratings, **and** whose `purpose` is "confirmation" with a recorded, pinned simulated power ≥ 0.8. Even then, only the named contrast carries `inference: "confirmatory"`; every other tier, level and contrast carries "estimation";
  - "estimation" for the same plan without that purpose and power;
  - otherwise "exploratory".

Run on the historical Phase 3.2 tasks with the post-hoc v1.1 ratings, the analysis reports the medium tier (NEW-01..03) as **inconclusive (ceiling)** and the hard tier (NEW-04 alone) as **inconclusive (one task)**. It does not report "no effect" (pinned by `test_ceiling_result_is_reported_as_inconclusive_not_as_no_effect` and `test_historical_all_valid_records_are_unaffected`).

Planned sensitivity analysis, not implemented: a mixed-effects logistic model (task random intercept and random treatment slope, tier × condition fixed effects), fitted offline with a standard statistics package and reported next to, never instead of, the task-level analysis. The existing exact permutation p-value in `analyze.py` stays descriptive.

## 9. Freezing procedure

Before the first Stage 2 run, and recorded in one commit:

1. Rubric, ratings (two raters, `prospective`), task projects, prompts and the plan with `status: "frozen"` and `inference_sets: ["confirmatory"]`. The plan pins the rubric and every rating file by SHA-256, and `difficulty.py` refuses any mismatch.
2. Private: hidden tests, inventories, references, alternative designs, mutants and the oracle source map, with their hashes recorded in the private key.
3. Skill SHA-256, model ID and variant, OpenCode version, sandbox image digest.
4. Thresholds (§7, including `min_discriminating_share`), the plan's `purpose` (and, for "confirmation", its recorded power), stop rules (§6), the seeded schedule created with `--counterbalance`, and the S/D variant draw (§4).

An evaluator defect found later is fixed in a new oracle version. Both scores are kept and the re-score is reported separately (the NEW-04 precedent). Re-scoring both arms is required, and the decision is made blind to the arm.

## 10. Budget estimate (not approved)

Observed: $0.25–$0.68 per run on the medium-rated Phase 3.2 tasks, with treatment 13–36% more expensive than control. Assumed per control run: easy $0.30, medium $0.60, hard $1.50 (multi-module, longer sessions; uncertain by 2× either way). Treatment ×1.4.

| Stage | Runs | Expected | Cap to approve (invalid runs and reruns included) |
|---|---|---|---|
| 1 calibration (2 tasks × 2 runs/arm × 3 tiers, + 4 hard control-only runs) | 28 | ≈ $29 | $60 |
| 2 estimation (6 × 2 × 2 × 3) | 72 | ≈ $69 | $140 |
| Later hard-only stage (25 tasks × 2 × 2) | 100 | ≈ $180 | to be estimated from Stage 1 costs |

No paid invocation without written approval of model, run count and cap. GitHub Actions minutes are not included.

## 11. Threats to validity

- **Selection bias:** prevented by the sealed calibration/confirmatory draw, the sealed S/D variant draw, and never choosing tasks because the control failed.
- **Arm/position confound:** counterbalanced run order (§5). In Phase 3.2 the treatment ran first in 4/4 pairs.
- **Tuning tasks toward the winning arm:** calibration feedback is control-only. Treatment results stay sealed until the confirmatory analysis (§6).
- **Requirement discovery confounded with difficulty:** two rubric axes and a crossed S/D design (§3, §4).
- **Difficulty misclassification:** two raters, written anchors, agreement reported, manipulation check on calibration tasks only. The historical ratings are post hoc, single-rater and exploratory.
- **Low power:** §6. Stage 2 is an estimation stage, labelled as such by the analysis. Report intervals and "inconclusive" honestly. The interaction needs about 100 tasks per tier.
- **Model drift:** pinned model ID and variant, both arms of a block run back to back, provider model metadata recorded (R05). Blocks spread over days are a residual risk; report the run dates.
- **Ceiling or floor:** made explicit by the discriminating-task rule and the ceiling-dominated share rule. Both apply to each side of an interaction.
- **Oracle over-strictness:** an alternative correct design must pass before freezing (R09).
- **Benchmark overfitting of the skill:** a revised skill (§12) is evaluated only on tasks it was not developed on.
- **Prompt leakage:** prompts are public by design (R11). Hidden checks, references and the oracle source map are private.
- **Scorer drift and post-unblinding edits:** oracle changes only by a new version with a separate re-score (§9).

## 12. Follow-up: skill revision and checker tool (only after Stage 2)

If, and only if, Stage 2 suggests a specific fixable weakness:

1. A versioned three-arm comparison on **new** tasks: no skill / current skill (`d050d00f…`) / revised skill.
2. Any executable helper (for example a scope checker such as the historical `scope_check.py`, which is not in this repository and was not inspected) is a tool intervention. It gets its own arm: revised skill text with the tool vs without it. It is never attributed to skill text.
